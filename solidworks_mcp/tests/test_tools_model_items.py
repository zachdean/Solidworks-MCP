"""
Regression tests for insert_model_items (solidworks_mcp/tools/
drawing_annotations.py, backed by DrawingOperations.insert_model_items in
solidworks_mcp/automation/drawings.py), dispatched through the real
`solidworks_mcp.tools` registry against the fake COM harness -- same
convention as test_tools_views_projected.py.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring test_tools_views_projected.py's `tool_sw`, connecting
    the shared `tools.sw_automation` singleton to a fresh fake
    `SldWorks.Application`."""
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


def _view(fake_sw, obj_id, name, type_code=None):
    """Build a fake `IView`-shaped object with `GetName2`/`Type` scripted
    under path-scoped keys, per test_tools_views_projected.py's own
    convention (multiple views in one test can't share a bare-name key)."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    return view


def _prep_single_view(fake_sw, view_name="Drawing View1"):
    sheet = fake_sw.ActiveDoc.GetCurrentSheet()
    sheet.set_return("GetViews", [_view(fake_sw, "v1", view_name)])
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
    return sheet


class TestInsertModelItemsBitmask:
    """Type flags combine into the correct swInsertAnnotation_e bitmask."""

    def test_default_types_is_dimensions_plus_hole_callouts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is True
        assert result["data"]["types"] == ["dimensions", "hole_callouts"]
        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        # swInsertDimensions (8) | swInsertholeCallout (1048576)
        assert call.args[1] == 1048584

    def test_dimensions_and_datums_bitmask(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1", "types": ["dimensions", "datums"],
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        # swInsertDimensions (8) | swInsertDatums (2)
        assert call.args[1] == 10

    def test_gtols_and_notes_bitmask(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1", "types": ["gtols", "notes"],
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        # swInsertGTols (32) | swInsertNotes (64)
        assert call.args[1] == 96

    def test_surface_finishes_welds_and_datum_targets_bitmask(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1",
            "types": ["surface_finishes", "welds", "datum_targets"],
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        # swInsertSFSymbols (128) | swInsertWelds (256) | swInsertDatumTargets (4)
        assert call.args[1] == 388

    def test_single_type_cosmetic_threads_bitmask(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1", "types": ["cosmetic_threads"],
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args[1] == 1

    def test_unknown_type_errors_invalid_input(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)

        result = dispatch("insert_model_items", {
            "view_name": "Drawing View1", "types": ["dimensions", "center_marks"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "center_marks" in result["message"]
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")

    def test_non_list_types_errors_invalid_input_instead_of_raising(self, tool_sw):
        """A bare string for `types` must not silently iterate into
        single-character 'unknown type' entries (`list("dimensions")` ->
        ['d','i','m',...]) -- reject the shape outright, matching
        insert_broken_out_section's `profile_points` isinstance guard."""
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)

        result = dispatch("insert_model_items", {
            "view_name": "Drawing View1", "types": "dimensions",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")


class TestInsertModelItemsSources:
    def test_default_source_is_entire_model(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["data"]["sources"] == "model"
        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args[0] == 0  # swImportModelItemsFromEntireModel

    def test_selected_feature_source(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1", "sources": "selected_feature",
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args[0] == 1  # swImportModelItemsFromSelectedFeature

    def test_unknown_source_errors_invalid_input(self, tool_sw):
        """DimXpert isn't a real swImportModelItemsSource_e member (verified
        against help.solidworks.com for this issue) -- it must fail loudly,
        not silently alias to another source."""
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)

        result = dispatch("insert_model_items", {
            "view_name": "Drawing View1", "sources": "dimxpert",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "dimxpert" in result["message"]
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")


class TestInsertModelItemsMutualExclusion:
    def test_view_name_and_all_views_both_given_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_model_items", {
            "view_name": "Drawing View1", "all_views": True,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")

    def test_neither_view_name_nor_all_views_errors(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("insert_model_items", {})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")


class TestInsertModelItemsZeroImportedWarning:
    def test_zero_imported_is_a_warned_success_not_bare_success(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [])

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is True
        assert result["data"]["total_imported"] == 0
        assert "0 annotations imported" in result["message"]

    def test_none_returned_from_com_also_counts_as_zero(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", None)

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is True
        assert result["data"]["total_imported"] == 0
        assert "0 annotations imported" in result["message"]


class TestInsertModelItemsSingleView:
    def test_happy_path_selects_view_before_calling(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw, "Drawing View1")
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object(), object(), object()])

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is True
        assert result["data"]["total_imported"] == 3
        assert result["data"]["views"] == [
            {"view_name": "Drawing View1", "success": True, "count": 3}
        ]
        log = fake_sw.call_log
        names = log.ordered_names()
        assert names.index("SelectByID2") < names.index("InsertModelAnnotations4")
        select_call = log.calls_to("SelectByID2")[0]
        assert select_call.args[0] == "Drawing View1"
        assert select_call.args[1] == "DRAWINGVIEW"

    def test_com_all_views_argument_is_always_false(self, tool_sw):
        """The COM `AllViews` positional argument is always False -- this
        tool handles its own per-view iteration rather than delegating to
        InsertModelAnnotations4's whole-drawing AllViews=True, since that
        gives no per-view breakdown."""
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {"view_name": "Drawing View1"})

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args[2] is False

    def test_full_positional_arity_and_order(self, tool_sw):
        """Pins InsertModelAnnotations4's exact name, arity (8), and
        positional order -- Option, Types, AllViews, DuplicateDims,
        HiddenFeatureDims, UsePlacementInSketch, InsertAllAnnotations,
        InsertAllReferenceGeometry -- so a future edit that drops/reorders
        one of the three unexposed trailing params (which the dossier says
        silently override Types when True) can't slip past the narrower
        single-index assertions elsewhere in this file."""
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {"view_name": "Drawing View1"})

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args == (0, 1048584, False, True, False, False, False, False)

    def test_eliminate_duplicates_and_hidden_features_passed_through(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        dispatch("insert_model_items", {
            "view_name": "Drawing View1",
            "eliminate_duplicates": False, "hidden_features": True,
        })

        call = fake_sw.call_log.calls_to("InsertModelAnnotations4")[0]
        assert call.args[3] is False  # DuplicateDims
        assert call.args[4] is True   # HiddenFeatureDims

    def test_unknown_view_name_errors_listing_available_views(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])

        result = dispatch("insert_model_items", {"view_name": "Bogus View"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Bogus View" in result["message"]
        assert "Drawing View1" in result["message"]
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")

    def test_com_exception_fails_the_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_single_view(fake_sw)
        fake_sw.ActiveDoc.set_raises("InsertModelAnnotations4", RuntimeError("boom"))

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View1" in result["message"]

    def test_selection_failure_fails_the_result_without_calling_insert(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [_view(fake_sw, "v1", "Drawing View1")])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        result = dispatch("insert_model_items", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert not fake_sw.call_log.calls_to("InsertModelAnnotations4")


class TestInsertModelItemsAllViews:
    def test_all_views_iterates_every_view_with_per_view_counts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1"),
            _view(fake_sw, "v2", "Drawing View2"),
        ])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_sequence("InsertModelAnnotations4", [
            [object(), object()], [object()],
        ])

        result = dispatch("insert_model_items", {"all_views": True})

        assert result["success"] is True
        assert result["data"]["total_imported"] == 3
        assert result["data"]["views"] == [
            {"view_name": "Drawing View1", "success": True, "count": 2},
            {"view_name": "Drawing View2", "success": True, "count": 1},
        ]
        select_calls = fake_sw.call_log.calls_to("SelectByID2")
        assert [c.args[0] for c in select_calls] == ["Drawing View1", "Drawing View2"]
        assert len(fake_sw.call_log.calls_to("InsertModelAnnotations4")) == 2

    def test_all_views_excludes_the_sheet_pseudo_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "sheet_pv", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet),
            _view(fake_sw, "v1", "Drawing View1"),
        ])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        result = dispatch("insert_model_items", {"all_views": True})

        assert result["success"] is True
        assert result["data"]["views"] == [
            {"view_name": "Drawing View1", "success": True, "count": 1}
        ]

    def test_all_views_no_views_on_sheet_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [])

        result = dispatch("insert_model_items", {"all_views": True})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_all_views_one_view_fails_the_whole_result_naming_it(self, tool_sw):
        """The second view's selection fails (SelectByID2 -> False); the
        first view's import still runs and is reported, but the overall
        result fails, naming the failed view."""
        fake_sw = tool_sw("drawing")
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [
            _view(fake_sw, "v1", "Drawing View1"),
            _view(fake_sw, "v2", "Drawing View2"),
        ])
        fake_sw.ActiveDoc.Extension.set_sequence("SelectByID2", [True, False])
        fake_sw.ActiveDoc.set_return("InsertModelAnnotations4", [object()])

        result = dispatch("insert_model_items", {"all_views": True})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Drawing View2" in result["message"]
        assert len(fake_sw.call_log.calls_to("InsertModelAnnotations4")) == 1
