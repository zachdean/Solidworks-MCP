"""
Regression tests for the note tools (solidworks_mcp/tools/
drawing_annotations.py's add_note, add_property_note, list_notes, edit_note),
dispatched through the real `solidworks_mcp.tools` registry (`dispatch()`)
against the fake COM harness -- same convention as test_tools_dimensions.py
and test_tools_model_items.py: exercise both the registry wiring and the
`DrawingOperations` automation methods, asserting COM call order/args
against the fake's call log.
"""

import pytest

from solidworks_mcp.constants_drawing import SwDrawingViewTypes, SwLeaderStyle
from solidworks_mcp.tools import dispatch


def _note(fake_sw, obj_id, name="Note1", text="", position=(0.0, 0.0, 0.0), layer=""):
    """A fake `INote` -> `GetAnnotation` -> `IAnnotation` chain, scripted
    with sensible defaults so a note flows through `_finalize_note`/
    `_describe_note`/`edit_note` without extra per-test setup: `GetName`,
    `GetPosition` (meters), `Layer`, `SetLeader3` (success status `0`),
    `SetPosition2`/`SetText` (`True`), `GetNext` (`None` -- chain terminator).
    """
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    ann.set_return(f"{obj_id}.ann.Layer", layer)
    ann.set_return(f"{obj_id}.ann.SetLeader3", 0)
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)
    ann.set_return(f"{obj_id}.ann.SetLeaderAttachmentPointAtIndex", True)

    note = fake_sw.new_object(obj_id)
    note.set_return(f"{obj_id}.GetAnnotation", ann)
    note.set_return(f"{obj_id}.GetText", text)
    note.set_return(f"{obj_id}.IsCompoundNote", False)
    note.set_return(f"{obj_id}.SetText", True)
    note.set_return(f"{obj_id}.GetNext", None)
    return note, ann


def _chain_notes(*notes):
    """Link `notes` (each an `(note, ann)` pair from `_note`) into a
    `GetNext` chain, last one terminating at `None` (already its default)."""
    for (note, _ann), (nxt, _nxt_ann) in zip(notes, notes[1:]):
        note.set_return(f"{note._path}.GetNext", nxt)


def _view(fake_sw, obj_id, name, type_code=None, first_note=None):
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    view.set_return(f"{obj_id}.GetFirstNote", first_note)
    view.set_return(f"{obj_id}.GetNextView", None)
    return view


def _chain_views(*views):
    for a, b in zip(views, views[1:]):
        a.set_return(f"{a._path}.GetNextView", b)


class TestAddNoteBasics:
    def test_success_converts_position_and_height_to_meters(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1", name="Note1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Hello", "x": 50, "y": 25, "height": 5})

        assert result["success"] is True, result
        log = fake_sw.call_log
        args = log.arg_of("CreateText2", 0), log.arg_of("CreateText2", 1), \
            log.arg_of("CreateText2", 2), log.arg_of("CreateText2", 3), \
            log.arg_of("CreateText2", 4), log.arg_of("CreateText2", 5)
        text_string, x_m, y_m, z_m, height_m, angle_rad = args
        assert text_string == "Hello"
        assert x_m == pytest.approx(0.05)
        assert y_m == pytest.approx(0.025)
        assert z_m == 0.0
        assert height_m == pytest.approx(0.005)
        assert angle_rad == pytest.approx(0.0)
        assert result["data"]["name"] == "Note1"

    def test_height_omitted_passes_zero_sentinel(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "No height", "x": 0, "y": 0})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 4) == 0.0

    def test_angle_degrees_converted_to_radians(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Angled", "x": 0, "y": 0, "angle": 90})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 5) == pytest.approx(1.5707963267948966)

    def test_multiline_text_passes_through_unchanged(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        multiline = "Line one\nLine two\nLine three"
        result = dispatch("add_note", {"text": multiline, "x": 0, "y": 0})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 0) == multiline

    def test_view_name_activates_view_before_creating_note(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "In view", "x": 0, "y": 0, "view_name": "Drawing View1"})

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.ordered_names().index("ActivateView") < log.ordered_names().index("CreateText2")
        log.assert_called_with("ActivateView", "Drawing View1")

    def test_unknown_view_name_fails_before_creating_note(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", False)

        result = dispatch("add_note", {"text": "Nope", "x": 0, "y": 0, "view_name": "Missing"})

        assert result["success"] is False
        assert not fake_sw.call_log.calls_to("CreateText2")

    def test_non_numeric_x_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_note", {"text": "Bad", "x": "oops", "y": 0})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateText2")


