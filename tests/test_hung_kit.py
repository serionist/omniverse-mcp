"""conftest.py's guard against a hung Kit (#54): a live call that times out while /health gets no answer either ends
the run, and each later live call fails at once; a slow call, or one outside the live suites, is left alone."""

import socket
from types import SimpleNamespace
from typing import Any

import pytest

from . import conftest
from .conftest import HungKit

CLIENT = SimpleNamespace(host="127.0.0.1", port=8212, timeout=30.0)


class Kit:
    """BridgeClient.request's stand-in: answers, or times out once told to."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hangs = False

    def request(self, client: Any, path: str, *args: Any) -> dict[str, Any]:
        self.calls.append(path)
        if self.hangs:
            raise TimeoutError("timed out")
        return {"status": "success"}


def _guarded(answers: bool) -> tuple[HungKit, Kit, Any, list[tuple[str, int]]]:
    """A guard over a Kit stand-in whose /health answers or not, and the list of the places it asked."""
    kit = Kit()
    asked: list[tuple[str, int]] = []

    def health(_request: Any, host: str, port: int) -> bool:
        asked.append((host, port))
        return answers

    hung = HungKit(answers=health)
    return hung, kit, hung.guard(kit.request), asked


def test_a_timeout_outside_the_live_suites_is_left_alone():
    hung, kit, request, asked = _guarded(answers=False)
    kit.hangs = True

    with pytest.raises(TimeoutError):
        request(CLIENT, "/scene/tree")

    assert hung.why == ""
    assert asked == []


def test_a_slow_call_while_health_answers_fails_only_itself():
    hung, kit, request, asked = _guarded(answers=True)
    hung.live = True
    kit.hangs = True

    with pytest.raises(TimeoutError):
        request(CLIENT, "/camera/capture")
    kit.hangs = False

    assert hung.why == ""
    assert request(CLIENT, "/health") == {"status": "success"}
    assert asked == [("127.0.0.1", 8212)]


def test_a_hung_kit_fails_each_later_live_call_at_once():
    hung, kit, request, _asked = _guarded(answers=False)
    hung.live = True
    kit.hangs = True

    with pytest.raises(TimeoutError):
        request(CLIENT, "/camera/capture")
    with pytest.raises(TimeoutError, match="stopped answering") as later:
        request(CLIENT, "/scene/delete")

    assert kit.calls == ["/camera/capture"]  # the later call never reached Kit
    assert "127.0.0.1:8212" in str(later.value)
    assert "py-spy dump" in str(later.value)
    hung.live = False
    kit.hangs = False
    assert request(CLIENT, "/health") == {"status": "success"}  # outside a live test, calls go through


def test_health_that_gets_no_answer_in_time_counts_as_hung(state, monkeypatch):
    monkeypatch.setattr(conftest, "PROBE_SECONDS", 0.3)
    with socket.socket() as listener:  # takes connections and never answers, as a hung Kit's port does
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        assert conftest.health_answers(conftest.BridgeClient.request, "127.0.0.1", port) is False


def test_health_on_a_port_nothing_listens_on_counts_as_hung(state):
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]

    assert conftest.health_answers(conftest.BridgeClient.request, "127.0.0.1", port) is False
