"""The release's checks (tools/release.py): the tag, the versions and the changelog agree; the wheel carries its
extension and a README PyPI can show; the notes are the changelog's section."""

import shutil
import zipfile
from pathlib import Path

import gate
import pytest
import release

CHANGELOG = """# Changelog

## Unreleased

## 1.2.0 (2027-01-05)

### Added

- A thing.

## 1.1.0 (2026-12-01)

- Before.
"""


def test_a_section_runs_to_the_next_heading():
    assert release.section(CHANGELOG, "1.2.0") == ("## 1.2.0 (2027-01-05)", "### Added\n\n- A thing.")
    assert release.section(CHANGELOG, "1.1.0") == ("## 1.1.0 (2026-12-01)", "- Before.")
    assert release.section(CHANGELOG, "1.3.0") == (None, "")


def test_a_dated_section_with_notes_passes():
    assert release.changelog_problems(CHANGELOG, "1.2.0") == []


@pytest.mark.parametrize(
    ("changelog", "expected"),
    [
        (CHANGELOG, "no `## 1.3.0 (YYYY-MM-DD)` section"),
        (CHANGELOG.replace("## 1.2.0 (2027-01-05)", "## 1.2.0"), "a release's reads `## 1.2.0 (YYYY-MM-DD)`"),
        (CHANGELOG.replace("### Added\n\n- A thing.\n", ""), "is empty"),
    ],
    ids=["missing", "undated", "empty"],
)
def test_a_release_needs_its_dated_section(changelog, expected):
    version = "1.3.0" if expected.startswith("no ") else "1.2.0"
    problems = release.changelog_problems(changelog, version)
    assert any(expected in p for p in problems), problems


def _repo(tmp_path: Path, version: str) -> Path:
    """The files tag_problems reads, copied from the repo, with a changelog section for version."""
    for rel in ("pyproject.toml", "extension/ovmcp.bridge/config/extension.toml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gate.ROOT / rel, tmp_path / rel)
    shutil.copytree(gate.ROOT / gate.PLUGIN_DIR, tmp_path / gate.PLUGIN_DIR)
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version} (2027-01-05)\n\n- Notes.\n", encoding="utf-8")
    return tmp_path


def test_the_tag_matches_every_version_the_repo_names(tmp_path):
    version = gate.plugin_versions(gate.ROOT, gate.json_object(gate.ROOT / gate.PLUGIN_MANIFEST))["pyproject.toml"]
    assert version
    assert release.tag_problems(f"v{version}", _repo(tmp_path, version)) == []


def test_a_tag_out_of_step_names_each_place(tmp_path):
    problems = release.tag_problems("v9.9.9", _repo(tmp_path, "9.9.9"))
    for where in (
        "pyproject.toml",
        "extension/ovmcp.bridge/config/extension.toml",
        gate.PLUGIN_MANIFEST,
        gate.PLUGIN_MCP,
    ):
        assert any(p.startswith(where) for p in problems), (where, problems)


@pytest.mark.parametrize("tag", ["0.2.0", "v0.2", "v0.2.0-rc.1", "release-0.2.0"])
def test_a_tag_that_is_not_a_release_is_refused(tag, tmp_path):
    (problem,) = release.tag_problems(tag, tmp_path)
    assert "is not vX.Y.Z" in problem


def _wheel(tmp_path: Path, version: str, extension: str | None, description: str) -> Path:
    path = tmp_path / f"omniverse_mcp-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(
            f"omniverse_mcp-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: omniverse-mcp\nVersion: {version}\n\n{description}",
        )
        if extension is not None:
            wheel.writestr(release.EXTENSION_TOML, f'[package]\nversion = "{extension}"\n')
    return path


IMAGE = '<img src="https://raw.githubusercontent.com/x/y/main/a.png">'
README = f"{IMAGE} [Tools](https://github.com/x/y/blob/main/b.md) [#](#c)"


def test_a_wheel_with_its_extension_and_absolute_paths_passes(tmp_path):
    assert release.wheel_problems(_wheel(tmp_path, "1.2.0", "1.2.0", README)) == []


@pytest.mark.parametrize(
    ("extension", "description", "expected"),
    [
        (None, README, "carries no Kit extension"),
        ("1.1.0", README, "is 1.2.0 and carries the extension 1.1.0"),
        ("1.2.0", '<img src="docs/images/a.png">', 'src="docs/images/a.png"'),
        ("1.2.0", '<a href="LICENSE">', 'href="LICENSE"'),
        ("1.2.0", "[Tools](docs/TOOLS.md)", "](docs/TOOLS.md)"),
    ],
    ids=["no extension", "another extension", "relative image", "relative href", "relative link"],
)
def test_a_wheel_that_is_wrong_says_how(extension, description, expected, tmp_path):
    problems = release.wheel_problems(_wheel(tmp_path, "1.2.0", extension, description))
    assert any(expected in p for p in problems), problems


def test_the_notes_are_the_section(tmp_path, monkeypatch, capsys):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    assert release.main(["notes", "1.2.0"]) == 0
    assert capsys.readouterr().out == "### Added\n\n- A thing.\n"
    assert release.main(["notes", "1.3.0"]) == 1
    assert release.main(["release"]) == 2
