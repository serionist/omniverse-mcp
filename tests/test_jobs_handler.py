"""The job handlers against a fake Kit (#158): /jobs/script starts a script given as code or as a file, refuses one
that never awaits, and answers at once; /jobs/get reads it, waiting when asked; /jobs/cancel cancels it; a job's prints
are its own while an /execute call prints into its answer; a job that watches the stage is cancelled when the stage
changes, a script job isn't; the shutdown cancels and refuses.

handlers/jobs.py and handlers/misc.py are loaded from their files, with Kit's modules and _utils faked in sys.modules,
as tests/test_recording_handler.py loads its handler; the core and _updates are the real ones.
"""

import asyncio
import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ovmcp.core import script
from ovmcp.core.jobs import CANCELLED, CANCELLING, COMPLETED, FAILED, WORKING, Job

from .conftest import HANDLERS, FakeUpdates, load_updates, reset_output

OPENED, CLOSING = "OPENED", "CLOSING"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


class FakeKit(FakeUpdates):
    """Kit as the handlers see it: the stage's id and state, and the update event."""

    def __init__(self) -> None:
        super().__init__()
        self.stage_id = 1
        self.stage_state = OPENED


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"handlers_under_test.{name}", HANDLERS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def handlers(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    async def next_update() -> None:
        await asyncio.sleep(0)

    context = SimpleNamespace(get_stage_id=lambda: kit.stage_id, get_stage_state=lambda: kit.stage_state)
    kit_app = _module("omni.kit.app", get_app=lambda: None, **FakeUpdates.APP)
    dispatcher = _module("carb.eventdispatcher", get_eventdispatcher=lambda: kit)
    usd = _module("omni.usd", get_context=lambda: context, StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING))
    omni_kit = _module("omni.kit", app=kit_app)
    fakes = {
        "carb": _module("carb", eventdispatcher=dispatcher),
        "carb.eventdispatcher": dispatcher,
        "omni": _module("omni", kit=omni_kit, usd=usd),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": usd,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils", _next_update=next_update, _get_stage=lambda: None
        ),
        "handlers_under_test._mcp_bridge": _module("handlers_under_test._mcp_bridge", mcp_bridge=None),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "handlers_under_test._updates", load_updates())
    for name in ("misc", "jobs"):
        monkeypatch.delitem(sys.modules, f"handlers_under_test.{name}", raising=False)
    misc = _load("misc")
    jobs = _load("jobs")
    # The list STEPPED puts its gate in, in the namespace each script gets.
    gates: list[asyncio.Future[None]] = []
    namespace = jobs.script_namespace
    monkeypatch.setattr(jobs, "script_namespace", lambda: {**namespace(), "GATES": gates})
    yield SimpleNamespace(misc=misc, jobs=jobs, gates=gates)
    reset_output()


async def _turns(count: int = 6) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def _get(jobs: ModuleType, job_id: str = "", wait: float = 0) -> dict[str, Any]:
    return await jobs.handle_job_get({"job_id": job_id, "wait": wait})


# A script that waits for the test between its steps, as a bake awaits Kit's updates.
STEPPED = """
import asyncio
gate = asyncio.get_running_loop().create_future()
GATES.append(gate)
print("1 of 2 stacks settled")
await gate
print("2 of 2 stacks settled")
result = {"poses": 2}
"""


# ----- /jobs/script -----


def test_a_script_job_answers_at_once_and_its_result_is_read_later(handlers):
    jobs = handlers.jobs
    gates = handlers.gates

    async def main() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        started = await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        working = await _get(jobs, "j1")
        gates[0].set_result(None)
        await _turns()
        return started, working, await _get(jobs)

    started, working, ended = asyncio.run(main())

    assert started == {"status": "success", "result": {"id": "j1", "kind": "script", "label": "import asyncio"}}
    assert (working["result"]["state"], working["result"]["lines"]) == (WORKING, ["1 of 2 stacks settled"])
    result = ended["result"]
    assert (result["state"], result["result"]) == (COMPLETED, {"return_value": {"poses": 2}})
    assert result["lines"] == ["2 of 2 stacks settled"]
    assert result["output"]["stdout"] == "1 of 2 stacks settled\n2 of 2 stacks settled\n"


@pytest.mark.parametrize(
    "code", ["for i in range(10**9):\n    pass", "import time\ntime.sleep(600)", "async def bake():\n    await x\n"]
)
def test_a_script_that_never_awaits_is_refused_and_nothing_starts(handlers, code):
    jobs = handlers.jobs

    async def main() -> tuple[dict[str, Any], dict[str, Any]]:
        return await jobs.handle_job_script({"code": code}), await _get(jobs)

    refused, read = asyncio.run(main())

    assert refused == {"status": "error", "error": script.NEVER_AWAITS}
    assert "await omni.kit.app.get_app().next_update_async()" in refused["error"]
    assert read["error"].startswith("No job has run")


