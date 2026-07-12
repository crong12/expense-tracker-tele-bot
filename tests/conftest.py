import os
import socket

import pytest
from pytest_socket import disable_socket, enable_socket


INERT_ENVIRONMENT = {
    "TELE_BOT_TOKEN": "test-token",
    "REGION": "test-region",
    "REGION2": "test-region-2",
    "DB_USER": "test-user",
    "DB_PASSWORD": "test-password",
    "DB_NAME": "test-db",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "OPENAI_API_KEY": "test-openai-key",
    "LANGSMITH_API_KEY": "test-langsmith-key",
    "GOOGLE_CLOUD_PROJECT": "test-project",
}

for name, value in INERT_ENVIRONMENT.items():
    os.environ[name] = value


_REAL_SOCKETPAIR = socket.socketpair


def _asyncio_socketpair():
    """Create only the private loopback pair used by Windows event loops."""
    enable_socket()
    try:
        return _REAL_SOCKETPAIR()
    finally:
        disable_socket()


@pytest.fixture(autouse=True)
def _block_network_access(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        enable_socket()
    else:
        # Windows asyncio needs one private loopback pair; all test-created
        # sockets, including connections to local services, remain blocked.
        monkeypatch.setattr(socket, "socketpair", _asyncio_socketpair)
        disable_socket()
    yield
    enable_socket()


@pytest.fixture
def tests_tmp_path(tmp_path, monkeypatch):
    path = str(tmp_path)
    monkeypatch.setenv("TEMP", path)
    monkeypatch.setenv("TMP", path)
    return tmp_path
