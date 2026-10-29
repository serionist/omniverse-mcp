"""Whether the bridge can use a Kit extension it needs, and what that takes. No Kit.

The bridge turns on an extension it draws with on first use, but only one this Kit app has on disk: Kit would look
for any other name in the extension registry, which is slow, may be offline, and logs an error on an app that never
had it.
"""

from collections.abc import Iterable, Mapping
from typing import Literal

Step = Literal["ready", "enable", "absent"]


def extension_step(enabled: bool, listed: bool) -> Step:
    """`ready` when the extension is on, `enable` when it is off but Kit lists it on disk here, `absent` otherwise."""
    if enabled:
        return "ready"
    return "enable" if listed else "absent"


def is_listed(name: str, extensions: Iterable[Mapping[str, object]]) -> bool:
    """Whether `name` is among the extensions Kit's extension manager lists (`get_extensions()`), by each one's name."""
    return any(entry.get("name") == name for entry in extensions)
