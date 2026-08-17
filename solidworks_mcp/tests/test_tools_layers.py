"""
Regression tests for the layer tools (solidworks_mcp/tools/drawing_layers.py:
create_layer, list_layers, set_current_layer, set_layer_properties,
move_annotations_to_layer), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
same convention as test_tools_notes.py/test_tools_export_pdf.py: exercise
both the registry wiring and the `DrawingOperations` automation methods,
asserting COM call order/args against the fake's call log.
"""

from solidworks_mcp.constants_drawing import SwLineStyles, SwLineWeights
from solidworks_mcp.tools import dispatch


def _layer_mgr(fake_sw, existing_names=()):
    """A fake `ILayerMgr`, wired onto `ActiveDoc.GetLayerManager()` and
    pre-scripted with `GetLayerList` -- the shared entry point every layer
    tool resolves first."""
    layer_mgr = fake_sw.new_object("layer_mgr")
    fake_sw.ActiveDoc.set_return("GetLayerManager", layer_mgr)
    layer_mgr.set_return("GetLayerList", list(existing_names))
    return layer_mgr


def _layer(fake_sw, obj_id, visible=True, printable=True, color=0,
           style=int(SwLineStyles.swLineCONTINUOUS), width=int(SwLineWeights.swLW_NORMAL),
           description=""):
    """A fake `ILayer`, pre-scripted with every property `_describe_layer`
    reads. Path-qualified keys throughout -- distinct `ILayer` fakes in the
    same test would otherwise clobber each other's bare `"Visible"`/etc.
    scripting in the harness's shared global registry (see
    test_tools_export_pdf.py's identical convention)."""
    layer = fake_sw.new_object(obj_id)
    layer.set_return(f"{obj_id}.Visible", visible)
    layer.set_return(f"{obj_id}.Printable", printable)
    layer.set_return(f"{obj_id}.Color", color)
    layer.set_return(f"{obj_id}.Style", style)
    layer.set_return(f"{obj_id}.Width", width)
    layer.set_return(f"{obj_id}.Description", description)
    return layer


class _RefusesPrintableOnHiddenLayer:
    """A hand-written `ILayer` stand-in that enforces the two behaviours
    `ILayer::Visible`/`ILayer::Printable`'s dossier records document but the
    fake harness cannot express (its property writes are plain stores, so
    `set_raises` -- which hooks call time -- can't reach them): hiding a
    layer clears `Printable` as a side effect, and writing `Printable =
    True` onto a hidden layer throws instead of taking."""

    def __init__(self):
        self.Description = ""
        self.Color = 0
        self.Style = int(SwLineStyles.swLineCONTINUOUS)
        self.Width = int(SwLineWeights.swLW_NORMAL)
        self._visible = True
        self._printable = True

    @property
    def Visible(self):
        return self._visible

    @Visible.setter
    def Visible(self, value):
        self._visible = bool(value)
        if not self._visible:
            self._printable = False

    @property
    def Printable(self):
        return self._printable

    @Printable.setter
    def Printable(self, value):
        if value and not self._visible:
            raise RuntimeError("cannot make a hidden layer printable")
        self._printable = bool(value)


