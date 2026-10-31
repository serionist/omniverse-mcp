"""Puts the Kit extension's folder and tools/ on sys.path, so tests import the extension's Kit-free core
(ovmcp.core) and the gate, hooks and setup scripts."""

import os
import sys
from pathlib import Path

import pytest

from omniverse_mcp.config import parse_args

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "extension" / "ovmcp.bridge"
sys.path.insert(0, str(EXTENSION_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The live suites run only with OMNIVERSE_MCP_SIM=1 (plan D11). A Kit app that happens to answer on the bridge's
    port is someone's open stage, which the scenarios change, and the coverage floor must not depend on one."""
    if os.environ.get("OMNIVERSE_MCP_SIM") == "1":
        return
    skip = pytest.mark.skip(reason="a live suite: set OMNIVERSE_MCP_SIM=1, with a Kit app running ovmcp.bridge")
    for item in items:
        if item.get_closest_marker("sim") or item.get_closest_marker("scenario"):
            item.add_marker(skip)


# execute_script code for the live suites: sets one of ovmcp.core.capture's limits, its time or its count of frames;
# an extension from before the bounded waits has none to set. The token says whose change it is: by value alone, an
# earlier run's late undo would put back a later run's limit mid-test. `undo` puts it back, and runs by itself after
# 60 s in case the test can't.
SET_LIMIT = """
import asyncio
try:
    from ovmcp.core import capture
except ImportError:
    capture = None
undo = None
if capture is not None:
    token = object()
    capture._ovmcp_test_{name} = token
    capture.{name} = {value!r}

    def undo():
        if getattr(capture, "_ovmcp_test_{name}", None) is token:
            capture.{name} = {default!r}
            capture._ovmcp_test_{name} = None

    asyncio.get_running_loop().call_later(60, undo)
result = capture is not None
"""

# execute_script code for the live suites, with TARGET bound before it: where the viewport's camera is, how far its -Z
# axis points off TARGET, its world scale, and the xform attributes the root layer holds of it, which an aim must not
# leave there, since Kit keeps its own cameras in the session layer (#82). Not checked: a scene camera's
# omni:kit:centerOfInterest, which the aim may author in the root layer, as that camera's other attributes are.
CAMERA_AIM = """
import math
from omni.kit.viewport.utility import get_active_viewport
from pxr import Gf, Usd, UsdGeom
stage = omni.usd.get_context().get_stage()
path = str(get_active_viewport().camera_path)
matrix = UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
eye = matrix.ExtractTranslation()
looks = matrix.TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()
towards = (Gf.Vec3d(*TARGET) - eye).GetNormalized()
spec = stage.GetRootLayer().GetPrimAtPath(path)
result = {
    "camera": path,
    "eye": [eye[0], eye[1], eye[2]],
    "degrees": math.degrees(math.acos(max(-1.0, min(1.0, Gf.Dot(looks, towards))))),
    "scale": [matrix.GetRow3(i).GetLength() for i in range(3)],
    "root_xform": sorted(n for n in (spec.attributes.keys() if spec else []) if n.startswith("xformOp")),
}
"""

# execute_script code for the live suites: whether the viewport's own instance segmentation is on, read without
# turning it on. Captures segment through camera feeds of their own, so nothing of the bridge's turns it on (#76).
VIEWPORT_SEGMENTATION_ON = """
from omni.kit.viewport.utility import get_active_viewport
from omni.syntheticdata import SyntheticData
name = SyntheticData.convert_sensor_type_to_rendervar("InstanceSegmentation") + "ExportRawArray"
result = SyntheticData.Get().is_node_template_activated(name, get_active_viewport().render_product_path)
"""

# execute_script code that puts a limit SET_LIMIT set back, from a test's cleanup.
RESTORE_LIMIT = """
from ovmcp.core import capture
capture.{name} = {default!r}
capture._ovmcp_test_{name} = None
result = capture.{name}
"""


def live_bridge() -> tuple[str, int]:
    """Where the live suites find the bridge: OMNIVERSE_MCP_HOST and OMNIVERSE_MCP_PORT, read by the server's own
    parser, so a Kit app of your own can keep 8211 while another runs them. Read when a live suite starts."""
    args = parse_args([])
    return args.host, args.port


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private token folder, and no token from the environment: never the developer's real ones."""
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path
