import importlib.util
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession, sessionmaker

from database import WhitelistedUsers


service_path = Path(__file__).parents[2] / "services" / "whitelist_svc.py"
spec = importlib.util.spec_from_file_location("integration_whitelist_svc", service_path)
whitelist_svc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = whitelist_svc
spec.loader.exec_module(whitelist_svc)

pytestmark = pytest.mark.integration


def test_empty_whitelist_lookup_returns_false(db):
    assert whitelist_svc.is_user_whitelisted("missing") is False


def test_add_without_notes_persists_null_notes(db):
    assert whitelist_svc.add_to_whitelist("alice") is True
    with db() as session:
        user = session.scalar(select(WhitelistedUsers).where(WhitelistedUsers.username == "alice"))
        assert user.notes is None


def test_add_with_notes_and_list_expose_public_serializable_fields(db):
    assert whitelist_svc.add_to_whitelist("bob", "family") is True
    listed = whitelist_svc.get_all_whitelisted_users()
    assert listed[0]["username"] == "bob"
    assert listed[0]["notes"] == "family"
    assert set(listed[0]) == {"username", "added_date", "notes"}
    json.dumps(listed)


def test_duplicate_add_returns_false_and_keeps_one_row(db):
    assert whitelist_svc.add_to_whitelist("carol") is True
    assert whitelist_svc.add_to_whitelist("CAROL", "duplicate") is False
    with db() as session:
        assert session.scalar(select(func.count()).select_from(WhitelistedUsers)) == 1
        assert session.scalar(select(WhitelistedUsers.notes)) is None


def test_remove_existing_succeeds_and_removes_row(db):
    assert whitelist_svc.add_to_whitelist("dave") is True
    assert whitelist_svc.remove_from_whitelist("dave") is True
    assert whitelist_svc.is_user_whitelisted("dave") is False


def test_remove_missing_returns_false(db):
    assert whitelist_svc.remove_from_whitelist("nobody") is False


def test_listing_is_ordered_by_username(db):
    for username in ("zoe", "amy", "mike"):
        assert whitelist_svc.add_to_whitelist(username) is True
    assert [row["username"] for row in whitelist_svc.get_all_whitelisted_users()] == ["amy", "mike", "zoe"]


def test_usernames_are_lowercased_and_leading_at_is_stripped(db):
    assert whitelist_svc.add_to_whitelist("@MixedCase") is True
    assert whitelist_svc.is_user_whitelisted("MIXEDCASE") is True
    assert whitelist_svc.is_user_whitelisted("@mixedcase") is True
    with db() as session:
        assert session.scalar(select(WhitelistedUsers.username)) == "mixedcase"


class TrackingSession(SASession):
    close_calls = 0

    def close(self):
        TrackingSession.close_calls += 1
        super().close()


@pytest.mark.parametrize(
    "operation",
    [
        lambda: whitelist_svc.is_user_whitelisted("missing"),
        lambda: whitelist_svc.add_to_whitelist("existing"),
        lambda: whitelist_svc.remove_from_whitelist("missing"),
        whitelist_svc.get_all_whitelisted_users,
    ],
)
def test_opened_sessions_close_on_success_and_early_return(db, monkeypatch, operation):
    assert whitelist_svc.add_to_whitelist("existing") is True
    TrackingSession.close_calls = 0
    monkeypatch.setattr(whitelist_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=TrackingSession))
    operation()
    assert TrackingSession.close_calls == 1


class FailingCommitSession(TrackingSession):
    rollback_calls = 0

    def commit(self):
        raise RuntimeError("forced commit failure")

    def rollback(self):
        FailingCommitSession.rollback_calls += 1
        super().rollback()


@pytest.mark.parametrize(
    "prepare,operation",
    [
        (lambda: None, lambda: whitelist_svc.add_to_whitelist("write-fail")),
        (lambda: whitelist_svc.add_to_whitelist("remove-fail"), lambda: whitelist_svc.remove_from_whitelist("remove-fail")),
    ],
)
def test_write_commit_failure_rolls_back_closes_and_returns_false(db, monkeypatch, prepare, operation):
    prepare()
    FailingCommitSession.rollback_calls = 0
    TrackingSession.close_calls = 0
    monkeypatch.setattr(whitelist_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=FailingCommitSession))
    assert operation() is False
    assert FailingCommitSession.rollback_calls == 1
    assert TrackingSession.close_calls == 1


class FailingQuerySession(TrackingSession):
    def query(self, *args, **kwargs):
        raise RuntimeError("forced query failure")


@pytest.mark.parametrize(
    "operation,expected",
    [
        (lambda: whitelist_svc.is_user_whitelisted("read-fail"), False),
        (whitelist_svc.get_all_whitelisted_users, []),
        (lambda: whitelist_svc.add_to_whitelist("query-fail"), False),
        (lambda: whitelist_svc.remove_from_whitelist("query-fail"), False),
    ],
)
def test_query_exceptions_return_safe_values_and_close(db, monkeypatch, operation, expected):
    TrackingSession.close_calls = 0
    monkeypatch.setattr(whitelist_svc, "SessionLocal", sessionmaker(bind=db.kw["bind"], class_=FailingQuerySession))
    assert operation() == expected
    assert TrackingSession.close_calls == 1
