"""Tests for scripts/check_api_docs.py."""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_api_docs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_api_docs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def check_api_docs():
    return _load_module()


GOOD_DOSSIER = """---
interface: IDrawingDoc
min_methods: 1
status: in-progress
---

# Example dossier

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


def test_valid_dossier_passes(tmp_path, check_api_docs, monkeypatch):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    (tmp_path / "drawing.md").write_text(GOOD_DOSSIER)
    assert check_api_docs.main() == 0


def test_readme_and_template_are_excluded(tmp_path, check_api_docs, monkeypatch):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    (tmp_path / "README.md").write_text("not a dossier, no front matter")
    (tmp_path / "_TEMPLATE.md").write_text("not a dossier, no front matter")
    assert check_api_docs.main() == 0


@pytest.mark.parametrize(
    "marker",
    [
        "**Signature:**",
        "**Source URL(s):**",
        "**status:** verified",
    ],
)
def test_missing_required_section_fails(tmp_path, check_api_docs, monkeypatch, marker, capsys):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    broken = GOOD_DOSSIER.replace(marker, marker.replace("*", "") + " (removed)")
    assert broken != GOOD_DOSSIER, f"marker {marker!r} not found in fixture"
    (tmp_path / "drawing.md").write_text(broken)
    assert check_api_docs.main() == 1
    assert "error:" in capsys.readouterr().err


def test_missing_parameter_table_separator_fails(tmp_path, check_api_docs, monkeypatch, capsys):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    broken = GOOD_DOSSIER.replace("| --- | --- | --- | --- | --- | --- |\n", "")
    assert broken != GOOD_DOSSIER
    (tmp_path / "drawing.md").write_text(broken)
    assert check_api_docs.main() == 1
    assert "Parameter table" in capsys.readouterr().err


def test_missing_front_matter_fails(tmp_path, check_api_docs, monkeypatch):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    (tmp_path / "drawing.md").write_text(GOOD_DOSSIER.split("---\n\n", 1)[1])
    assert check_api_docs.main() == 1


def test_too_few_methods_for_declared_min_methods_fails(tmp_path, check_api_docs, monkeypatch):
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    (tmp_path / "drawing.md").write_text(GOOD_DOSSIER.replace("min_methods: 1", "min_methods: 2"))
    assert check_api_docs.main() == 1


def test_real_template_file_would_pass_if_not_excluded(check_api_docs, tmp_path, monkeypatch):
    """The shipped _TEMPLATE.md content is a valid dossier in its own right —
    prove the record it demonstrates satisfies the validator's own rules."""
    monkeypatch.setattr(check_api_docs, "DOCS_DIR", tmp_path)
    template_text = (REPO_ROOT / "docs" / "api" / "_TEMPLATE.md").read_text(encoding="utf-8")
    (tmp_path / "not_excluded.md").write_text(template_text)
    assert check_api_docs.main() == 0
