"""Version helper for AVD4Linux."""

import sys

__version__ = "0.2.8.1"

try:
    if sys.version_info >= (3, 8):
        from importlib.metadata import PackageNotFoundError, version
        try:
            __version__ = version("avd4linux")
        except PackageNotFoundError:
            pass
except Exception:
    pass
