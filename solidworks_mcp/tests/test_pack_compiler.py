"""
Regression tests for solidworks_mcp.pack.compiler (compile()/Step/Ref) and
the create_drawing_pack composite tool (solidworks_mcp/tools/drawing_pack.py).

Two layers, tested separately:

- `compile()` is pure (no COM, no `dispatch()`) -- `TestCompilePure` below
  exercises it directly against `PackSpec` objects, with no fake-COM harness
  installed at all except where a test needs to assert the *absence* of any
  COM call.
- `create_drawing_pack`'s execution loop (Ref resolution, on_error handling,
  the step log, the summary) is its own concern, independent of what any
  individual underlying tool (`add_sheet`, `insert_model_view`, ...) does --
  those already have their own dedicated test modules. `TestCreateDrawingPackTool`
  exercises that loop with a scripted fake `dispatch()` rather than wiring a
  full multi-step SolidWorks COM object graph, which would mostly be
  re-testing tools this module doesn't own. `dry_run=True` is the one path
  that's both COM-free by construction *and* exercises the real registry
  `dispatch()`, so it doubles as the registration smoke test.
"""

import copy
import json
import pathlib

import pytest

from solidworks_mcp.pack import AnnotationSpec, PackSpec, ScaleSpec, SheetSpec, TableSpec, ViewSpec
from solidworks_mcp.pack.compiler import Ref, Step, compile as pack_compile
from solidworks_mcp.testing import install_fake_backend
from solidworks_mcp.tools import dispatch

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "docs" / "packs"
EXAMPLE_FILES = [
    EXAMPLES_DIR / "single_part.json",
    EXAMPLES_DIR / "assembly_with_bom.json",
    EXAMPLES_DIR / "multi_sheet_section_detail.json",
]


def _model_view(name="FrontView", **overrides) -> ViewSpec:
    kwargs = {"kind": "model", "name": name, "model_path": "C:\\p.sldprt", "x": 100, "y": 100}
    kwargs.update(overrides)
    return ViewSpec(**kwargs)


def _sheet(name="Sheet1", views=None, annotations=None, tables=None, properties=None) -> SheetSpec:
    return SheetSpec(
        name=name, model_path="C:\\p.sldprt", scale=ScaleSpec(1, 1),
        views=views or [], annotations=annotations or [], tables=tables or [],
        properties=properties or {},
    )


def _pack(sheets) -> PackSpec:
    return PackSpec(drawing_template="C:\\t.drwdot", output="C:\\o.slddrw", sheets=sheets)


# ---------------------------------------------------------------------------
# compile() -- pure
# ---------------------------------------------------------------------------


