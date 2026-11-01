"""Where an agent sends a bug report (#109): the server's instructions, the plugin's report-bug skill and the guide for
clients without the plugin name this repository's issues, and send a security hole to its private advisories instead;
the skill drafts on the bug form's own fields, in the form's order, so a draft filed with gh, or pasted into the form,
reads as one filed from the form."""

import re
import tomllib

from omniverse_mcp.server import INSTRUCTIONS

from .conftest import REPO_ROOT

SKILL = REPO_ROOT / "plugin" / "skills" / "report-bug" / "SKILL.md"
GUIDE = REPO_ROOT / "docs" / "AI_GUIDE.md"
FORM = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
SECURITY = REPO_ROOT / "SECURITY.md"
# The skill's table of the form's fields starts with this header and ends at a blank line.
TABLE_HEAD = "| Field | What goes in it |"


def _urls() -> dict[str, str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["urls"]


def _form_labels(text: str) -> list[str]:
    """The labels of the form's fields, in order: each element with an `id:`, whose `label:` follows."""
    return re.findall(r"^ {4}id: \S+\n {4}attributes:\n {6}label: (.+)$", text, re.MULTILINE)


def _skill_labels(text: str) -> list[str]:
    """The first cell of each row of the skill's field table, its header left out."""
    table = text.split(TABLE_HEAD, 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^ *\| ([^|]+?) \| ", table, re.MULTILINE)


def test_the_instructions_the_skill_and_the_guide_send_reports_to_this_repository():
    url = _urls()["Issues"]
    form = f"{url}/new?template={FORM.name}"
    owner_repo = url.removeprefix("https://github.com/").removesuffix("/issues")
    skill, guide = SKILL.read_text(encoding="utf-8"), GUIDE.read_text(encoding="utf-8")
    assert url in INSTRUCTIONS
    assert form in skill
    assert form in guide
    # Every gh call the skill makes names the repository: without --repo, gh reads the user's own checkout's remote.
    commands = re.findall(r"gh (?:issue|release) \w+ .*", skill)
    assert any(c.startswith("gh issue create ") for c in commands), "the skill files with gh"
    assert any(c.startswith("gh release list ") for c in commands), commands
    assert all(f"--repo {owner_repo}" in c for c in commands), commands


def test_a_security_hole_goes_to_a_private_advisory_never_an_issue():
    # gh issue create --body-file never shows the bug form's own note pointing at private reports.
    advisory = f"{_urls()['Repository']}/security/advisories/new"
    what_counts = f"{_urls()['Repository']}/blob/main/SECURITY.md#what-counts"
    skill, guide = SKILL.read_text(encoding="utf-8"), GUIDE.read_text(encoding="utf-8")
    for text in (INSTRUCTIONS, skill, guide):
        assert advisory in text
    assert what_counts in skill
    assert what_counts in guide
    assert re.search(r"^## What counts$", SECURITY.read_text(encoding="utf-8"), re.MULTILINE)


def test_the_instructions_and_the_skill_ask_for_get_sim_state_s_versions_and_kit_s_log():
    # get_sim_state answers `server_version = ...` and `extension_version = ...` (tests/test_tools.py).
    for text in (INSTRUCTIONS, SKILL.read_text(encoding="utf-8")):
        assert "server_version" in text
        assert "extension_version" in text
        assert 'get_logs(min_level="warn")' in text


def test_the_skill_drafts_on_the_bug_form_s_fields_in_its_order():
    form = _form_labels(FORM.read_text(encoding="utf-8"))
    assert form[:2] == ["Kit app and version", "Operating system"], "the form's fields aren't read: fix _form_labels"
    assert _skill_labels(SKILL.read_text(encoding="utf-8")) == form


def test_a_field_renamed_on_the_form_is_found():
    form = FORM.read_text(encoding="utf-8").replace("label: Operating system\n", "label: OS\n")
    assert _skill_labels(SKILL.read_text(encoding="utf-8")) != _form_labels(form)
