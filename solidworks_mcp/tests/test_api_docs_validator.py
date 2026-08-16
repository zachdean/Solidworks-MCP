"""Tests for scripts/check_api_docs.py."""
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_api_docs.py"


@pytest.fixture
def check_api_docs():
    """The validator, loaded by path — it lives in scripts/, not an importable package."""
    spec = importlib.util.spec_from_file_location("check_api_docs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A minimal record in the shape docs/api/_TEMPLATE.md defines canonically. Kept
# inline (rather than read from the template) so the mutation tests below can
# point at exactly one field each. It is deliberately smaller than the
# template's worked 16-parameter record — only the field *set* is shared, and
# test_template_and_fixture_share_the_same_fields is what holds those together.
FRONT_MATTER = """---
interface: IDrawingDoc
min_methods: 1
status: in-progress
---

"""

GOOD_DOSSIER = FRONT_MATTER + """# Example dossier

### IDrawingDoc::NewSheet4

- **Interface:** IDrawingDoc
- **Method:** NewSheet4
- **Minimum SW version:** SOLIDWORKS 2015 FCS

**Signature:**

```vb
Function NewSheet4(ByVal Name As String) As Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Sheet name | |

**Returns:** Boolean.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~NewSheet4.html

**status:** verified

**Gotchas:**
- None.
"""


def test_valid_dossier_passes(tmp_path, check_api_docs):
    (tmp_path / "drawing.md").write_text(GOOD_DOSSIER)
    assert check_api_docs.main(tmp_path) == 0


def test_readme_and_underscore_files_are_excluded(tmp_path, check_api_docs):
    """README.md and `_`-prefixed scaffolding are skipped, not validated.

    The real dossier alongside them is what makes this meaningful: it keeps the
    run from passing merely because nothing at all got validated.
    """
    (tmp_path / "drawing.md").write_text(GOOD_DOSSIER)
    for name in ("README.md", "_TEMPLATE.md", "_scratch.md"):
        (tmp_path / name).write_text("not a dossier, no front matter")
    assert check_api_docs.main(tmp_path) == 0


def test_directory_with_no_dossiers_fails(tmp_path, check_api_docs, capsys):
    """Validating nothing is a failure, not a pass — otherwise a stray `_`
    rename silently drops files out of the gate with pytest still green."""
    (tmp_path / "README.md").write_text("not a dossier")
    (tmp_path / "_01-documents.md").write_text("garbage, no front matter")
    assert check_api_docs.main(tmp_path) == 1
    assert "no dossier files" in capsys.readouterr().err


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("**Signature:**", "Signature: (removed)", "Signature"),
        ("| --- | --- | --- | --- | --- | --- |\n", "", "Parameter table"),
        ("**Returns:**", "Returns: (removed)", "Returns:"),
        ("**Prior selection required:**", "Prior selection required: (removed)", "Prior selection required"),
        ("**Source URL(s):**", "Source URL(s): (removed)", "Source URL"),
        ("**status:** verified", "status: verified (removed)", "status:"),
        ("min_methods: 1", "min_methods: 2", "min_methods=2"),
        ("min_methods: 1", "min_methods: many", "not an integer"),
        # isdigit() is true for "²" but int("²") raises — the message must
        # still be the clean one, not a traceback.
        ("min_methods: 1", "min_methods: ²", "not an integer"),
        (FRONT_MATTER, "", "front matter"),
    ],
    ids=[
        "signature",
        "parameter-table",
        "returns",
        "prior-selection",
        "source-url",
        "status",
        "too-few-methods",
        "min-methods-not-an-int",
        "min-methods-superscript-digit",
        "no-front-matter",
    ],
)
def test_invalid_dossier_fails(tmp_path, check_api_docs, capsys, old, new, expected):
    broken = GOOD_DOSSIER.replace(old, new)
    assert broken != GOOD_DOSSIER, f"fixture does not contain {old!r}"
    (tmp_path / "drawing.md").write_text(broken)
    assert check_api_docs.main(tmp_path) == 1
    assert expected in capsys.readouterr().err


PARAMETER_TABLE = """| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Sheet name | |
"""

OTHER_TABLE = """| Version | Behavior |
| --- | --- |
| 2025 | Fine |
"""


def test_table_outside_parameters_section_does_not_satisfy_the_check(tmp_path, check_api_docs, capsys):
    """A table in Gotchas is not a parameter table, even though both are tables."""
    broken = GOOD_DOSSIER.replace(PARAMETER_TABLE, "").replace("- None.\n", OTHER_TABLE)
    assert PARAMETER_TABLE not in broken and OTHER_TABLE in broken
    (tmp_path / "drawing.md").write_text(broken)
    assert check_api_docs.main(tmp_path) == 1
    assert "Parameter table" in capsys.readouterr().err


def test_trailing_h2_section_is_not_part_of_the_last_record(tmp_path, check_api_docs, capsys):
    """The last record ends at the following `## Enums`, so that section's
    tables can't stand in for the record's own missing parameter table."""
    broken = GOOD_DOSSIER.replace(PARAMETER_TABLE, "") + "\n## Enums\n\n" + OTHER_TABLE
    (tmp_path / "drawing.md").write_text(broken)
    assert check_api_docs.main(tmp_path) == 1
    assert "Parameter table" in capsys.readouterr().err


def test_real_dossiers_are_valid(check_api_docs):
    """The gate that matters: the shipped docs/api/ dossiers pass their own validator.

    Without this, `pytest` stays green on a corrupted dossier and only
    scripts/check.sh catches it.
    """
    assert check_api_docs.main() == 0


def test_real_template_file_would_pass_if_not_excluded(check_api_docs, tmp_path):
    """The shipped _TEMPLATE.md content is a valid dossier in its own right —
    prove the record it demonstrates satisfies the validator's own rules."""
    template_text = (check_api_docs.DOCS_DIR / "_TEMPLATE.md").read_text(encoding="utf-8")
    (tmp_path / "not_excluded.md").write_text(template_text)
    assert check_api_docs.main(tmp_path) == 0


def test_template_and_fixture_share_the_same_fields(check_api_docs):
    """GOOD_DOSSIER must keep testing the shape _TEMPLATE.md actually defines.

    Passing the validator isn't enough on its own: the validator only checks a
    subset of the format, so both could pass while the fixture drifted into a
    record shape no real dossier uses. Compare the bold field labels directly.
    """
    def field_labels(text: str) -> set[str]:
        _, body = check_api_docs.split_records(text)[0]
        return set(re.findall(r"^\*\*(.+?):?\*\*", body, re.M))

    template_text = (check_api_docs.DOCS_DIR / "_TEMPLATE.md").read_text(encoding="utf-8")
    assert field_labels(GOOD_DOSSIER) == field_labels(template_text)