class TestCompilePure:
    def test_returns_a_list_of_step_objects(self):
        steps = pack_compile(_pack([_sheet(views=[_model_view()])]))
        assert isinstance(steps, list)
        assert steps
        assert all(isinstance(s, Step) for s in steps)

    def test_first_sheet_uses_new_drawing_from_template(self):
        steps = pack_compile(_pack([_sheet(views=[_model_view()])]))
        assert steps[0].tool == "new_drawing_from_template"
        assert steps[0].args["template_path"] == "C:\\t.drwdot"

    def test_second_sheet_uses_add_sheet_not_new_drawing_from_template(self):
        pack = _pack([
            _sheet(name="Sheet1", views=[_model_view("V1")]),
            _sheet(name="Sheet2", views=[_model_view("V2")]),
        ])
        steps = pack_compile(pack)
        sheet_creation_tools = [s.tool for s in steps if s.category == "sheet" and s.label.startswith("sheet:")]
        assert sheet_creation_tools == ["new_drawing_from_template", "add_sheet"]
        add_sheet_step = next(s for s in steps if s.tool == "add_sheet")
        assert add_sheet_step.args["name"] == "Sheet2"

    def test_export_step_is_last_and_uses_save_drawing_with_output(self):
        steps = pack_compile(_pack([_sheet(views=[_model_view()])]))
        assert steps[-1].tool == "save_drawing"
        assert steps[-1].args == {"filepath": "C:\\o.slddrw"}
        assert steps[-1].category == "export"

    def test_export_step_is_emitted_exactly_once_for_a_multi_sheet_pack(self):
        pack = _pack([
            _sheet(name="Sheet1", views=[_model_view("V1")]),
            _sheet(name="Sheet2", views=[_model_view("V2")]),
        ])
        steps = pack_compile(pack)
        export_steps = [s for s in steps if s.tool == "save_drawing"]
        assert len(export_steps) == 1
        assert steps[-1] is export_steps[0]

    def test_rebuild_steps_at_expected_indices_with_annotations_and_tables(self):
        sheet = _sheet(
            views=[_model_view("V1")],
            annotations=[AnnotationSpec(kind="note", view="V1", text="hi", x=1, y=1)],
            tables=[TableSpec(kind="bom", view="V1")],
        )
        steps = pack_compile(_pack([sheet]))
        # index: 0 new_drawing_from_template, 1 rename_sheet,
        # 2 set_sheet_properties, 3 insert_model_view, 4 auto_arrange_views,
        # 5 REBUILD, 6 add_note, 7 insert_bom_table, 8 REBUILD, 9 update_table, ...
        assert steps[5].tool == "rebuild_document"
        assert steps[8].tool == "rebuild_document"
        # and nothing else in the list is a rebuild
        rebuild_indices = [i for i, s in enumerate(steps) if s.tool == "rebuild_document"]
        assert rebuild_indices == [5, 8]

    def test_rebuild_steps_present_even_with_no_annotations_or_tables(self):
        steps = pack_compile(_pack([_sheet(views=[_model_view("V1")])]))
        rebuild_indices = [i for i, s in enumerate(steps) if s.tool == "rebuild_document"]
        assert len(rebuild_indices) == 2
        # Both rebuilds sit back-to-back once there's nothing to annotate/table.
        assert rebuild_indices[1] == rebuild_indices[0] + 1

    def test_rebuild_steps_emitted_per_sheet(self):
        pack = _pack([
            _sheet(name="Sheet1", views=[_model_view("V1")]),
            _sheet(name="Sheet2", views=[_model_view("V2")]),
        ])
        steps = pack_compile(pack)
        assert sum(1 for s in steps if s.tool == "rebuild_document") == 4

    def test_parent_views_ordered_before_children_when_listed_in_order(self):
        sheet = _sheet(views=[
            _model_view("Front"),
            ViewSpec(kind="projected", name="Top", parent="Front", direction="up"),
        ])
        steps = pack_compile(_pack([sheet]))
        view_tools = [s for s in steps if s.category == "view" and s.tool != "auto_arrange_views"]
        assert [s.label for s in view_tools] == ["view:Front", "view:Top"]

    def test_parent_views_ordered_before_children_when_listed_out_of_order(self):
        # compile() does not itself call validate() -- validate() would
        # reject this ordering, but compile() must still cope (and correct
        # it), since create_drawing_pack calls validate() *then* compile()
        # and this exercises compile()'s own topological sort directly.
        sheet = _sheet(views=[
            ViewSpec(kind="projected", name="Top", parent="Front", direction="up"),
            _model_view("Front"),
        ])
        steps = pack_compile(_pack([sheet]))
        view_tools = [s for s in steps if s.category == "view" and s.tool != "auto_arrange_views"]
        assert [s.label for s in view_tools] == ["view:Front", "view:Top"]
        # And the projected view's parent_view_name Ref points at Front's key.
        top_step = next(s for s in view_tools if s.label == "view:Top")
        front_step = next(s for s in view_tools if s.label == "view:Front")
        assert top_step.args["parent_view_name"] == Ref(front_step.binds)

    def test_multi_level_parent_chain_ordered_correctly_when_fully_reversed(self):
        sheet = _sheet(views=[
            ViewSpec(kind="detail", name="Detail1", parent="Section1", center_x=1, center_y=1, radius=1),
            ViewSpec(kind="section", name="Section1", parent="Front", cut_points=[[0, 0], [1, 1]]),
            _model_view("Front"),
        ])
        steps = pack_compile(_pack([sheet]))
        view_labels = [s.label for s in steps if s.category == "view" and s.tool != "auto_arrange_views"]
        assert view_labels == ["view:Front", "view:Section1", "view:Detail1"]

    def test_break_view_does_not_bind_a_new_view_name(self):
        sheet = _sheet(views=[
            _model_view("Front"),
            ViewSpec(kind="break", target="Front", position1=1, position2=2),
        ])
        steps = pack_compile(_pack([sheet]))
        break_step = next(s for s in steps if s.tool == "insert_break_view")
        assert break_step.binds is None
        front_step = next(s for s in steps if s.tool == "insert_model_view")
        assert break_step.args["view_name"] == Ref(front_step.binds)

    def test_crop_view_does_not_bind_a_new_view_name(self):
        sheet = _sheet(views=[
            _model_view("Front"),
            ViewSpec(kind="crop", target="Front", profile_points=[[0, 0], [1, 0], [1, 1]]),
        ])
        steps = pack_compile(_pack([sheet]))
        crop_step = next(s for s in steps if s.tool == "add_crop_view")
        assert crop_step.binds is None

    def test_broken_out_binds_its_own_name_and_references_its_parent(self):
        # A broken-out section mutates its parent view in place -- SolidWorks
        # never assigns it a separate name -- but the pack spec still lets
        # later annotations/tables address it by its own declared `name`, so
        # it must bind under its *own* key (not reuse the parent's), while
        # its `parent_view_name` argument still resolves through the parent.
        sheet = _sheet(views=[
            _model_view("Front"),
            ViewSpec(kind="broken_out", name="BO1", parent="Front", profile_points=[[0, 0], [1, 0], [1, 1]], depth=5),
        ])
        steps = pack_compile(_pack([sheet]))
        front_step = next(s for s in steps if s.tool == "insert_model_view")
        bo_step = next(s for s in steps if s.tool == "insert_broken_out_section")
        assert bo_step.binds is not None
        assert bo_step.binds != front_step.binds
        assert bo_step.bind_field == "view_name"
        assert bo_step.args["parent_view_name"] == Ref(front_step.binds)

    def test_balloons_compiled_after_tables_and_before_custom_properties(self):
        sheet = _sheet(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(kind="note", view="V1", text="note", x=0, y=0),
                AnnotationSpec(kind="balloon", view="V1", entity={"kind": "component", "x": 1, "y": 1}, x=1, y=1),
            ],
            tables=[TableSpec(kind="bom", view="V1")],
            properties={"Description": "x"},
        )
        steps = pack_compile(_pack([sheet]))
        tools = [s.tool for s in steps]
        assert tools.index("insert_bom_table") < tools.index("update_table") < tools.index("add_balloon")
        assert tools.index("add_note") < tools.index("insert_bom_table")
        assert tools.index("add_balloon") < tools.index("set_custom_properties")

    def test_custom_properties_step_omitted_when_sheet_has_no_properties(self):
        steps = pack_compile(_pack([_sheet(views=[_model_view()])]))
        assert not any(s.tool == "set_custom_properties" for s in steps)

    def test_custom_properties_step_included_when_sheet_has_properties(self):
        sheet = _sheet(views=[_model_view()], properties={"Description": "Bracket"})
        steps = pack_compile(_pack([sheet]))
        props_step = next(s for s in steps if s.tool == "set_custom_properties")
        assert props_step.args["properties"] == {"Description": "Bracket"}

    def test_compile_makes_no_com_calls(self):
        with install_fake_backend("drawing") as fake_sw:
            # Installing the fixture itself touches the fake object graph
            # (building ActiveDoc/Sheet/etc.) -- clear that setup noise so
            # this only asserts on what compile() itself does.
            fake_sw.call_log.calls.clear()
            pack = _pack([_sheet(
                views=[_model_view("V1"), ViewSpec(kind="projected", name="V2", parent="V1", direction="up")],
                annotations=[AnnotationSpec(kind="note", view="V1", text="hi", x=0, y=0)],
                tables=[TableSpec(kind="bom", view="V1")],
                properties={"Description": "x"},
            )])
            pack_compile(pack)
            assert fake_sw.call_log.calls == []

    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
    def test_example_packs_compile_without_error(self, path):
        pack = PackSpec.from_json_file(str(path))
        assert pack.validate() == []
        steps = pack_compile(pack)
        assert len(steps) > 0
        assert steps[-1].tool == "save_drawing"

    def test_all_three_example_packs_are_covered(self):
        assert len(EXAMPLE_FILES) == 3

    def test_hole_table_gets_a_default_datum_entity(self):
        sheet = _sheet(views=[_model_view("V1")], tables=[TableSpec(kind="hole", view="V1")])
        steps = pack_compile(_pack([sheet]))
        hole_step = next(s for s in steps if s.tool == "insert_hole_table")
        assert hole_step.args["datum_entity"] == {"kind": "vertex", "x": 0, "y": 0}

    def test_revision_table_omits_xy_and_defaults_to_anchor(self):
        sheet = _sheet(views=[_model_view("V1")], tables=[TableSpec(kind="revision")])
        steps = pack_compile(_pack([sheet]))
        rev_step = next(s for s in steps if s.tool == "insert_revision_table")
        assert "x" not in rev_step.args
        assert "y" not in rev_step.args

    @pytest.mark.parametrize("kind,tool_name,extra", [
        ("model", "insert_model_view", {}),
        ("projected", "insert_projected_view", {"parent": "Front", "direction": "up"}),
        ("section", "insert_section_view", {"parent": "Front", "cut_points": [[0, 0], [1, 1]]}),
        ("detail", "insert_detail_view", {"parent": "Front", "center_x": 1, "center_y": 1, "radius": 1}),
        ("broken_out", "insert_broken_out_section",
         {"parent": "Front", "profile_points": [[0, 0], [1, 0], [1, 1]], "depth": 5}),
    ])
    def test_creating_view_kind_maps_to_expected_tool(self, kind, tool_name, extra):
        views = [_model_view("Front")]
        if kind != "model":
            kwargs = {"kind": kind, "name": "Child"}
            kwargs.update(extra)
            views.append(ViewSpec(**kwargs))
        sheet = _sheet(views=views)
        steps = pack_compile(_pack([sheet]))
        assert any(s.tool == tool_name for s in steps)

    @pytest.mark.parametrize("kind,tool_name,extra", [
        ("note", "add_note", {"text": "hi"}),
        ("gtol", "add_gtol", {"entity": {"kind": "face", "x": 0, "y": 0}, "symbol": "flatness", "tolerance": 0.1}),
        ("datum_feature", "add_datum_feature", {"entity": {"kind": "edge", "x": 0, "y": 0}, "label": "A"}),
        ("datum_target", "add_datum_target",
         {"entity": {"kind": "face", "x": 0, "y": 0}, "label": "a1", "area_type": "point", "size": 1}),
        ("surface_finish", "add_surface_finish", {"entity": {"kind": "face", "x": 0, "y": 0}, "symbol_type": "basic"}),
        ("balloon", "add_balloon", {"entity": {"kind": "component", "x": 0, "y": 0}}),
    ])
    def test_annotation_kind_maps_to_expected_tool(self, kind, tool_name, extra):
        kwargs = {"kind": kind, "view": "Front", "x": 0, "y": 0}
        kwargs.update(extra)
        sheet = _sheet(
            views=[_model_view("Front")],
            annotations=[AnnotationSpec(**kwargs)],
            tables=[TableSpec(kind="bom", view="Front")] if kind == "balloon" else [],
        )
        steps = pack_compile(_pack([sheet]))
        assert any(s.tool == tool_name for s in steps)

    def test_step_to_dict_serializes_ref_as_dollar_ref(self):
        sheet = _sheet(views=[
            _model_view("Front"),
            ViewSpec(kind="projected", name="Top", parent="Front", direction="up"),
        ])
        steps = pack_compile(_pack([sheet]))
        top_step = next(s for s in steps if s.tool == "insert_projected_view")
        d = top_step.to_dict()
        assert d["args"]["parent_view_name"] == {"$ref": top_step.args["parent_view_name"].key}

    def test_view_name_namespace_is_scoped_per_sheet(self):
        pack = _pack([
            _sheet(name="Sheet1", views=[_model_view("Front")]),
            _sheet(name="Sheet2", views=[_model_view("Front")]),
        ])
        steps = pack_compile(pack)
        binds = [s.binds for s in steps if s.tool == "insert_model_view"]
        assert len(binds) == 2
        assert binds[0] != binds[1]


