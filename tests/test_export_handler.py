import importlib.util
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.ext import ConversationHandler


ROOT = Path(__file__).parents[1]
AWAITING_EXPORT_CONFIRMATION = 7
USER_ID = 42


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 7, 11)


handlers_package = types.ModuleType("handlers")
handlers_package.__path__ = [str(ROOT / "handlers")]
services_package = types.ModuleType("services")
services_package.__path__ = []
expenses_stub = types.ModuleType("services.expenses_svc")
expenses_stub.export_expenses_to_csv = MagicMock()
expenses_stub.get_or_create_user = MagicMock()
config_stub = types.ModuleType("config")
config_stub.AWAITING_EXPORT_CONFIRMATION = AWAITING_EXPORT_CONFIRMATION


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


saved_modules = {name: sys.modules.get(name) for name in (
    "services", "services.expenses_svc", "config",
)}
sys.modules["handlers"] = handlers_package
sys.modules["services"] = services_package
sys.modules["services.expenses_svc"] = expenses_stub
sys.modules["config"] = config_stub
export_calendar = load_module("handlers.export_calendar", ROOT / "handlers" / "export_calendar.py")
export_handler = load_module("handlers.export", ROOT / "handlers" / "export.py")
for name, module in saved_modules.items():
    if module is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = module

CalendarAction = export_calendar.CalendarAction
CalendarCallbackError = export_calendar.CalendarCallbackError
export_expenses = export_handler.export_expenses


def update_for(data):
    message = SimpleNamespace(reply_text=AsyncMock(), edit_text=AsyncMock())
    query = SimpleNamespace(data=data, answer=AsyncMock(), message=message)
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=123, username="tester"),
        effective_chat=SimpleNamespace(id=456),
    )


class ExportHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = SimpleNamespace(user_data={}, bot=SimpleNamespace(send_document=AsyncMock()))
        self.tempdir = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.tempdir.name, "expenses.csv")
        Path(self.csv_path).write_text("date,price\n", encoding="utf-8")
        self.patches = [
            patch.object(export_handler, "date", FixedDate),
            patch.object(export_handler, "get_or_create_user", return_value=USER_ID),
            patch.object(export_handler, "export_expenses_to_csv"),
            patch.object(export_handler, "build_calendar", return_value=MagicMock(name="calendar"), create=True),
            patch.object(export_handler, "parse_calendar_callback", create=True),
        ]
        self.mock_date, self.get_user, self.export_csv, self.build_calendar, self.parse_calendar_callback = [
            item.start() for item in self.patches
        ]

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tempdir.cleanup()

    async def test_custom_range_opens_start_calendar(self):
        result = await export_expenses(update_for("custom_range"), self.context)
        self.assertEqual(result, AWAITING_EXPORT_CONFIRMATION)
        self.build_calendar.assert_called_once_with(date(2026, 7, 1), date.min, date(2026, 7, 11))

    async def test_start_selection_is_persisted_as_iso_and_constrains_end_calendar(self):
        self.parse_calendar_callback.return_value = CalendarAction("select", date(2026, 6, 15))
        result = await export_expenses(update_for("xcal:d:2026-06-15"), self.context)
        self.assertEqual(self.context.user_data["export_start_date"], "2026-06-15")
        self.assertEqual(result, AWAITING_EXPORT_CONFIRMATION)
        self.build_calendar.assert_called_with(date(2026, 6, 1), date(2026, 6, 15), date(2026, 7, 11))

    async def test_end_selection_exports_inclusive_range_and_clears_state(self):
        self.context.user_data["export_start_date"] = "2026-06-15"
        self.parse_calendar_callback.return_value = CalendarAction("select", date(2026, 7, 11))
        self.export_csv.return_value = self.csv_path
        result = await export_expenses(update_for("xcal:d:2026-07-11"), self.context)
        self.export_csv.assert_called_once_with(
            USER_ID, "tester", time_range="custom_range",
            start_date=date(2026, 6, 15), end_date=date(2026, 7, 11),
        )
        self.assertNotIn("export_start_date", self.context.user_data)
        self.assertEqual(result, ConversationHandler.END)

    async def test_navigation_edits_calendar_without_storing_start_date(self):
        update = update_for("xcal:n:2026-06-01")
        self.parse_calendar_callback.return_value = CalendarAction("navigate", date(2026, 6, 1))
        result = await export_expenses(update, self.context)
        update.callback_query.message.edit_text.assert_awaited_once()
        self.assertNotIn("export_start_date", self.context.user_data)
        self.assertEqual(result, AWAITING_EXPORT_CONFIRMATION)

    async def test_invalid_callback_shows_alert_without_exporting(self):
        update = update_for("xcal:d:2099-01-01")
        self.parse_calendar_callback.side_effect = CalendarCallbackError("bad")
        result = await export_expenses(update, self.context)
        update.callback_query.answer.assert_awaited_once_with(
            "That calendar selection is no longer valid.", show_alert=True
        )
        self.export_csv.assert_not_called()
        self.assertEqual(result, AWAITING_EXPORT_CONFIRMATION)

    async def test_no_results_clears_start_date(self):
        update = update_for("xcal:d:2026-07-11")
        self.context.user_data["export_start_date"] = "2026-06-15"
        self.parse_calendar_callback.return_value = CalendarAction("select", date(2026, 7, 11))
        self.export_csv.return_value = None
        result = await export_expenses(update, self.context)
        self.assertNotIn("export_start_date", self.context.user_data)
        update.callback_query.message.reply_text.assert_awaited_once_with("No expenses found to export 😔")
        self.assertEqual(result, ConversationHandler.END)

    async def test_this_month_export_is_unchanged(self):
        self.export_csv.return_value = None
        await export_expenses(update_for("this_month"), self.context)
        self.export_csv.assert_called_once_with(
            USER_ID, "tester", time_range="this_month", start_date=None, end_date=None
        )

    async def test_all_expenses_export_is_unchanged(self):
        self.export_csv.return_value = None
        await export_expenses(update_for("all_expenses"), self.context)
        self.export_csv.assert_called_once_with(
            USER_ID, "tester", time_range="all_expenses", start_date=None, end_date=None
        )


if __name__ == "__main__":
    unittest.main()
