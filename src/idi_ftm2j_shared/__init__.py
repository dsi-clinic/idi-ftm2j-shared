"""Shared runtime utilities for FTM2J pipeline processors."""

from importlib.metadata import version

__version__ = version("idi-ftm2j-shared")

__all__ = ["__version__", "get_version"]


def get_version() -> str:
    """Return the installed package version."""
    return __version__
