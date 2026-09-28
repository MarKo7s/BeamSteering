"""Micrometre scan grid to Zernike tilt. No hardware and no Qt."""

import numpy as np


def ax_to_n(ax_um, f_mm, wav_nm=843.5, aperture_mm=7.5):
    """Convert a focal-plane offset in micrometres to a Zernike tilt coefficient."""
    ax_mm = np.asarray(ax_um, dtype=float) * 1e-3
    wav_mm = float(wav_nm) * 1e-6
    return ax_mm * float(aperture_mm) / (wav_mm * float(f_mm))


def make_scan_grid(scan_radius_um, step_um, f_mm, wav_nm, aperture_mm):
    """Square window from ``-radius`` to ``+radius``, and the tilt grids for it.

    ``x_um`` and ``y_um`` are the 1D sample coordinates. ``nx`` and ``ny`` match
    ``meshgrid`` of those axes, in the same order the scan loop flattens.
    """
    step = float(step_um)
    if step <= 0:
        raise ValueError("step_um must be positive")
    radius = float(scan_radius_um)
    if radius < 0:
        raise ValueError("scan_radius_um must be non-negative")

    x_um = np.arange(-radius, radius + step, step)
    y_um = np.array(x_um, copy=True)
    x_grid, y_grid = np.meshgrid(x_um, y_um)
    nx = ax_to_n(x_grid, f_mm, wav_nm, aperture_mm)
    ny = ax_to_n(y_grid, f_mm, wav_nm, aperture_mm)
    return x_um, y_um, nx, ny


def pixel_edges(axis_um):
    """Half-pixel edges so sample coordinates sit on pixel centers."""
    axis = np.asarray(axis_um, dtype=float)
    if axis.size == 0:
        raise ValueError("scan axis is empty")
    if axis.size == 1:
        step = 1.0
    else:
        step = float(axis[1] - axis[0])
    return float(axis[0] - step / 2.0), float(axis[-1] + step / 2.0)
