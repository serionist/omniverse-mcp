"""viewport_light's decisions: the mode in effect, and what the legacy camera-light switch does."""

import pytest

from ovmcp.core.lighting import camera_light_switch, current_mode


@pytest.mark.parametrize(
    ("flag", "menu", "mode"),
    [
        (True, None, "camera"),
        (True, "Default", "camera"),
        (True, "stage", "camera"),
        (False, "camera", "stage"),  # the menu's record is stale: the flag is off
        (False, None, "stage"),
        (False, "", "stage"),
        (False, "stage", "stage"),
        (False, "off", "off"),
        (False, "Default", "Default"),
        (False, "Grey Studio", "Grey Studio"),
    ],
)
def test_current_mode(flag, menu, mode):
    assert current_mode(flag, menu) == mode


@pytest.mark.parametrize(
    ("enabled", "current", "sets"),
    [
        (True, "stage", "camera"),
        (True, "Default", "camera"),
        (True, "camera", "camera"),
        (False, "camera", "stage"),
        (False, "Default", None),  # a rig stays; only the flag is cleared, as before
        (False, "stage", None),
        (False, "off", None),
    ],
)
def test_camera_light_switch(enabled, current, sets):
    assert camera_light_switch(enabled, current) == sets
