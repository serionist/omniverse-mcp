"""The release's checks (tools/release.py): the tag, the versions and the changelog agree; the wheel carries its
extension and a README PyPI can show and the MCP registry trusts; the notes are the changelog's section and the
install lines."""

import shutil
import zipfile
from pathlib import Path

import gate
import pytest
import release

from .test_gate import new_repo

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
    for rel in (
        "pyproject.toml",
        "extension/ovmcp.bridge/config/extension.toml",
        gate.SERVER_JSON,
        gate.EXTENSION_README,
    ):
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
        gate.SERVER_JSON,
        f"{gate.SERVER_JSON} (package 1)",
        f"{gate.EXTENSION_README} (pin 1)",
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
NAME = gate.json_object(gate.ROOT / gate.SERVER_JSON)["name"]
README = f"{IMAGE} [Tools](https://github.com/x/y/blob/main/b.md) [#](#c)\n<!-- mcp-name: {NAME} -->"


def test_a_wheel_with_its_extension_and_absolute_paths_passes(tmp_path):
    assert release.wheel_problems(_wheel(tmp_path, "1.2.0", "1.2.0", README)) == []
    mail = README + ' [mail](mailto:a@example.org) <a href="mailto:a@example.org">'
    assert release.wheel_problems(_wheel(tmp_path, "1.2.0", "1.2.0", mail)) == []


@pytest.mark.parametrize(
    ("extension", "description", "expected"),
    [
        (None, README, "carries no Kit extension"),
        ("1.1.0", README, "is 1.2.0 and carries the extension 1.1.0"),
        ("1.2.0", '<img src="docs/images/a.png">', 'src="docs/images/a.png"'),
        ("1.2.0", '<a href="LICENSE">', 'href="LICENSE"'),
        ("1.2.0", "[Tools](docs/TOOLS.md)", "](docs/TOOLS.md)"),
        ("1.2.0", '[Tools](docs/TOOLS.md "Every tool")', "](docs/TOOLS.md "),
        ("1.2.0", "See [the tools].\n\n[the tools]: docs/TOOLS.md", "[the tools]: docs/TOOLS.md"),
        ("1.2.0", "![A](https://github.com/x/y/blob/main/a.png)", "![A](https://github.com/x/y/blob/main/a.png"),
        ("1.2.0", '<img src="https://github.com/x/y/blob/main/a.png">', 'src="https://github.com/x/y/blob/main/a.png"'),
        ("1.2.0", "[Help](#user-content-help)", "](#user-content-help)"),
        ("1.2.0", '<a href="#user-content-help">', 'href="#user-content-help"'),
        ("1.2.0", IMAGE, f"lacks `mcp-name: {NAME}`"),
        ("1.2.0", f"<!-- mcp-name: {NAME}-next -->", f"lacks `mcp-name: {NAME}`"),
    ],
    ids=[
        "no extension",
        "another extension",
        "relative image",
        "relative href",
        "relative link",
        "link with a title",
        "reference",
        "image on a page",
        "img on a page",
        "prefixed link",
        "prefixed href",
        "no registry name",
        "another registry name",
    ],
)
def test_a_wheel_that_is_wrong_says_how(extension, description, expected, tmp_path):
    problems = release.wheel_problems(_wheel(tmp_path, "1.2.0", extension, description))
    assert any(expected in p for p in problems), problems


def test_the_notes_put_each_paragraph_on_one_line():
    items = ["- **A thing** that wraps", "  onto a second line.", "- Another.", "", "A paragraph", "that wraps.", ""]
    wrapped = "\n".join([*items, "### Added", "", "1. One", "   more."])
    unwrapped = ["- **A thing** that wraps onto a second line.", "- Another.", "", "A paragraph that wraps.", ""]
    assert release.unwrap(wrapped) == "\n".join([*unwrapped, "### Added", "", "1. One more."])


def test_a_release_pr_is_checked_as_its_tag_will_be(tmp_path):
    version = gate.plugin_versions(gate.ROOT, gate.json_object(gate.ROOT / gate.PLUGIN_MANIFEST))["pyproject.toml"]
    assert version
    root = _repo(tmp_path, version)
    assert release.pull_request_problems(root) == []
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version}\n\n- Undated.\n", encoding="utf-8")
    (problem,) = release.pull_request_problems(root) or []
    assert "(YYYY-MM-DD)" in problem
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- Work.\n", encoding="utf-8")
    assert release.pull_request_problems(root) is None


def test_the_notes_are_the_section(tmp_path, monkeypatch, capsys):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    assert release.main(["notes", "1.2.0"]) == 0
    assert capsys.readouterr().out == f"### Added\n\n- A thing.\n\n{release.INSTALL.format(version='1.2.0')}"
    assert release.main(["notes", "1.3.0"]) == 1


def test_the_notes_pair_the_registry_s_bridge_with_its_server():
    # A bridge from Kit's community registry comes without its server: the notes name the release's (#101).
    (registry,) = [
        line for line in release.INSTALL.format(version="1.2.0").splitlines() if "community registry" in line
    ]
    assert "*Omniverse MCP Bridge* 1.2.0" in registry
    assert "`uvx omniverse-mcp==1.2.0`" in registry
    assert "docs/SETUP.md#from-kits-community-registry" in registry
    assert release.main(["release"]) == 2


# The Kit extension's zips (#101): Kit's community registry reads two of them by name, and Kit installs one.

GOOD_TOML = """[package]
version = "1.2.0"
repository = "https://github.com/serionist/omniverse-mcp"
readme = "docs/README.md"
icon = "data/icon.png"
preview_image = "data/preview.png"

[package.target]
kit = ["107.0"]
"""


def _extension_zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return path


