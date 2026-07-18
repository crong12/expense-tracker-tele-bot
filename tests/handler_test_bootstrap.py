"""Expose real handler submodules without running cloud-backed package setup."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def ensure_focused_handlers_package():
    """Install only a namespace pointing at the repository's real handlers."""
    if "handlers" not in sys.modules:
        handlers_package = types.ModuleType("handlers")
        handlers_package.__path__ = [
            str(Path(__file__).parents[1] / "handlers")
        ]
        handlers_package.__package__ = "handlers"
        sys.modules["handlers"] = handlers_package


def ensure_focused_handler_dependencies():
    """Provide inert direct dependencies for isolated handler imports."""
    if "config" not in sys.modules:
        config = types.ModuleType("config")
        (
            config.WAITING_FOR_EXPENSE,
            config.AWAITING_CONFIRMATION,
            config.AWAITING_REFINEMENT,
            config.AWAITING_EDIT,
            config.AWAITING_DELETE_REQUEST,
            config.AWAITING_DELETE_CONFIRMATION,
            config.AWAITING_QUERY,
            config.AWAITING_EXPORT_CONFIRMATION,
            config.AWAITING_CATEGORY_RULE,
        ) = range(9)
        sys.modules["config"] = config

    if "services" not in sys.modules:
        services = types.ModuleType("services")
        services.get_or_create_user = MagicMock()
        sys.modules["services"] = services


ensure_focused_handlers_package()
ensure_focused_handler_dependencies()
