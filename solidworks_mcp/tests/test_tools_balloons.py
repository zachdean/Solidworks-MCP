"""
Regression tests for the balloon tools (solidworks_mcp/tools/
drawing_tables.py's auto_balloon_view, add_balloon, renumber_balloons,
remove_balloons), dispatched through the real `solidworks_mcp.tools`
registry (`dispatch()`) against the fake COM harness -- same convention as
test_tools_bom.py/test_tools_center_marks.py: exercise both the registry
wiring and the `DrawingOperations` automation methods, asserting COM call
names/order/args against the fake's call log.
"""

import pytest

from solidworks_mcp.constants_drawing import (
    SwBalloonFit,
    SwBalloonLayoutType,
    SwBalloonStyle,
    SwBalloonTextContent,
    SwDrawingViewTypes,
    SwTableAnnotationType,
)
from solidworks_mcp.tools import dispatch, sw_automation


def _view(fake_sw, obj_id, name, type_code=None, first_table=None, first_note=None):
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(
        f"{obj_id}.Type",
        int(type_code if type_code is not None else SwDrawingViewTypes.swDrawingStandardView),
    )
    view.set_return(f"{obj_id}.GetFirstTableAnnotation", first_table)
    view.set_return(f"{obj_id}.GetFirstNote", first_note)
    view.set_return(f"{obj_id}.GetNextView", None)
    return view


