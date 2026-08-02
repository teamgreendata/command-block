import asyncio

import pytest
from aiomcrcon import IncorrectPasswordError, RCONConnectionError

import app.rcon as rcon_mod
from app.rcon import RconError, execute


class FakeClient:
    connect_exc: Exception | None = None
    send_exc: Exception | None = None
    response = "ok"

    def __init__(self, host, port, password):
        pass

    async def connect(self):
        if self.connect_exc:
            raise self.connect_exc

    async def send_cmd(self, cmd, timeout=2.0):
        if self.send_exc:
            raise self.send_exc
        return (self.response, 1)

    async def close(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    class Client(FakeClient):
        pass

    monkeypatch.setattr(rcon_mod, "Client", Client)
    return Client


def run(coro):
    return asyncio.run(coro)


def test_success_returns_response(fake_client):
    assert run(execute("h", 25575, "pw", "list")) == "ok"


def test_wrong_password_is_clean_error(fake_client):
    fake_client.connect_exc = IncorrectPasswordError()
    with pytest.raises(RconError, match="password"):
        run(execute("h", 25575, "pw", "list"))


def test_unreachable_server_is_clean_error(fake_client):
    fake_client.connect_exc = RCONConnectionError("nope")
    with pytest.raises(RconError, match="reach"):
        run(execute("h", 25575, "pw", "list"))


def test_disconnect_mid_command_is_error_normally(fake_client):
    fake_client.send_exc = ConnectionResetError()
    with pytest.raises(RconError, match="dropped"):
        run(execute("h", 25575, "pw", "list"))


def test_disconnect_after_stop_is_success(fake_client):
    fake_client.send_exc = ConnectionResetError()
    assert run(execute("h", 25575, "pw", "stop", expect_disconnect=True)) == ""


def test_timeout_after_stop_is_success(fake_client):
    fake_client.send_exc = asyncio.TimeoutError()
    assert run(execute("h", 25575, "pw", "stop", expect_disconnect=True)) == ""
