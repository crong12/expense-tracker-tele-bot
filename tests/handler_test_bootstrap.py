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


def ensure_focused_handler_dependencies(reset=False):
    """Provide inert direct dependencies for isolated handler imports."""
    if reset:
        for name in ("handlers.expenses_handler", "services.gemini_svc", "services.expenses_svc", "services.sql_agent_svc"):
            sys.modules.pop(name, None)
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

    def install(name, **attributes):
        module = types.ModuleType(name)
        for attribute, value in attributes.items():
            setattr(module, attribute, value)
        sys.modules[name] = module

    if "services.gemini_svc" not in sys.modules:
        install(
            "services.gemini_svc",
            process_expense_text=MagicMock(),
            process_expense_image=MagicMock(),
            refine_expense_details=MagicMock(),
        )
    if "services.expenses_svc" not in sys.modules:
        install(
            "services.expenses_svc",
            insert_expense=MagicMock(), update_expense=MagicMock(),
            get_or_create_user=MagicMock(), exact_expense_matching=MagicMock(),
            delete_all_expenses=MagicMock(), delete_specific_expense=MagicMock(),
            get_categories=MagicMock(), get_user_preferred_currency=MagicMock(),
            set_user_preferred_currency=MagicMock(), get_category_rules=MagicMock(),
            insert_category_rule=MagicMock(),
        )
    if "services.sql_agent_svc" not in sys.modules:
        install("services.sql_agent_svc", analyser_agent=MagicMock())


ensure_focused_handlers_package()
ensure_focused_handler_dependencies()
