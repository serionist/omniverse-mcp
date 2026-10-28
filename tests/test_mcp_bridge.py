"""The `mcp` object execute_script scripts get: its signatures, checked without Kit."""

import importlib.util

import pytest

from .conftest import EXTENSION_ROOT

# Loaded from its file: the handlers package it belongs to imports Kit, and the class imports its handlers lazily.
_spec = importlib.util.spec_from_file_location(
    "mcp_bridge_under_test", EXTENSION_ROOT / "isaacsim" / "mcp" / "bridge" / "handlers" / "_mcp_bridge.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def test_inspect_refuses_an_old_positional_distance():
    with pytest.raises(TypeError):
        _module.MCPBridge().inspect("/World/Cube", None, 640, 480, 5.0)