def test_a_script_that_only_schedules_its_coroutine_is_told_to_await_it(handlers, tmp_path: Path):
    # Rightly refused, since the job would end at once with its coroutine out of reach; it holds no thread, though.
    path = tmp_path / "bake.py"
    path.write_bytes(
        b"import asyncio\n\nasync def main():\n    await asyncio.sleep(0)\n\nasyncio.ensure_future(main())\n"
    )

    refused = asyncio.run(handlers.jobs.handle_job_script({"file": str(path)}))

    assert "a coroutine the script only defines or schedules doesn't count" in refused["error"]
    assert "await it at the top level, `await main()`" in refused["error"]
    assert "would hold Kit's main thread from its start to its end" not in refused["error"]


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({}, "Give the script as code or as file, one of them"),
        ({"code": "await x", "file": "bake.py"}, "Give the script as code or as file, one of them"),
        ({"code": "  \n"}, "Give the script as code or as file, one of them"),
        ({"code": 3}, "code and file are text"),
        ({"code": "await x\nx = = 1"}, "The script doesn't compile: invalid syntax"),
    ],
)
def test_a_start_without_one_good_script_is_refused(handlers, body, says):
    r = asyncio.run(handlers.jobs.handle_job_script(body))
    assert r["status"] == "error"
    assert r["error"].startswith(says)


def test_a_file_starts_a_job_named_by_its_path_and_its_traceback_names_its_line(handlers, tmp_path: Path):
    path = tmp_path / "bake.py"
    path.write_bytes(b"import asyncio\nawait asyncio.sleep(0)\nraise ValueError('stack 3 fell over')\n")
    jobs = handlers.jobs

    async def main() -> tuple[dict[str, Any], dict[str, Any]]:
        started = await jobs.handle_job_script({"file": str(path)})
        await _turns()
        return started, await _get(jobs)

    started, read = asyncio.run(main())

    assert Path(started["result"]["label"]) == path.resolve()
    result = read["result"]
    assert (result["state"], result["error"]) == (FAILED, "stack 3 fell over")
    assert f'File "{path.resolve()}", line 3, in <module>' in result["traceback"]


def test_a_file_that_isnt_there_is_refused(handlers, tmp_path: Path):
    r = asyncio.run(handlers.jobs.handle_job_script({"file": str(tmp_path / "nowhere.py")}))
    assert r["error"].startswith(f"Can't read the script file {tmp_path / 'nowhere.py'} on the Kit app's machine")


def test_a_second_start_is_refused_naming_the_running_job(handlers):
    jobs = handlers.jobs
    gates = handlers.gates

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        second = await jobs.handle_job_script({"code": STEPPED})
        gates[0].set_result(None)
        await _turns()
        return second

    assert asyncio.run(main())["error"].startswith("Job j1 (script) is working: one job runs at a time")


def test_a_script_calling_sys_exit_fails_its_job(handlers):
    jobs = handlers.jobs

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": "import asyncio, sys\nawait asyncio.sleep(0)\nsys.exit(2)"})
        await _turns()
        return await _get(jobs)

    result = asyncio.run(main())["result"]
    assert (result["state"], result["error"]) == (FAILED, "The job called sys.exit(2), which would end Kit's loop")


# ----- output -----


def test_a_job_s_prints_are_its_own_while_an_execute_call_prints_into_its_answer(handlers):
    jobs, misc = handlers.jobs, handlers.misc
    gates = handlers.gates

    async def main() -> tuple[dict[str, Any], dict[str, Any]]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        executed = await misc.handle_execute({"code": "import asyncio\nprint('from the call')\nawait asyncio.sleep(0)"})
        gates[0].set_result(None)
        await _turns()
        return executed, await _get(jobs)

    executed, read = asyncio.run(main())

    assert executed["result"]["stdout"] == "from the call\n"
    assert read["result"]["output"]["stdout"] == "1 of 2 stacks settled\n2 of 2 stacks settled\n"


# ----- /jobs/get -----


def test_a_get_waits_until_the_job_ends(handlers):
    jobs = handlers.jobs
    gates = handlers.gates

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        reading = asyncio.ensure_future(_get(jobs, "j1", wait=30))
        await _turns()
        assert not reading.done()
        gates[0].set_result(None)
        return await asyncio.wait_for(reading, timeout=5)

    assert asyncio.run(main())["result"]["state"] == COMPLETED


@pytest.mark.parametrize(("wait", "waited"), [(1000, 100.0), (-5, 0.0), ("2.5", 2.5), (None, 0.0)])
def test_a_get_s_wait_is_bounded_to_100_s(handlers, monkeypatch, wait, waited):
    jobs = handlers.jobs
    seen: list[float] = []

    async def wait_for(_job: Job, seconds: float) -> None:
        seen.append(seconds)

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": "import asyncio\nawait asyncio.sleep(0)"})
        monkeypatch.setattr(jobs._board, "wait", wait_for)
        return await jobs.handle_job_get({"wait": wait})

    assert asyncio.run(main())["status"] == "success"
    assert seen == [waited]


