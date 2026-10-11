"""VideoMaker パッケージの公開インターフェース。"""

from importlib.metadata import version

__all__ = ["get_version"]


def get_version() -> str:
    """パッケージバージョンを返す。"""
    try:
        return version("videomaker")
    except Exception:  # pragma: no cover
        return "0.1.0"
