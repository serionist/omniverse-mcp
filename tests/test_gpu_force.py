"""apply_force under PhysX's Direct GPU API, live (#68): the push goes through PhysX's tensor API, and the bodies'
momentum changes by exactly the push.

Run alone, on a Kit app of its own with a CUDA GPU (Isaac Sim 6.2 and 5.1 headless are the ones measured), and restart
Kit after:

    OMNIVERSE_MCP_SIM=1 OMNIVERSE_MCP_GPU=1 uv run pytest tests/test_gpu_force.py

It switches the Kit app to the GPU pipeline with Isaac Sim's SimulationManager.set_device("cuda:0")
(set_physics_sim_device in 5.x), which set_device("cpu") doesn't fully undo: Fabric stays on and USD write-back off,
so a pose read through USD goes stale (#68's E17). Without OMNIVERSE_MCP_GPU=1 this module skips; with it every other
live test fails at setup, before it reaches Kit, so a variable left set can't pass a run of the live suites that
skipped them all (tests/conftest.py).

The tests run in the order of their numbers: the first two check the Kit app is fit to switch, the third switches it,
and each push skips unless the third passed. Momentum is read through a tensor view of the test's own, as #68's probe
read it, and not through PhysX's pose calls: with readback suppressed, PhysX doesn't copy the GPU's state back for them.
"""

import time
import unittest
from typing import Any

import pytest

from omniverse_mcp.client import BridgeClient

from .conftest import live_bridge
from .physics_checks import PhysicsChecks

pytestmark = [pytest.mark.gpu, pytest.mark.sim]

# Whether the Kit app runs PhysX's Direct GPU API already, from an earlier run's switch or its own settings.
SUPPRESS_READBACK = """
import carb
result = carb.settings.get_settings().get_as_bool('/physics/suppressReadback')
"""

# What the switch needs, read before anything changes: warp's count of CUDA devices, and Isaac Sim's
# SimulationManager, which other Kit apps lack. A missing one fails the script.
GPU_AND_SIMULATION_MANAGER = """
import warp
from isaacsim.core.simulation_manager import SimulationManager
result = int(warp.get_cuda_device_count())
"""

# SimulationManager's device setter: set_device from Isaac Sim 6, set_physics_sim_device in 5.x, which sets the same
# settings and scene attributes.
SET_DEVICE = """
from isaacsim.core.simulation_manager import SimulationManager

set_device = getattr(SimulationManager, "set_device", None) or SimulationManager.set_physics_sim_device
"""

# The switch, as #68's probe made it. A stage without a physics scene gets one first, and an update before the switch,
# so Isaac Sim's SimulationManager, which tracks the scenes added to the stage, has it when set_device sets their GPU
# dynamics. Then 40 updates of play, after which a tensor view says the device PhysX simulates on, and a stop. The
# result: the setting the handler chooses its path by, and the first scene's GPU dynamics and the device, which say
# PhysX simulates on the GPU.
SWITCH = (
    SET_DEVICE
    + """
import carb
import omni.kit.app
import omni.timeline
import omni.usd
from omni.physics import tensors

app = omni.kit.app.get_app()
stage = omni.usd.get_context().get_stage()
made = None
if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse()):
    made = "/World/PhysicsScene"
    UsdPhysics.Scene.Define(stage, made)
    await app.next_update_async()
set_device("cuda:0")
timeline = omni.timeline.get_timeline_interface()
timeline.play()
for _ in range(40):
    await app.next_update_async()
view = tensors.create_simulation_view("warp", omni.usd.get_context().get_stage_id())
device = str(view.device)
view.invalidate()
timeline.stop()
await app.next_update_async()
scene = next(prim for prim in stage.Traverse() if prim.IsA(UsdPhysics.Scene))
result = {
    "made": made,
    "suppress_readback": carb.settings.get_settings().get_as_bool('/physics/suppressReadback'),
    "gpu_dynamics": scene.GetAttribute('physxScene:enableGPUDynamics').Get(),
    "device": device,
}
"""
)

