"""Tests for scripts/gen_tools_doc.py.

Proves the `--check` contract `scripts/check.sh` relies on: a stale or missing
`docs/TOOLS.md` fails (exit 1), an up-to-date one passes (exit 0), and every
registered tool ends up covered. Exercised against a temp `--output` path so
these tests never touch the real, committed `docs/TOOLS.md`.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_tools_doc.py"


@pytest.fixture
def gen_tools_doc():
    """The generator, loaded by path -- it lives in scripts/, not an
    importable package (same pattern as test_api_docs_validator.py)."""
    spec = importlib.util.spec_from_file_location("gen_tools_doc", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGenerate:
    def test_covers_every_registered_tool(self, gen_tools_doc):
        from solidworks_mcp.tools import registered_names

        content = gen_tools_doc.generate()

        for name in registered_names():
            assert f"## `{name}`" in content

    def test_output_states_the_tool_count(self, gen_tools_doc):
        from solidworks_mcp.tools import registered_names

        content = gen_tools_doc.generate()
        assert f"{len(registered_names())} tool(s) registered" in content


class TestCheckFlag:
    def test_fails_when_the_output_file_does_not_exist(self, gen_tools_doc, tmp_path):
        missing = tmp_path / "TOOLS.md"
        assert gen_tools_doc.main(["--check", "--output", str(missing)]) == 1

    def test_fails_when_the_output_file_is_stale(self, gen_tools_doc, tmp_path):
        stale = tmp_path / "TOOLS.md"
        stale.write_text("# This is not what the registry would generate\n", encoding="utf-8")

        assert gen_tools_doc.main(["--check", "--output", str(stale)]) == 1

    def test_passes_once_regenerated(self, gen_tools_doc, tmp_path):
        target = tmp_path / "TOOLS.md"

        assert gen_tools_doc.main(["--output", str(target)]) == 0
        assert gen_tools_doc.main(["--check", "--output", str(target)]) == 0

    def test_passes_against_the_committed_default_output(self, gen_tools_doc):
        # No --output: exactly the invocation scripts/check.sh runs. Proves
        # the committed docs/TOOLS.md is in sync, not just that the
        # generator/checker agree with each other against a scratch file.
        assert gen_tools_doc.main(["--check"]) == 0

    def test_check_does_not_write_when_stale(self, gen_tools_doc, tmp_path):
        stale = tmp_path / "TOOLS.md"
        original = "# stale placeholder\n"
        stale.write_text(original, encoding="utf-8")

        gen_tools_doc.main(["--check", "--output", str(stale)])

        assert stale.read_text(encoding="utf-8") == original


class TestDossierCrossReference:
    def test_links_a_description_mentioning_a_documented_method(self, gen_tools_doc):
        index = {"IDrawingDoc::NewSheet4": ("api/01-documents-and-sheets.md", "idrawingdocnewsheet4")}
        refs = gen_tools_doc.find_dossier_refs(
            "Creates a new sheet via IDrawingDoc::NewSheet4.", index
        )
        assert refs == [("IDrawingDoc::NewSheet4", "api/01-documents-and-sheets.md", "idrawingdocnewsheet4")]

    def test_no_match_when_the_token_is_not_in_the_index(self, gen_tools_doc):
        assert gen_tools_doc.find_dossier_refs("Calls IFoo::Bar internally.", {}) == []

    def test_build_dossier_index_finds_the_real_dossier_files(self, gen_tools_doc):
        index = gen_tools_doc.build_dossier_index()
        assert "IDrawingDoc::NewSheet4" in index
        assert "ISldWorks::RevisionNumber" in index


class TestOutputIsConfigIndependent:
    """The committed `docs/TOOLS.md` must depend on committed code only.
    `config.py` loads `solidworks_mcp/config.json` at import, and lowering
    `min_release` there is the documented way to test against an older
    install -- it must not rewrite every "Minimum release:" line and fail
    `check.sh` for a reason unrelated to the developer's change."""

    def test_lowering_the_configured_floor_does_not_change_the_doc(
        self, gen_tools_doc, monkeypatch
    ):
        from solidworks_mcp import config as config_module

        before = gen_tools_doc.generate()

        monkeypatch.setattr(config_module.get_config(), "min_release", 2021)
        assert config_module.get_config().min_release == 2021

        assert gen_tools_doc.generate() == before

    def test_declared_floor_still_reaches_the_doc(self, gen_tools_doc):
        """Config-independent must not mean release-blind: the committed
        default is still what gets rendered."""
        from solidworks_mcp.config import SolidWorksConfig

        default = SolidWorksConfig.__dataclass_fields__["min_release"].default
        content = gen_tools_doc.generate()

        assert f"- **Minimum release:** SOLIDWORKS {default}" in content
        assert "- **Minimum release:** none -- exempt from the version gate" in content
