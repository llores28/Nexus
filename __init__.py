"""Nexus — Intelligent Project Operating System."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nexus-bootstrap")
except PackageNotFoundError:  # source tree before installation
    __version__ = "0.3.0"
