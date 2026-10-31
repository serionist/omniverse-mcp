"""What every tool does with the bridge: one request, and its error as a tool error."""

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from omniverse_mcp.client import BridgeError
from omniverse_mcp.kit_extension import install_command

# How much of the bridge's traceback a tool error carries: enough to place the failure, short enough to read.
TRACEBACK_LINES = 5
# How the bridge answers a route it hasn't got: an extension older than the tool that asked.
UNKNOWN_ROUTE = "Unknown endpoint"


def bridge_answer(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """The bridge's answer to one request, an error answer included.

    ToolError only when the Kit app couldn't be reached or refused the request: a tool that reads an error answer as
    part of its own, such as get_robot_info's joint states, still fails when Kit is gone.
    """
    try:
        return fn(*args, **kwargs)
    except (OSError, BridgeError) as e:
        raise ToolError(f"Kit app connection failed: {e}") from e


def bridge_call(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """The bridge's answer to one request, when it succeeded.

    Otherwise ToolError, which the MCP client gets as an error result (isError) the model reads: the bridge's own
    error with the last lines of its traceback, or why the Kit app couldn't be reached or refused the request. A route
    the extension hasn't got also names the command that installs this server's.
    """
    resp = bridge_answer(fn, *args, **kwargs)
    if resp.get("status") == "error":
        message = str(resp.get("error", "the bridge reported an error"))
        if message.startswith(UNKNOWN_ROUTE):
            message += (
                ". The Kit extension is older than this MCP server and lacks this tool: install the server's, "
                f"{install_command()}, then restart Kit"
            )
        traceback = str(resp.get("traceback", "")).strip()
        if traceback:
            message += "\n" + "\n".join(traceback.splitlines()[-TRACEBACK_LINES:])
        raise ToolError(message)
    return resp