def test_a_get_with_a_wait_that_isnt_a_number_is_refused(handlers):
    r = asyncio.run(handlers.jobs.handle_job_get({"wait": "soon"}))
    assert r == {"status": "error", "error": "wait is a number of seconds, 0 to 100"}


def test_a_get_of_another_id_names_the_job_kept(handlers):
    jobs = handlers.jobs

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": "import asyncio\nawait asyncio.sleep(0)"})
        await _turns()
        return await _get(jobs, "j7")

    assert asyncio.run(main())["error"].startswith("No job j7: the bridge keeps only the last job, j1")


# ----- /jobs/cancel -----


def test_cancel_cancels_the_job_at_its_next_await(handlers):
    jobs = handlers.jobs

    async def main() -> tuple[dict[str, Any], dict[str, Any]]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        cancelled = await jobs.handle_job_cancel({"job_id": "j1"})
        await _turns()
        return cancelled, await _get(jobs)

    cancelled, read = asyncio.run(main())

    assert cancelled["result"] == {
        "id": "j1",
        "kind": "script",
        "state": CANCELLING,
        "was": WORKING,
        "message": "cancel_job was called",
    }
    assert (read["result"]["state"], read["result"]["message"]) == (CANCELLED, "cancel_job was called")
    assert read["result"]["output"]["stdout"] == "1 of 2 stacks settled\n"


@pytest.mark.parametrize(("body", "says"), [({}, "job_id is required"), ({"job_id": "j1"}, "No job has run")])
def test_a_cancel_without_a_job_is_refused(handlers, body, says):
    r = asyncio.run(handlers.jobs.handle_job_cancel(body))
    assert r["error"].startswith(says)


# ----- the stage watch -----


def test_a_watching_job_is_cancelled_with_the_reason_when_the_stage_changes(handlers, kit):
    jobs = handlers.jobs
    seen: list[Any] = []

    async def sweep(_job: Job) -> dict[str, Any]:
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError as e:
            seen.append(e.args)
            raise
        return {}

    async def main() -> Job:
        job = jobs.start_job("sweep", "400 shots", sweep, watch_stage=True)
        await _turns()
        kit.update()
        assert job.state == WORKING
        kit.stage_id = 2
        kit.update()
        kit.update()
        await _turns()
        return job

    job = asyncio.run(main())

    assert seen == [("the stage changed",)]
    assert (job.state, job.message) == (CANCELLED, "the stage changed")
    assert kit.names == [], "the watch ends with the job"


def test_a_watching_job_stops_when_the_stage_begins_to_close(handlers, kit):
    jobs = handlers.jobs

    async def sweep(_job: Job) -> dict[str, Any]:
        await asyncio.get_running_loop().create_future()
        return {}

    async def main() -> Job:
        job = jobs.start_job("sweep", "", sweep, watch_stage=True)
        await _turns()
        kit.stage_state = CLOSING
        kit.update()
        await _turns()
        return job

    assert asyncio.run(main()).message == "the stage began to close"


def test_a_script_job_runs_on_through_a_stage_change(handlers, kit):
    # A bake may open stages itself: a script job doesn't watch.
    jobs = handlers.jobs
    gates = handlers.gates

    async def main() -> dict[str, Any]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        kit.stage_id = 2
        kit.update()
        await _turns()
        assert kit.names == []
        gates[0].set_result(None)
        await _turns()
        return await _get(jobs)

    assert asyncio.run(main())["result"]["state"] == COMPLETED


# ----- get_sim_state's line and the shutdown -----


def test_the_brief_names_the_running_job_alone(handlers):
    jobs = handlers.jobs
    gates = handlers.gates

    async def main() -> tuple[Any, Any]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        running = jobs.job_brief()
        gates[0].set_result(None)
        await _turns()
        return running, jobs.job_brief()

    running, after = asyncio.run(main())

    assert (running["id"], running["kind"], running["state"]) == ("j1", "script", WORKING)
    assert after is None


def test_the_shutdown_cancels_the_job_and_refuses_a_start_after_it(handlers):
    jobs = handlers.jobs

    async def main() -> tuple[dict[str, Any], dict[str, Any]]:
        await jobs.handle_job_script({"code": STEPPED})
        await _turns()
        jobs.shut_down()
        await _turns()
        return await _get(jobs), await jobs.handle_job_script({"code": STEPPED})

    read, refused = asyncio.run(main())

    assert (read["result"]["state"], read["result"]["message"]) == (CANCELLED, "the extension shut down")
    assert refused["error"].startswith("No job starts now: the extension shut down")
