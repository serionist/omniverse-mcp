"""conftest.py's rule for the live tests: which run, skip or fail for OMNIVERSE_MCP_SIM and OMNIVERSE_MCP_GPU (plan
D11, #68).

The live suites need OMNIVERSE_MCP_SIM=1. The GPU module (marker `gpu`) switches the Kit app to the GPU pipeline, so
it needs OMNIVERSE_MCP_GPU=1 as well, and then runs alone: every other live test fails at setup, so a variable left
set can't pass a run of the live suites with all of them skipped. A test with no marker always runs.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from . import conftest, test_gpu_force

# A test of each kind, by its markers: the GPU module's carries `sim` too, so #94's guard covers it.
KINDS = {"gpu": ("gpu", "sim"), "sim": ("sim",), "scenario": ("scenario",), "unit": ()}


class Item:
    """A collected test as the hooks see it: its markers, and the marks the collection hook adds to it."""

    def __init__(self, markers: tuple[str, ...]) -> None:
        self.markers = markers
        self.added: list[pytest.MarkDecorator] = []

    def get_closest_marker(self, name: str) -> str | None:
        return name if name in self.markers else None

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.added.append(marker)


def _environ(monkeypatch: pytest.MonkeyPatch, sim: str | None, gpu: str | None) -> None:
    """The two variables set as given; None unsets one."""
    for name, value in (("OMNIVERSE_MCP_SIM", sim), ("OMNIVERSE_MCP_GPU", gpu)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _collect(monkeypatch: pytest.MonkeyPatch, sim: str | None, gpu: str | None) -> dict[str, Item]:
    """One test of each kind through the collection hook."""
    _environ(monkeypatch, sim, gpu)
    items = {kind: Item(markers) for kind, markers in KINDS.items()}
    conftest.pytest_collection_modifyitems(cast("Any", None), cast("Any", list(items.values())))
    return items


def _outcomes(monkeypatch: pytest.MonkeyPatch, sim: str | None, gpu: str | None) -> dict[str, str]:
    """What becomes of a test of each kind: "skips" at collection, "fails" at setup, or "runs"."""
    outcomes: dict[str, str] = {}
    for kind, item in _collect(monkeypatch, sim, gpu).items():
        if item.added:
            outcomes[kind] = "skips"
            continue
        try:
            conftest.pytest_runtest_setup(cast("Any", item))
        except pytest.fail.Exception:
            outcomes[kind] = "fails"
        else:
            outcomes[kind] = "runs"
    return outcomes


@pytest.mark.parametrize(
    ("sim", "gpu", "outcomes"),
    [
        pytest.param(None, None, ("skips", "skips", "skips", "runs"), id="plain"),
        pytest.param("1", None, ("skips", "runs", "runs", "runs"), id="the-live-suites"),
        pytest.param("1", "1", ("runs", "fails", "fails", "runs"), id="the-gpu-module-alone"),
        pytest.param(None, "1", ("skips", "skips", "skips", "runs"), id="gpu-without-sim"),
        pytest.param("0", "0", ("skips", "skips", "skips", "runs"), id="zero-is-off"),
        pytest.param("1", "0", ("skips", "runs", "runs", "runs"), id="gpu-zero-is-the-live-suites"),
    ],
)
def test_which_tests_run_skip_or_fail(monkeypatch, sim, gpu, outcomes):
    assert _outcomes(monkeypatch, sim, gpu) == dict(zip(KINDS, outcomes, strict=True))
    for item in _collect(monkeypatch, sim, gpu).values():
        assert all(mark.name == "skip" and mark.kwargs["reason"] for mark in item.added)
        assert len(item.added) <= 1


def test_the_gpu_module_says_what_it_needs_beside_the_live_suites(monkeypatch):
    (skip,) = _collect(monkeypatch, "1", None)["gpu"].added
    assert "OMNIVERSE_MCP_SIM=1 and OMNIVERSE_MCP_GPU=1" in skip.kwargs["reason"]


@pytest.mark.parametrize("kind", ["sim", "scenario"])
def test_a_gpu_run_fails_the_other_live_tests_and_says_to_unset_it(monkeypatch, kind):
    item = _collect(monkeypatch, "1", "1")[kind]
    with pytest.raises(pytest.fail.Exception) as failed:
        conftest.pytest_runtest_setup(cast("Any", item))
    assert str(failed.value) == (
        "OMNIVERSE_MCP_GPU=1 is set: it runs the GPU module alone; unset it to run the live suites"
    )


def test_without_sim_the_live_suites_say_to_set_it(monkeypatch):
    (skip,) = _collect(monkeypatch, None, "1")["sim"].added
    assert skip.kwargs["reason"].startswith("a live suite: set OMNIVERSE_MCP_SIM=1")


def test_the_gpu_module_is_marked_gpu_and_sim():
    # gpu keeps it out of a run that didn't ask for it; sim puts it under #94's guard of a hung Kit, which keys on sim.
    assert {mark.name for mark in test_gpu_force.pytestmark} >= {"gpu", "sim"}


# Two live classes for a pytest of their own: each one's setUpClass, where a live class reaches Kit, leaves a file.
LIVE_CLASS = """
import pathlib
import unittest

import pytest

pytestmark = {marks}


class TestReached(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (pathlib.Path(__file__).parent / "{kind}-reached").touch()

    def test_it(self):
        pass
"""


def test_a_gpu_run_fails_a_live_class_before_its_set_up_class(tmp_path: Path):
    # A real pytest in a folder of its own, with conftest.py's two hooks, so the order of pytest's own setup is the one
    # tested.
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    sim: live\n    gpu: live\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        f"import sys\nsys.path.insert(0, {str(conftest.REPO_ROOT)!r})\n"
        "from tests.conftest import pytest_collection_modifyitems, pytest_runtest_setup  # noqa: E402, F401\n",
        encoding="utf-8",
    )
    for kind, marks in (("sim", "[pytest.mark.sim]"), ("gpu", "[pytest.mark.gpu, pytest.mark.sim]")):
        source = textwrap.dedent(LIVE_CLASS).format(marks=marks, kind=kind)
        (tmp_path / f"test_live_{kind}.py").write_text(source, encoding="utf-8")
    env = {**os.environ, "OMNIVERSE_MCP_SIM": "1", "OMNIVERSE_MCP_GPU": "1"}
    env.pop("PYTEST_ADDOPTS", None)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "pytest.ini", "-p", "no:cacheprovider", "-rA", "."],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    out = run.stdout + run.stderr
    assert run.returncode == 1, out
    assert "1 passed, 1 error" in out, out
    assert "OMNIVERSE_MCP_GPU=1 is set: it runs the GPU module alone; unset it to run the live suites" in out
    assert not (tmp_path / "sim-reached").exists(), "the live class's setUpClass ran"
    assert (tmp_path / "gpu-reached").exists(), "the GPU module's class didn't run"
