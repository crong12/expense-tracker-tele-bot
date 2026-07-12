import csv
import importlib.util
import os
import sys
import socket
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession, sessionmaker

from database import CategoryRules, Expenses, Users, create_database_engine, create_session_factory
from pathlib import Path
from urllib.parse import urlparse

service_path = Path(__file__).parents[2] / "services" / "expenses_svc.py"
spec = importlib.util.spec_from_file_location("integration_expenses_svc", service_path)
expenses_svc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = expenses_svc
spec.loader.exec_module(expenses_svc)


pytestmark = pytest.mark.integration


def _user(telegram_id):
    return expenses_svc.get_or_create_user(telegram_id)


def _expense(user_id, *, amount="12.34", category="Food", description="Lunch", day=date(2026, 7, 1), currency="GBP"):
    return expenses_svc.insert_expense(user_id, Decimal(amount), category, description, day, currency)


def test_engine_and_session_factory_use_explicit_postgres_url(postgres_engine):
    engine = create_database_engine(str(postgres_engine.url))
    factory = create_session_factory(engine)
    try:
        assert factory.kw["bind"] is engine
        assert engine.dialect.name == "postgresql"
    finally:
        engine.dispose()


def test_users_are_stable_and_distinct(db):
    first = _user(1001)
    assert _user(1001) == first
    assert _user(1002) != first


def test_preferred_currency_defaults_and_persists(db):
    _user(1101)
    assert expenses_svc.get_user_preferred_currency(1101) == "GBP"
    assert expenses_svc.set_user_preferred_currency(1101, "EUR") is True
    assert expenses_svc.get_user_preferred_currency(1101) == "EUR"


def test_categories_are_distinct_and_user_isolated(db):
    one, two = _user(1201), _user(1202)
    _expense(one, category="Food")
    _expense(one, category="Food", description="Dinner")
    _expense(one, category="Travel")
    _expense(two, category="Private")
    assert set(expenses_svc.get_categories(one)) == {"Food", "Travel"}
    assert expenses_svc.get_categories(two) == ["Private"]


def test_insert_stores_all_fields_for_the_selected_user(db):
    user_id = _user(1301)
    expense_id = _expense(user_id, amount="19.95", category="Travel", description="Train", day=date(2026, 6, 30), currency="EUR")
    with db() as session:
        stored = session.get(Expenses, expense_id)
        assert (stored.user_id, stored.price, stored.category, stored.description, stored.date, stored.currency) == (
            user_id, Decimal("19.95"), "Travel", "Train", date(2026, 6, 30), "EUR"
        )


def test_update_changes_only_selected_expense_and_missing_returns_false(db):
    user_id = _user(1401)
    selected = _expense(user_id, description="Before")
    untouched = _expense(user_id, amount="8.00", description="Other")
    assert expenses_svc.update_expense(selected, Decimal("20.00"), "Travel", "After", date(2026, 7, 2), "USD") == selected
    assert expenses_svc.update_expense(999999, Decimal("1"), "X", "Missing", date(2026, 1, 1), "GBP") is False
    with db() as session:
        assert session.get(Expenses, selected).description == "After"
        assert session.get(Expenses, untouched).description == "Other"


def test_exact_matching_returns_expected_id_and_rejects_nonmatch(db):
    expense_id = _expense(_user(1501), amount="7.50", category="Coffee", description="Flat white", day=date(2026, 7, 3), currency="GBP")
    text = "Currency: GBP\nAmount: 7.50\nCategory: Coffee\nDescription: Flat white\nDate: 2026-07-03"
    assert expenses_svc.exact_expense_matching(text) == expense_id
    assert expenses_svc.exact_expense_matching(text.replace("Flat white", "Tea")) is None


def test_exact_matching_rejects_identical_cross_user_matches(db):
    first, second = _user(1502), _user(1503)
    first_id = _expense(first, amount="7.50", category="Coffee", description="Shared", day=date(2026, 7, 3), currency="GBP")
    second_id = _expense(second, amount="7.50", category="Coffee", description="Shared", day=date(2026, 7, 3), currency="GBP")
    text = "Currency: GBP\nAmount: 7.50\nCategory: Coffee\nDescription: Shared\nDate: 2026-07-03"
    assert expenses_svc.exact_expense_matching(text) is None
    assert first_id != second_id


def test_specific_and_bulk_deletion_are_user_isolated(db):
    one, two = _user(1601), _user(1602)
    one_a, one_b, two_a = _expense(one), _expense(one, description="Second"), _expense(two, description="Private")
    assert expenses_svc.delete_specific_expense(one, two_a) is False
    assert expenses_svc.delete_specific_expense(one, one_a) is True
    assert expenses_svc.delete_all_expenses(one) is True
    with db() as session:
        assert session.get(Expenses, one_a) is None
        assert session.get(Expenses, one_b) is None
        assert session.get(Expenses, two_a) is not None


def test_category_rules_persist_update_and_remain_isolated(db):
    one, two = _user(1701), _user(1702)
    assert expenses_svc.insert_category_rule(one, "TESCO", "Groceries") is True
    assert expenses_svc.insert_category_rule(one, "tesco", "Food") is True
    assert expenses_svc.insert_category_rule(two, "tesco", "Private") is True
    assert expenses_svc.get_category_rules(one) == [{"keyword": "tesco", "category": "Food"}]
    assert expenses_svc.get_category_rules(two) == [{"keyword": "tesco", "category": "Private"}]


