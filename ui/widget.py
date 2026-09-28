"""Controls for ZernikeSteering. The engine stays free of Qt."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .view import SteeringMapView


def _clock(stamp):
    """``2026-09-28T14:05:31+10:00`` to ``2026-09-28 14:05:31``."""
    if not stamp:
        return ""
    return stamp[:19].replace("T", " ")


class SteeringWidget(QWidget):
    """Scan window, pattern flag, and the H and V maps."""

    def __init__(self, engine, slm_widget, zernike_widget, powermeter_widget, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._slm_widget = slm_widget
        self._zernike_widget = zernike_widget
        self._powermeter_widget = powermeter_widget
        self._busy = False
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _build_ui(self):
        self.setWindowTitle("SMF steering")
        self.resize(1100, 700)

        self._pol_h = QCheckBox("H")
        self._pol_v = QCheckBox("V")
        self._pol_h.setChecked(True)
        self._pol_v.setChecked(True)
        pol_box = QGroupBox("Polarization")
        pol_layout = QVBoxLayout(pol_box)
        pol_layout.addWidget(self._pol_h)
        pol_layout.addWidget(self._pol_v)

        self._pattern = QCheckBox("Pattern on")
        self._pattern.setChecked(True)
        pattern_box = QGroupBox("Pattern")
        pattern_layout = QVBoxLayout(pattern_box)
        pattern_layout.addWidget(self._pattern)

        self._radius = self._spin(5.0, 0.05, 500.0, 0.1, 2, " µm")
        self._step = self._spin(0.2, 0.01, 50.0, 0.05, 2, " µm")
        scan_box = QGroupBox("Scan")
        scan_layout = QVBoxLayout(scan_box)
        scan_layout.addWidget(QLabel("Radius"))
        scan_layout.addWidget(self._radius)
        scan_layout.addWidget(QLabel("Step"))
        scan_layout.addWidget(self._step)

        self._focal = self._spin(10.0, 0.1, 1000.0, 0.5, 2, " mm")
        self._wave = self._spin(843.5, 200.0, 2000.0, 0.1, 1, " nm")
        optics_box = QGroupBox("Optics")
        optics_layout = QVBoxLayout(optics_box)
        optics_layout.addWidget(QLabel("Focal length"))
        optics_layout.addWidget(self._focal)
        optics_layout.addWidget(QLabel("Wavelength"))
        optics_layout.addWidget(self._wave)
        optics_layout.addWidget(QLabel(f"Aperture {self._engine.aperture_mm:g} mm"))

        self._input_boxes = (pol_box, pattern_box, scan_box, optics_box)

        self._scan_button = QPushButton("Start Steering Scan")
        self._scan_button.clicked.connect(self._on_scan_button)
        self._save_button = QPushButton("Save")
        self._save_button.clicked.connect(self._on_save)
        buttons = QVBoxLayout()
        buttons.addWidget(self._scan_button)
        buttons.addWidget(self._save_button)
        buttons.addStretch(1)

        pol_and_pattern = QVBoxLayout()
        pol_and_pattern.addWidget(pol_box)
        pol_and_pattern.addWidget(pattern_box)

        options = QHBoxLayout()
        options.addLayout(pol_and_pattern)
        options.addWidget(scan_box)
        options.addWidget(optics_box)
        options.addLayout(buttons)
        options.addStretch(1)

        self._view_h = SteeringMapView("H")
        self._view_v = SteeringMapView("V")
        maps = QHBoxLayout()
        maps.addWidget(self._view_h, stretch=1)
        maps.addWidget(self._view_v, stretch=1)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m")
        self._status = QLabel("idle")

        layout = QVBoxLayout(self)
        layout.addLayout(options)
        layout.addLayout(maps, stretch=1)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)

    @staticmethod
    def _spin(value, low, high, step, decimals, suffix):
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setValue(value)
        return box

    def _selected_pol(self):
        h_on = self._pol_h.isChecked()
        v_on = self._pol_v.isChecked()
        if h_on and v_on:
            return "HV"
        if h_on:
            return "H"
        if v_on:
            return "V"
        return None

    def _on_scan_button(self):
        if self._engine.running or self._busy:
            self._engine.stop()
            return

        pol = self._selected_pol()
        if pol is None:
            return

        self._engine.set_scan_parameters(
            f_mm=self._focal.value(),
            wav_nm=self._wave.value(),
            scan_radius_um=self._radius.value(),
            step_um=self._step.value(),
        )
        self._lock_instruments()
        self._busy = True
        started = self._engine.scan(
            pol,
            pattern_enabled=self._pattern.isChecked(),
            on_sample=self._on_sample,
            on_finished=self._queue_unlock,
        )
        if not started:
            self._busy = False
            self._unlock_instruments()

    def _on_save(self):
        try:
            folder = self._engine.save()
        except RuntimeError as exc:
            QMessageBox.warning(self, "SMF steering", str(exc))
            return
        self._status.setText(f"Saved {folder}")

    def _on_sample(self, power_w):
        self._powermeter_widget.feed(power_w)

    def _queue_unlock(self):
        QTimer.singleShot(0, self, self._unlock_instruments)

    def _lock_instruments(self):
        self._slm_widget.disable_user_interface()
        self._zernike_widget.setEnabled(False)
        self._powermeter_widget.reset_extrema()
        self._powermeter_widget.remote()

    def _unlock_instruments(self):
        try:
            self._slm_widget.enable_user_interface()
            self._zernike_widget.refresh_all_from_zernikes()
            self._zernike_widget.enable_user_interface(True)
            self._powermeter_widget.start()
        finally:
            self._busy = False

    def _refresh(self):
        maps, progress, running = self._engine.view_state()
        busy = running or self._busy
        self._apply_busy(busy)
        self._show_progress(progress, busy)
        self._show_map(self._view_h, "H", maps.get("H"))
        self._show_map(self._view_v, "V", maps.get("V"))

    def _apply_busy(self, busy):
        for box in self._input_boxes:
            box.setEnabled(not busy)
        self._save_button.setEnabled(not busy)
        if busy:
            self._scan_button.setText("Stop Steering Scan")
        else:
            self._scan_button.setText("Start Steering Scan")

    def _show_progress(self, progress, busy):
        total = int(progress["total"])
        iteration = int(progress["iteration"])
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(min(iteration, max(total, 1)))
        if self._status.text().startswith("Saved") and not busy:
            return
        pol = progress["active_pol"] or ""
        if busy:
            state = "stopping" if self._engine.stop_requested else "scanning"
            self._status.setText(f"{state}  {pol}  {iteration} / {total}".strip())
        elif total:
            self._status.setText(f"idle  {iteration} / {total}")
        else:
            self._status.setText("idle")

    @staticmethod
    def _show_map(view, pol, record):
        if record is None:
            view.set_caption(pol)
            return
        when = _clock(record["finished_at"])
        if when:
            view.set_caption(f"{pol}  {when}")
        else:
            view.set_caption(pol)
        view.set_map(record["power_w"], record["x_um"], record["y_um"])
