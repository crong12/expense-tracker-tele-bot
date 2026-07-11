"""Expose real handler submodules without running cloud-backed package setup."""

import sys
import types
from pathlib import Path


def ensure_focused_handlers_package():
    """Install only a namespace pointing at the repository's real handlers."""
    if "handlers" not in sys.modules:
        handlers_package = types.ModuleType("handlers")
        handlers_package.__path__ = [
            str(Path(__file__).parents[1] / "handlers")
        ]
        handlers_package.__package__ = "handlers"
        sys.modules["handlers"] = handlers_package


ensure_focused_handlers_package()
