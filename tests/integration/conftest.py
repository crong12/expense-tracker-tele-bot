import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def postgres_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")

    from database import Base

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(postgres_engine, monkeypatch):
    from database import CategoryRules, Expenses, Users, WhitelistedUsers
    expenses_svc = sys.modules["integration_expenses_svc"]

    factory = sessionmaker(bind=postgres_engine)
    monkeypatch.setattr(expenses_svc, "SessionLocal", factory)
    with postgres_engine.begin() as connection:
        for table in (CategoryRules, Expenses, WhitelistedUsers, Users):
            connection.execute(table.__table__.delete())
    yield factory
    with postgres_engine.begin() as connection:
        for table in (CategoryRules, Expenses, WhitelistedUsers, Users):
            connection.execute(table.__table__.delete())
