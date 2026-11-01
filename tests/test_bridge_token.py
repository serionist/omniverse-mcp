"""The token file and the protocol constant: what the extension writes, the MCP server reads."""

import platform
import sys
import tomllib

import pytest

from omniverse_mcp import bridge_token, client
from ovmcp.core import protocol as ext_protocol
from ovmcp.core import token as ext_token

from .conftest import EXTENSION_ROOT, REPO_ROOT


def test_both_sides_agree_on_the_token_path(state):
    assert ext_token.token_path(8211) == bridge_token.token_path(8211) == state / "bridge-8211.token"


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_both_sides_agree_without_an_override(platform, tmp_path, monkeypatch):
    monkeypatch.delenv("OMNIVERSE_MCP_STATE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(sys, "platform", platform)
    assert ext_token.state_dir() == bridge_token.state_dir()
    assert ext_token.state_dir().name == "omniverse-mcp"


def test_written_token_is_read_back(state):
    token = ext_token.new_token()
    ext_token.write_token(8211, token)
    assert bridge_token.read_token(8211) == token
    assert bridge_token.read_token(8212) is None


def test_write_replaces_an_earlier_token(state):
    ext_token.write_token(8211, "first")
    ext_token.write_token(8211, "second")
    assert bridge_token.read_token(8211) == "second"
    assert not list(state.glob("*.tmp"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_token_file_is_readable_by_its_owner_only(state):
    path = ext_token.write_token(8211, "secret")
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_leftover_temporary_file_never_holds_the_token_with_its_old_mode(state):
    leftover = state / "bridge-8211.token.tmp"
    leftover.write_text("old")
    leftover.chmod(0o644)
    path = ext_token.write_token(8211, "secret")
    assert path.stat().st_mode & 0o777 == 0o600
    assert not leftover.exists()


def test_remove_leaves_another_instances_token(state):
    ext_token.write_token(8211, "ours")
    ext_token.remove_token(8211, "theirs")
    assert bridge_token.read_token(8211) == "ours"
    ext_token.remove_token(8211, "ours")
    assert bridge_token.read_token(8211) is None


def test_environment_token_comes_first(state, monkeypatch):
    ext_token.write_token(8211, "from-file")
    monkeypatch.setenv("OMNIVERSE_MCP_TOKEN", "from-env")
    assert bridge_token.read_token(8211) == "from-env"


def test_both_sides_speak_the_same_protocol():
    assert client.PROTOCOL == ext_protocol.PROTOCOL


def test_extension_and_server_carry_one_version():
    # Kit hands on_startup "<name>-<version>" from extension.toml; the server's version is pyproject.toml's (plan D7).
    with (EXTENSION_ROOT / "config" / "extension.toml").open("rb") as f:
        extension_version = tomllib.load(f)["package"]["version"]
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        server_version = tomllib.load(f)["project"]["version"]
    assert extension_version == server_version
    ext_id = f"{ext_protocol.EXTENSION_NAME}-{extension_version}"
    assert ext_protocol.version_from_ext_id(ext_id) == extension_version


def test_extension_toml_uses_the_extension_name_everywhere():
    # Kit finds the module by [[python.module]] name and reads settings under exts."<name>"; the folder is the id.
    with (EXTENSION_ROOT / "config" / "extension.toml").open("rb") as f:
        toml = tomllib.load(f)
    name = ext_protocol.EXTENSION_NAME
    assert [module["name"] for module in toml["python"]["module"]] == [name]
    assert list(toml["settings"]["exts"]) == [name]
    assert set(toml["settings"]["exts"][name]) == {"host", "port", "token"}
    assert REPO_ROOT / "extension" / name == EXTENSION_ROOT


@pytest.mark.parametrize(
    ("ext_id", "version"),
    [("ovmcp.bridge-0.1.0", "0.1.0"), ("ovmcp.bridge-0.2.0-rc.1", "0.2.0-rc.1"), ("other-1.0", "unknown")],
)
def test_version_from_ext_id(ext_id, version):
    assert ext_protocol.version_from_ext_id(ext_id) == version


# ---- the Kit app the bridge runs in, for get_sim_state and a bug report (#105) ----


class _App:
    """omni.kit.app's IApp, as #105's probe read it on Isaac Sim 6.2 headless."""

    def get_app_name(self) -> str:
        return "Isaac-Sim Python"

    def get_app_version(self) -> str:
        return "6.2.0"

    def get_kit_version(self) -> str:
        return "110.4.0+feature.386251.187cf21b.gl"


def test_the_kit_app_s_facts_are_its_getters_and_python_s_os():
    assert ext_protocol.kit_app_facts(_App()) == {
        "kit_app_name": "Isaac-Sim Python",
        "kit_app_version": "6.2.0",
        "kit_version": "110.4.0+feature.386251.187cf21b.gl",
        "kit_os": platform.platform(),
    }


def test_a_getter_that_raises_or_is_missing_reads_unknown_and_the_rest_still_come():
    class _Older:
        """An app whose version getter fails, as Kit's bindings do, and that has no get_kit_version."""

        def get_app_name(self) -> str:
            return "Isaac-Sim Python"

        def get_app_version(self) -> str:
            raise RuntimeError("no version here")

    facts = ext_protocol.kit_app_facts(_Older())

    assert facts["kit_app_name"] == "Isaac-Sim Python"
    assert facts["kit_app_version"] == facts["kit_version"] == "unknown"


def test_the_facts_are_unknown_until_the_extension_starts_and_kept_after(monkeypatch):
    # The module's own default, four facts each unknown, which no test here sets without monkeypatch (review I11).
    facts = ("kit_app_name", "kit_app_version", "kit_version", "kit_os")
    assert ext_protocol.kit_app() == dict.fromkeys(facts, "unknown")
    monkeypatch.setattr(ext_protocol, "_kit_app", ext_protocol.kit_app())

    ext_protocol.set_kit_app(ext_protocol.kit_app_facts(_App()))

    assert ext_protocol.kit_app()["kit_app_name"] == "Isaac-Sim Python"
