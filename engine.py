"""Threaded SMF tilt scan. Talks to the SLM, Zernikes, and power meter only."""

import copy
import json
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread

import numpy as np

from .grid import make_scan_grid, pixel_edges

_POLS = ("H", "V", "HV")
_SAVE_PATH_ERROR = "Provide a path to save() or call set_saving_path() first."


def _now():
    return datetime.now().astimezone().replace(microsecond=0)


class ZernikeSteering:
    """Scan tilt around the current Zernike coefficients and record power.

    ``slm_widget``, ``zernike_widget``, and ``powermeter_widget`` are optional.
    When all three are passed, ``scan`` locks them and the thread unlocks them
    when it finishes. With none of them, the hardware loop and ``stop`` still run.
    """

    def __init__(
        self,
        slm,
        zernike,
        powermeter,
        slm_widget=None,
        zernike_widget=None,
        powermeter_widget=None,
        f_mm=10,
        wav_nm=843.5,
        aperture_mm=7.5,
        scan_radius_um=5,
        step_um=0.2,
    ):
        self.slm = slm
        self.zernike = zernike
        self.powermeter = powermeter
        self.slm_widget = slm_widget
        self.zernike_widget = zernike_widget
        self.powermeter_widget = powermeter_widget
        self.slm_delay = 0.2

        self.f_mm = float(f_mm)
        self.wav_nm = float(wav_nm)
        self.aperture_mm = float(aperture_mm)
        self.scan_radius_um = float(scan_radius_um)
        self.step_um = float(step_um)
        self._rebuild_grid()

        self.maps = {}
        self.progress = {"iteration": 0, "total": 0, "active_pol": None}
        self._saving_path = None
        self._stop = False
        self._starting = False
        self._thread = None
        self._lock = Lock()

    @property
    def running(self):
        thread = self._thread
        return self._starting or (thread is not None and thread.is_alive())

    def set_scan_parameters(
        self,
        f_mm=None,
        wav_nm=None,
        aperture_mm=None,
        scan_radius_um=None,
        step_um=None,
    ):
        """Replace any argument that is not None and rebuild the tilt grid.

        A scan that has already started keeps the grid it copied at launch.
        """
        if f_mm is not None:
            self.f_mm = float(f_mm)
        if wav_nm is not None:
            self.wav_nm = float(wav_nm)
        if aperture_mm is not None:
            self.aperture_mm = float(aperture_mm)
        if scan_radius_um is not None:
            self.scan_radius_um = float(scan_radius_um)
        if step_um is not None:
            self.step_um = float(step_um)
        self._rebuild_grid()

    def set_saving_path(self, path):
        """Parent directory for later ``save()`` calls."""
        self._saving_path = Path(path)

    def scan(self, pol, pattern_enabled=True, on_sample=None, on_finished=None):
        """Start one scan on a daemon thread. Return False if one is already running."""
        if pol not in _POLS:
            raise ValueError(f"Invalid polarization: {pol}")
        with self._lock:
            if self.running:
                return False
            self._starting = True
        try:
            grid = self._snapshot_grid()
            self._stop = False
            n_points = int(grid["nx"].size)
            with self._lock:
                self.progress = {
                    "iteration": 0,
                    "total": n_points * len(pol),
                    "active_pol": None,
                }
            self.pre_scan_routine()
            self._thread = Thread(
                target=self._scan_thread,
                args=(pol, bool(pattern_enabled), grid, on_sample, on_finished),
                daemon=True,
            )
            self._thread.start()
            return True
        finally:
            self._starting = False

    def stop(self):
        """Ask the running scan to finish the current point and then return."""
        self._stop = True

    @property
    def stop_requested(self):
        return self._stop

    def view_state(self):
        """Copies of the maps and progress for a GUI timer."""
        with self._lock:
            maps = {}
            for pol, record in self.maps.items():
                maps[pol] = {
                    "power_w": np.array(record["power_w"], copy=True),
                    "x_um": np.array(record["x_um"], copy=True),
                    "y_um": np.array(record["y_um"], copy=True),
                    "finished_at": record["finished_at"],
                }
            progress = dict(self.progress)
        return maps, progress, self.running

    def save(self, path=None):
        """Write one new folder of JSON, npz, and png files. Return that folder.

        ``path`` is the parent directory. When it is omitted, the directory from
        ``set_saving_path`` is used. With neither, this raises ``RuntimeError``.
        """
        if self.running:
            raise RuntimeError("A steering scan is running. Save when it has finished.")

        parent = self._parent_directory(path)
        with self._lock:
            records = {pol: dict(record) for pol, record in self.maps.items()}
            for record in records.values():
                record["power_w"] = np.array(record["power_w"], copy=True)
                record["x_um"] = np.array(record["x_um"], copy=True)
                record["y_um"] = np.array(record["y_um"], copy=True)
                record["coefficients"] = copy.deepcopy(record["coefficients"])
                record["centers"] = copy.deepcopy(record["centers"])

        if not records:
            raise RuntimeError("No steering scan to save.")

        when = _now()
        folder = parent / _folder_name(records, when)
        if folder.exists():
            folder = parent / f"{folder.name}_{when.strftime('%f')}"
        folder.mkdir(parents=True, exist_ok=False)
        for pol, record in records.items():
            _write_pol(folder, pol, record)
        return folder

    def _parent_directory(self, path):
        if path is not None:
            return Path(path)
        if self._saving_path is not None:
            return self._saving_path
        raise RuntimeError(_SAVE_PATH_ERROR)

    def pre_scan_routine(self):
        """Lock the instrument panels. No-op when they were not passed in."""
        if not self._panels_connected():
            return
        self.slm_widget.disable_user_interface()
        self.zernike_widget.setEnabled(False)
        self.powermeter_widget.reset_extrema()
        self.powermeter_widget.remote()

    def post_scan_routine(self):
        """Unlock the instrument panels from the worker thread.

        The SLM is enabled before the Zernike refresh so the restored phase
        is pushed onto the mask.
        """
        if not self._panels_connected():
            return
        self.slm_widget.enable_user_interface(run_async=True)
        self.zernike_widget.refresh_all_from_zernikes_async()
        self.zernike_widget.enable_user_interface(True, run_async=True)
        self.powermeter_widget.start(run_async=True)

    def _panels_connected(self):
        return (
            self.slm_widget is not None
            and self.zernike_widget is not None
            and self.powermeter_widget is not None
        )

    def _rebuild_grid(self):
        self.x_um, self.y_um, self.nx, self.ny = make_scan_grid(
            self.scan_radius_um,
            self.step_um,
            self.f_mm,
            self.wav_nm,
            self.aperture_mm,
        )

    def _snapshot_grid(self):
        return {
            "x_um": np.array(self.x_um, copy=True),
            "y_um": np.array(self.y_um, copy=True),
            "nx": np.array(self.nx, copy=True),
            "ny": np.array(self.ny, copy=True),
            "f_mm": self.f_mm,
            "wav_nm": self.wav_nm,
            "aperture_mm": self.aperture_mm,
            "scan_radius_um": self.scan_radius_um,
            "step_um": self.step_um,
        }

    def _scan_thread(self, pol, pattern_enabled, grid, on_sample, on_finished):
        try:
            for target_pol in pol:
                if self._stop:
                    break
                self._scan_polarization(target_pol, pattern_enabled, grid, on_sample)
        finally:
            with self._lock:
                self.progress["active_pol"] = None
            self.post_scan_routine()
            if on_finished is not None:
                on_finished()

    def _scan_polarization(self, pol, pattern_enabled, grid, on_sample):
        from zernikes.utils import zernike_coefficients_to_dict

        power = np.full(grid["nx"].shape, np.nan, dtype=float)
        record = {
            "power_w": power,
            "x_um": grid["x_um"],
            "y_um": grid["y_um"],
            "finished_at": None,
            "pattern_enabled": pattern_enabled,
            "coefficients": zernike_coefficients_to_dict(
                self.zernike, _now().isoformat(timespec="seconds")
            ),
            "centers": _slm_centers(self.slm),
            "f_mm": grid["f_mm"],
            "wav_nm": grid["wav_nm"],
            "aperture_mm": grid["aperture_mm"],
            "scan_radius_um": grid["scan_radius_um"],
            "step_um": grid["step_um"],
        }
        with self._lock:
            self.maps[pol] = record
            self.progress["active_pol"] = pol

        side = self.slm.ModMuxMask.H if pol == "H" else self.slm.ModMuxMask.V
        side.pattern_enabled = pattern_enabled
        flat_power = power.ravel()
        for index, (tilt_x, tilt_y) in enumerate(zip(grid["nx"].ravel(), grid["ny"].ravel())):
            if self._stop:
                break
            measured = self._measure_point(pol, side, float(tilt_x), float(tilt_y))
            flat_power[index] = measured
            with self._lock:
                self.progress["iteration"] += 1
            if on_sample is not None:
                on_sample(measured)

        with self._lock:
            record["finished_at"] = _now().isoformat(timespec="seconds")

    def _measure_point(self, pol, side, tilt_x, tilt_y):
        import time

        self.zernike.modify_zernike_coefs(
            pol=pol,
            scan_tilt=True,
            tilt_x=tilt_x,
            tilt_y=tilt_y,
        )
        self.zernike.calculate_znk_phase_mask(restore_coefs=True)
        if pol == "H":
            side.zernike = self.zernike.znk_phase_h
        else:
            side.zernike = self.zernike.znk_phase_v
        self.slm.setmask(pol=pol)
        time.sleep(self.slm_delay)
        measured = float(self.powermeter.meas_power())
        if self.powermeter_widget is not None:
            self.powermeter_widget.feed(measured)
        return measured