class TestAddNoteBoldItalic:
    def test_bold_wraps_font_style_b(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Bold text", "x": 0, "y": 0, "bold": True})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 0) == "<FONT style=B>Bold text"

    def test_bold_and_italic_chain_both_font_tags(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch(
            "add_note", {"text": "Both", "x": 0, "y": 0, "bold": True, "italic": True},
        )

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 0) == "<FONT style=B><FONT style=I>Both"


class TestAddNoteLeader:
    @pytest.mark.parametrize("style_key,expected_enum", [
        ("none", SwLeaderStyle.swNO_LEADER),
        ("straight", SwLeaderStyle.swSTRAIGHT),
        ("bent", SwLeaderStyle.swBENT),
        ("underline", SwLeaderStyle.swUNDERLINED),
    ])
    def test_leader_style_maps_to_dossier_enum(self, tool_sw, style_key, expected_enum):
        fake_sw = tool_sw("drawing")
        note, ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch(
            "add_note", {"text": "Leader", "x": 0, "y": 0, "leader": {"style": style_key}},
        )

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetLeader3", 0) == int(expected_enum)

    def test_leader_none_produces_leaderless_note_no_setleader_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Plain", "x": 0, "y": 0})

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("SetLeader3")

    def test_unknown_leader_style_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch(
            "add_note", {"text": "Bad leader", "x": 0, "y": 0, "leader": {"style": "wiggly"}},
        )

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateText2")

    def test_leader_with_attach_point_calls_set_leader_attachment_point(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {
            "text": "Attached", "x": 0, "y": 0,
            "leader": {"style": "bent", "x": 12, "y": 34},
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        log.assert_called_with(
            "SetLeaderAttachmentPointAtIndex", 0, pytest.approx(0.012), pytest.approx(0.034), 0.0,
        )

    def test_leader_setleader3_failure_status_fails_result(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, ann = _note(fake_sw, "n1")
        ann.set_return(f"{ann._path}.SetLeader3", -3)
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Rejected", "x": 0, "y": 0, "leader": {"style": "bent"}})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestAddNoteLayer:
    def test_layer_sets_annotation_layer(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_note", {"text": "Layered", "x": 0, "y": 0, "layer": "Notes-Layer"})

        assert result["success"] is True, result
        assert ann.Layer == "Notes-Layer"


class TestAddPropertyNote:
    def test_source_sheet_emits_prpsheet(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_property_note", {"property_name": "SW-Mass", "x": 10, "y": 20})

        assert result["success"] is True, result
        assert note.PropertyLinkedText == '$PRPSHEET:"SW-Mass"'
        assert result["data"]["linked_text"] == '$PRPSHEET:"SW-Mass"'

    def test_source_model_emits_prp(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch(
            "add_property_note", {"property_name": "PartNo", "x": 0, "y": 0, "source": "model"},
        )

        assert result["success"] is True, result
        assert note.PropertyLinkedText == '$PRP:"PartNo"'

    def test_prefix_and_suffix_wrap_the_link(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_property_note", {
            "property_name": "SW-Mass", "x": 0, "y": 0,
            "prefix": "Weight: ", "suffix": " kg",
        })

        assert result["success"] is True, result
        assert note.PropertyLinkedText == 'Weight: $PRPSHEET:"SW-Mass" kg'

    def test_unknown_source_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch(
            "add_property_note", {"property_name": "SW-Mass", "x": 0, "y": 0, "source": "bogus"},
        )

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateText2")

    def test_creation_uses_empty_placeholder_text(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ann = _note(fake_sw, "n1")
        fake_sw.ActiveDoc.set_return("CreateText2", note)

        result = dispatch("add_property_note", {"property_name": "SW-Mass", "x": 0, "y": 0})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("CreateText2", 0) == ""


class TestListNotes:
    def test_lists_notes_across_every_view_in_document(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note1, _ann1 = _note(fake_sw, "n1", name="Note1", text="First", position=(0.01, 0.02, 0.0))
        note2, _ann2 = _note(fake_sw, "n2", name="Note2", text="Second", position=(0.03, 0.04, 0.0))
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_note=note1)
        view2 = _view(fake_sw, "v2", "Drawing View1", first_note=note2)
        _chain_views(view1, view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("list_notes", {})

        assert result["success"] is True, result
        names = {n["name"] for n in result["data"]["notes"]}
        assert names == {"Note1", "Note2"}
        by_name = {n["name"]: n for n in result["data"]["notes"]}
        assert by_name["Note1"]["text"] == "First"
        assert by_name["Note1"]["x"] == pytest.approx(10.0)  # meters -> mm default unit
        assert by_name["Note1"]["view_name"] == "Sheet1"
        assert by_name["Note2"]["view_name"] == "Drawing View1"

    def test_view_name_filters_to_one_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note1, _ann1 = _note(fake_sw, "n1", name="Note1")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        # `ActiveDrawingView` is a bare (uncalled) property read in
        # production code, per test_selection.py::TestListViewEntities'
        # own convention -- script directly onto the auto-vivified child
        # the bare access returns, not via `set_return("ActiveDrawingView", ...)`
        # (which only affects a *called* `ActiveDrawingView()`).
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetFirstNote", note1)

        result = dispatch("list_notes", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert [n["name"] for n in result["data"]["notes"]] == ["Note1"]
        fake_sw.call_log.assert_called_with("ActivateView", "Drawing View1")

    def test_empty_view_returns_no_notes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetFirstNote", None)

        result = dispatch("list_notes", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["notes"] == []


class TestEditNote:
    def test_updates_text_on_matching_note(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note1, _ann1 = _note(fake_sw, "n1", name="Note1")
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_note=note1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("edit_note", {"note_name": "Note1", "text": "Updated"})

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetText", "Updated")

    def test_updates_position_reads_back_missing_axis(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note1, ann1 = _note(fake_sw, "n1", name="Note1", position=(0.01, 0.02, 0.0))
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_note=note1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("edit_note", {"note_name": "Note1", "x": 100})

        assert result["success"] is True, result
        # x -> 100mm -> 0.1m; y left at its current 0.02m read-back; z at 0.0
        fake_sw.call_log.assert_called_with("SetPosition2", pytest.approx(0.1), pytest.approx(0.02), 0.0)

    def test_unknown_note_name_lists_available_notes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note1, _ann1 = _note(fake_sw, "n1", name="Note1")
        view1 = _view(fake_sw, "v1", "Sheet1", type_code=SwDrawingViewTypes.swDrawingSheet, first_note=note1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("edit_note", {"note_name": "NoSuchNote", "text": "x"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Note1" in result["data"]["available_notes"]
        assert "NoSuchNote" in result["message"]

    def test_no_fields_given_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("edit_note", {"note_name": "Note1"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetFirstView")
