"""What each tool does to the Kit app, as MCP tool annotations: hints a client may use to ask before it runs one; and
tool(), which registers a tool with its hints.

They are hints, never security: the bridge's token is what keeps others out (docs/ARCHITECTURE.md).
"""

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

# Queries and captures: nothing in the stage, the simulation or the viewport changes.
READS = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Changes that destroy nothing: transforms, new prims, materials, the camera, lights, the simulation's state.
EDITS = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
# Deletes or overwrites: prims, the whole stage, USD files on disk.
DESTROYS = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
# Runs Python or loads extensions inside the Kit app: anything can happen, beyond the stage too.
RUNS = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

F = TypeVar("F", bound=Callable[..., Any])


def tool(mcp: MCPServer, hints: ToolAnnotations) -> Callable[[F], F]:
    """Registers the function it decorates as a tool with these hints, its docstring the description.

    The SDK sends a docstring as __doc__ holds it, and Python before 3.13 keeps the source's indentation there, so
    every line but the first reached the client indented: cleandoc takes it out.
    """

    def register(fn: F) -> F:
        return mcp.tool(annotations=hints, description=inspect.cleandoc(fn.__doc__ or ""))(fn)

    return register
