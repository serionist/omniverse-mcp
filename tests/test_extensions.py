"""Turning on an extension the bridge needs: only one this Kit app has on disk, so an app without it gets no registry
fetch and no error in Kit's log."""

import pytest

from ovmcp.core.extensions import extension_step, is_listed


@pytest.mark.parametrize(
    ("enabled", "listed", "step"),
    [
        (True, True, "ready"),
        (True, False, "ready"),  # on, whatever the listing says
        (False, True, "enable"),
        (False, False, "absent"),
    ],
)
def test_extension_step(enabled, listed, step):
    assert extension_step(enabled, listed) == step


# The shape of Kit's get_extensions(): a dict per extension on disk, its name without the version.
LISTING = (
    {"id": "omni.debugdraw-0.1.4", "name": "omni.debugdraw", "enabled": False},
    {"id": "isaacsim.util.debug_draw-3.2.8", "name": "isaacsim.util.debug_draw", "enabled": True},
)


@pytest.mark.parametrize(
    ("name", "listed"),
    [
        ("omni.debugdraw", True),
        ("isaacsim.util.debug_draw", True),
        ("omni.invented", False),
        ("omni.debugdraw-0.1.4", False),  # an id, not a name
        ("omni", False),
    ],
)
def test_is_listed(name, listed):
    assert is_listed(name, LISTING) is listed


def test_nothing_is_listed_in_an_empty_listing():
    assert not is_listed("omni.debugdraw", ())