# The module's cleanup: the timeline stopped, then the CPU device, as #68's probe switched back.
SWITCH_BACK = (
    SET_DEVICE
    + """
import omni.kit.app
import omni.timeline

omni.timeline.get_timeline_interface().stop()
await omni.kit.app.get_app().next_update_async()
set_device("cpu")
result = True
"""
)

# The bodies PATHS names, set before it, through a tensor view of our own: their total linear momentum, each one's,
# their largest angular speed, and each one's origin. With no contact and gravity off, a push of J N s changes a body's
# momentum, or a free articulation's, by exactly J, wherever it lands: #58's measure and #68's probe's.
STATE = """
import numpy as np
import omni.usd
from omni.physics import tensors

view = tensors.create_simulation_view("warp", omni.usd.get_context().get_stage_id())
try:
    bodies = view.create_rigid_body_view(PATHS)
    n = bodies.count
    paths = list(bodies.prim_paths)
    velocity = bodies.get_velocities().numpy().reshape(n, 6)
    mass = bodies.get_masses().numpy().reshape(n, 1)
    pose = bodies.get_transforms().numpy().reshape(n, 7)
    momentum = mass * velocity[:, :3]
    result = {
        "paths": paths,
        "momentum": [float(v) for v in momentum.sum(0)],
        "each": {path: [float(v) for v in momentum[i]] for i, path in enumerate(paths)},
        "spin": float(np.abs(velocity[:, 3:]).max()) if n else 0.0,
        "origin": {path: [float(v) for v in pose[i, :3]] for i, path in enumerate(paths)},
    }
finally:
    view.invalidate()
"""

# Updates played after a push before the momentum is read again; the push lands on the first step.
FRAMES = 12
# An impulse in N s, and a force in N, large enough that 2% of the momentum it gives stands well clear of float32's
# noise: a force gives force * dt, 5 N s at 60 steps a second.
IMPULSE = 10.0
FORCE = 300.0


