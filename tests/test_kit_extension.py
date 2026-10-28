"""`omniverse-mcp extension install|path`: the extension of this release copied to the user's folder, whole, from a
checkout or from the wheel; an install that fails leaves the one before it in place."""

import shutil
import sys
import zipfile
from pathlib import Path

import gate
import pytest

from omniverse_mcp import kit_extension
from omniverse_mcp.server import main

from .conftest import EXTENSION_ROOT, REPO_ROOT


def _files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def _tracked() -> set[str]:
    """The extension's files as git has them: a stray file in the working tree is not what a release ships."""
    done = gate.git("-c", "safe.directory=*", "ls-files", "--", "extension/ovmcp.bridge", cwd=REPO_ROOT)
    assert done.returncode == 0, done.stderr
    return {line.removeprefix("extension/ovmcp.bridge/") for line in done.stdout.splitlines()}


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


def test_a_checkout_installs_its_own_extension(data: Path, capsys: pytest.CaptureFixture[str]):
    assert kit_extension.source() == EXTENSION_ROOT
    assert _install(["install"]) == 0
    target = data / "exts" / "ovmcp.bridge"
    assert _files(target) == _tracked()
    assert not (target / "ovmcp" / "__pycache__").exists()
    out = capsys.readouterr().out
    assert f"Installed ovmcp.bridge {kit_extension.extension_version(EXTENSION_ROOT)} in {target}." in out
    assert f"--ext-folder {data / 'exts'} --enable ovmcp.bridge" in out


def test_an_install_replaces_the_one_before_whole(data: Path, capsys: pytest.CaptureFixture[str]):
    target = _old_install(data / "exts")
    assert _install(["install"]) == 0
    assert _files(target) == _tracked()
    assert "in place of 0.0.1" in capsys.readouterr().out
    # Neither the copy nor the old one is left beside it.
    assert [p.name for p in (data / "exts").iterdir()] == ["ovmcp.bridge"]


def test_an_install_that_fails_keeps_the_one_before(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    target = _old_install(data / "exts")
    rename = Path.rename

    def held(self: Path, to: Path) -> Path:
        # As Windows refuses when a Kit app holds the folder.
        if self.name.startswith(".ovmcp.bridge.new-"):
            raise PermissionError(13, "Access is denied")
        return rename(self, to)

    monkeypatch.setattr(Path, "rename", held)
    assert _install(["install"]) == 1
    assert "quit it, and run this again" in capsys.readouterr().err
    assert kit_extension.extension_version(target) == "0.0.1"
    assert (target / "ovmcp" / "dropped.py").is_file()
    assert [p.name for p in (data / "exts").iterdir()] == ["ovmcp.bridge"]


def test_an_install_without_the_extension_says_so(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(kit_extension, "_PACKAGE", tmp_path / "site" / "omniverse_mcp")
    assert _install(["install"]) == 1
    assert "carries no Kit extension" in capsys.readouterr().err
    assert not data.exists()


def test_path_prints_the_folder_and_fails_until_installed(data: Path, capsys: pytest.CaptureFixture[str]):
    assert _install(["path"]) == 1
    out, err = capsys.readouterr()
    assert out.strip() == str(data / "exts")
    assert "not installed there yet" in err
    _old_install(data / "exts")
    assert _install(["path"]) == 0
    assert capsys.readouterr().out.strip() == str(data / "exts")


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
    built = gate.run([uv, "build", "--wheel", "--out-dir", str(tmp_path / "dist"), str(REPO_ROOT)])
    assert built.returncode == 0, built.stderr
    (wheel,) = (tmp_path / "dist").glob("*.whl")
    site = tmp_path / "site"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(site)
    # The package where the wheel puts it, with no checkout beside it to fall back on.
    monkeypatch.setattr(kit_extension, "_PACKAGE", site / "omniverse_mcp")
    carried = site / "omniverse_mcp" / "_extension" / "ovmcp.bridge"
    assert kit_extension.source() == carried
    assert _install(["install"]) == 0
    assert _files(carried) == _files(data / "exts" / "ovmcp.bridge") == _tracked()
