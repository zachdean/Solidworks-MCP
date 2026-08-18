"""Cross-checks that the drawing-tool documentation set (sw-17y.3) hasn't
drifted from the actual tool registry.

Three things are enforced here, all machine-checked rather than
review-only:

1. The new docs required by sw-17y.3 (`docs/WINDOWS_SETUP.md`,
   `docs/DRAWING_PACKS.md`, `scripts/setup_dev.ps1`) exist.
2. README.md's tool-count claims (per-category and total) match the actual
   registry, computed independently from the `@tool(...)` decorators in
   `solidworks_mcp/tools/*.py` -- not from `docs/TOOLS.md` itself, so this
   can't pass by the two generated-looking numbers merely agreeing with each
   other while both drift from the code. `docs/TOOLS.md`'s own declared
   total is cross-checked too, satisfying "parses both" literally.
3. Every tool name any doc calls out for verification (README.md,
   docs/WINDOWS_SETUP.md, docs/DRAWING_PACKS.md) is a real registered tool.
   Free-form prose in those docs also mentions plenty of *field* names
   (`model_path`, `paper_size`, `on_error`, ...) that are not tool names and
   must not be checked against the registry -- so verification is scoped to
   text inside explicit ``<!-- registered-tools:start -->`` /
   ``<!-- registered-tools:end -->`` marker pairs, which each doc uses
   exactly where it lists real tool names. README's marked region is also
   checked for *completeness*: it must list every registered tool, not just
   real ones, so a newly added tool can't silently go undocumented there.

`DEVELOPMENT_ROADMAP.md` and `docs/api/`/`docs/TOOLS.md` are deliberately out
of scope for the "every mentioned tool name is real" check: the roadmap's
7.3 intentionally preserves superseded, never-implemented names
(`create_drawing`, `add_drawing_view`, `add_drawing_dimension`) as history,
and `docs/TOOLS.md` is generated *from* the registry, so checking it against
itself would be circular.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from solidworks_mcp.tools import registry as tool_registry

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README_PATH = REPO_ROOT / "README.md"
TOOLS_DOC_PATH = REPO_ROOT / "docs" / "TOOLS.md"
WINDOWS_SETUP_PATH = REPO_ROOT / "docs" / "WINDOWS_SETUP.md"
DRAWING_PACKS_PATH = REPO_ROOT / "docs" / "DRAWING_PACKS.md"
SETUP_PS1_PATH = REPO_ROOT / "scripts" / "setup_dev.ps1"
SETUP_SH_PATH = REPO_ROOT / "scripts" / "setup_dev.sh"
TOOLS_PKG_DIR = REPO_ROOT / "solidworks_mcp" / "tools"

# Maps each tool module (source of truth: `@tool(...)` decorator count in
# that file) to the category label used in README.md's summary table. Kept
# here, independent of README's prose, so the test derives its expectation
# from the code rather than from the same document it's checking.
MODULE_TO_CATEGORY = {
    "connection.py": "Connection & Session",
    "documents.py": "Documents",
    "sketches.py": "Sketches",
    "features.py": "Features",
    "utility.py": "Utilities",
    "capabilities.py": "Capabilities",
    "drawing_documents.py": "Drawing Documents & Export",
    "drawing_sheets.py": "Drawing Sheets",
    "drawing_views.py": "Drawing Views",
    "drawing_view_layout.py": "View Layout",
    "drawing_annotations.py": "Annotations & GD&T",
    "drawing_tables.py": "Tables & Balloons",
    "drawing_layers.py": "Layers",
    "drawing_line_format.py": "Line Format & Drafting Standards",
    "drawing_pack.py": "Drawing Packs",
}

_TOOL_DECORATOR_RE = re.compile(r"^@tool\(", re.M)
_MARKER_RE = re.compile(
    r"<!--\s*registered-tools:start\s*-->(.*?)<!--\s*registered-tools:end\s*-->",
    re.S,
)
_BACKTICK_IDENTIFIER_RE = re.compile(r"`([a-z][a-z0-9_]*)`")


@lru_cache(maxsize=None)
def _read(path: Path) -> str:
    """Docs are read by several tests each; they don't change mid-run."""
    return path.read_text(encoding="utf-8")


