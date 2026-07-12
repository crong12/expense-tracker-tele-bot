import os

import pytest
from pytest_socket import enable_socket, socket_allow_hosts


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
    os.environ.setdefault(name, value)


@pytest.fixture(autouse=True)
def _block_network_access(request):
    if request.node.get_closest_marker("live"):
        enable_socket()
    else:
        # Windows asyncio uses a loopback socket pair to wake its event loop.
        socket_allow_hosts(["localhost", "127.0.0.1", "::1"])
    yield


@pytest.fixture
def tests_tmp_path(tmp_path, monkeypatch):
    path = str(tmp_path)
    monkeypatch.setenv("TEMP", path)
    monkeypatch.setenv("TMP", path)
    return tmp_path
