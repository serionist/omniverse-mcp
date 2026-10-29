"""draw_debug's Kit-free part: each shape as segments, its colour, and the book of what still shows, on a fake clock."""

import math

import pytest

from ovmcp.core.debug_draw import RED, DebugBook, argb, duration_seconds, rgba, segments

# --- Shapes ---


def test_a_line_is_one_segment():
    shape = segments("line", {"start": [0, 0, 0], "end": [1, 2, 3]})
    assert shape.segments == [((0.0, 0.0, 0.0), (1.0, 2.0, 3.0))]
    assert shape.drawn == [{"type": "line", "start": [0.0, 0.0, 0.0], "end": [1.0, 2.0, 3.0]}]


def test_lines_join_neighbours():
    shape = segments("lines", {"points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]})
    assert shape.segments == [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0))]
    assert shape.drawn == [{"type": "lines", "segments": 2}]


def test_a_sphere_is_three_crossing_lines():
    shape = segments("sphere", {"center": [1, 2, 3], "radius": 0.5})
    assert shape.segments == [
        ((0.5, 2.0, 3.0), (1.5, 2.0, 3.0)),
        ((1.0, 1.5, 3.0), (1.0, 2.5, 3.0)),
        ((1.0, 2.0, 2.5), (1.0, 2.0, 3.5)),
    ]
    assert shape.drawn == [{"type": "sphere", "center": [1.0, 2.0, 3.0], "radius": 0.5}]


def test_a_sphere_takes_the_default_radius():
    shape = segments("sphere", {"center": [0, 0, 0]})
    assert shape.segments[0] == ((-0.1, 0.0, 0.0), (0.1, 0.0, 0.0))


def test_each_point_is_a_cross_of_half_length_size():
    shape = segments("points", {"points": [[0, 0, 0], [5, 5, 5]], "size": 1})
    assert len(shape.segments) == 6
    assert shape.segments[3:] == [
        ((4.0, 5.0, 5.0), (6.0, 5.0, 5.0)),
        ((5.0, 4.0, 5.0), (5.0, 6.0, 5.0)),
        ((5.0, 5.0, 4.0), (5.0, 5.0, 6.0)),
    ]
    assert shape.drawn == [{"type": "point", "position": [0.0, 0.0, 0.0]}, {"type": "point", "position": [5.0] * 3}]


def test_points_take_the_default_size():
    shape = segments("points", {"points": [[0, 0, 0]]})
    assert shape.segments[0] == ((-0.05, 0.0, 0.0), (0.05, 0.0, 0.0))


def test_a_point_is_one_cross():
    shape = segments("point", {"position": [0, 0, 0], "size": 2})
    assert shape.segments[1] == ((0.0, -2.0, 0.0), (0.0, 2.0, 0.0))
    assert shape.drawn == [{"type": "point", "position": [0.0, 0.0, 0.0]}]


