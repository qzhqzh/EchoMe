"""EchoMe MCP Server - Personal memory access for AI CLI tools."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("echome")
except PackageNotFoundError:
    __version__ = "1.8.0"
