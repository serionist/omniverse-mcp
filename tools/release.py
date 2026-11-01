"""The release's checks, which release.yml and ci.yml run, and its notes (plan S9; docs/releasing.md).

Usage: python tools/release.py check <tag>      the tag is vX.Y.Z, every version the repo names is X.Y.Z, and
                                                CHANGELOG.md has a dated section for it
       python tools/release.py wheel <wheel>    the wheel carries the extension of its own version, and the README
                                                PyPI shows has no relative path left, nor a link PyPI prefixes twice,
                                                and names server.json's server for the MCP registry
       python tools/release.py notes <version>  print CHANGELOG.md's section for the version, each paragraph on one
                                                line, and the install lines: the release's notes
       python tools/release.py pr               when CHANGELOG.md has a section for pyproject.toml's version (a
                                                release PR, and every change after one), check as its tag would
       python tools/release.py archives <dir> [<tag>]
                                                zip the Kit extension from HEAD into <dir> under the names a release
                                                attaches, Kit's community registry's two among them, and check them;
                                                the tag's version, or pyproject.toml's

Standard library only, as the gate: CI runs it before anything is installed.
"""

from __future__ import annotations

import re
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

import gate

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
EXTENSION_TOML = "omniverse_mcp/_extension/ovmcp.bridge/config/extension.toml"
EXTENSION = "ovmcp.bridge"
# Kit's community registry's crawler builds its archives' names from the repository and the tag (#101): renaming
# either stops the listing, and a listed version installs from its release's file (AGENTS.md, One-way doors).
REPOSITORY = "serionist/omniverse-mcp"
# What PyPI can't show, with no repo around the README (#36): an image or a link that isn't absolute (or an anchor, or
# mail), whatever its form, and an image pointing at a github.com page instead of the file. pyproject.toml's
# substitutions rewrite the common forms; this finds any they miss, such as a link with a title or a reference.
_RELATIVE = re.compile(
    r'src="(?!https?://)[^"]+"'
    r'|href="(?!https?://|#|mailto:)[^"]+"'
    r"|\]\((?!https?://|#|mailto:)[^)\s]+[)\s]"
    r"|^ {0,3}\[[^\]]+\]:[ \t]*(?!https?://|#|mailto:)\S+"
    r'|src="https://github\.com/[^"]*/blob/[^"]*"'
    r"|!\[[^\]]*\]\(https://github\.com/[^)\s]*/blob/[^)\s]*",
    re.MULTILINE,
)
# PyPI prefixes an in-page link with `user-content-` itself, so one that already has it points nowhere there (#62).
_PREFIXED = re.compile(r'\]\(#user-content-[^)\s]*\)|href="#user-content-[^"]*"')
# Under each release's notes on GitHub (plan S10), as the README's Install and Updating say it. GitHub breaks a release
# body where its lines break, so each item is one line.
INSTALL = (
    "### Install\n\n"
    "- **Claude Code:** `/plugin marketplace add serionist/omniverse-mcp`, then"
    " `/plugin install omniverse-mcp@omniverse-mcp` and `/omniverse-mcp:setup`. To update:"
    " `claude plugin marketplace update omniverse-mcp`, then `claude plugin update omniverse-mcp@omniverse-mcp`,"
    " restart Claude Code and run `/omniverse-mcp:setup`.\n"
    "- **Other MCP clients:** `uvx omniverse-mcp=={version} extension install`, then the server,"
    " `uvx omniverse-mcp=={version}`, in the client's config"
    " ([Install](https://github.com/serionist/omniverse-mcp#other-mcp-clients)).\n"
    "- **Kit's community registry:** from the day after, Kit's Extensions window lists *Omniverse MCP Bridge*"
    " {version}; run the server of the same release, `uvx omniverse-mcp=={version}`"
    " ([From Kit's community registry](https://github.com/serionist/omniverse-mcp/blob/main/docs/SETUP.md"
    "#from-kits-community-registry)).\n"
)


def section(changelog: str, version: str) -> tuple[str | None, str]:
    """CHANGELOG.md's `## <version> ...` heading and the text under it, up to the next `## ` heading."""
    heading, body, inside = None, [], False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if inside:
                break
            if line[3:].split(" ", 1)[0] == version:
                heading, inside = line, True
                continue
        if inside:
            body.append(line)
    return heading, "\n".join(body).strip()


def unwrap(markdown: str) -> str:
    """The text with each wrapped paragraph or list item on one line: GitHub renders a release body's every newline as a
    line break, so CHANGELOG.md's 120-column lines would break mid-sentence."""
    lines: list[str] = []
    for line in markdown.splitlines():
        text = line.strip()
        starts = not text or text.startswith(("#", "- ", "* ", "|", ">")) or re.match(r"\d+\. ", text)
        if lines and lines[-1].strip() and not starts:
            lines[-1] = f"{lines[-1]} {text}"
        else:
            lines.append(line.rstrip())
    return "\n".join(lines)