def _category_counts_from_source() -> dict:
    """Independent ground truth: count `@tool(` decorators per module file
    and roll up by category, without ever importing the registry."""
    counts: dict[str, int] = {}
    for filename, category in MODULE_TO_CATEGORY.items():
        path = TOOLS_PKG_DIR / filename
        counts[category] = counts.get(category, 0) + len(_TOOL_DECORATOR_RE.findall(_read(path)))
    return counts


def _marked_tool_names(path: Path) -> set:
    """Every backticked identifier inside `path`'s ``registered-tools``
    marker pairs. Callers check these against the real registry, so no
    guessing about which are tool names is needed here -- the docs only
    list tool names inside those markers, which is what keeps field names
    (`model_path`, `on_error`, ...) in the surrounding prose out."""
    text = _read(path)
    return {
        name
        for region in _MARKER_RE.findall(text)
        for name in _BACKTICK_IDENTIFIER_RE.findall(region)
    }


def test_new_docs_and_scripts_exist():
    missing = [
        str(p) for p in (WINDOWS_SETUP_PATH, DRAWING_PACKS_PATH, SETUP_PS1_PATH)
        if not p.is_file()
    ]
    assert not missing, f"required file(s) missing: {missing}"


def test_setup_ps1_mirrors_setup_sh_steps():
    ps1 = _read(SETUP_PS1_PATH)
    sh = _read(SETUP_SH_PATH)

    assert "venv" in sh and "venv" in ps1
    assert "requirements.txt" in ps1 and "requirements-dev.txt" in ps1
    assert "requirements.txt" in sh and "requirements-dev.txt" in sh
    assert "pip install --upgrade pip" in ps1
    assert "pip install --upgrade pip" in sh


def test_readme_category_counts_match_registered_tool_modules():
    expected_by_category = _category_counts_from_source()
    expected_total = sum(expected_by_category.values())

    readme = _read(README_PATH)

    # Also cross-check against docs/TOOLS.md's own declared total, per the
    # acceptance criterion's literal "parses both README and docs/TOOLS.md".
    tools_doc_text = _read(TOOLS_DOC_PATH)
    tools_doc_total = int(re.search(r"(\d+) tool\(s\) registered", tools_doc_text).group(1))
    assert expected_total == tools_doc_total, (
        f"sum of @tool(...) decorators across solidworks_mcp/tools/*.py ({expected_total}) "
        f"!= docs/TOOLS.md's declared total ({tools_doc_total})"
    )

    row_re = re.compile(r"^\|\s*([^|]+?)\s*\|[^|]*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|\s*$", re.M)
    found_by_category = {}
    for category, count in row_re.findall(readme):
        category = category.strip()
        if category in expected_by_category or category == "**Total**":
            found_by_category[category] = int(count)

    for category, expected_count in expected_by_category.items():
        assert category in found_by_category, (
            f"README.md's tool-category table is missing a row for {category!r}"
        )
        assert found_by_category[category] == expected_count, (
            f"README.md claims {found_by_category[category]} tools for "
            f"{category!r}, but solidworks_mcp/tools/*.py has {expected_count}"
        )

    assert found_by_category.get("**Total**") == expected_total, (
        f"README.md's total tool count ({found_by_category.get('**Total**')}) "
        f"!= actual registered tool count ({expected_total})"
    )


def test_every_marked_tool_reference_is_a_real_registered_tool():
    registered = set(tool_registry.registered_names())

    for path in (README_PATH, WINDOWS_SETUP_PATH, DRAWING_PACKS_PATH):
        assert _MARKER_RE.search(_read(path)), (
            f"{path} has no <!-- registered-tools:start/end --> marked region"
        )
        unknown = _marked_tool_names(path) - registered
        assert not unknown, f"{path} references unregistered tool name(s): {sorted(unknown)}"


def test_readme_tool_table_lists_every_registered_tool():
    registered = set(tool_registry.registered_names())

    missing = registered - _marked_tool_names(README_PATH)
    assert not missing, (
        f"README.md's tool tables are missing {len(missing)} registered tool(s): "
        f"{sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}"
    )
