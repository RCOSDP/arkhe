"""arkhe: infrastructure for ARK identifiers."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    #: The version is decided in one place. This reads what pyproject set, through the
    #: installed metadata. Written twice, one copy always goes stale.
    __version__ = _version("arkhe")
except PackageNotFoundError:  # pragma: no cover - running straight from the repository
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