def _folder_name(records, when):
    flags = {record["pattern_enabled"] for record in records.values()}
    if flags == {True}:
        flag = "on"
    elif flags == {False}:
        flag = "off"
    else:
        flag = "mixed"
    stamp = when.strftime("%Y-%m-%d_%H%M%S")
    return f"steering_znk_pattern_{flag}_{stamp}"


def _slm_centers(slm):
    """Caller pixel centers, the same pair ``slm.save()`` writes."""
    center_h, center_v = slm.ModMuxMask.get_centers()
    return {
        "H": [int(center_h[0]), int(center_h[1])],
        "V": [int(center_v[0]), int(center_v[1])],
    }


def _write_pol(folder, pol, record):
    saved_at = record["finished_at"]
    payload = copy.deepcopy(record["coefficients"])
    payload["preamble"]["saved_at"] = saved_at
    payload["centers"] = copy.deepcopy(record["centers"])
    payload["scan"] = {
        "scan_radius_um": record["scan_radius_um"],
        "step_um": record["step_um"],
        "f_mm": record["f_mm"],
        "wav_nm": record["wav_nm"],
        "aperture_mm": record["aperture_mm"],
        "pattern_enabled": record["pattern_enabled"],
        "finished_at": saved_at,
    }
    json_path = folder / f"znk_{pol}.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    np.savez(
        folder / f"{pol}_scan.npz",
        power_w=record["power_w"],
        x_um=record["x_um"],
        y_um=record["y_um"],
    )
    _write_png(folder / f"{pol}_scan.png", pol, record)


def _write_png(path, pol, record):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    power_nw = np.asarray(record["power_w"], dtype=float) * 1e9
    x_um = np.asarray(record["x_um"], dtype=float)
    y_um = np.asarray(record["y_um"], dtype=float)
    x0, x1 = pixel_edges(x_um)
    y0, y1 = pixel_edges(y_um)

    figure = Figure(figsize=(5.2, 4.4), dpi=120)
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)
    image = axes.imshow(
        power_nw,
        origin="lower",
        extent=(x0, x1, y0, y1),
        aspect="equal",
        cmap="jet",
    )
    axes.set_xlabel("x (um)")
    axes.set_ylabel("y (um)")
    axes.set_title(pol)
    figure.colorbar(image, ax=axes, label="power (nW)")
    figure.tight_layout()
    figure.savefig(path)
