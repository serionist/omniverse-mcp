"""Where a tool loads a USD file it is given from: a URL, a file on the Kit app's machine, or a path in Isaac Sim's
asset library. create_robot and open_scene share the rule (#40, #79).

Kit-free, so unit-tested without Kit: the handler passes in how to find Isaac Sim's asset root, whether a file exists
on the Kit app's machine, and how to make a path whole there.
"""

import re
from collections.abc import Callable

# A path in Isaac Sim's asset library, such as the robots' own, is found under the library's root, a URL Isaac Sim
# knows; any other path is a file on the Kit app's machine.
LIBRARY_PREFIX = "/Isaac/"
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def is_url(path: str) -> bool:
    """Whether path is a URL (scheme://...), which loads as given."""
    return bool(_URL.match(path))


def usd_file_url(
    usd_path: str,
    assets_root: Callable[[], str | None],
    is_file: Callable[[str], bool],
    whole: Callable[[str], str],
) -> str | None:
    """Where to load usd_path from: a URL as given, a file on this machine made whole, a library path under the
    library's root; None for a path that is none of these. assets_root is asked only for a library path: Isaac Sim may
    look on the network to find it."""
    if is_url(usd_path):
        return usd_path
    if is_file(usd_path):
        # A reference reads a relative path against the stage's own folder, not the one Kit was started in.
        return whole(usd_path)
    if usd_path.startswith(LIBRARY_PREFIX):
        root = assets_root()
        return root.rstrip("/") + usd_path if root else usd_path
    return None
