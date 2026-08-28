"""arkhe — ARK 識別子の基盤。"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    #: **版はここだけで決める。** pyproject の値をインストール済みメタデータから引く。
    #: 版を 2 か所に書くと、必ずどちらかが古くなる。
    __version__ = _version("arkhe")
except PackageNotFoundError:  # pragma: no cover - リポジトリから直接動かした場合
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