@pytest.mark.parametrize(
    ("shape", "body", "message"),
    [
        # What a shape needs, with the messages from before
        ("line", {"start": [0, 0, 0]}, "start and end required for line"),
        ("line", {"end": [0, 0, 0]}, "start and end required for line"),
        ("lines", {"points": [[0, 0, 0]]}, "At least 2 points needed for lines"),
        ("lines", {}, "At least 2 points needed for lines"),
        ("sphere", {}, "center required for sphere"),
        ("points", {"points": []}, "points list required for points"),
        ("points", {}, "points list required for points"),
        ("point", {}, "position required for point"),
        # Vectors and numbers
        ("line", {"start": [0, 0], "end": [1, 1, 1]}, "start must be [x, y, z]"),
        ("line", {"start": [0, 0, 0], "end": [1, 1, 1, 1]}, "end must be [x, y, z]"),
        ("line", {"start": [0, 0, "1"], "end": [1, 1, 1]}, "start must be [x, y, z]"),
        ("line", {"start": [0, 0, math.nan], "end": [1, 1, 1]}, "start must be [x, y, z]"),
        ("line", {"start": [0, 0, True], "end": [1, 1, 1]}, "start must be [x, y, z]"),
        ("line", {"start": "0, 0, 0", "end": [1, 1, 1]}, "start must be [x, y, z]"),
        ("lines", {"points": [[0, 0, 0], [1, math.inf, 0]]}, "points[1] must be [x, y, z]"),
        ("lines", {"points": 3}, "points must be a list of [x, y, z]"),
        ("sphere", {"center": [0, 0, 0], "radius": "big"}, "radius must be a finite number"),
        ("points", {"points": [[0, 0, 0]], "size": None}, "size must be a finite number"),
        ("point", {"position": [0, 0, 0], "size": math.inf}, "size must be a finite number"),
        # A shape the bridge doesn't draw, which once drew nothing and reported success
        ("box", {"center": [0, 0, 0]}, "Unknown shape 'box'"),
        ("Line", {"start": [0, 0, 0], "end": [1, 1, 1]}, "Unknown shape 'Line'"),
    ],
)
def test_what_is_wrong_is_said(shape, body, message):
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        segments(shape, body)


# --- Colours ---


def test_red_when_no_colour_is_given():
    assert rgba(None) == RED == (1.0, 0.0, 0.0, 1.0)


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        ([0, 1, 0], (0.0, 1.0, 0.0, 1.0)),
        ((0.25, 0.5, 0.75), (0.25, 0.5, 0.75, 1.0)),
        ([2, -1, 0.5], (1.0, 0.0, 0.5, 1.0)),  # clamped to 0-1
        ([255, 0, 0], (1.0, 0.0, 0.0, 1.0)),
        ([0, 0, 1, 0.5], (0.0, 0.0, 1.0, 1.0)),  # past the third ignored, as before
    ],
)
def test_colours_are_clamped_with_alpha_one(color, expected):
    assert rgba(color) == expected


@pytest.mark.parametrize("color", [[1, 0], [], "red", [1, 0, "0"], [1, 0, math.nan], 1.0])
def test_a_colour_that_isnt_three_numbers_is_refused(color):
    with pytest.raises(ValueError, match="color must be"):
        rgba(color)


@pytest.mark.parametrize(
    ("color", "packed"),
    [
        (RED, 0xFFFF0000),
        ((0.0, 1.0, 0.0, 1.0), 0xFF00FF00),
        ((0.0, 0.0, 1.0, 0.0), 0x000000FF),
        ((1.0, 1.0, 1.0, 1.0), 0xFFFFFFFF),
        ((0.5, 0.0, 0.0, 1.0), 0xFF800000),
    ],
)
def test_argb_packs_alpha_red_green_blue(color, packed):
    assert argb(color) == packed


def test_a_channel_above_one_doesnt_spill_into_the_next():
    # Unclamped, a red of 2 packed as 510 << 16 and turned alpha's bits.
    assert argb((2.0, 0.0, 0.0, 1.0)) == 0xFFFF0000
    assert argb((0.0, 3.0, -1.0, 1.0)) == 0xFF00FF00
    assert argb(rgba([2, 0, 0])) == 0xFFFF0000


# --- Duration ---


@pytest.mark.parametrize(("value", "seconds"), [(5, 5.0), (0.25, 0.25), (30.0, 30.0)])
def test_a_duration_is_seconds_above_zero(value, seconds):
    assert duration_seconds(value) == seconds


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan, "5", None, True])
def test_a_duration_that_isnt_seconds_above_zero_is_refused(value):
    with pytest.raises(ValueError, match="duration must be a number of seconds above 0"):
        duration_seconds(value)


# --- The book ---

LINE = [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))]
CROSS = segments("sphere", {"center": [0, 0, 0]}).segments
GREEN = (0.0, 1.0, 0.0, 1.0)
STAGE, OTHER_STAGE = 7, 8


