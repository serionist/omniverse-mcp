"""`omniverse-mcp extension install|path`: the extension of this release copied to the user's folder, whole, from a
checkout or from the wheel; an install that fails leaves the one before it in place."""

import shutil
import sys
import tomllib
import zipfile
from importlib.metadata import version
from pathlib import Path

import gate
import pytest

from omniverse_mcp import kit_extension
from omniverse_mcp.server import main

from .conftest import EXTENSION_ROOT, REPO_ROOT


def _files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def _install(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exited:
        main(["extension", *argv])
    return int(exited.value.code or 0)


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A user data folder of the test's own: never the developer's real one."""
    folder = tmp_path / "data"
    monkeypatch.setattr(kit_extension, "data_dir", lambda: folder)
    return folder


def _old_install(root: Path) -> Path:
    target = root / "ovmcp.bridge"
    (target / "config").mkdir(parents=True)
    (target / "config" / "extension.toml").write_text('[package]\nversion = "0.0.1"\n', encoding="utf-8")
    (target / "ovmcp" / "dropped.py").parent.mkdir()
    (target / "ovmcp" / "dropped.py").write_text("", encoding="utf-8")
    return target


def _only_the_install(data: Path) -> None:
    """Neither the copy nor the old one is left beside the install, nor in the folder above it."""
    assert [p.name for p in data.iterdir()] == ["exts"]
    assert [p.name for p in (data / "exts").iterdir()] == ["ovmcp.bridge"]


def test_a_checkout_installs_its_own_extension(data: Path, capsys: pytest.CaptureFixture[str]):
    assert kit_extension.source() == EXTENSION_ROOT
    assert _install(["install"]) == 0
    target = data / "exts" / "ovmcp.bridge"
    assert _files(target) == _files(EXTENSION_ROOT)
    assert not (target / "ovmcp" / "__pycache__").exists()
    _only_the_install(data)
    out = capsys.readouterr().out
    assert f"Installed ovmcp.bridge {kit_extension.extension_version(EXTENSION_ROOT)} in {target}." in out
    # Quoted, as a shell takes it: a profile folder may hold a space.
    assert f"--ext-folder {kit_extension._quoted(data / 'exts')} --enable ovmcp.bridge" in out


def test_the_listing_s_files_are_in_the_extension():
    # Kit's Extensions window, and Kit's community registry, show what the toml names (#101); `exchange` would label the
    # extension verified by NVIDIA.
    with (EXTENSION_ROOT / "config" / "extension.toml").open("rb") as f:
        package = tomllib.load(f)["package"]
    for key in ("readme", "icon", "preview_image"):
        assert (EXTENSION_ROOT / package[key]).is_file(), key
    assert package["repository"] == "https://github.com/serionist/omniverse-mcp"
    assert package["keywords"]
    assert "exchange" not in package
    # Kit 107 or later, as the README says; Kit reads a target as "this version or later".
    assert package["target"] == {"kit": ["107.0"]}


def test_an_install_replaces_the_one_before_whole(data: Path, capsys: pytest.CaptureFixture[str]):
    target = _old_install(data / "exts")
    assert _install(["install"]) == 0
    assert _files(target) == _files(EXTENSION_ROOT)
    assert "in place of 0.0.1" in capsys.readouterr().out
    _only_the_install(data)


def _refuse(monkeypatch: pytest.MonkeyPatch, *prefixes: str) -> None:
    """Renames of folders named with these prefixes fail, as Windows refuses while a Kit app holds the folder."""
    rename = Path.rename

    def held(self: Path, to: Path) -> Path:
        if self.name.startswith(prefixes):
            raise PermissionError(13, "Access is denied")
        return rename(self, to)

    monkeypatch.setattr(Path, "rename", held)


@pytest.mark.parametrize("held", [".ovmcp.bridge.new-", "ovmcp.bridge"], ids=["swap", "move-aside"])
def test_an_install_that_fails_keeps_the_one_before(
    held: str, data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    target = _old_install(data / "exts")
    _refuse(monkeypatch, held)
    assert _install(["install"]) == 1
    assert "quit it, and run this again" in capsys.readouterr().err
    assert kit_extension.extension_version(target) == "0.0.1"
    assert (target / "ovmcp" / "dropped.py").is_file()
    _only_the_install(data)


def test_an_install_that_cannot_put_the_one_before_back_keeps_it_and_says_where(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _old_install(data / "exts")
    _refuse(monkeypatch, ".ovmcp.bridge.new-", ".ovmcp.bridge.old-")
    assert _install(["install"]) == 1
    err = capsys.readouterr().err
    (kept,) = data.glob(".ovmcp.bridge.old-*")
    assert f"It is in {kept}" in err
    assert kit_extension.extension_version(kept) == "0.0.1"
    assert not (data / "exts" / "ovmcp.bridge").exists()


def test_an_install_without_the_extension_says_so(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(kit_extension, "_PACKAGE", tmp_path / "site" / "omniverse_mcp")
    assert _install(["install"]) == 1
    assert "carries no Kit extension" in capsys.readouterr().err
    assert not data.exists()


def test_an_install_into_a_folder_it_cannot_write_says_so(data: Path, capsys: pytest.CaptureFixture[str]):
    data.parent.mkdir(exist_ok=True)
    data.write_text("a file where the folder goes", encoding="utf-8")
    assert _install(["install"]) == 1
    assert f"Could not write to {data / 'exts'}" in capsys.readouterr().err


def test_path_prints_the_folder_and_fails_until_installed(data: Path, capsys: pytest.CaptureFixture[str]):
    assert _install(["path"]) == 1
    out, err = capsys.readouterr()
    assert out.strip() == str(data / "exts")
    assert f"not installed there yet: {kit_extension.install_command()}" in err
    _old_install(data / "exts")
    assert _install(["path"]) == 0
    assert capsys.readouterr().out.strip() == str(data / "exts")


def test_the_install_command_fits_the_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # A checkout's version need not be on PyPI: it installs its own extension.
    assert kit_extension.install_command().startswith("uv run --project ")
    assert kit_extension.install_command().endswith(" omniverse-mcp extension install")
    wheel = tmp_path / "site" / "omniverse_mcp"
    (wheel / "_extension" / "ovmcp.bridge" / "config").mkdir(parents=True)
    (wheel / "_extension" / "ovmcp.bridge" / "config" / "extension.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(kit_extension, "_PACKAGE", wheel)
    release = f"uvx omniverse-mcp=={version('omniverse-mcp')} extension install"
    assert kit_extension.install_command() == release
    shutil.rmtree(wheel / "_extension")
    assert kit_extension.install_command() == release


def test_the_advice_names_the_command_and_the_registry_s_way(monkeypatch: pytest.MonkeyPatch):
    # A bridge from Kit's community registry isn't in the folder the command fills: its user picks the version in Kit.
    monkeypatch.setattr(kit_extension, "install_command", lambda: "uvx omniverse-mcp==9.8.7 extension install")
    monkeypatch.setattr(kit_extension, "carried_version", lambda: "9.8.7")
    assert kit_extension.install_advice() == (
        "uvx omniverse-mcp==9.8.7 extension install, then restart Kit; with the extension from Kit's community "
        "registry, install 9.8.7 in Kit's Extensions window instead"
    )


@pytest.mark.parametrize(
    ("platform", "env", "base"),
    [
        ("win32", {"LOCALAPPDATA": "C:/Users/u/AppData/Local"}, Path("C:/Users/u/AppData/Local")),
        ("linux", {"XDG_DATA_HOME": "/home/u/.data"}, Path("/home/u/.data")),
        ("linux", {}, Path.home() / ".local" / "share"),
        ("darwin", {}, Path.home() / "Library" / "Application Support"),
    ],
)
def test_the_data_folder_is_where_platformdirs_puts_it(
    platform: str, env: dict[str, str], base: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", platform)
    for name in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert kit_extension.data_dir() == base / "omniverse-mcp"


def test_the_wheel_installs_the_extension_it_carries(data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    uv = shutil.which("uv")
    assert uv, "the wheel is built with uv"
    # Offline: the build backend is in uv's cache from the editable install the tests run in.
    built = gate.run([uv, "build", "--wheel", "--offline", "--out-dir", str(tmp_path / "dist"), str(REPO_ROOT)])
    assert built.returncode == 0, built.stderr
    (wheel,) = (tmp_path / "dist").glob("*.whl")
    site = tmp_path / "site"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(site)
    # The package where the wheel puts it, with no checkout beside it to fall back on.
    monkeypatch.setattr(kit_extension, "_PACKAGE", site / "omniverse_mcp")
    carried = site / "omniverse_mcp" / "_extension" / "ovmcp.bridge"
    assert kit_extension.source() == carried
    assert _files(carried) == _files(EXTENSION_ROOT)
    assert _install(["install"]) == 0
    assert _files(data / "exts" / "ovmcp.bridge") == _files(carried)
