"""Tests for scripts/validate_on_windows.py (sw-17y.2).

Exercises the runner entirely against a fake registry (no SolidWorks, no
real dispatch) -- `--only`/`--skip` filtering, one report entry per
registered tool regardless of filtering/exclusion, the failure-continues
behaviour, COM HRESULT/message extraction, and the macOS platform guard.
Loaded by path (same pattern as test_gen_tools_doc.py) since scripts/ is not
an importable package.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_on_windows.py"


@pytest.fixture
def validate_module():
    spec = importlib.util.spec_from_file_location("validate_on_windows", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclasses' deferred (`from __future__ import annotations`) type
    # resolution looks the module up in sys.modules by name -- without this,
    # ToolRecord/ToolSpec's field type hints fail to resolve at class-body
    # execution time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _schema(required=None, properties=None):
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


class FakeRegistry:
    """A minimal stand-in for solidworks_mcp.tools.registry: only
    `describe_tools()` and `dispatch(name, arguments)`, exactly the surface
    `run_validation` depends on."""

    def __init__(self, tools, responses=None, raises=None):
        self._tools = tools  # list of (name, schema)
        self._responses = responses or {}
        self._raises = raises or {}
        self.calls = []

    def describe_tools(self):
        return [
            {"name": name, "description": "", "schema": schema, "min_release": None}
            for name, schema in self._tools
        ]

    def dispatch(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self._raises:
            raise self._raises[name]
        if name in self._responses:
            return self._responses[name]
        return {"success": True, "message": f"{name} ok", "error_code": 0,
                "error_name": "swSuccess", "data": {}}


def _make_ctx(validate_module, dispatch_fn, tmp_path):
    return validate_module.ScriptContext(
        dispatch_fn, tmp_path / "bracket.sldprt", tmp_path / "bracket_assembly.sldasm", tmp_path / "out")


class TestFiltering:
    def test_only_matches_glob(self, validate_module):
        assert validate_module.filter_status("insert_bom_table", "insert_*", None) is None
        assert validate_module.filter_status("delete_table", "insert_*", None) == "filtered"

    def test_skip_matches_glob(self, validate_module):
        assert validate_module.filter_status("execute_python", None, "execute_*") == "filtered"
        assert validate_module.filter_status("insert_bom_table", None, "execute_*") is None

    def test_only_and_skip_combine(self, validate_module):
        # In the --only set, but also excluded by --skip -> filtered.
        assert validate_module.filter_status("add_note", "add_*", "add_note") == "filtered"
        # In the --only set and not skipped -> passes.
        assert validate_module.filter_status("add_gtol", "add_*", "add_note") is None

    def test_comma_separated_patterns(self, validate_module):
        assert validate_module.filter_status("add_note", "add_note,add_gtol", None) is None
        assert validate_module.filter_status("add_weld_symbol", "add_note,add_gtol", None) == "filtered"

    def test_no_patterns_means_unfiltered(self, validate_module):
        assert validate_module.filter_status("anything", None, None) is None


class TestRunValidationReportCoverage:
    def test_one_record_per_registered_tool_regardless_of_filtering(self, validate_module, tmp_path):
        tools = [("a", _schema()), ("b", _schema()), ("execute_python", _schema(["code"]))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx, only="a")

        assert {r.name for r in records} == {"a", "b", "execute_python"}
        by_name = {r.name: r for r in records}
        assert by_name["a"].status == "pass"
        assert by_name["b"].status == "filtered"
        assert by_name["execute_python"].status == "skipped"

    def test_exclusions_apply_even_when_explicitly_selected_via_only(self, validate_module, tmp_path):
        """execute_python must never be dispatched, even if a caller
        explicitly asks for it via --only -- see the module docstring's
        exclusion-precedence note."""
        tools = [("execute_python", _schema(["code"]))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx, only="execute_python")

        assert records[0].status == "skipped"
        assert registry.calls == []

    def test_skipped_tool_carries_the_exclusion_reason(self, validate_module, tmp_path):
        tools = [("execute_python", _schema(["code"]))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx)

        assert records[0].reason == validate_module.EXCLUSIONS["execute_python"]


class TestFailureContinuesTheRun:
    def test_a_raising_tool_is_recorded_and_the_run_continues(self, validate_module, tmp_path):
        tools = [("first", _schema()), ("boom", _schema()), ("last", _schema())]
        registry = FakeRegistry(tools, raises={"boom": RuntimeError("kaboom")})
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx)

        statuses = {r.name: r.status for r in records}
        assert statuses == {"first": "pass", "boom": "fail", "last": "pass"}
        boom = next(r for r in records if r.name == "boom")
        assert "kaboom" in boom.message
        assert boom.error is not None  # traceback captured

    def test_a_result_dict_reporting_failure_is_recorded_as_fail_not_pass(self, validate_module, tmp_path):
        tools = [("flaky", _schema())]
        registry = FakeRegistry(tools, responses={
            "flaky": {"success": False, "message": "SolidWorks refused", "error_code": 5, "data": {}},
        })
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx)

        assert records[0].status == "fail"
        assert records[0].message == "SolidWorks refused"

    def test_a_raising_arg_builder_does_not_abort_the_sweep(self, validate_module, tmp_path):
        tools = [("weird", _schema()), ("normal", _schema())]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)
        validate_module.TOOL_SPECS["weird"] = validate_module.ToolSpec(
            build=lambda ctx: (_ for _ in ()).throw(ValueError("bad builder")))
        try:
            records = validate_module.run_validation(registry, ctx)
        finally:
            del validate_module.TOOL_SPECS["weird"]

        statuses = {r.name: r.status for r in records}
        assert statuses["weird"] == "fail"
        assert statuses["normal"] == "pass"


class TestHresultAndMessageExtraction:
    def test_plain_exception_has_no_hresult(self, validate_module):
        assert validate_module._extract_hresult(RuntimeError("x")) is None

    def test_hresult_attribute_is_used_when_present(self, validate_module):
        exc = RuntimeError("x")
        exc.hresult = -2147352567
        assert validate_module._extract_hresult(exc) == -2147352567

    def test_com_error_shaped_args_yield_hresult_and_excepinfo_description(self, validate_module):
        exc = Exception(
            -2147352567, "Exception occurred.",
            (0, "SLDWORKS", "The real failure reason", None, 0, -2147352567), None,
        )
        assert validate_module._extract_hresult(exc) == -2147352567
        assert validate_module._describe_exception(exc) == "The real failure reason"

    def test_plain_exception_falls_back_to_str(self, validate_module):
        assert validate_module._describe_exception(ValueError("plain message")) == "plain message"


class TestReportGeneration:
    def test_summary_counts_every_status(self, validate_module):
        records = [
            validate_module.ToolRecord(name="a", status="pass"),
            validate_module.ToolRecord(name="b", status="fail"),
            validate_module.ToolRecord(name="c", status="skipped", reason="r"),
            validate_module.ToolRecord(name="d", status="filtered", reason="r"),
        ]
        report = validate_module.build_report(records, {"generated_at": "t"})
        assert report["summary"] == {"total": 4, "pass": 1, "fail": 1, "skipped": 1, "filtered": 1}
        assert len(report["tools"]) == 4

    def test_write_reports_writes_both_files_with_one_entry_per_tool(self, validate_module, tmp_path):
        tools = [("a", _schema()), ("b", _schema()), ("execute_python", _schema(["code"]))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)
        records = validate_module.run_validation(registry, ctx)
        report = validate_module.build_report(records, {"generated_at": "t", "min_release": 2025})

        out_dir = tmp_path / "reports"
        validate_module.write_reports(report, out_dir)

        json_path = out_dir / "validation_report.json"
        md_path = out_dir / "validation_report.md"
        assert json_path.exists()
        assert md_path.exists()

        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(loaded["tools"]) == 3
        assert {t["name"] for t in loaded["tools"]} == {"a", "b", "execute_python"}

        markdown = md_path.read_text(encoding="utf-8")
        assert "execute_python" in markdown
        assert "## Excluded (never dispatched)" in markdown

    def test_failures_get_their_own_markdown_section_with_traceback(self, validate_module, tmp_path):
        tools = [("boom", _schema())]
        registry = FakeRegistry(tools, raises={"boom": RuntimeError("kaboom")})
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)
        records = validate_module.run_validation(registry, ctx)
        report = validate_module.build_report(records, {"generated_at": "t"})

        markdown = validate_module.render_markdown(report)

        assert "## Failures" in markdown
        assert "kaboom" in markdown
        assert "Traceback" in markdown or "```" in markdown


class TestGenericArgumentSynthesis:
    def test_required_string_gets_a_placeholder(self, validate_module, tmp_path):
        tools = [("mystery_tool", _schema(["some_name"], {"some_name": {"type": "string"}}))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx)

        assert records[0].status == "pass"
        assert isinstance(registry.calls[0][1]["some_name"], str)
        assert registry.calls[0][1]["some_name"]

    def test_required_field_with_a_schema_default_uses_it(self, validate_module, tmp_path):
        tools = [("mystery_tool", _schema(
            ["mode"], {"mode": {"type": "string", "default": "fast"}}))]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        validate_module.run_validation(registry, ctx)

        assert registry.calls[0][1]["mode"] == "fast"

    def test_a_newly_registered_tool_with_no_spec_is_still_dispatched(self, validate_module, tmp_path):
        """The whole point of driving the sweep off describe_tools() rather
        than a hardcoded list (sw-17y.2 acceptance criteria)."""
        tools = [("totally_new_tool_from_the_future", _schema())]
        registry = FakeRegistry(tools)
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        records = validate_module.run_validation(registry, ctx)

        assert records[0].status == "pass"
        assert registry.calls == [("totally_new_tool_from_the_future", {})]


class TestScriptContext:
    def test_ensure_drawing_creates_and_saves_once(self, validate_module, tmp_path):
        registry = FakeRegistry([], responses={
            "get_document_type": {"success": True, "data": {"type": "Part"}},
            "new_drawing_from_template": {"success": True, "data": {"sheet_name": "Sheet1"}},
            "save_drawing": {"success": True, "data": {}},
        })
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        ctx.ensure_drawing()

        assert ctx.sheet_name == "Sheet1"
        assert ctx.drawing_path is not None
        assert ("new_drawing_from_template", {}) in registry.calls

    def test_ensure_drawing_reactivates_an_existing_drawing_instead_of_recreating(
            self, validate_module, tmp_path):
        registry = FakeRegistry([], responses={
            "get_document_type": {"success": True, "data": {"type": "Drawing"}},
        })
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)
        ctx.drawing_path = str(tmp_path / "existing.slddrw")

        ctx.ensure_drawing()

        assert all(name != "new_drawing_from_template" for name, _ in registry.calls)

    def test_ensure_part_view_reuses_an_existing_view(self, validate_module, tmp_path):
        registry = FakeRegistry([], responses={
            "get_document_type": {"success": True, "data": {"type": "Drawing"}},
            "list_views": {"success": True, "data": {"views": [{"name": "Front1"}]}},
        })
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)
        ctx.drawing_path = str(tmp_path / "existing.slddrw")
        ctx.view_name = "Front1"

        ctx.ensure_part_view()

        assert all(name != "insert_model_view" for name, _ in registry.calls)

    def test_setup_call_failures_are_recorded_as_warnings_not_raised(self, validate_module, tmp_path):
        registry = FakeRegistry([], responses={
            "get_document_type": {"success": False, "message": "no active document", "data": {}},
            "new_drawing_from_template": {"success": False, "message": "no template found", "data": {}},
        })
        ctx = _make_ctx(validate_module, registry.dispatch, tmp_path)

        ctx.ensure_drawing()  # must not raise

        assert any("new_drawing_from_template" in w for w in ctx.warnings)
        assert ctx.drawing_path is None


class TestPlatformGuard:
    def test_main_refuses_to_run_off_windows(self, validate_module, monkeypatch, capsys):
        if sys.platform == "win32":
            pytest.skip("this assertion only applies off Windows")
        exit_code = validate_module.main([])
        assert exit_code != 0

    def test_main_does_not_touch_solidworks_off_windows(self, validate_module, monkeypatch):
        if sys.platform == "win32":
            pytest.skip("this assertion only applies off Windows")
        calls = []
        monkeypatch.setattr(
            validate_module.tool_registry, "dispatch",
            lambda name, args: calls.append(name) or {"success": True})
        validate_module.main([])
        assert calls == []
