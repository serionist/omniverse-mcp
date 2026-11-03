"""The timeline's range and looping as get_sim_state reads them (#180), from a fake of Kit's timeline."""

from dataclasses import dataclass

import pytest

from ovmcp.core.timeline import timeline_range


@dataclass
class FakeTimeline:
    start: float
    end: float
    loops: bool

    def get_start_time(self) -> float:
        return self.start

    def get_end_time(self) -> float:
        return self.end

    def is_looping(self) -> bool:
        return self.loops


@pytest.mark.parametrize("loops", [True, False])
def test_the_range_in_seconds_and_the_looping_are_read_together(loops: bool):
    assert timeline_range(FakeTimeline(0.0, 16666.666666666668, loops)) == {
        "start_time": 0.0,
        "end_time": 16666.666666666668,
        "looping": loops,
    }


def test_kit_s_whole_numbers_come_back_as_floats():
    # The answer is JSON either way; a whole number of seconds still reads as seconds.
    got = timeline_range(FakeTimeline(0, 2, True))

    assert got == {"start_time": 0.0, "end_time": 2.0, "looping": True}
    assert [type(v) for v in got.values()] == [float, float, bool]
