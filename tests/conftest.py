"""Puts the Kit extension's folder and tools/ on sys.path, so tests import the extension's Kit-free core
(ovmcp.core) and the gate, hooks and setup scripts."""

import asyncio
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from omniverse_mcp.client import BridgeClient, BridgeError
from omniverse_mcp.config import parse_args
from omniverse_mcp.server import create_server

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "extension" / "ovmcp.bridge"
sys.path.insert(0, str(EXTENSION_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


NO_SIM = "a live suite: set OMNIVERSE_MCP_SIM=1, with a Kit app running ovmcp.bridge"
NO_GPU = (
    "the GPU module switches Kit to the GPU pipeline: set OMNIVERSE_MCP_SIM=1 and OMNIVERSE_MCP_GPU=1, on a Kit app of "
    "its own"
)
GPU_ALONE = "OMNIVERSE_MCP_GPU=1 is set: it runs the GPU module alone; unset it to run the live suites"


def live_rule(item: pytest.Item) -> tuple[str, str] | None:
    """What becomes of a test for OMNIVERSE_MCP_SIM and OMNIVERSE_MCP_GPU: ("skip", why), ("fail", why), or None when
    it runs.

    The live suites run only with OMNIVERSE_MCP_SIM=1 (plan D11). A Kit app that happens to answer on the bridge's
    port is someone's open stage, which the scenarios change, and the coverage floor must not depend on one.

    The GPU module (marker `gpu`, #68) switches the Kit app to the GPU pipeline, which a switch back doesn't fully undo
    (Fabric stays on, USD write-back off): it runs only with OMNIVERSE_MCP_SIM=1 and OMNIVERSE_MCP_GPU=1, and then
    alone, so no other live test reads the Kit app it changed. Its rule is read first and holds whatever SIM is. Under
    both, every other live test fails rather than skips: a PowerShell variable lasts the session, and one left set
    after a GPU run would otherwise pass the next run of the live suites with every test skipped.
    """
    sim = os.environ.get("OMNIVERSE_MCP_SIM") == "1"
    gpu = os.environ.get("OMNIVERSE_MCP_GPU") == "1"
    if item.get_closest_marker("gpu"):
        return None if sim and gpu else ("skip", NO_GPU)
    if item.get_closest_marker("sim") or item.get_closest_marker("scenario"):
        if not sim:
            return "skip", NO_SIM
        if gpu:
            return "fail", GPU_ALONE
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The live tests that skip, by live_rule."""
    for item in items:
        rule = live_rule(item)
        if rule is not None and rule[0] == "skip":
            item.add_marker(pytest.mark.skip(reason=rule[1]))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """The live tests that fail, by live_rule: at setup, before any fixture, so a unittest class's setUpClass never
    reaches Kit."""
    rule = live_rule(item)
    if rule is not None and rule[0] == "fail":
        pytest.fail(rule[1], pytrace=False)


# How long /health may take when a live call has timed out, before Kit counts as hung: a handler that runs long on
# Kit's loop holds /health back too, so it gets twice the scenarios' usual timeout.
PROBE_SECONDS = 20.0
Request = Callable[..., dict[str, Any]]
# BridgeClient.request as the client defines it, before the session's guard wraps it.
UNGUARDED: Request = BridgeClient.request


def health_answers(request: Request, host: str, port: int) -> bool:
    """Whether the bridge at host:port answers /health within PROBE_SECONDS, through request, the unwrapped
    BridgeClient.request."""
    probe = BridgeClient(host=host, port=port, timeout=PROBE_SECONDS)
    try:
        return request(probe, "/health", {}, "GET").get("status") == "success"
    except BridgeError:
        return True  # a refused token is an answer: Kit is running, perhaps restarted with another token
    except OSError:
        return False
    finally:
        probe.close()


class HungKit:
    """A Kit that stopped answering ends a live run at its first timeout (#54). Kit has hung inside NVIDIA's code
    during the live suites, and each later call and cleanup then waited out its own timeout, about an hour for a run.
    A call that times out only counts when /health gets no answer either, so a slow call still fails only its test."""

    def __init__(self, answers: Callable[[Request, str, int], bool] = health_answers) -> None:
        self.answers = answers
        self.live = False  # while a live test's setup, call or teardown runs
        self.why = ""

    def guard(self, request: Request) -> Request:
        """request wrapped: once Kit counts as hung, each live call fails at once."""

        def guarded(client: BridgeClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
            if self.live and self.why:
                raise TimeoutError(self.why)
            try:
                return request(client, *args, **kwargs)
            except TimeoutError:
                if self.live and not self.answers(request, client.host, client.port):
                    self.why = (
                        f"Kit at {client.host}:{client.port} stopped answering: a call timed out after "
                        f"{client.timeout:g} s and /health got no answer in {PROBE_SECONDS:g} s, so the live run stops "
                        "here (#54). Take a thread dump before ending Kit: uvx py-spy dump --native --pid <Kit's pid>"
                    )
                raise

        return guarded


HUNG = HungKit()


@pytest.fixture(autouse=True, scope="session")
def _stop_at_a_hung_kit() -> Iterator[None]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BridgeClient, "request", HUNG.guard(UNGUARDED))
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    HUNG.live = bool(item.get_closest_marker("sim") or item.get_closest_marker("scenario"))
    yield
    HUNG.live = False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    yield
    if HUNG.why:
        item.session.shouldstop = HUNG.why


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


def call_tool(tool: str, args: dict[str, Any], output_dir: str | Path) -> tuple[bool, str]:
    """A tool called as an MCP client calls it, for the live suites: the server built on a BridgeClient at
    live_bridge(), with the server's own timeout, and reached through the SDK's in-memory client, as
    tests/test_tools.py reaches it against the mock. Whether it erred, and its text.

    The live suites otherwise drive the routes, so what a tool makes of them, such as the route a merged tool picks
    and the answer it builds from two (#77), shows only through the server. Its files go to output_dir, which Kit
    writes into too, so it is a folder on this machine."""
    host, port = live_bridge()
    bridge = BridgeClient(host=host, port=port)

    async def call() -> Any:
        async with Client(create_server(host, port, str(output_dir), client=bridge)) as client:
            return await client.call_tool(tool, args)

    try:
        result = asyncio.run(call())
    finally:
        bridge.close()
    return bool(result.is_error), "\n".join(getattr(c, "text", "") for c in result.content)


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private token folder, and no token from the environment: never the developer's real ones."""
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path
