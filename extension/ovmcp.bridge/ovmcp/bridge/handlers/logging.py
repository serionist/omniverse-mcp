"""get_logs: Kit's log file, read into ovmcp.core.logs' ring from where it ended when the extension started.

The bridge hands Kit's logging no Python callback, in any form: Kit runs one on the thread that logs, and one
deadlocked Kit when a physics worker logged while the main thread held the GIL (#5). tests/test_logs.py fails on one.
This module keeps only the Kit calls: the setting, carb.tokens, and the token.
"""

import carb.settings
import carb.tokens

from ovmcp.core.logs import KitLog

# Started from extension.py's on_startup; /logs reads through it.
kit_log = KitLog()


def start(token: str) -> None:
    """Find Kit's log file and note where it ends now: /logs reads what Kit writes after, with token redacted."""
    tokens = carb.tokens.get_tokens_interface()

    def resolve(text: str) -> object:
        # A token carb can't resolve stays as it is, so the core can tell it from a path.
        return tokens.resolve(text, carb.tokens.RESOLVE_FLAG_LEAVE_TOKEN_IF_NOT_FOUND)

    kit_log.start(carb.settings.get_settings().get("/log/file"), resolve, token)


# ---------------------------------------------------------------------------
# /logs
# ---------------------------------------------------------------------------


async def handle_get_logs(body: dict) -> dict:
    """The newest entries of Kit's log that pass the request's filters, read from Kit's log file on the main thread."""
    return kit_log.query(body)
