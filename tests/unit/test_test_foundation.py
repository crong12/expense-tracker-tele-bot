import asyncio
import os
import socket
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError


pytestmark = pytest.mark.unit


def test_required_environment_overwrites_existing_values():
    assert os.environ["TELE_BOT_TOKEN"] == "test-token"


def test_default_network_policy_blocks_loopback_tcp():
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)


def test_default_network_policy_allows_asyncio_internal_socket_pair():
    loop = asyncio.new_event_loop()
    loop.close()


def test_ci_runs_feature_branches_once_via_pull_requests():
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "test.yml").read_text()

    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:" in workflow
