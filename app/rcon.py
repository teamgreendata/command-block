"""Per-request RCON wrapper: connect -> auth -> send -> close.

One connection per command on purpose — the server is quiet enough that
pooling is complexity without payoff (build plan, Part C).
"""

from aiomcrcon import Client, IncorrectPasswordError, RCONConnectionError


class RconError(Exception):
    """RCON failure with a message safe to show in the UI."""


# The socket dying mid-command is the *expected* outcome of `stop`.
_DISCONNECT_ERRORS = (OSError, EOFError)


async def execute(
    host: str,
    port: int,
    password: str,
    command: str,
    *,
    expect_disconnect: bool = False,
) -> str:
    client = Client(host, port, password)
    try:
        try:
            await client.connect()
        except IncorrectPasswordError:
            raise RconError(
                "RCON password rejected — compare RCON_PASSWORD with the "
                "minecraft stack's .env (and remember it was baked into "
                "server.properties at world creation)."
            )
        except (RCONConnectionError, *_DISCONNECT_ERRORS):
            raise RconError(
                f"Can't reach RCON at {host}:{port} — is the Minecraft server up?"
            )
        try:
            response, _ = await client.send_cmd(command, timeout=10.0)
            return response
        except _DISCONNECT_ERRORS:
            if expect_disconnect:
                return ""
            raise RconError(
                "RCON connection dropped mid-command — the server may be restarting."
            )
    finally:
        try:
            await client.close()
        except Exception:
            pass