def _good_files(toml: str = GOOD_TOML) -> dict[str, str]:
    return {
        "ovmcp.bridge/config/extension.toml": toml,
        "ovmcp.bridge/docs/README.md": "# Omniverse MCP Bridge\n",
        "ovmcp.bridge/data/icon.png": "png",
        "ovmcp.bridge/data/preview.png": "png",
        "ovmcp.bridge/ovmcp/__init__.py": "",
    }


def test_the_release_names_its_zips_for_people_and_for_the_registry():
    assert release.archive_names("1.2.0") == [
        "ovmcp.bridge-1.2.0.zip",
        "serionist-omniverse-mcp-linux-x86_64-v1.2.0.zip",
        "serionist-omniverse-mcp-windows-x86_64-v1.2.0.zip",
    ]


def test_an_extension_zip_kit_can_take_passes(tmp_path):
    assert release.archive_problems(_extension_zip(tmp_path / "x.zip", _good_files()), "1.2.0") == []


def _without(files: dict[str, str], name: str) -> dict[str, str]:
    return {k: v for k, v in files.items() if k != name}


def _renamed(files: dict[str, str], prefix: str) -> dict[str, str]:
    return {k.replace("ovmcp.bridge/", prefix, 1): v for k, v in files.items()}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        # A toml at the root: the registry indexed three such archives under its own temp folder's name.
        (_renamed(_good_files(), ""), "is outside ovmcp.bridge/"),
        ({**_good_files(), "README.md": "x"}, "README.md is outside ovmcp.bridge/"),
        ({**_good_files(), "ovmcp.bridge/ovmcp/__pycache__/x.cpython-312.pyc": ""}, "is compiled Python"),
        (_without(_good_files(), "ovmcp.bridge/config/extension.toml"), "has no ovmcp.bridge/config/extension.toml"),
        (_good_files(GOOD_TOML.replace('"1.2.0"', '"1.1.0"')), "is the extension '1.1.0', the release '1.2.0'"),
        (_good_files(GOOD_TOML.replace("repository = ", "# ")), "the extension's repository is None"),
        (_good_files(GOOD_TOML.replace('kit = ["107.0"]', "")), "has no [package.target] kit"),
        (_good_files(GOOD_TOML.replace('icon = "data/icon.png"\n', "")), "names no icon"),
        (_without(_good_files(), "ovmcp.bridge/data/preview.png"), "preview_image, data/preview.png, isn't in the zip"),
        # The window showed its placeholder for a JPEG preview from a registry (the plan's E4).
        (
            {**_good_files(GOOD_TOML.replace("preview.png", "preview.jpg")), "ovmcp.bridge/data/preview.jpg": "jpg"},
            "preview_image, data/preview.jpg, isn't a PNG",
        ),
    ],
    ids=[
        "toml at the root",
        "a file at the root",
        "compiled",
        "no toml",
        "version",
        "repository",
        "target",
        "icon",
        "preview",
        "a JPEG preview",
    ],
)
def test_an_extension_zip_kit_would_misread_says_how(files, expected, tmp_path):
    problems = release.archive_problems(_extension_zip(tmp_path / "x.zip", files), "1.2.0")
    assert any(expected in p for p in problems), problems


def test_the_folder_holds_the_release_s_zips_and_no_other(tmp_path):
    for name in release.archive_names("1.2.0"):
        _extension_zip(tmp_path / name, _good_files())
    assert release.folder_problems(tmp_path, "1.2.0") == []
    _extension_zip(tmp_path / "ovmcp.bridge-1.1.0.zip", _good_files())
    (tmp_path / "serionist-omniverse-mcp-windows-x86_64-v1.2.0.zip").unlink()
    problems = release.folder_problems(tmp_path, "1.2.0")
    assert any("ovmcp.bridge-1.1.0.zip is in" in p and "would attach it" in p for p in problems), problems
    assert any("serionist-omniverse-mcp-windows-x86_64-v1.2.0.zip is missing" in p for p in problems), problems


def test_the_zips_are_head_s_extension_under_its_folder(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = new_repo(repo)
    for name, text in _good_files().items():
        path = repo / "extension" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (repo / "extension" / "ovmcp.bridge" / "untracked.txt").write_text("", encoding="utf-8")
    run("add", "extension/ovmcp.bridge/config", "extension/ovmcp.bridge/docs", "extension/ovmcp.bridge/data")
    run("add", "extension/ovmcp.bridge/ovmcp")
    run("commit", "-q", "-m", "An extension")

    built = release.build_archives(tmp_path / "out", "1.2.0", root=repo)

    assert [p.name for p in built] == release.archive_names("1.2.0")
    assert len({p.read_bytes() for p in built}) == 1
    with zipfile.ZipFile(built[0]) as z:
        files = {n for n in z.namelist() if not n.endswith("/")}
    assert files == set(_good_files())
    assert release.folder_problems(tmp_path / "out", "1.2.0") == []


def test_the_repo_s_own_extension_is_a_zip_kit_can_take(tmp_path):
    # The working tree's extension, zipped as the release does: the toml names files it has, at the release's version.
    root = gate.ROOT / "extension" / "ovmcp.bridge"
    files = {
        f"ovmcp.bridge/{p.relative_to(root).as_posix()}": p.read_text(encoding="utf-8", errors="replace")
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    version = gate.plugin_versions(gate.ROOT, gate.json_object(gate.ROOT / gate.PLUGIN_MANIFEST))["pyproject.toml"]
    assert version
    assert release.archive_problems(_extension_zip(tmp_path / "x.zip", files), version) == []


def test_archives_refuses_a_tag_that_is_not_a_release(tmp_path, capsys):
    assert release.main(["archives", str(tmp_path), "v1.2"]) == 1
    assert "is not vX.Y.Z" in capsys.readouterr().err
