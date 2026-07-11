import csv
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import Column, Date, Integer, String, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class LiteralDate(TypeDecorator):
    """Date type with literal rendering for the project's SQLAlchemy version."""

    impl = Date
    cache_ok = True

    def literal_processor(self, dialect):
        return lambda value: repr(value.isoformat())


class Expenses(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    date = Column(LiteralDate, nullable=False)
    description = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)


database_stub = types.ModuleType("database")
database_stub.SessionLocal = MagicMock()
database_stub.Users = type("Users", (), {})
database_stub.Expenses = Expenses
database_stub.CategoryRules = type("CategoryRules", (), {})

services_package = types.ModuleType("services")
services_package.__path__ = []
service_path = Path(__file__).parents[1] / "services" / "expenses_svc.py"
spec = importlib.util.spec_from_file_location("services.expenses_svc", service_path)
expenses_svc = importlib.util.module_from_spec(spec)
services_package.expenses_svc = expenses_svc

original_database = sys.modules.get("database")
original_services = sys.modules.get("services")
original_expenses_svc = sys.modules.get("services.expenses_svc")
sys.modules["database"] = database_stub
sys.modules["services"] = services_package
sys.modules["services.expenses_svc"] = expenses_svc
spec.loader.exec_module(expenses_svc)

if original_database is not None:
    sys.modules["database"] = original_database
else:
    del sys.modules["database"]
if original_services is not None:
    sys.modules["services"] = original_services
else:
    del sys.modules["services"]
sys.modules["services.expenses_svc"] = expenses_svc

export_expenses_to_csv = expenses_svc.export_expenses_to_csv
USER_ID = 42


class FakeResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class ExpenseExportTests(unittest.TestCase):
    def setUp(self):
        self.prior_services = sys.modules.get("services")
        sys.modules["services"] = services_package
        self.session = MagicMock()
        self.session_factory = MagicMock(return_value=self.session)
        self.session_patch = patch(
            "services.expenses_svc.SessionLocal", self.session_factory
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        if self.prior_services is not None:
            sys.modules["services"] = self.prior_services
        else:
            del sys.modules["services"]

    def _compile_executed_statement(self):
        statement = self.session.execute.call_args.args[0]
        return str(statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))

    def _export_in_temporary_directory(self, *args, expenses):
        self.session.execute.return_value = FakeResult(expenses)
        prior_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                file_path = export_expenses_to_csv(*args)
                if file_path is None:
                    return None
                with open(file_path, newline="", encoding="utf-8") as exported:
                    return list(csv.DictReader(exported))
            finally:
                os.chdir(prior_directory)

    def test_custom_range_requires_both_dates_before_opening_session(self):
        with self.assertRaisesRegex(ValueError, "requires start_date and end_date"):
            export_expenses_to_csv(USER_ID, "tester", "custom_range")
        self.session_factory.assert_not_called()

    def test_custom_range_rejects_reversed_dates_before_opening_session(self):
        with self.assertRaisesRegex(ValueError, "start_date must not be after end_date"):
            export_expenses_to_csv(
                USER_ID, "tester", "custom_range",
                start_date=date(2026, 7, 2), end_date=date(2026, 7, 1),
            )
        self.session_factory.assert_not_called()

    def test_custom_range_query_is_inclusive_and_ordered(self):
        expenses = [
            SimpleNamespace(date=date(2026, 7, 1), description="Start", category="Food", price=1, currency="GBP"),
            SimpleNamespace(date=date(2026, 7, 11), description="End", category="Travel", price=2, currency="GBP"),
        ]
        rows = self._export_in_temporary_directory(
            USER_ID, "tester", "custom_range",
            date(2026, 7, 1), date(2026, 7, 11), expenses=expenses,
        )

        self.assertEqual([row["Description"] for row in rows], ["Start", "End"])
        sql = self._compile_executed_statement()
        self.assertIn("expenses.date >= '2026-07-01'", sql)
        self.assertIn("expenses.date <= '2026-07-11'", sql)
        self.assertIn("ORDER BY expenses.date", sql)

    def test_one_day_custom_range_is_valid(self):
        self._export_in_temporary_directory(
            USER_ID, "tester", "custom_range",
            date(2026, 7, 11), date(2026, 7, 11), expenses=[],
        )
        sql = self._compile_executed_statement()
        self.assertIn("expenses.date >= '2026-07-11'", sql)
        self.assertIn("expenses.date <= '2026-07-11'", sql)

    def test_empty_result_returns_none(self):
        result = self._export_in_temporary_directory(
            USER_ID, "tester", "all_expenses", expenses=[]
        )
        self.assertIsNone(result)
        self.session.close.assert_called_once_with()

    def test_this_month_still_filters_month_and_year(self):
        self._export_in_temporary_directory(
            USER_ID, "tester", "this_month", expenses=[]
        )
        sql = self._compile_executed_statement()
        self.assertIn("EXTRACT(month FROM expenses.date)", sql)
        self.assertIn("EXTRACT(year FROM expenses.date)", sql)

    def test_all_expenses_remains_unbounded(self):
        self._export_in_temporary_directory(
            USER_ID, "tester", "all_expenses", expenses=[]
        )
        sql = self._compile_executed_statement()
        self.assertNotIn("expenses.date >=", sql)
        self.assertNotIn("expenses.date <=", sql)
        self.assertIn("ORDER BY expenses.date", sql)


if __name__ == "__main__":
    unittest.main()
