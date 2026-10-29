"""The release's checks, which release.yml and ci.yml run, and its notes (plan S9; docs/releasing.md).

Usage: python tools/release.py check <tag>      the tag is vX.Y.Z, every version the repo names is X.Y.Z, and
                                                CHANGELOG.md has a dated section for it
       python tools/release.py wheel <wheel>    the wheel carries the extension of its own version, and the README
                                                PyPI shows has no relative path left, nor a link PyPI prefixes twice
       python tools/release.py notes <version>  print CHANGELOG.md's section for the version, each paragraph on one
                                                line: the release's notes
       python tools/release.py pr               when CHANGELOG.md has a section for pyproject.toml's version (a
                                                release PR, and every change after one), check as its tag would

Standard library only, as the gate: CI runs it before anything is installed.
"""

from __future__ import annotations

import re
import sys
import tomllib
import zipfile
from pathlib import Path

import gate

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
EXTENSION_TOML = "omniverse_mcp/_extension/ovmcp.bridge/config/extension.toml"
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


def wheel_problems(path: Path) -> list[str]:
    """The wheel carries the Kit extension of its own version, and PyPI's copy of the README resolves."""
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
    if len(args) != 2 or args[0] not in ("check", "wheel", "notes"):
        print(__doc__, file=sys.stderr)
        return 2
    command, value = args
    if command == "notes":
        heading, body = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), value)
        if heading is None or not body:
            print(f"CHANGELOG.md has no section for {value}", file=sys.stderr)
            return 1
        print(unwrap(body))
        return 0
    problems = tag_problems(value) if command == "check" else wheel_problems(Path(value))
    for problem in problems:
        print(f"release.py {command}: {problem}", file=sys.stderr)
    if not problems:
        print(f"release.py {command} {value}: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
