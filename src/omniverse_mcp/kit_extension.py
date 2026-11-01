"""The Kit extension this release carries, and `omniverse-mcp extension install|path` (plan D9).

The wheel holds the extension as `omniverse_mcp/_extension/ovmcp.bridge`; a checkout has it at
`extension/ovmcp.bridge`. `install` copies it to one per-user folder that Kit's extension search path points at once,
so the server and the extension a Kit app loads come from the same release.
"""

import os
import shlex
import shutil
import sys
import tempfile
import tomllib
from importlib.metadata import version
from pathlib import Path

# The extension's id, and the name of its folder; the server never imports the extension's own constant.
EXTENSION_ID = "ovmcp.bridge"

_PACKAGE = Path(__file__).resolve().parent


class InstallError(RuntimeError):
    """The extension could not be installed. The message says what to do."""


def data_dir() -> Path:
    """The user's data folder for omniverse-mcp, where platformdirs would put it."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "omniverse-mcp"


def exts_dir() -> Path:
    """The folder Kit's extension search path points at: it holds the installed `ovmcp.bridge`."""
    return data_dir() / "exts"


def _carried() -> Path:
    return _PACKAGE / "_extension" / EXTENSION_ID


def source() -> Path:
    """The extension this install carries: the wheel's copy, else a checkout's, where an editable install has none."""
    for candidate in (_carried(), _PACKAGE.parents[1] / "extension" / EXTENSION_ID):
        if (candidate / "config" / "extension.toml").is_file():
            return candidate
    raise InstallError(f"This omniverse-mcp install carries no Kit extension: {_PACKAGE} has no _extension folder.")


def extension_version(folder: Path) -> str | None:
    """The version in a folder's extension.toml, or None when there is none to read."""
    try:
        with (folder / "config" / "extension.toml").open("rb") as f:
            return str(tomllib.load(f)["package"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def carried_version() -> str:
    """The version of the extension this server carries, which `install_command()` installs: the same string Kit
    reports. A checkout's package metadata keeps the version of its last sync; its extension.toml doesn't."""
    try:
        carried = extension_version(source())
    except InstallError:
        carried = None
    return carried or version("omniverse-mcp")


def install_command() -> str:
    """The command that installs the extension of this server's release, for messages. A checkout's version need not
    be on PyPI, nor its extension the release's, so a checkout gets its own."""
    try:
        checkout = source() != _carried()
    except InstallError:
        checkout = False
    if checkout:
        return f"uv run --project {_quoted(_PACKAGE.parents[1])} omniverse-mcp extension install"
    return f"uvx omniverse-mcp=={version('omniverse-mcp')} extension install"


def install_advice() -> str:
    """How to give Kit this server's extension, for each text that finds another release's there: the command and a
    restart, or, for an extension from Kit's community registry, which the command's folder never reaches, the version
    to install in Kit's Extensions window (#101)."""
    return (
        f"{install_command()}, then restart Kit; with the extension from Kit's community registry, install "
        f"{carried_version()} in Kit's Extensions window instead"
    )


def _quoted(path: Path) -> str:
    """A path as a shell takes it: a profile folder may hold a space."""
    return f'"{path}"' if sys.platform == "win32" else shlex.quote(str(path))


def install(root: Path | None = None) -> tuple[Path, str | None]:
    """Install the extension into root (exts_dir() by default) and return its folder and the version it replaced.

    The copy is made outside root, where Kit never sees half of it, and swapped in by renaming, so no module the new
    release dropped is left behind to be loaded. When the swap fails the old one is put back.
    """
    src = source()
    root = root or exts_dir()
    target = root / EXTENSION_ID
    previous = extension_version(target)
    try:
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{EXTENSION_ID}.new-", dir=root.parent))
    except OSError as e:
        raise InstallError(f"Could not write to {root}: {e}") from e
    old = staging.with_name(staging.name.replace(".new-", ".old-"))
    keep_old = False
    try:
        shutil.copytree(src, staging, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if target.exists():
            target.rename(old)
        staging.rename(target)
    except OSError as e:
        if old.exists() and not target.exists():
            try:
                old.rename(target)
            except OSError:
                keep_old = True
                raise InstallError(
                    f"Could not install the extension in {target}: {e}; nor put the one before back. It is in "
                    f"{old}: rename that folder to {target} once nothing holds it."
                ) from e
        raise InstallError(
            f"Could not install the extension in {target}: {e}. A Kit app that has it loaded may hold the folder: "
            "quit it, and run this again."
        ) from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if not keep_old:
            shutil.rmtree(old, ignore_errors=True)
    return target, previous


def _utf8_streams() -> None:
    # A path may hold characters a Windows code page lacks, and piped output (an agent's shell) is in that code page.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(action: str) -> int:
    """`omniverse-mcp extension <action>`: the exit code."""
    _utf8_streams()
    root = exts_dir()
    if action == "path":
        print(root)
        if extension_version(root / EXTENSION_ID) is None:
            print(f"{EXTENSION_ID} is not installed there yet: {install_command()}", file=sys.stderr)
            return 1
        return 0
    try:
        target, previous = install(root)
    except InstallError as e:
        print(e, file=sys.stderr)
        return 1
    replaced = f", in place of {previous}" if previous else ""
    print(f"Installed {EXTENSION_ID} {extension_version(target)} in {target}{replaced}.")
    print("Kit finds it once its extension search paths hold this folder:")
    print(f"  {root}")
    print(
        f"In Kit: Window > Extensions, the menu > Settings, add the folder; then turn on {EXTENSION_ID} with Autoload. "
        f"Or start Kit with --ext-folder {_quoted(root)} --enable {EXTENSION_ID}. Restart any Kit app that runs the "
        "extension, so it loads this one."
    )
    return 0
