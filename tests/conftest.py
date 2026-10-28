"""Puts the Kit extension's folder on sys.path, so tests import its Kit-free core (isaacsim.mcp.bridge.core)."""

import sys
from pathlib import Path

EXTENSION_ROOT = Path(__file__).resolve().parents[1] / "extension" / "isaacsim.mcp.bridge-1.0.0"
sys.path.insert(0, str(EXTENSION_ROOT))