def changelog_problems(changelog: str, version: str) -> list[str]:
    """A release needs its CHANGELOG.md section, dated `## X.Y.Z (YYYY-MM-DD)`, with something under it: its notes."""
    heading, body = section(changelog, version)
    if heading is None:
        return [f"CHANGELOG.md has no `## {version} (YYYY-MM-DD)` section: date Unreleased as it (docs/releasing.md)"]
    problems = []
    if not re.fullmatch(rf"## {re.escape(version)} \(\d{{4}}-\d{{2}}-\d{{2}}\)", heading):
        problems.append(f"CHANGELOG.md's heading is {heading!r}; a release's reads `## {version} (YYYY-MM-DD)`")
    if not body:
        problems.append(f"CHANGELOG.md's section for {version} is empty: it is the release's notes")
    return problems


def tag_problems(tag: str, root: Path = ROOT) -> list[str]:
    """The tag names a release, every version the repo names equals it, and its changelog section is there."""
    match = TAG.match(tag)
    if not match:
        return [f"the tag {tag!r} is not vX.Y.Z: a release has no prerelease suffix (plan: none on an index)"]
    version = match.group(1)
    plugin = gate.json_object(root / gate.PLUGIN_MANIFEST)
    versions = gate.plugin_versions(root, plugin)
    problems = [
        f"{where} has version {got!r}, the tag {version!r}: the release PR bumps them all (docs/releasing.md)"
        for where, got in versions.items()
        if got != version
    ]
    return problems + changelog_problems((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)


def pull_request_problems(root: Path = ROOT) -> list[str] | None:
    """The problems a tag for pyproject.toml's version would meet, once CHANGELOG.md has its section: on a release PR,
    and on every change after it, which keeps that release's versions until the next one. None before the first."""
    with (root / "pyproject.toml").open("rb") as f:
        version = str(tomllib.load(f)["project"]["version"])
    heading, _ = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    return None if heading is None else tag_problems(f"v{version}", root)


def wheel_problems(path: Path, root: Path = ROOT) -> list[str]:
    """The wheel carries the Kit extension of its own version, and PyPI's copy of the README resolves and names the
    server for the MCP registry."""
    name = gate.json_object(root / gate.SERVER_JSON).get("name")
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        metadata = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if metadata is None:
            return [f"{path.name} has no METADATA"]
        headers, _, description = wheel.read(metadata).decode("utf-8").partition("\n\n")
        version = next((line.split(": ", 1)[1] for line in headers.splitlines() if line.startswith("Version: ")), None)
        if EXTENSION_TOML not in names:
            return [f"{path.name} carries no Kit extension: {EXTENSION_TOML} is missing (pyproject's force-include)"]
        extension = tomllib.loads(wheel.read(EXTENSION_TOML).decode("utf-8")).get("package", {}).get("version")
    problems = []
    if extension != version:
        problems.append(f"{path.name} is {version} and carries the extension {extension}")
    relative = [m.group(0) for m in _RELATIVE.finditer(description)]
    if relative:
        problems.append(f"{path.name}'s README has relative paths PyPI can't resolve (#36): {', '.join(relative[:5])}")
    prefixed = [m.group(0) for m in _PREFIXED.finditer(description)]
    if prefixed:
        problems.append(f"{path.name}'s README has links PyPI prefixes twice (#62): {', '.join(prefixed[:5])}")
    # The registry trusts a PyPI package whose README holds `mcp-name: <the name>`, ended by a space, a tag or a
    # comment's end, and refuses the entry otherwise; PyPI's copy can't change once uploaded.
    if not isinstance(name, str) or not re.search(rf"mcp-name: {re.escape(name)}(?=\s|<|-->|$)", description):
        problems.append(f"{path.name}'s README lacks `mcp-name: {name}`, by which the MCP registry trusts it")
    return problems


def archive_names(version: str) -> list[str]:
    """The zips of the Kit extension a release attaches: `ovmcp.bridge-X.Y.Z.zip`, for people, and the two names Kit's
    community registry's crawler reads, one per platform; a Python-only extension's are the same bytes (#101)."""
    prefix = REPOSITORY.replace("/", "-")
    return [f"{EXTENSION}-{version}.zip", *(f"{prefix}-{os}-x86_64-v{version}.zip" for os in ("linux", "windows"))]


def build_archives(out: Path, version: str, root: Path = ROOT) -> list[Path]:
    """Zip HEAD's extension, as `git archive` gives its tracked files, under each of archive_names(version)."""
    out.mkdir(parents=True, exist_ok=True)
    first, *copies = (out / name for name in archive_names(version))
    done = gate.git(
        "archive", "--format=zip", f"--prefix={EXTENSION}/", "-o", str(first), f"HEAD:extension/{EXTENSION}", cwd=root
    )
    if done.returncode != 0:
        raise RuntimeError(f"git archive failed: {done.stderr.strip()}")
    for copy in copies:
        shutil.copyfile(first, copy)
    return [first, *copies]


def archive_problems(path: Path, version: str) -> list[str]:
    """What would keep Kit, or Kit's community registry, from taking the zip as this release's extension (#101)."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        problems = [
            f"{path.name}: {name} is outside {EXTENSION}/, where Kit names the extension by its folder; at the root, "
            "the community registry names it after its own temp folder"
            for name in names
            if not name.startswith(f"{EXTENSION}/")
        ][:3]
        problems += [
            f"{path.name}: {name} is compiled Python, which Kit makes itself"
            for name in names
            if name.endswith(".pyc") or "/__pycache__/" in name
        ][:3]
        toml = f"{EXTENSION}/config/extension.toml"
        if toml not in names:
            return [*problems, f"{path.name} has no {toml}"]
        package = tomllib.loads(archive.read(toml).decode("utf-8")).get("package", {})
    if package.get("version") != version:
        problems.append(f"{path.name} is the extension {package.get('version')!r}, the release {version!r}")
    if package.get("repository") != f"https://github.com/{REPOSITORY}":
        problems.append(
            f"{path.name}: the extension's repository is {package.get('repository')!r}, not "
            f"'https://github.com/{REPOSITORY}', which Kit's community registry requires"
        )
    if not (package.get("target") or {}).get("kit"):
        problems.append(f"{path.name}: the extension has no [package.target] kit, the Kit floor Kit's window reads")
    for key in ("readme", "icon", "preview_image"):
        named = package.get(key)
        if not named:
            problems.append(f"{path.name}: the extension names no {key}, which Kit's Extensions window shows")
        elif f"{EXTENSION}/{named}" not in names:
            problems.append(f"{path.name}: the extension's {key}, {named}, isn't in the zip")
        elif key != "readme" and not str(named).lower().endswith(".png"):
            # Kit's Extensions window shows a registry's image only as PNG (REMOTE_IMAGE_SUPPORTED_EXTS, Kit 107 and
            # 110): any other type gets its placeholder.
            problems.append(f"{path.name}: the extension's {key}, {named}, isn't a PNG, the only image Kit shows")
    return problems


def folder_problems(out: Path, version: str) -> list[str]:
    """The release attaches every zip in the folder: only its own, each one Kit can take."""
    want = archive_names(version)
    problems = [
        f"{name} is in {out}, and the release would attach it"
        for name in sorted(p.name for p in out.glob("*.zip"))
        if name not in want
    ]
    for name in want:
        problems += archive_problems(out / name, version) if (out / name).is_file() else [f"{out / name} is missing"]
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["pr"]:
        problems = pull_request_problems()
        if problems is None:
            print("release.py pr: no release yet (CHANGELOG.md has no section for pyproject.toml's version)")
            return 0
        for problem in problems:
            print(f"release.py pr: {problem}", file=sys.stderr)
        return 1 if problems else 0
    if args[:1] == ["archives"] and len(args) in (2, 3):
        return _archives(Path(args[1]), args[2] if len(args) == 3 else None)
    if len(args) != 2 or args[0] not in ("check", "wheel", "notes"):
        print(__doc__, file=sys.stderr)
        return 2
    command, value = args
    if command == "notes":
        heading, body = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), value)
        if heading is None or not body:
            print(f"CHANGELOG.md has no section for {value}", file=sys.stderr)
            return 1
        print(f"{unwrap(body)}\n\n{INSTALL.format(version=value)}", end="")
        return 0
    problems = tag_problems(value) if command == "check" else wheel_problems(Path(value))
    for problem in problems:
        print(f"release.py {command}: {problem}", file=sys.stderr)
    if not problems:
        print(f"release.py {command} {value}: ok")
    return 1 if problems else 0


def _archives(out: Path, tag: str | None) -> int:
    """`archives <dir> [<tag>]`: build and check the release's zips of the Kit extension."""
    if tag is None:
        with (ROOT / "pyproject.toml").open("rb") as f:
            version = str(tomllib.load(f)["project"]["version"])
    elif match := TAG.match(tag):
        version = match.group(1)
    else:
        print(f"release.py archives: the tag {tag!r} is not vX.Y.Z", file=sys.stderr)
        return 1
    try:
        build_archives(out, version)
    except RuntimeError as e:
        print(f"release.py archives: {e}", file=sys.stderr)
        return 1
    problems = folder_problems(out, version)
    for problem in problems:
        print(f"release.py archives: {problem}", file=sys.stderr)
    if not problems:
        print(f"release.py archives {version}: ok, {', '.join(archive_names(version))}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
