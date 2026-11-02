"""Kit's update event, observed through Events 2.0: the one way the bridge runs code on every app update (#122).

Kit's own `next_update_async` observes this event in Kit 107 and Kit 110 alike; the app's event streams log a
deprecation, with a call stack, at each call. tests/test_updates.py fails on any of them in the extension.
"""

from collections.abc import Callable
from typing import Any


def on_update(name: str, callback: Callable[[], None]) -> Any:
    """Calls `callback` once each update of Kit's main run loop, on Kit's main thread, until the guard it returns is
    dropped or reset, from inside `callback` too.

    At order 0, where the app's update stream ran its subscriptions (measured the same place on Isaac Sim 6.2, #122's
    P1): after USD's update and the physics step (-10), before the UI (15), Fabric's flush (20), Hydra's render (30),
    `next_update_async` (50) and the asyncio loop that runs the handlers (100), as Kit's KitUpdateOrder.h orders them.
    A callback that raises is Kit's to log, and Kit calls it again on the next update (P4).
    """
    # Imported here, as camera_feed.py imports carb.eventdispatcher where it observes: a handler that imports this
    # module still loads where a test fakes Kit without them.
    import carb.eventdispatcher
    import omni.kit.app

    return carb.eventdispatcher.get_eventdispatcher().observe_event(
        order=omni.kit.app.UPDATE_ORDER_UNSPECIFIED,
        event_name=omni.kit.app.GLOBAL_EVENT_UPDATE,
        on_event=lambda _event: callback(),
        observer_name=f"ovmcp.bridge {name}",
    )
