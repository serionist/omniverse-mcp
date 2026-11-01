"""What the bridge tells the MCP server about itself in /health: the protocol, its version, and the Kit app it runs
in, which /sim/state gives get_sim_state too."""

import platform

# Raised when the server and the extension stop understanding each other's requests. The server's copy is
# omniverse_mcp.client.PROTOCOL; tests/test_bridge_token.py keeps them equal.
PROTOCOL = 1

EXTENSION_NAME = "ovmcp.bridge"

_version = "unknown"


def version_from_ext_id(ext_id: str) -> str:
    """Kit hands on_startup an id of the form '<name>-<version>'."""
    prefix = EXTENSION_NAME + "-"
    return ext_id[len(prefix) :] if ext_id.startswith(prefix) else "unknown"


def set_extension_version(version: str) -> None:
    global _version
    _version = version


def extension_version() -> str:
    return _version


UNKNOWN = "unknown"
# IApp's getter for each fact (omni.kit.app's _app.pyi in Isaac Sim 6.2's kernel).
_GETTERS = {"kit_app_name": "get_app_name", "kit_app_version": "get_app_version", "kit_version": "get_kit_version"}
_kit_app: dict[str, str] = dict.fromkeys((*_GETTERS, "kit_os"), UNKNOWN)


def kit_app_facts(app: object) -> dict[str, str]:
    """The Kit app's name, its version and Kit's, from app, omni.kit.app's IApp, and the OS it runs on, as Python names
    it: what a bug report asks for (#105). Each is read on its own, so one a Kit app lacks, or one that raises, reads
    unknown and the rest still come."""
    facts: dict[str, str] = {}
    for key, getter in _GETTERS.items():
        try:
            value = str(getattr(app, getter)())
        except (AttributeError, TypeError, RuntimeError):
            # A Kit app without the getter, or one whose getter fails, as Kit's bindings do with a RuntimeError.
            value = ""
        facts[key] = value or UNKNOWN
    facts["kit_os"] = platform.platform() or UNKNOWN
    return facts


def set_kit_app(facts: dict[str, str]) -> None:
    """Kept at the extension's start: nothing in them changes while Kit runs, and a reload starts it again."""
    global _kit_app
    _kit_app = dict(facts)


def kit_app() -> dict[str, str]:
    return dict(_kit_app)
