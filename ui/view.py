"""One steering map. This widget does not know the scan engine."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..grid import pixel_edges


def _power_colormap():
    return pg.colormap.getFromMatplotlib("jet")


class SteeringMapView(QWidget):
    """Power image on micrometre axes. ``values`` are watts; the plot shows ``scale``."""

    def __init__(self, title, scale=1e9, unit="nW", parent=None):
        super().__init__(parent)
        self._title = title
        self._scale = float(scale)
        self._unit = unit
        self._extent_key = None

        pg.setConfigOptions(useOpenGL=False, antialias=False)
        self._graphics = pg.GraphicsLayoutWidget()
        self._plot = self._graphics.addPlot(row=0, col=0, title=title)
        self._plot.setLabel("bottom", "x", units="um")
        self._plot.setLabel("left", "y", units="um")
        self._plot.getAxis("bottom").enableAutoSIPrefix(False)
        self._plot.getAxis("left").enableAutoSIPrefix(False)
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=False, y=False)

        self._image = pg.ImageItem(axisOrder="row-major")
        cmap = _power_colormap()
        self._image.setColorMap(cmap)
        self._plot.addItem(self._image)

        self._colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=cmap,
            label=f"power ({unit})",
            width=18,
        )
        self._graphics.addItem(self._colorbar, row=0, col=1)
        self._colorbar.setImageItem(self._image)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)

    def set_caption(self, text):
        self._plot.setTitle(text)

    def set_map(self, values, x_um, y_um):
        """Draw ``values`` (watts). NaNs stay empty. Pixel centers sit on the axes."""
        shown = np.asarray(values, dtype=float) * self._scale
        self._image.setImage(shown, autoLevels=False)

        x0, x1 = pixel_edges(x_um)
        y0, y1 = pixel_edges(y_um)
        self._image.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))

        finite = shown[np.isfinite(shown)]
        if finite.size:
            low = float(finite.min())
            high = float(finite.max())
            if low == high:
                high = low + 1.0
            self._image.setLevels((low, high))
            self._colorbar.setLevels((low, high))

        extent_key = (float(x0), float(x1), float(y0), float(y1), shown.shape)
        if extent_key != self._extent_key:
            self._extent_key = extent_key
            self._plot.autoRange()
