"""conftest.py's collection rule: which tests run for OMNIVERSE_MCP_SIM and OMNIVERSE_MCP_GPU (plan D11, #68).

The live suites need OMNIVERSE_MCP_SIM=1. The GPU module (marker `gpu`) switches the Kit app to the GPU pipeline, so
it needs OMNIVERSE_MCP_GPU=1 as well, and then runs alone among the live tests. A test with no marker always runs.
"""

from typing import Any, cast

import pytest

from . import conftest

# A test of each kind, by its markers: the GPU module's carries `sim` too, so #94's guard covers it.
KINDS = {"gpu": ("gpu", "sim"), "sim": ("sim",), "scenario": ("scenario",), "unit": ()}


class Item:
    """A collected test as the hook sees it: its markers, and the marks the hook adds to it."""

    def __init__(self, markers: tuple[str, ...]) -> None:
        self.markers = markers
        self.added: list[pytest.MarkDecorator] = []

    def get_closest_marker(self, name: str) -> str | None:
        return name if name in self.markers else None

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.added.append(marker)


def _collect(monkeypatch: pytest.MonkeyPatch, sim: str | None, gpu: str | None) -> dict[str, Item]:
    """One test of each kind through the hook, with the two variables set as given (None unsets one)."""
    for name, value in (("OMNIVERSE_MCP_SIM", sim), ("OMNIVERSE_MCP_GPU", gpu)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    items = {kind: Item(markers) for kind, markers in KINDS.items()}
    conftest.pytest_collection_modifyitems(cast("Any", None), cast("Any", list(items.values())))
    return items


@pytest.mark.parametrize(
    ("sim", "gpu", "runs"),
    [
        pytest.param(None, None, {"unit"}, id="plain"),
        pytest.param("1", None, {"sim", "scenario", "unit"}, id="the-live-suites"),
        pytest.param("1", "1", {"gpu", "unit"}, id="the-gpu-module-alone"),
        pytest.param(None, "1", {"unit"}, id="gpu-without-sim"),
        pytest.param("0", "0", {"unit"}, id="zero-is-off"),
        pytest.param("1", "0", {"sim", "scenario", "unit"}, id="gpu-zero-is-the-live-suites"),
    ],
)
def test_which_tests_run(monkeypatch, sim, gpu, runs):
    items = _collect(monkeypatch, sim, gpu)

    assert {kind for kind, item in items.items() if not item.added} == runs
    for item in items.values():
        assert all(mark.name == "skip" and mark.kwargs["reason"] for mark in item.added)
        assert len(item.added) <= 1


def test_the_gpu_module_says_what_it_needs_beside_the_live_suites(monkeypatch):
    (skip,) = _collect(monkeypatch, "1", None)["gpu"].added
    assert "OMNIVERSE_MCP_SIM=1 and OMNIVERSE_MCP_GPU=1" in skip.kwargs["reason"]


@pytest.mark.parametrize("kind", ["sim", "scenario"])
def test_a_gpu_run_says_why_the_other_live_tests_skip(monkeypatch, kind):
    (skip,) = _collect(monkeypatch, "1", "1")[kind].added
    assert skip.kwargs["reason"] == "OMNIVERSE_MCP_GPU=1 runs the GPU module alone, on a Kit app of its own"


def test_without_sim_the_live_suites_say_to_set_it(monkeypatch):
    (skip,) = _collect(monkeypatch, None, "1")["sim"].added
    assert skip.kwargs["reason"].startswith("a live suite: set OMNIVERSE_MCP_SIM=1")
