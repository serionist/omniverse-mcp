"""What every tool does with the bridge: one request, and its error as a tool error."""

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from omniverse_mcp.client import BridgeError

# How much of the bridge's traceback a tool error carries: enough to place the failure, short enough to read.
TRACEBACK_LINES = 5


def bridge_call(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """The bridge's answer to one request, when it succeeded.

    Otherwise ToolError, which the MCP client gets as an error result (isError) the model reads: the bridge's own
    error with the last lines of its traceback, or why the Kit app couldn't be reached or refused the request.
    """
    try:
        resp = fn(*args, **kwargs)
    except (OSError, BridgeError) as e:
        raise ToolError(f"Kit app connection failed: {e}") from e
    if resp.get("status") == "error":
        message = str(resp.get("error", "the bridge reported an error"))
        traceback = str(resp.get("traceback", "")).strip()
        if traceback:
            message += "\n" + "\n".join(traceback.splitlines()[-TRACEBACK_LINES:])
        raise ToolError(message)
    return resp