def test_an_empty_book_is_idle_and_has_no_lines():
    book = DebugBook()
    assert book.empty
    assert book.idle
    assert book.lines() == ([], [], [])


def test_the_book_lists_every_segment_with_its_colour():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=0.0, duration=1.0)
    book.add(CROSS, GREEN, STAGE, now=0.0, duration=3.0)
    starts, ends, colours = book.lines()
    assert starts == [LINE[0][0], *(s for s, _ in CROSS)]
    assert ends == [LINE[0][1], *(e for _, e in CROSS)]
    assert colours == [RED, GREEN, GREEN, GREEN]
    assert not book.empty


def test_of_two_durations_the_shorter_goes_first_then_the_other():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=10.0, duration=1.0)
    book.add(CROSS, GREEN, STAGE, now=10.0, duration=3.0)
    assert not book.expire(10.5)  # nothing went
    assert book.expire(11.0)  # the 1 s line, at its moment
    assert book.lines()[2] == [GREEN] * 3
    assert not book.expire(12.9)
    assert book.expire(13.0)
    assert book.empty
    assert not book.expire(20.0)


def test_keep_stage_drops_another_stages_drawings_and_keeps_this_ones():
    book = DebugBook()
    book.add(LINE, RED, OTHER_STAGE, now=0.0, duration=30.0)
    book.add(CROSS, GREEN, STAGE, now=0.0, duration=30.0)
    assert book.keep_stage(STAGE)  # the line, drawn on the other stage, goes
    assert book.lines()[2] == [GREEN] * 3
    assert not book.keep_stage(STAGE)  # nothing more goes
    assert book.lines()[2] == [GREEN] * 3


def test_a_tick_owes_a_clear_when_a_drawing_goes_and_pays_it_now_while_the_stage_is_open():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=0.0, duration=1.0)
    book.add(CROSS, GREEN, STAGE, now=0.0, duration=3.0)
    assert not book.tick(0.5, STAGE, stage_open=True)  # nothing went: nothing to clear
    assert book.tick(1.0, STAGE, stage_open=True)  # the line went: clear, then draw the cross again
    assert not book.clear_owed
    assert book.lines()[2] == [GREEN] * 3
    assert not book.tick(2.0, STAGE, stage_open=True)
    assert book.tick(3.0, STAGE, stage_open=True)
    assert book.idle


def test_a_clear_owed_while_the_stage_changes_waits_for_it_to_open():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=0.0, duration=1.0)
    # The line expires while the stage closes: no clear then, which crashed Kit before debug_draw 3.2.8.
    assert not book.tick(1.0, STAGE, stage_open=False)
    assert book.clear_owed
    assert book.empty
    assert not book.idle  # the subscription stays until the clear is paid
    assert not book.tick(1.5, STAGE, stage_open=False)
    assert book.tick(2.0, STAGE, stage_open=True)
    assert book.idle


def test_a_tick_on_a_new_stage_drops_the_old_ones_drawings():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=0.0, duration=30.0)
    # new_scene: the stage's id changes while it opens, then it is open.
    assert not book.tick(1.0, OTHER_STAGE, stage_open=False)
    assert book.empty
    book.add(CROSS, GREEN, OTHER_STAGE, now=1.5, duration=1.0)
    assert book.tick(2.0, OTHER_STAGE, stage_open=True)  # the owed clear, then the cross alone
    assert book.lines()[2] == [GREEN] * 3
    assert book.tick(2.5, OTHER_STAGE, stage_open=True)
    assert book.idle


def test_reset_forgets_drawings_and_the_clear_owed():
    book = DebugBook()
    book.add(LINE, RED, STAGE, now=0.0, duration=1.0)
    book.tick(1.0, STAGE, stage_open=False)
    book.add(CROSS, GREEN, STAGE, now=1.0, duration=1.0)
    book.reset()
    assert book.idle
    assert book.lines() == ([], [], [])