# ---------------------------------------------------------------------------
# create_drawing_pack -- execution loop
# ---------------------------------------------------------------------------


class _FakeDispatch:
    """Scriptable stand-in for `solidworks_mcp.tools.registry.dispatch`,
    swapped into `solidworks_mcp.tools.drawing_pack.dispatch` -- lets
    create_drawing_pack's own Ref-resolution/on_error/summary logic be
    tested without wiring a full multi-step fake-COM object graph (each
    underlying tool already has its own dedicated test module)."""

    def __init__(self):
        self.calls = []
        self._results = {}

    def succeed(self, tool_name, data=None):
        self._results[tool_name] = {"success": True, "message": "ok", "data": data or {}}

    def fail(self, tool_name, message="failed"):
        self._results[tool_name] = {"success": False, "message": message, "data": {}}

    def __call__(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        return self._results.get(name, {"success": True, "message": "ok", "data": {}})


@pytest.fixture
def fake_dispatch(monkeypatch):
    fd = _FakeDispatch()
    monkeypatch.setattr("solidworks_mcp.tools.drawing_pack.dispatch", fd)
    return fd


def _minimal_spec_dict():
    return {
        "drawing_template": "C:\\t.drwdot",
        "output": "C:\\o.slddrw",
        "sheets": [{
            "name": "Sheet1", "model_path": "C:\\p.sldprt",
            "views": [{"kind": "model", "name": "Front", "model_path": "C:\\p.sldprt", "x": 0, "y": 0}],
        }],
    }


class TestCreateDrawingPackTool:
    def test_registered_and_dry_run_returns_step_list_via_real_registry(self):
        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "dry_run": True})
        assert result["success"] is True, result
        assert result["data"]["dry_run"] is True
        assert isinstance(result["data"]["steps"], list)
        assert result["data"]["steps"][0]["tool"] == "new_drawing_from_template"
        assert result["data"]["steps"][-1]["tool"] == "save_drawing"

    def test_dry_run_makes_no_com_calls(self):
        with install_fake_backend("drawing") as fake_sw:
            fake_sw.call_log.calls.clear()
            result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "dry_run": True})
            assert result["success"] is True
            assert fake_sw.call_log.calls == []

    def test_invalid_spec_type_is_rejected(self):
        result = dispatch("create_drawing_pack", {"spec": "not-an-object"})
        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_spec_failing_validation_is_rejected_before_compiling(self):
        bad_spec = _minimal_spec_dict()
        bad_spec["sheets"][0]["views"][0]["kind"] = "bogus_kind"
        result = dispatch("create_drawing_pack", {"spec": bad_spec})
        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["validation_errors"]

    def test_unknown_on_error_value_rejected(self):
        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "on_error": "retry"})
        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_on_error_abort_stops_at_first_failure(self, fake_dispatch):
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.fail("set_sheet_properties", "boom")
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView1"})

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "on_error": "abort"})

        assert result["success"] is False
        called_tools = [name for name, _ in fake_dispatch.calls]
        # rename_sheet is a no-op here (the scripted template sheet is
        # already named "Sheet1", matching the spec) so it's never dispatched.
        assert called_tools == ["new_drawing_from_template", "set_sheet_properties"]
        step_log = result["data"]["steps"]
        assert step_log[1]["tool"] == "rename_sheet"
        assert step_log[2]["tool"] == "set_sheet_properties"
        assert step_log[2]["success"] is False
        assert step_log[3]["skipped"] is True

    def test_on_error_continue_runs_rest_and_reports_both_failures(self, fake_dispatch):
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.fail("set_sheet_properties", "boom1")
        fake_dispatch.fail("insert_model_view", "boom2")

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "on_error": "continue"})

        called_tools = [name for name, _ in fake_dispatch.calls]
        # Every step still ran, including save_drawing at the very end.
        assert called_tools[-1] == "save_drawing"
        assert len(result["data"]["summary"]["failures"]) == 2
        assert result["success"] is False

    def test_ref_resolution_uses_actual_created_view_name(self, fake_dispatch):
        spec = _minimal_spec_dict()
        spec["sheets"][0]["views"].append({
            "kind": "projected", "name": "Top", "parent": "Front", "direction": "up",
        })
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView7"})
        fake_dispatch.succeed("insert_projected_view", {"view_name": "DrawingView8"})

        result = dispatch("create_drawing_pack", {"spec": spec})

        assert result["success"] is True, result
        projected_call = next(args for name, args in fake_dispatch.calls if name == "insert_projected_view")
        assert projected_call["parent_view_name"] == "DrawingView7"

    def test_ref_resolution_uses_actual_created_sheet_name(self, fake_dispatch):
        # The spec declares "Sheet1", but the template's own first sheet
        # (data.sheet_name from new_drawing_from_template) is named
        # something else -- the compiler's rename_sheet step should bring it
        # in line, and every later step should address the *renamed* sheet.
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "SomeTemplateSheet"})
        fake_dispatch.succeed("rename_sheet", {"name": "SomeTemplateSheet", "new_name": "Sheet1"})
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView1"})

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict()})

        assert result["success"] is True, result
        rename_call = next(args for name, args in fake_dispatch.calls if name == "rename_sheet")
        assert rename_call == {"old_name": "SomeTemplateSheet", "new_name": "Sheet1"}
        props_call = next(args for name, args in fake_dispatch.calls if name == "set_sheet_properties")
        assert props_call["sheet_name"] == "Sheet1"
        view_call = next(args for name, args in fake_dispatch.calls if name == "insert_model_view")
        assert view_call["sheet_name"] == "Sheet1"

    def test_rename_sheet_not_dispatched_when_template_already_matches(self, fake_dispatch):
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView1"})

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict()})

        assert result["success"] is True, result
        called_tools = [name for name, _ in fake_dispatch.calls]
        assert "rename_sheet" not in called_tools
        rename_entry = next(s for s in result["data"]["steps"] if s["tool"] == "rename_sheet")
        assert rename_entry["success"] is True

    def test_unresolved_ref_is_skipped_not_dispatched_when_dependency_fails(self, fake_dispatch):
        fake_dispatch.fail("new_drawing_from_template", "no template found")

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict(), "on_error": "continue"})

        called_tools = [name for name, _ in fake_dispatch.calls]
        # rename_sheet/set_sheet_properties/insert_model_view all need the
        # sheet Ref, which never bound -- they must not reach dispatch()
        # with an unresolved Ref.
        assert "rename_sheet" not in called_tools
        assert "set_sheet_properties" not in called_tools
        assert "insert_model_view" not in called_tools
        step_log = result["data"]["steps"]
        sheet_props_entry = next(s for s in step_log if s["tool"] == "set_sheet_properties")
        assert sheet_props_entry["success"] is False
        assert "dependency" in sheet_props_entry["message"].lower()

    def test_summary_counts_by_category(self, fake_dispatch):
        spec = _minimal_spec_dict()
        spec["sheets"][0]["annotations"] = [
            {"kind": "note", "view": "Front", "text": "hi", "x": 0, "y": 0},
        ]
        spec["sheets"][0]["properties"] = {"Description": "x"}
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView1"})

        result = dispatch("create_drawing_pack", {"spec": spec})

        assert result["success"] is True, result
        summary = result["data"]["summary"]
        assert summary["sheets_created"] == 1
        assert summary["views_inserted"] == 1
        assert summary["annotations_added"] == 1
        assert summary["files_exported"] == 1
        assert summary["failures"] == []

    def test_full_step_log_returned_on_success(self, fake_dispatch):
        fake_dispatch.succeed("new_drawing_from_template", {"name": "Draw1", "sheet_name": "Sheet1"})
        fake_dispatch.succeed("insert_model_view", {"view_name": "DrawingView1"})

        result = dispatch("create_drawing_pack", {"spec": _minimal_spec_dict()})

        steps = result["data"]["steps"]
        # new_drawing_from_template, rename_sheet (a no-op here -- see
        # test_rename_sheet_not_dispatched_when_template_already_matches),
        # set_sheet_properties, insert_model_view, auto_arrange_views,
        # 2x rebuild_document, update_table, save_drawing.
        assert len(steps) == 9
        assert all("message" in s and "success" in s for s in steps)
        assert all(s["success"] is True for s in steps)