def _annotation_owner(fake_sw, obj_id, next_method="GetNext"):
    """A fake `INote`/`IDatumTag`/`ITableAnnotation`-shaped wrapper: `.
    GetAnnotation()` -> a fresh `IAnnotation` fake (whose `.Layer` a test
    reads back after the call, the same way test_tools_notes.py's `ann.Layer
    == ...` checks work -- a plain attribute assignment never touches the
    call log), and `.GetNext()` pre-scripted to `None` (chain terminator)."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    owner = fake_sw.new_object(obj_id)
    owner.set_return(f"{obj_id}.GetAnnotation", ann)
    owner.set_return(f"{obj_id}.{next_method}", None)
    return owner, ann


def _chain(owners, next_method="GetNext"):
    """Link `owners` (each from `_annotation_owner`) into a `GetNext` chain,
    the last one terminating at `None` (already its default)."""
    for a, b in zip(owners, owners[1:]):
        a.set_return(f"{a._path}.{next_method}", b)


def _move_view(fake_sw, obj_id, first_note=None, first_datum_tag=None, first_table=None,
                first_dimension=None):
    """A fake `IView` scripted for `_iter_document_views`'s
    `GetFirstView`/`GetNextView` walk, plus each annotation family's own
    `GetFirstX` head -- `move_annotations_to_layer`'s per-view entry
    points."""
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetFirstNote", first_note)
    view.set_return(f"{obj_id}.GetFirstDatumTag", first_datum_tag)
    view.set_return(f"{obj_id}.GetFirstTableAnnotation", first_table)
    view.set_return(f"{obj_id}.GetFirstDisplayDimension6", first_dimension)
    view.set_return(f"{obj_id}.GetNextView", None)
    return view


class TestCreateLayer:
    def test_happy_path_creates_layer_and_applies_visible_then_printable(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 1)
        layer = _layer(fake_sw, "new_layer")
        layer_mgr.set_return("GetLayer", layer)

        result = dispatch("create_layer", {
            "name": "Dims", "description": "Generated dimensions",
            "color": "#FF0000", "style": "hidden", "width": "thick",
            "visible": True, "printable": False,
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.arg_of("AddLayer", 0) == "Dims"
        assert log.arg_of("AddLayer", 1) == "Generated dimensions"
        assert log.arg_of("AddLayer", 3) == int(SwLineStyles.swLineHIDDEN)
        assert log.arg_of("AddLayer", 4) == int(SwLineWeights.swLW_THICK)
        assert layer.Visible is True
        assert layer.Printable is False
        assert result["data"]["color"] == "#FF0000"
        assert result["data"]["style"] == "hidden"
        assert result["data"]["width"] == "thick"
        # visible/printable are read back off the layer, not echoed from the
        # request -- see test_getlayer_failure_falls_back_to_requested_visible_printable
        # for why that distinction matters.
        assert result["data"]["visible"] is True
        assert result["data"]["printable"] is False

    def test_getlayer_failure_reports_visible_printable_as_unknown(self, tool_sw):
        """`ILayer::Printable`'s dossier record documents that SolidWorks
        can silently refuse `Printable == True` on a layer that isn't
        `Visible` -- so the response reads the layer back after writing it
        rather than echoing the request. When the layer can't be re-resolved
        (`GetLayer` returns nothing here) those two writes never happen at
        all, so the response reports them as unknown rather than echoing a
        state the layer provably isn't in."""
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 1)
        layer_mgr.set_return("GetLayer", None)

        result = dispatch("create_layer", {
            "name": "L0", "visible": False, "printable": True,
        })

        assert result["success"] is True, result
        assert result["data"]["visible"] is None
        assert result["data"]["printable"] is None

    def test_hex_color_converts_to_bgr_packed_colorref(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 1)
        layer_mgr.set_return("GetLayer", _layer(fake_sw, "layer_x"))

        result = dispatch("create_layer", {"name": "L1", "color": "#112233"})

        assert result["success"] is True, result
        # COLORREF packs 0x00BBGGRR -- red in the low byte, blue in the high
        # byte, the reverse of the 0xRRGGBB order the hex string itself uses.
        expected = 0x11 | (0x22 << 8) | (0x33 << 16)
        assert expected == 0x332211
        assert fake_sw.call_log.arg_of("AddLayer", 2) == expected

    def test_rgb_triple_produces_the_same_colorref_as_equivalent_hex(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 1)
        layer_mgr.set_return("GetLayer", _layer(fake_sw, "layer_y"))

        result = dispatch("create_layer", {"name": "L2", "color": [0x11, 0x22, 0x33]})

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("AddLayer", 2) == 0x332211

    def test_default_color_style_width_when_omitted(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 1)
        layer_mgr.set_return("GetLayer", _layer(fake_sw, "layer_z"))

        result = dispatch("create_layer", {"name": "L3"})

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.arg_of("AddLayer", 2) == 0  # black
        assert log.arg_of("AddLayer", 3) == int(SwLineStyles.swLineCONTINUOUS)
        assert log.arg_of("AddLayer", 4) == int(SwLineWeights.swLW_NORMAL)

    def test_duplicate_name_rejected_before_addlayer_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims"])

        result = dispatch("create_layer", {"name": "Dims"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Dims" in result["message"]
        assert not fake_sw.call_log.calls_to("AddLayer")

    def test_invalid_color_rejected_without_any_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("create_layer", {"name": "L4", "color": "not-a-color"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetLayerManager")

    def test_unknown_style_key_rejected_without_any_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("create_layer", {"name": "L5", "style": "dotted"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetLayerManager")

    def test_addlayer_falsy_return_is_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, [])
        layer_mgr.set_return("AddLayer", 0)

        result = dispatch("create_layer", {"name": "L6"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_blank_name_rejected_without_any_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("create_layer", {"name": "   "})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetLayerManager")


class TestListLayers:
    def test_lists_every_layer_with_full_properties(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims", "Notes"])
        dims = _layer(fake_sw, "dims_layer", visible=True, printable=True,
                       color=0x0000FF, style=int(SwLineStyles.swLineHIDDEN),
                       width=int(SwLineWeights.swLW_THICK), description="Dimensions")
        notes = _layer(fake_sw, "notes_layer", visible=False, printable=False,
                        color=0x00FF00, style=int(SwLineStyles.swLineCONTINUOUS),
                        width=int(SwLineWeights.swLW_NORMAL), description="Notes")
        layer_mgr.set_sequence("GetLayer", [dims, notes])

        result = dispatch("list_layers", {})

        assert result["success"] is True, result
        layers = result["data"]["layers"]
        assert [entry["name"] for entry in layers] == ["Dims", "Notes"]
        by_name = {entry["name"]: entry for entry in layers}
        assert by_name["Dims"]["color"] == "#FF0000"
        assert by_name["Dims"]["style"] == "hidden"
        assert by_name["Dims"]["width"] == "thick"
        assert by_name["Dims"]["visible"] is True
        assert by_name["Dims"]["printable"] is True
        assert by_name["Dims"]["description"] == "Dimensions"
        assert by_name["Notes"]["visible"] is False
        assert by_name["Notes"]["printable"] is False
        assert by_name["Notes"]["color"] == "#00FF00"

    def test_no_layers_returns_empty_list(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, [])

        result = dispatch("list_layers", {})

        assert result["success"] is True, result
        assert result["data"]["layers"] == []


class TestSetCurrentLayer:
    def test_success_calls_setcurrentlayer_with_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer_mgr.set_return("SetCurrentLayer", 1)

        result = dispatch("set_current_layer", {"name": "Dims"})

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetCurrentLayer", "Dims")

    def test_unknown_layer_lists_existing_layers_without_calling_setcurrentlayer(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims", "Notes"])

        result = dispatch("set_current_layer", {"name": "Bogus"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["existing_layers"] == ["Dims", "Notes"]
        assert "Dims" in result["message"] and "Notes" in result["message"]
        assert not fake_sw.call_log.calls_to("SetCurrentLayer")

    def test_setcurrentlayer_falsy_return_is_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer_mgr.set_return("SetCurrentLayer", 0)

        result = dispatch("set_current_layer", {"name": "Dims"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestSetLayerProperties:
    def test_partial_update_changes_only_the_given_field(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer = _layer(fake_sw, "dims_layer", visible=True, printable=True,
                        color=0x1E140A, style=int(SwLineStyles.swLineHIDDEN),
                        width=int(SwLineWeights.swLW_THICK))
        layer_mgr.set_return("GetLayer", layer)

        result = dispatch("set_layer_properties", {"name": "Dims", "visible": False})

        assert result["success"] is True, result
        assert layer.Visible is False
        data = result["data"]
        assert data["visible"] is False
        # Everything left unspecified reads back exactly as it was scripted.
        assert data["printable"] is True
        assert data["color"] == "#0A141E"
        assert data["style"] == "hidden"
        assert data["width"] == "thick"

    def test_every_field_can_be_updated_at_once(self, tool_sw):
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer = _layer(fake_sw, "dims_layer")
        layer_mgr.set_return("GetLayer", layer)

        result = dispatch("set_layer_properties", {
            "name": "Dims", "visible": False, "printable": False,
            "color": "#00FF00", "style": "chain", "width": "thin",
        })

        assert result["success"] is True, result
        assert layer.Visible is False
        assert layer.Printable is False
        assert layer.Color == 0x00FF00
        assert layer.Style == int(SwLineStyles.swLineCHAIN)
        assert layer.Width == int(SwLineWeights.swLW_THIN)

    def test_visible_side_effect_on_printable_is_reverted_when_printable_omitted(self, tool_sw):
        """`ILayer::Visible`'s dossier record documents that setting Visible
        can change Printable as a side effect. Simulate that here via a
        `set_sequence` on Printable's getter: the first read (the pre-
        `Visible`-write snapshot) sees True, the second (taken right after
        `Visible` is set) sees SolidWorks having flipped it to False -- the
        tool must write Printable back to True since the caller never asked
        to change it."""
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer = _layer(fake_sw, "dims_layer", visible=True)
        layer.set_sequence("dims_layer.Printable", [True, False])
        layer_mgr.set_return("GetLayer", layer)

        result = dispatch("set_layer_properties", {"name": "Dims", "visible": False})

        assert result["success"] is True, result
        assert layer.Visible is False
        assert layer.Printable is True

    def test_unknown_layer_lists_existing_layers(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims"])

        result = dispatch("set_layer_properties", {"name": "Bogus", "visible": True})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["existing_layers"] == ["Dims"]

    def test_invalid_color_rejected_before_any_mutation(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims"])

        result = dispatch("set_layer_properties", {"name": "Dims", "color": "not-a-color"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetLayer")

    def test_signed_hex_color_rejected(self, tool_sw):
        """`"#-1-2-3"` is six characters, so a length check alone lets it
        through and `int(..., 16)` happily parses signed channels into a
        negative COLORREF. The hex branch is as strict about 0-255 as the
        `(r, g, b)` branch."""
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims"])

        result = dispatch("set_layer_properties", {"name": "Dims", "color": "#-1-2-3"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetLayer")

    def test_impossible_printable_restore_is_logged_not_fatal(self, tool_sw):
        """Hiding a layer whose `printable` the caller never mentioned makes
        the tool try to re-assert `Printable == True` on a now-hidden layer
        -- exactly the write `ILayer::Printable`'s dossier record documents
        as impossible. A real SolidWorks that throws there must not turn a
        successful hide into a failed call; `data` reports what actually
        stuck."""
        fake_sw = tool_sw("drawing")
        layer_mgr = _layer_mgr(fake_sw, ["Dims"])
        layer_mgr.set_return("GetLayer", _RefusesPrintableOnHiddenLayer())

        result = dispatch("set_layer_properties", {"name": "Dims", "visible": False})

        assert result["success"] is True, result
        assert result["data"]["visible"] is False
        # Not True: the restore was refused, and the response says so rather
        # than echoing the value the tool tried to preserve.
        assert result["data"]["printable"] is False


class TestMoveAnnotationsToLayer:
    def test_moves_notes_datum_tags_tables_and_dimensions_by_default(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        note1, note1_ann = _annotation_owner(fake_sw, "note1")
        note2, note2_ann = _annotation_owner(fake_sw, "note2")
        _chain([note1, note2])
        tag1, tag1_ann = _annotation_owner(fake_sw, "tag1")
        table1, table1_ann = _annotation_owner(fake_sw, "table1")
        dim1, dim1_ann = _annotation_owner(fake_sw, "dim1", next_method="GetNext5")
        view = _move_view(
            fake_sw, "v1", first_note=note1, first_datum_tag=tag1, first_table=table1,
            first_dimension=dim1,
        )
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("move_annotations_to_layer", {"layer_name": "Reviewed"})

        assert result["success"] is True, result
        assert note1_ann.Layer == "Reviewed"
        assert note2_ann.Layer == "Reviewed"
        assert tag1_ann.Layer == "Reviewed"
        assert table1_ann.Layer == "Reviewed"
        assert dim1_ann.Layer == "Reviewed"
        assert result["data"]["moved"] == {"note": 2, "datum_tag": 1, "table": 1, "dimension": 1}
        assert result["data"]["total"] == 5

    def test_dimension_type_filter_moves_only_dimensions(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        note1, note1_ann = _annotation_owner(fake_sw, "note1")
        dim1, dim1_ann = _annotation_owner(fake_sw, "dim1", next_method="GetNext5")
        view = _move_view(fake_sw, "v1", first_note=note1, first_dimension=dim1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("move_annotations_to_layer", {
            "layer_name": "Reviewed", "annotation_types": ["dimension"],
        })

        assert result["success"] is True, result
        assert dim1_ann.Layer == "Reviewed"
        assert note1_ann.Layer != "Reviewed"
        assert result["data"]["moved"] == {"dimension": 1}

    def test_unknown_layer_lists_existing_layers(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Dims"])

        result = dispatch("move_annotations_to_layer", {"layer_name": "Bogus"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["existing_layers"] == ["Dims"]

    def test_view_name_restricts_to_one_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        fake_sw.ActiveDoc.set_return("ActivateView", True)
        note1, note1_ann = _annotation_owner(fake_sw, "note1")
        view = fake_sw.ActiveDoc.ActiveDrawingView
        view.set_return("GetFirstNote", note1)
        view.set_return("GetFirstDatumTag", None)
        view.set_return("GetFirstTableAnnotation", None)
        view.set_return("GetFirstDisplayDimension6", None)

        result = dispatch("move_annotations_to_layer", {
            "layer_name": "Reviewed", "view_name": "Drawing View1",
        })

        assert result["success"] is True, result
        assert note1_ann.Layer == "Reviewed"
        fake_sw.call_log.assert_called_with("ActivateView", "Drawing View1")
        assert result["data"]["moved"]["note"] == 1
        assert not fake_sw.call_log.calls_to("GetFirstView")

    def test_annotation_types_filter_limits_moved_families(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        note1, note1_ann = _annotation_owner(fake_sw, "note1")
        tag1, tag1_ann = _annotation_owner(fake_sw, "tag1")
        view = _move_view(fake_sw, "v1", first_note=note1, first_datum_tag=tag1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("move_annotations_to_layer", {
            "layer_name": "Reviewed", "annotation_types": ["note"],
        })

        assert result["success"] is True, result
        assert note1_ann.Layer == "Reviewed"
        assert tag1_ann.Layer != "Reviewed"
        assert result["data"]["moved"] == {"note": 1}

    def test_repeated_annotation_type_is_not_counted_twice(self, tool_sw):
        """A repeated key must not walk the same family twice -- the `Layer`
        writes are idempotent, but the counts would double and over-report
        how much of the pack was actually reassigned."""
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        note1, note1_ann = _annotation_owner(fake_sw, "note1")
        view = _move_view(fake_sw, "v1", first_note=note1)
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("move_annotations_to_layer", {
            "layer_name": "Reviewed", "annotation_types": ["note", "note"],
        })

        assert result["success"] is True, result
        assert note1_ann.Layer == "Reviewed"
        assert result["data"]["moved"] == {"note": 1}
        assert result["data"]["total"] == 1

    def test_unknown_annotation_type_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])

        result = dispatch("move_annotations_to_layer", {
            "layer_name": "Reviewed", "annotation_types": ["gtol"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_no_annotations_found_is_still_success_with_zero_counts(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _layer_mgr(fake_sw, ["Reviewed"])
        view = _move_view(fake_sw, "v1")
        fake_sw.ActiveDoc.set_return("GetFirstView", view)

        result = dispatch("move_annotations_to_layer", {"layer_name": "Reviewed"})

        assert result["success"] is True, result
        assert result["data"]["total"] == 0
