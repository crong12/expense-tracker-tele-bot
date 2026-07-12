import os
import ipaddress
import socket
import sys
from urllib.parse import urlparse

import pytest
from sqlalchemy.orm import sessionmaker
from pytest_socket import disable_socket, enable_socket

from database import create_database_engine


_REAL_CONNECT = socket.socket.connect


@pytest.fixture
def integration_test_support():
    return sys.modules[__name__]


def _validated_test_database_endpoint():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        pytest.fail("TEST_DATABASE_URL must include a host and port")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.lower() != "localhost":
            pytest.fail("TEST_DATABASE_URL must resolve only to loopback addresses")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, port)}
        except socket.gaierror as error:
            pytest.fail(f"Cannot resolve TEST_DATABASE_URL host: {error}")
    else:
        addresses = {str(address)}

    if not addresses or any(not ipaddress.ip_address(item).is_loopback for item in addresses):
        pytest.fail("TEST_DATABASE_URL must resolve only to loopback addresses")
    return url, host, port, addresses


def _create_validated_postgres_engine():
    url, _, _, _ = _validated_test_database_endpoint()
    return create_database_engine(url)


@pytest.fixture(autouse=True)
def _allow_only_test_database_endpoint(monkeypatch):
    if not os.environ.get("TEST_DATABASE_URL"):
        yield
        return
    _, host, port, addresses = _validated_test_database_endpoint()
    allowed = {(address, port) for address in addresses} | {(host, port)}

    def guarded_connect(instance, address):
        endpoint = (address[0], address[1]) if isinstance(address, tuple) else None
        if endpoint not in allowed:
            raise RuntimeError(f"Socket endpoint is not the test database: {endpoint}")
        return _REAL_CONNECT(instance, address)

    enable_socket()
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    try:
        yield
    finally:
        disable_socket()


@pytest.fixture(scope="session")
def postgres_engine():
    engine = _create_validated_postgres_engine()
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")
    with engine.connect() as connection:
        major = int(connection.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000
    if major != 16:
        engine.dispose()
        pytest.fail(f"PostgreSQL 16 is required, got major version {major}")

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