def _table(fake_sw, obj_id, name="BomTable1",
           type_code=SwTableAnnotationType.swTableAnnotation_BillOfMaterials):
    """A fake `IBomTableAnnotation` -> `GetAnnotation` -> `IAnnotation` chain,
    with `GetNext` pre-terminated at `None` -- matches test_tools_bom.py's
    `_table` convention (trimmed to what `auto_balloon_view`'s BOM detection
    actually reads: `Type` and the annotation's `GetName`)."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)

    table = fake_sw.new_object(obj_id)
    table.set_return(f"{obj_id}.GetAnnotation", ann)
    table.set_return(f"{obj_id}.Type", int(type_code))
    table.set_return(f"{obj_id}.GetNext", None)
    return table


def _prep_sheet(fake_sw, view):
    """Wires the default drawing's pre-existing "Sheet1" so both
    `GetCurrentSheet()` (used to resolve the active sheet's name) and
    `Sheet("Sheet1")` (used by `_scoped_views`'s BOM-table walk) answer the
    same sheet object, with `view` as its only view -- and so `view` is
    reachable via the document-wide `GetFirstView`/`GetNextView` walk
    `_scoped_views`/`_iter_document_views` use."""
    sheet = fake_sw.ActiveDoc.GetCurrentSheet()
    sheet.set_return("GetViews", [view])
    fake_sw.ActiveDoc.set_return("Sheet", sheet)
    fake_sw.ActiveDoc.set_return("GetFirstView", view)
    return sheet


def _balloon_note(fake_sw, obj_id, name="Balloon1", position=(0.0, 0.0, 0.0),
                   is_balloon=True, lower_style=0, lower_text=""):
    """A fake `INote` BOM balloon -> `GetAnnotation` -> `IAnnotation` chain,
    scripted with `IsBomBalloon`/`GetBomBalloonTextStyle`/`GetBomBalloonText`/
    `SetBomBalloonText` for `renumber_balloons`/`remove_balloons`, and
    `GetName`/`GetPosition`/`SetPosition2` for `add_balloon`'s placement
    read-back. `GetNext` pre-terminated at `None` (chain terminator)."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)

    note = fake_sw.new_object(obj_id)
    note.set_return(f"{obj_id}.GetAnnotation", ann)
    note.set_return(f"{obj_id}.IsBomBalloon", is_balloon)
    note.set_return(f"{obj_id}.GetBomBalloonTextStyle", lower_style)
    note.set_return(f"{obj_id}.GetBomBalloonText", lower_text)
    note.set_return(f"{obj_id}.SetBomBalloonText", True)
    note.set_return(f"{obj_id}.GetNext", None)
    return note, ann


def _chain_notes(*notes):
    for a, b in zip(notes, notes[1:]):
        a.set_return(f"{a._path}.GetNext", b)


def _active_view(fake_sw, first_note=None):
    """`remove_balloons` reads `doc.ActiveDrawingView` as a bare attribute
    (never called), so it resolves to the same auto-vivified child
    `FakeComObject` every access -- `set_return("ActiveDrawingView", ...)`
    would only ever satisfy the *called* form `doc.ActiveDrawingView()`, per
    the fake-COM harness's call/value duality. Grabbing that child directly
    and scripting members on it is the only way to make `view.GetFirstNote`
    answer what a test wants."""
    view = fake_sw.ActiveDoc.ActiveDrawingView
    view.set_return("GetFirstNote", first_note)
    return view


class TestAutoBalloonView:
    def test_every_exposed_option_is_set_before_autoballoon5_is_called(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        bom_table = _table(fake_sw, "t1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=bom_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        options = fake_sw.new_object("opts")
        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", options)
        balloons = [fake_sw.new_object("b1"), fake_sw.new_object("b2")]
        fake_sw.ActiveDoc.set_return("AutoBalloon5", balloons)

        result = dispatch("auto_balloon_view", {
            "view_name": "Drawing View1", "layout": "circle", "style": "triangle",
            "size": "3_chars", "text_content": "quantity", "reverse_direction": True,
            "ignore_multiple": False, "insert_magnetic_line": True, "leader_attachment": "face",
        })

        assert result["success"] is True, result
        assert result["data"]["count"] == 2
        assert result["data"]["has_bom"] is True

        assert options.Layout == int(SwBalloonLayoutType.swDetailingBalloonLayout_Circle)
        assert options.Style == int(SwBalloonStyle.swBS_Triangle)
        assert options.Size == int(SwBalloonFit.swBF_3Chars)
        assert options.UpperTextContent == int(SwBalloonTextContent.swBalloonTextQuantity)
        assert options.ReverseDirection is True
        assert options.IgnoreMultiple is False
        assert options.InsertMagneticLine is True
        assert options.LeaderAttachmentToFaces is True

        auto_balloon_call = fake_sw.call_log.calls_to("AutoBalloon5")[0]
        assert auto_balloon_call.args == (options,)

    def test_defaults_match_the_documented_defaults(self, tool_sw):
        fake_sw = tool_sw("drawing")
        bom_table = _table(fake_sw, "t1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=bom_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        options = fake_sw.new_object("opts")
        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", options)
        fake_sw.ActiveDoc.set_return("AutoBalloon5", [])

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert options.Layout == int(SwBalloonLayoutType.swDetailingBalloonLayout_Square)
        assert options.Style == int(SwBalloonStyle.swBS_Circular)
        assert options.Size == int(SwBalloonFit.swBF_Tightest)
        assert options.UpperTextContent == int(SwBalloonTextContent.swBalloonTextItemNumber)
        assert options.IgnoreMultiple is True
        assert options.LeaderAttachmentToFaces is False

    def test_no_bom_table_on_sheet_warns_in_message(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Drawing View1")  # no tables at all
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", fake_sw.new_object("opts"))
        fake_sw.ActiveDoc.set_return("AutoBalloon5", [fake_sw.new_object("b1")])

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["has_bom"] is False
        assert "WARNING" in result["message"]
        assert "no BOM table" in result["message"]

    def test_bom_table_name_that_does_not_exist_is_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        other_table = _table(fake_sw, "t1", name="SomeOtherTable")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=other_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        result = dispatch("auto_balloon_view", {
            "view_name": "Drawing View1", "bom_table_name": "BomTable1",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("AutoBalloon5")

    def test_autoballoon5_returning_none_is_a_warned_success_with_zero_count(self, tool_sw):
        """`AutoBalloon5`'s page documents no "nothing to balloon" sentinel,
        and pywin32 commonly marshals an empty SAFEARRAY back as `None` --
        this must read the same as the other batch-annotation tools'
        (`add_center_marks`/`add_centerlines`/`remove_center_marks`) "0
        produced" convention, not a hard failure."""
        fake_sw = tool_sw("drawing")
        bom_table = _table(fake_sw, "t1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=bom_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", fake_sw.new_object("opts"))
        fake_sw.ActiveDoc.set_return("AutoBalloon5", None)

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0

    def test_create_options_returning_nothing_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        bom_table = _table(fake_sw, "t1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=bom_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", None)

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert not fake_sw.call_log.calls_to("AutoBalloon5")

    def test_a_rejected_option_property_blocks_autoballoon5_entirely(self, tool_sw):
        """Proves the property-set-before-call ordering the acceptance
        criteria call out: a options object that refuses every property
        assignment must fail *before* `AutoBalloon5` is ever invoked, not
        merely alongside it -- mirrors test_tools_center_marks.py's
        `_RejectingMark` stub, since `FakeComObject.__setattr__` stores a
        property set directly rather than routing it through `set_raises`
        (which only covers invocations)."""
        fake_sw = tool_sw("drawing")
        bom_table = _table(fake_sw, "t1")
        view = _view(fake_sw, "v1", "Drawing View1", first_table=bom_table)
        _prep_sheet(fake_sw, view)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        class _RejectingOptions:
            def __setattr__(self, name, value):
                raise RuntimeError(f"read-only property {name!r}")

        fake_sw.ActiveDoc.set_return("CreateAutoBalloonOptions", _RejectingOptions())

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "Set auto-balloon option" in result["message"]
        assert not fake_sw.call_log.calls_to("AutoBalloon5")

    def test_unreadable_sheet_name_does_not_silently_widen_the_bom_scan(self, tool_sw):
        """An unreadable `ISheet::GetName` must not fall through to
        `_scoped_views`' "no sheet_name -> scan the whole document" branch
        -- that would let a BOM table on an unrelated sheet silently
        suppress the missing-BOM warning for this one."""
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Drawing View1")
        sheet = _prep_sheet(fake_sw, view)
        sheet.set_return("ISheet.GetName", "")
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"
        assert not fake_sw.call_log.calls_to("AutoBalloon5")

    @pytest.mark.parametrize("field,bad_value", [
        ("layout", "diagonal"),
        ("style", "hexagram"),
        ("size", "6_chars"),
        ("text_content", "made_up"),
        ("leader_attachment", "corner"),
    ])
    def test_unknown_enum_values_are_rejected_without_any_com_call(self, tool_sw, field, bad_value):
        fake_sw = tool_sw("drawing")

        result = dispatch("auto_balloon_view", {"view_name": "Drawing View1", field: bad_value})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("CreateAutoBalloonOptions")
        assert not fake_sw.call_log.calls_to("AutoBalloon5")


class TestAddBalloon:
    def test_positional_args_match_dossier_order(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        note, _ann = _balloon_note(fake_sw, "b1", name="Balloon1", position=(0.05, 0.025, 0.0))
        fake_sw.ActiveDoc.Extension.set_return("InsertBOMBalloon", note)

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1",
            "entity": {"kind": "component", "x": 10, "y": 20, "z": 0},
            "x": 50, "y": 25,
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBOMBalloon")[0].args
        assert args == (
            int(SwBalloonStyle.swBS_Circular), int(SwBalloonFit.swBF_Tightest),
            int(SwBalloonTextContent.swBalloonTextItemNumber), "",
            0, "",
            pytest.approx(0.0), False, 0, "",
        )
        assert result["data"]["name"] == "Balloon1"
        assert result["data"]["x"] == pytest.approx(50.0)
        assert result["data"]["y"] == pytest.approx(25.0)

    def test_custom_text_content_and_quantity_display_flow_through(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        note, _ann = _balloon_note(fake_sw, "b1")
        fake_sw.ActiveDoc.Extension.set_return("InsertBOMBalloon", note)

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "edge", "x": 1, "y": 2},
            "x": 1, "y": 1, "text_content": "custom", "upper_text": "QTY-1",
            "quantity_display": True,
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBOMBalloon")[0].args
        assert args[2] == int(SwBalloonTextContent.swBalloonTextCustom)
        assert args[3] == "QTY-1"
        assert args[7] is True  # ShowQuantity

    def test_split_circle_with_lower_text_sets_lower_style_custom(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        note, _ann = _balloon_note(fake_sw, "b1")
        fake_sw.ActiveDoc.Extension.set_return("InsertBOMBalloon", note)

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "edge", "x": 1, "y": 2},
            "x": 1, "y": 1, "style": "split_circle", "lower_text": "REV-A",
        })

        assert result["success"] is True, result
        args = fake_sw.call_log.calls_to("InsertBOMBalloon")[0].args
        assert args[0] == int(SwBalloonStyle.swBS_SplitCirc)
        assert args[4] == int(SwBalloonTextContent.swBalloonTextCustom)
        assert args[5] == "REV-A"

    def test_lower_text_requires_split_circle_style(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "edge", "x": 1, "y": 2},
            "x": 1, "y": 1, "lower_text": "B",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBOMBalloon")

    def test_unknown_style_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "edge", "x": 1, "y": 2},
            "x": 1, "y": 1, "style": "hexagram",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertBOMBalloon")

    def test_component_entity_kind_selects_via_component_type_string(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        note, _ann = _balloon_note(fake_sw, "b1")
        fake_sw.ActiveDoc.Extension.set_return("InsertBOMBalloon", note)

        dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "component", "x": 5, "y": 6},
            "x": 1, "y": 1,
        })

        call = fake_sw.call_log.calls_to("SelectByID2")[0]
        assert call.args[1] == "COMPONENT"

    def test_insert_returning_nothing_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("InsertBOMBalloon", None)

        result = dispatch("add_balloon", {
            "view_name": "Drawing View1", "entity": {"kind": "component", "x": 1, "y": 2},
            "x": 1, "y": 1,
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestRenumberBalloons:
    def test_sorts_top_left_first_by_position(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        top_left, _ = _balloon_note(fake_sw, "n1", name="TopLeft", position=(0.01, 0.05, 0.0))
        top_right, _ = _balloon_note(fake_sw, "n2", name="TopRight", position=(0.03, 0.05, 0.0))
        bottom, _ = _balloon_note(fake_sw, "n3", name="Bottom", position=(0.01, 0.01, 0.0))
        _chain_notes(top_left, top_right, bottom)
        view = _view(fake_sw, "v1", "Drawing View1", first_note=top_left)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("renumber_balloons", {"start": 5})

        assert result["success"] is True, result
        assert result["data"]["count"] == 3
        names = [b["name"] for b in result["data"]["balloons"]]
        numbers = [b["item_number"] for b in result["data"]["balloons"]]
        assert names == ["TopLeft", "TopRight", "Bottom"]
        assert numbers == [5, 6, 7]

        calls = fake_sw.call_log.calls_to("SetBomBalloonText")
        assert [c.args[1] for c in calls] == ["5", "6", "7"]

    def test_deterministic_across_two_calls_with_unchanged_positions(self, tool_sw):
        fake_sw = tool_sw("drawing")
        sw_automation._units.default_unit = "mm"
        a, _ = _balloon_note(fake_sw, "n1", name="A", position=(0.02, 0.05, 0.0))
        b, _ = _balloon_note(fake_sw, "n2", name="B", position=(0.01, 0.05, 0.0))
        _chain_notes(a, b)
        view = _view(fake_sw, "v1", "Drawing View1", first_note=a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        first = dispatch("renumber_balloons", {})
        second = dispatch("renumber_balloons", {})

        assert first["success"] is True and second["success"] is True
        assert first["data"]["balloons"] == second["data"]["balloons"]

    def test_preserves_existing_lower_text_and_style(self, tool_sw):
        fake_sw = tool_sw("drawing")
        note, _ = _balloon_note(
            fake_sw, "n1", name="Split1", position=(0.01, 0.01, 0.0),
            lower_style=int(SwBalloonTextContent.swBalloonTextCustom), lower_text="REV-A",
        )
        view = _view(fake_sw, "v1", "Drawing View1", first_note=note)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("renumber_balloons", {"start": 1})

        assert result["success"] is True, result
        call = fake_sw.call_log.calls_to("SetBomBalloonText")[0]
        assert call.args[0] == int(SwBalloonTextContent.swBalloonTextCustom)
        assert call.args[1] == "1"
        assert call.args[2] == int(SwBalloonTextContent.swBalloonTextCustom)
        assert call.args[3] == "REV-A"

    def test_non_balloon_notes_are_ignored(self, tool_sw):
        fake_sw = tool_sw("drawing")
        plain, _ = _balloon_note(fake_sw, "n1", name="PlainNote", is_balloon=False)
        view = _view(fake_sw, "v1", "Drawing View1", first_note=plain)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("renumber_balloons", {})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("SetBomBalloonText")

    def test_no_balloons_is_success_with_zero_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view = _view(fake_sw, "v1", "Drawing View1")
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("renumber_balloons", {})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert result["data"]["balloons"] == []

    def test_unknown_order_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("renumber_balloons", {"order": "by_creation"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetBomBalloonText")

    def test_non_integer_start_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("renumber_balloons", {"start": 1.5})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetBomBalloonText")

    def test_view_name_restricts_to_that_views_balloons(self, tool_sw):
        fake_sw = tool_sw("drawing")
        in_scope, _ = _balloon_note(fake_sw, "n1", name="InScope", position=(0.01, 0.01, 0.0))
        out_of_scope, _ = _balloon_note(fake_sw, "n2", name="OutOfScope", position=(0.02, 0.02, 0.0))
        view1 = _view(fake_sw, "v1", "Drawing View1", first_note=in_scope)
        view2 = _view(fake_sw, "v2", "Drawing View2", first_note=out_of_scope)
        sheet = fake_sw.ActiveDoc.GetCurrentSheet()
        sheet.set_return("GetViews", [view1, view2])
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("renumber_balloons", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 1
        assert result["data"]["balloons"][0]["name"] == "InScope"


class TestRemoveBalloons:
    def test_removes_only_balloon_notes_not_plain_notes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        balloon1, _ = _balloon_note(fake_sw, "n1", name="Balloon1")
        plain, _ = _balloon_note(fake_sw, "n2", name="PlainNote", is_balloon=False)
        balloon2, _ = _balloon_note(fake_sw, "n3", name="Balloon2")
        _chain_notes(balloon1, plain, balloon2)
        _active_view(fake_sw, first_note=balloon1)

        result = dispatch("remove_balloons", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 2
        assert result["data"]["removed"] == 2
        assert len(fake_sw.call_log.calls_to("DeleteSelection2")) == 2
        selected_names = {c.args[0] for c in fake_sw.call_log.calls_to("SelectByID2")}
        assert selected_names == {"Balloon1", "Balloon2"}

    def test_no_balloons_is_success_with_zero_count(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        _active_view(fake_sw)

        result = dispatch("remove_balloons", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 0
        assert not fake_sw.call_log.calls_to("DeleteSelection2")

    def test_one_failed_selection_is_skipped_but_does_not_fail_the_batch(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)
        # First balloon selects fine, second fails to select.
        fake_sw.ActiveDoc.Extension.set_sequence("SelectByID2", [True, False])

        balloon1, _ = _balloon_note(fake_sw, "n1", name="Balloon1")
        balloon2, _ = _balloon_note(fake_sw, "n2", name="Balloon2")
        _chain_notes(balloon1, balloon2)
        _active_view(fake_sw, first_note=balloon1)

        result = dispatch("remove_balloons", {"view_name": "Drawing View1"})

        assert result["success"] is True, result
        assert result["data"]["count"] == 1
        assert len(fake_sw.call_log.calls_to("DeleteSelection2")) == 1

    def test_all_selection_failures_is_a_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", False)

        balloon1, _ = _balloon_note(fake_sw, "n1", name="Balloon1")
        _active_view(fake_sw, first_note=balloon1)

        result = dispatch("remove_balloons", {"view_name": "Drawing View1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["count"] == 0
