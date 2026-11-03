"""The timeline's range and whether it loops, for get_sim_state (#180).

Kit's timeline gives every time in seconds (`omni.timeline`'s `TIME_PARAMETERS.md`, Kit 110; the same getters in Kit
107). Its own tests say what happens at the end (`omni.timeline`'s `tests.py`, Kit 107 and 110): a looping timeline goes
back to its start, at `elapsed % (end - start) + start`; one that doesn't loop pauses at its end, its time equal to the
end. The server says so in its answer.
"""

from typing import Protocol


class Timeline(Protocol):
    """What get_sim_state reads of Kit's timeline (omni.timeline's Timeline, Kit 107 and 110)."""

    def get_start_time(self) -> float: ...
    def get_end_time(self) -> float: ...
    def is_looping(self) -> bool: ...


def timeline_range(timeline: Timeline) -> dict[str, float | bool]:
    """The timeline's start and end in seconds and whether it loops, read together."""
    return {
        "start_time": float(timeline.get_start_time()),
        "end_time": float(timeline.get_end_time()),
        "looping": bool(timeline.is_looping()),
    }
