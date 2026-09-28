"""ModeLab tilt scan of coupled power around the current Zernike state."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("BeamSteering")
except PackageNotFoundError:
    __version__ = "1.0.0"

from .engine import ZernikeSteering

__all__ = [
    "ZernikeSteering",
    "__version__",
]