def _read_export(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    result = expenses_svc.export_expenses_to_csv(*args)
    if result is None:
        return None
    with open(result, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_exports_ranges_empty_and_deterministic_order(db, tmp_path, monkeypatch):
    user_id, other = _user(1801), _user(1802)
    today = datetime.now().date()
    same_month_early = today.replace(day=1)
    same_month_late = today.replace(day=min(2, today.day))
    _expense(user_id, description="Late", day=same_month_late)
    _expense(user_id, description="Early", day=same_month_early)
    _expense(user_id, description="Old", day=date(2020, 1, 1))
    _expense(other, description="Private", day=same_month_early)

    rows = _read_export(tmp_path, monkeypatch, user_id, "all", "all_expenses")
    assert [row["Description"] for row in rows] == ["Old", "Early", "Late"]
    assert list(rows[0]) == ["Date", "Description", "Category", "Price", "Currency"]
    assert [row["Description"] for row in _read_export(tmp_path, monkeypatch, user_id, "month", "this_month")] == ["Early", "Late"]
    assert [row["Description"] for row in _read_export(tmp_path, monkeypatch, user_id, "day", "custom_range", same_month_early, same_month_early)] == ["Early"]
    assert [row["Description"] for row in _read_export(tmp_path, monkeypatch, user_id, "range", "custom_range", same_month_early, same_month_late)] == ["Early", "Late"]
    assert _read_export(tmp_path, monkeypatch, _user(1803), "empty", "all_expenses") is None
    with pytest.raises(ValueError, match="must not be after"):
        expenses_svc.export_expenses_to_csv(user_id, "bad", "custom_range", same_month_late, same_month_early)


def test_export_breaks_same_date_ties_by_expense_id(db, tmp_path, monkeypatch):
    user_id = _user(1804)
    shared_date = date(2026, 5, 5)
    with db() as session:
        session.add_all([
            Expenses(id=900002, user_id=user_id, price=1, category="Food", description="Higher id", date=shared_date, currency="GBP"),
            Expenses(id=900001, user_id=user_id, price=1, category="Food", description="Lower id", date=shared_date, currency="GBP"),
        ])
        session.commit()
    rows = _read_export(tmp_path, monkeypatch, user_id, "ties", "all_expenses")
    assert [row["Description"] for row in rows] == ["Lower id", "Higher id"]


class FailingCommitSession(SASession):
    rollback_calls = 0
    close_calls = 0

    def commit(self):
        raise RuntimeError("forced commit failure")

    def rollback(self):
        FailingCommitSession.rollback_calls += 1
        super().rollback()

    def close(self):
        FailingCommitSession.close_calls += 1
        super().close()


def test_get_or_create_commit_failure_rolls_back_closes_and_preserves_exception(db, monkeypatch):
    FailingCommitSession.rollback_calls = FailingCommitSession.close_calls = 0
    monkeypatch.setattr(expenses_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=FailingCommitSession))
    with pytest.raises(RuntimeError, match="forced commit failure"):
        expenses_svc.get_or_create_user(1902)
    assert FailingCommitSession.rollback_calls == 1
    assert FailingCommitSession.close_calls == 1


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (lambda user, expense: expenses_svc.set_user_preferred_currency(1901, "EUR"), False),
        (lambda user, expense: expenses_svc.insert_expense(user, Decimal("1"), "Food", "Fail", date(2026, 1, 1), "GBP"), None),
        (lambda user, expense: expenses_svc.update_expense(expense, Decimal("2"), "Food", "Fail", date(2026, 1, 2), "GBP"), False),
        (lambda user, expense: expenses_svc.delete_all_expenses(user), False),
        (lambda user, expense: expenses_svc.delete_specific_expense(user, expense), False),
        (lambda user, expense: expenses_svc.insert_category_rule(user, "fail", "Food"), False),
    ],
)
def test_write_commit_failures_roll_back_close_and_return_documented_value(db, monkeypatch, operation, expected):
    user = _user(1901)
    expense = _expense(user)
    FailingCommitSession.rollback_calls = FailingCommitSession.close_calls = 0
    monkeypatch.setattr(expenses_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=FailingCommitSession))
    assert operation(user, expense) is expected
    assert FailingCommitSession.rollback_calls == 1
    assert FailingCommitSession.close_calls == 1


def test_read_sessions_close_deterministically(db, monkeypatch):
    closes = []
    class TrackingSession(SASession):
        def close(self):
            closes.append(True)
            super().close()
    factory = sessionmaker(bind=db.kw["bind"], class_=TrackingSession)
    monkeypatch.setattr(expenses_svc, "SessionLocal", factory)
    expenses_svc.get_user_preferred_currency(999999)
    assert closes == [True]


def test_exact_matching_closes_session_when_parsing_raises(db, monkeypatch):
    closes = []
    class TrackingSession(SASession):
        def close(self):
            closes.append(True)
            super().close()
    monkeypatch.setattr(expenses_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=TrackingSession))
    with pytest.raises(AttributeError):
        expenses_svc.exact_expense_matching("malformed")
    assert closes == [True]


def test_integration_socket_guard_allows_database_only(db):
    with db() as session:
        assert session.execute(select(1)).scalar_one() == 1
    database_port = urlparse(os.environ["TEST_DATABASE_URL"]).port
    for endpoint in (("127.0.0.1", database_port + 1), ("8.8.8.8", 53)):
        candidate = socket.socket()
        try:
            with pytest.raises(RuntimeError, match="not the test database"):
                candidate.connect(endpoint)
        finally:
            candidate.close()
