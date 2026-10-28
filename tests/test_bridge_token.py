"""The token file and the protocol constant: what the extension writes, the MCP server reads."""

import sys
import tomllib

import pytest
from isaacsim.mcp.bridge.core import protocol as ext_protocol
from isaacsim.mcp.bridge.core import token as ext_token

from isaac_sim_mcp import bridge_token, client

from .conftest import EXTENSION_ROOT


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path


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


def test_extension_folder_name_matches_its_id_and_version():
    # Kit derives the ext_id it hands on_startup from these; version_from_ext_id reads it back.
    with (EXTENSION_ROOT / "config" / "extension.toml").open("rb") as f:
        version = tomllib.load(f)["package"]["version"]
    assert EXTENSION_ROOT.name == f"{ext_protocol.EXTENSION_NAME}-{version}"
    assert ext_protocol.version_from_ext_id(EXTENSION_ROOT.name) == version


@pytest.mark.parametrize(
    ("ext_id", "version"),
    [("isaacsim.mcp.bridge-1.0.0", "1.0.0"), ("isaacsim.mcp.bridge-0.2.0-rc.1", "0.2.0-rc.1"), ("other-1.0", "unknown")],
)
def test_version_from_ext_id(ext_id, version):
    assert ext_protocol.version_from_ext_id(ext_id) == version
