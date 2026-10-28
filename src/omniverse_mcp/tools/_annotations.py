"""What each tool does to the Kit app, as MCP tool annotations: hints a client may use to ask before it runs one.

They are hints, never security: the bridge's token is what keeps others out (docs/ARCHITECTURE.md).
"""

from mcp.types import ToolAnnotations

# Queries and captures: nothing in the stage, the simulation or the viewport changes.
READS = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Changes that destroy nothing: transforms, new prims, materials, the camera, lights, the simulation's state.
EDITS = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
# Deletes or overwrites: prims, the whole stage, USD files on disk.
DESTROYS = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
# Runs Python or loads extensions inside the Kit app: anything can happen, beyond the stage too.
RUNS = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)
