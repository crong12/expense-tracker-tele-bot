import asyncio
import os
import socket

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