class TestGpuForce(PhysicsChecks):
    """apply_force through the tensor API, on a Kit app switched to the GPU pipeline: a lone cube and a two-link
    articulation, gravity off, each pushed with a force and an impulse, at its centre of mass and at a point."""

    # Why the switch can't happen or didn't: set by the first three tests.
    blocked: str | None = None
    # set_device("cuda:0") was called, so the cleanup calls set_device("cpu"), whatever failed after.
    switched = False
    # test_03 found the Direct GPU API on: the pushes run only then.
    on_gpu = False
    made_scene: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        host, port = live_bridge()
        probe = BridgeClient(host=host, port=port, timeout=2.0)
        try:
            health = probe.health()
        finally:
            probe.close()
        if health["status"] != "success":
            raise ConnectionError(f"Health check failed at {host}:{port}: {health}")
        # The switch plays 40 updates in one call, the first on a scene PhysX builds anew on the GPU.
        cls.c = BridgeClient(host=host, port=port, timeout=60.0)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            if cls.switched:
                r = cls.c.execute(SWITCH_BACK)
                if r["status"] != "success":
                    print(f"\n  set_device('cpu') failed: {r.get('error')}")
                print("\n  set_device('cpu') leaves Fabric on and USD write-back off: restart Kit before another run")
            if cls.made_scene:
                cls.c.delete_prim(cls.made_scene)
        finally:
            cls.c.close()

    def _switched(self) -> None:
        """Skips a test of the Direct GPU API unless test_03 switched the Kit app to it."""
        if not self.on_gpu:
            self.skipTest(self.blocked or "test_03 switches the Kit app to the Direct GPU API: run the module whole")

    def _kit(self, code: str) -> Any:
        """execute_script's return value, its success checked."""
        r = self.c.execute(code)
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _state(self, paths: list[str]) -> dict[str, Any]:
        """STATE of the bodies, each held by the tensor API."""
        state = self._kit(f"PATHS = {paths!r}\n" + STATE)
        self.assertEqual(sorted(state["paths"]), sorted(paths), "the tensor API doesn't hold each body")
        return state

    def _push(
        self, paths: list[str], body: str, force: float, *, impulse: bool, above: float | None = None
    ) -> tuple[dict[str, Any], list[float], dict[str, Any], dict[str, Any]]:
        """Plays, pushes `body`, one of `paths`, along X at its centre of mass or `above` its origin along the up
        axis, plays FRAMES and pauses. The push's answer, the bodies' change of momentum, their state before and
        after.

        It pushes during play, with Isaac Sim's own view live beside the handler's, which #58's E5 found harmless.
        Nothing else moves the bodies, so the reads before and after may fall on any step."""
        self.assertEqual(self.c.sim_control("play")["status"], "success")
        before = self._state(paths)
        position = None
        if above is not None:
            position = list(before["origin"][body])
            position[self._up_axis()] += above
        r = self.c.apply_force(body, force=[force, 0.0, 0.0], position=position, impulse=impulse)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(
            r["result"]["method"], "tensor", f"apply_force_at_pos moves nothing under the Direct GPU API: {r}"
        )
        self._run_frames(FRAMES)
        after = self._state(paths)
        change = [a - b for a, b in zip(after["momentum"], before["momentum"], strict=True)]
        print(f"  {'impulse' if impulse else 'force'} {force:g} on {body}: momentum change {change}")
        return r["result"], change, before, after

    def _assert_change(self, change: list[float], expected: float) -> None:
        """The momentum changed by `expected` along X, within 2%, and by next to nothing across it."""
        self.assertAlmostEqual(change[0], expected, delta=expected * 0.02)
        self.assertLess(abs(change[1]) + abs(change[2]), expected * 0.02)

    # ----- the Kit app is fit to switch, and switches -----

    def test_01_the_kit_app_is_on_the_cpu_pipeline(self) -> None:
        # Set until the check passes, so a failure here holds back the switch.
        type(self).blocked = "test_01 found the Kit app unfit to switch"
        if self._kit(SUPPRESS_READBACK):
            self.fail(
                "/physics/suppressReadback is true: this Kit app runs PhysX's Direct GPU API already, from an earlier "
                "run of this module or its own settings. A switch back leaves Fabric on and USD write-back off, so "
                "restart Kit, then run this module alone on it"
            )
        type(self).blocked = None

    def test_02_the_kit_app_has_a_cuda_gpu_and_isaac_sims_simulation_manager(self) -> None:
        if self.blocked:
            self.skipTest(self.blocked)
        r = self.c.execute(GPU_AND_SIMULATION_MANAGER)
        if r["status"] != "success":
            type(self).blocked = f"no warp or no Isaac Sim SimulationManager in this Kit app: {r.get('error')}"
        elif not r["result"]["return_value"]:
            type(self).blocked = "warp finds no CUDA device"
        if self.blocked:
            self.skipTest(self.blocked)

    def test_03_the_kit_app_switches_to_the_direct_gpu_api(self) -> None:
        if self.blocked:
            self.skipTest(self.blocked)
        self.assertEqual(self.c.sim_control("stop")["status"], "success")
        type(self).blocked = "the switch to the Direct GPU API failed (test_03)"
        type(self).switched = True
        got = self._kit(SWITCH)
        type(self).made_scene = got["made"]
        print(f"  After set_device('cuda:0'): {got}")
        self.assertIs(got["suppress_readback"], True, got)
        self.assertIs(got["gpu_dynamics"], True, got)
        self.assertTrue(got["device"].startswith("cuda"), f"PhysX simulates on {got['device']}")
        type(self).blocked = None
        type(self).on_gpu = True

    # ----- a lone cube -----

    def test_04_an_impulse_at_a_cubes_centre_of_mass_moves_it_by_the_impulse(self) -> None:
        self._switched()
        cube = self._force_body("GpuImpulseCube")
        answer, change, before, after = self._push([cube], cube, IMPULSE, impulse=True)
        self.assertEqual(answer["at"], "centre of mass")
        # None is authored, so the centre of mass is the cube's origin.
        for got, origin in zip(answer["position"], before["origin"][cube], strict=True):
            self.assertAlmostEqual(got, origin, delta=1e-3)
        self._assert_change(change, IMPULSE)
        self.assertLess(after["spin"], 0.01, "a push at the centre of mass turned the cube")

    def test_05_a_force_at_a_cubes_centre_of_mass_moves_it_by_the_force_over_one_step(self) -> None:
        self._switched()
        cube = self._force_body("GpuForceCube")
        answer, change, _, after = self._push([cube], cube, FORCE, impulse=False)
        self.assertEqual(answer["at"], "centre of mass")
        self._assert_change(change, FORCE * self._physics_step())
        self.assertLess(after["spin"], 0.01, "a push at the centre of mass turned the cube")

    def test_06_an_impulse_above_a_cubes_centre_moves_it_by_the_impulse_and_turns_it(self) -> None:
        self._switched()
        cube = self._force_body("GpuImpulsePointCube")
        up = self._up_axis()
        answer, change, before, after = self._push([cube], cube, IMPULSE, impulse=True, above=0.2)
        self.assertEqual(answer["at"], "given")
        self.assertAlmostEqual(answer["position"][up], before["origin"][cube][up] + 0.2)
        self._assert_change(change, IMPULSE)
        self.assertGreater(after["spin"], 0.5, "a push above the centre of mass didn't turn the cube")

    def test_07_a_force_above_a_cubes_centre_moves_it_by_the_force_over_one_step_and_turns_it(self) -> None:
        self._switched()
        cube = self._force_body("GpuForcePointCube")
        answer, change, _, after = self._push([cube], cube, FORCE, impulse=False, above=0.2)
        self.assertEqual(answer["at"], "given")
        self._assert_change(change, FORCE * self._physics_step())
        self.assertGreater(after["spin"], 0.5, "a push above the centre of mass didn't turn the cube")

    def test_08_a_cube_is_pushed_at_its_centre_of_mass_off_its_origin(self) -> None:
        self._switched()
        side = 3 - self._up_axis()  # neither X nor up: the centre of mass sits off the origin along it
        offset = [0.0, 0.0, 0.0]
        offset[side] = 0.5  # in the cube's own units, so 0.15 once its 0.3 scale applies
        cube = self._force_body("GpuOffCentreCube", centre_of_mass=offset)
        answer, change, before, after = self._push([cube], cube, IMPULSE, impulse=True)
        off = answer["position"][side] - before["origin"][cube][side]
        print(f"  The point pushed at is {off:.3f} off the origin along {'XYZ'[side]} (0.15 authored)")
        self.assertAlmostEqual(off, 0.15, delta=0.02)
        self._assert_change(change, IMPULSE)
        self.assertLess(after["spin"], 0.01, "a push at the centre of mass turned the cube")

    # ----- a link of a free articulation: the push moves both links -----

    def test_09_an_impulse_at_a_links_centre_of_mass_moves_its_articulation_by_the_impulse(self) -> None:
        self._switched()
        links = list(self._force_pair("GpuPairImpulse"))
        answer, change, _, _ = self._push(links, links[1], IMPULSE, impulse=True)
        self.assertEqual(answer["at"], "centre of mass")
        self._assert_change(change, IMPULSE)

    def test_10_a_force_at_a_links_centre_of_mass_moves_its_articulation_by_the_force_over_one_step(self) -> None:
        self._switched()
        links = list(self._force_pair("GpuPairForce"))
        answer, change, _, _ = self._push(links, links[1], FORCE, impulse=False)
        self.assertEqual(answer["at"], "centre of mass")
        self._assert_change(change, FORCE * self._physics_step())

    def test_11_an_impulse_above_a_links_centre_moves_its_articulation_by_the_impulse(self) -> None:
        self._switched()
        links = list(self._force_pair("GpuPairImpulsePoint"))
        answer, change, _, _ = self._push(links, links[1], IMPULSE, impulse=True, above=0.2)
        self.assertEqual(answer["at"], "given")
        self._assert_change(change, IMPULSE)

    def test_12_a_force_above_a_links_centre_moves_its_articulation_by_the_force_over_one_step(self) -> None:
        self._switched()
        links = list(self._force_pair("GpuPairForcePoint"))
        answer, change, _, _ = self._push(links, links[1], FORCE, impulse=False, above=0.2)
        self.assertEqual(answer["at"], "given")
        self._assert_change(change, FORCE * self._physics_step())

    # ----- refused there as on the CPU -----

    def test_13_a_push_while_stopped_is_refused(self) -> None:
        self._switched()
        cube = self._force_body("GpuStoppedCube")  # leaves the simulation stopped
        r = self.c.apply_force(cube, force=[1.0, 0.0, 0.0])
        self.assertEqual(r["status"], "error", r)
        self.assertIn("stopped", r["error"])

    def test_14_a_push_on_a_kinematic_body_is_refused(self) -> None:
        self._switched()
        cube = self._force_body("GpuKinematicCube", kinematic=True)
        self._start_physics()
        r = self.c.apply_force(cube, force=[1.0, 0.0, 0.0])
        self.assertEqual(r["status"], "error", r)
        self.assertIn("kinematic", r["error"])

    # ----- cubes of their own, side by side -----

    def _cubes(self, root: str, paths: list[str], *, xforms: tuple[str, ...] = ()) -> list[str]:
        """5 kg cubes of their own at `paths`, under `root` and the `xforms` between, plain Xforms all. Gravity is off
        and they sit 2 apart along X, away from the scene, so only a push moves each. Deleted after, the simulation
        stopped first."""
        position = [-50.0, 0.0, 0.0]
        position[self._up_axis()] = 5.0
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.addCleanup(self.c.delete_prim, root)
        self.addCleanup(self.c.sim_control, "stop")
        r = self.c.execute(
            "from pxr import PhysxSchema\n"
            "stage = omni.usd.get_context().get_stage()\n"
            f"for path in {[root, *xforms]!r}:\n"
            "    UsdGeom.Xform.Define(stage, path)\n"
            f"x, y, z = {position!r}\n"
            f"for i, path in enumerate({paths!r}):\n"
            "    cube = UsdGeom.Cube.Define(stage, path)\n"
            "    cube.CreateSizeAttr(0.3)\n"
            "    UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(x + 2 * i, y, z))\n"
            "    UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())\n"
            "    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())\n"
            "    UsdPhysics.MassAPI.Apply(cube.GetPrim()).CreateMassAttr(5.0)\n"
            "    PhysxSchema.PhysxRigidBodyAPI.Apply(cube.GetPrim()).CreateDisableGravityAttr(True)\n"
            "result = 'ok'"
        )
        self.assertEqual(r["status"], "success", r)
        return paths

    def _each(self, paths: list[str]) -> dict[str, list[float]]:
        """Each body's linear momentum, through a tensor view of the bodies' paths."""
        each = self._kit(f"PATHS = {paths!r}\n" + STATE)["each"]
        self.assertLessEqual(set(paths), set(each), "the tensor API doesn't hold each body")
        return each

    def _moved(self, before: dict[str, list[float]], after: dict[str, list[float]]) -> dict[str, list[float]]:
        """Each body's change of momentum between two reads of _each."""
        return {path: [a - b for a, b in zip(after[path], before[path], strict=True)] for path in before}

    # ----- pushes while paused -----

    def test_15_paused_a_second_push_on_one_body_replaces_the_first_and_pushes_on_two_bodies_each_land(self) -> None:
        """Measured on Isaac Sim 6.2 (#68's E19): under the Direct GPU API a second push on a body before the next
        physics step replaces the first, where on the CPU pipeline the two add (#58's E4), and pushes on different
        bodies each land. The tool's docs say so: one push per body per step, the pushes combined into one."""
        self._switched()
        root = "/World/GpuPaused"
        twice, once_a, once_b = cubes = self._cubes(root, [f"{root}/Twice", f"{root}/OnceA", f"{root}/OnceB"])
        self._start_physics()
        before = self._each(cubes)
        # In the probe's order: one push on each of two bodies, then two on the third.
        for path in (once_a, once_b, twice, twice):
            r = self.c.apply_force(path, force=[IMPULSE, 0.0, 0.0], impulse=True)
            self.assertEqual(r["status"], "success", r)
            self.assertEqual(r["result"]["method"], "tensor", r)
        self._run_frames(FRAMES)
        moved = self._moved(before, self._each(cubes))
        print(f"  impulses of {IMPULSE:g} while paused, two on {twice} and one on each other: momentum changes {moved}")
        self.assertAlmostEqual(
            moved[twice][0],
            IMPULSE,
            delta=IMPULSE * 0.02,
            msg=f"two pushes of {IMPULSE:g} N s on {twice} while paused moved its momentum by {moved[twice][0]:.4f}: "
            f"{2 * IMPULSE:g} would mean the pushes now add, as on the CPU pipeline, and the docs that say the second "
            "replaces the first should change",
        )
        for path in (once_a, once_b):
            self.assertAlmostEqual(
                moved[path][0],
                IMPULSE,
                delta=IMPULSE * 0.02,
                msg=f"one push of {IMPULSE:g} N s on {path} while paused, beside pushes on other bodies, moved its "
                f"momentum by {moved[path][0]:.4f}",
            )
        for path, change in moved.items():
            self.assertLess(abs(change[1]) + abs(change[2]), IMPULSE * 0.02, f"{path} moved across X: {change}")

    # ----- a body whose name repeats deeper under its parent -----

    def test_16_a_body_whose_name_repeats_deeper_under_its_parent_is_pushed_alone(self) -> None:
        """On Isaac Sim 6.2 the tensor API's view of a plain path holds that body alone (#68's E18): the view of
        /World/GpuTwin/Cube doesn't hold /World/GpuTwin/Shelf/Cube, though omni.physics.tensors' docs say a plain last
        name matches at any depth under the parent. The handler pushes on the body's own row all the same, and this
        guards a Kit whose view holds the twin too: the push moves the body named, and its twin not at all."""
        self._switched()
        root = "/World/GpuTwin"
        outer, twin = self._cubes(root, [f"{root}/Cube", f"{root}/Shelf/Cube"], xforms=(f"{root}/Shelf",))
        self.assertEqual(self.c.sim_control("play")["status"], "success")
        before = self._each([outer, twin])
        r = self.c.apply_force(outer, force=[IMPULSE, 0.0, 0.0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["method"], "tensor", r)
        self._run_frames(FRAMES)
        moved = self._moved(before, self._each([outer, twin]))
        print(f"  impulse {IMPULSE:g} on {outer}: its momentum change {moved[outer]}, its twin's {moved[twin]}")
        what_moved = f"{outer}'s momentum changed by {moved[outer]} and its twin {twin}'s by {moved[twin]}"
        self.assertAlmostEqual(moved[outer][0], IMPULSE, delta=IMPULSE * 0.02, msg=what_moved)
        self.assertLess(abs(moved[outer][1]) + abs(moved[outer][2]), IMPULSE * 0.02, what_moved)
        self.assertLess(
            max(abs(v) for v in moved[twin]),
            IMPULSE * 0.01,
            f"the push on {outer} moved its twin: {what_moved}",
        )


if __name__ == "__main__":
    unittest.main()
