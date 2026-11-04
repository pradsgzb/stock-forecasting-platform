"""Stock forecasting platform foundation package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stock-forecasting-platform")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.6.0"

__all__ = ["__version__"]
