"""
Regression tests for the GD&T tools (solidworks_mcp/tools/
drawing_annotations.py's list_datums, add_datum_feature, add_gtol,
add_datum_target), dispatched through the real `solidworks_mcp.tools`
registry (`dispatch()`) against the fake COM harness -- same convention as
test_tools_notes.py/test_tools_dimensions.py: exercise both the registry
wiring and the `DrawingOperations` automation methods, asserting COM call
order/args against the fake's call log.
"""

import pytest

from solidworks_mcp.automation.drawings import _GTOL_SYMBOLS
from solidworks_mcp.tools import dispatch


def _prep_view(fake_sw):
    """Common setup every happy/near-happy-path test needs: ActivateView and
    SelectByID2 both scripted to succeed."""
    fake_sw.ActiveDoc.set_return("ActivateView", True)
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)


def _entity(kind="edge", x=1, y=2, z=0):
    return {"kind": kind, "x": x, "y": y, "z": z}


def _datum_tag(fake_sw, obj_id, label="A", name="DatumTag1", position=(0.0, 0.0, 0.0)):
    """A fake `IDatumTag` -> `GetAnnotation` -> `IAnnotation` chain --
    `GetLabel`, `SetLabel` (success), `SetDisplayStyle` (success),
    `GetNext` (`None` -- chain terminator), same shape as
    test_tools_notes.py's `_note` helper."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)

    tag = fake_sw.new_object(obj_id)
    tag.set_return(f"{obj_id}.GetAnnotation", ann)
    tag.set_return(f"{obj_id}.GetLabel", label)
    tag.set_return(f"{obj_id}.SetLabel", True)
    tag.set_return(f"{obj_id}.SetDisplayStyle", True)
    tag.set_return(f"{obj_id}.GetNext", None)
    return tag, ann


def _chain_datum_tags(*tags):
    for (tag, _ann), (nxt, _nxt_ann) in zip(tags, tags[1:]):
        tag.set_return(f"{tag._path}.GetNext", nxt)


def _view(fake_sw, obj_id, name, first_datum_tag=None):
    view = fake_sw.new_object(obj_id)
    view.set_return(f"{obj_id}.GetName2", name)
    view.set_return(f"{obj_id}.Type", 1)
    view.set_return(f"{obj_id}.GetFirstDatumTag", first_datum_tag)
    view.set_return(f"{obj_id}.GetFirstNote", None)
    view.set_return(f"{obj_id}.GetNextView", None)
    return view


def _gtol(fake_sw, obj_id, name="Gtol1", position=(0.0, 0.0, 0.0)):
    """A fake `IGtol` -> `GetAnnotation` -> `IAnnotation` chain --
    `SetFrameValues2`/`SetPTZHeight2` scripted to succeed."""
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)

    gtol = fake_sw.new_object(obj_id)
    gtol.set_return(f"{obj_id}.GetAnnotation", ann)
    gtol.set_return(f"{obj_id}.SetFrameValues2", True)
    gtol.set_return(f"{obj_id}.SetPTZHeight2", True)
    return gtol, ann


def _datum_target(fake_sw, obj_id, name="DatumTarget1", position=(0.0, 0.0, 0.0)):
    ann = fake_sw.new_object(f"{obj_id}.ann")
    ann.set_return(f"{obj_id}.ann.GetName", name)
    ann.set_return(f"{obj_id}.ann.GetPosition", list(position))
    ann.set_return(f"{obj_id}.ann.SetPosition2", True)

    target = fake_sw.new_object(obj_id)
    target.set_return(f"{obj_id}.GetAnnotation", ann)
    return target, ann


class TestListDatums:
    def test_lists_datum_tags_across_every_view(self, tool_sw):
        fake_sw = tool_sw("drawing")
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        tag_b, _ = _datum_tag(fake_sw, "db", label="B")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        view2 = _view(fake_sw, "v2", "Drawing View1", first_datum_tag=tag_b)
        view1.set_return("v1.GetNextView", view2)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("list_datums", {})

        assert result["success"] is True, result
        assert result["data"]["letters"] == ["A", "B"]
        labels = {d["label"] for d in result["data"]["datums"]}
        assert labels == {"A", "B"}

    def test_empty_document_returns_no_datums(self, tool_sw):
        fake_sw = tool_sw("drawing")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("list_datums", {})

        assert result["success"] is True, result
        assert result["data"]["datums"] == []
        assert result["data"]["letters"] == []


class TestAddDatumFeature:
    def test_explicit_label_creates_tag(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        tag, ann = _datum_tag(fake_sw, "t1", label="A")
        fake_sw.ActiveDoc.set_return("InsertDatumTag2", tag)

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "label": "A", "x": 10, "y": 20,
        })

        assert result["success"] is True, result
        assert result["data"]["label"] == "A"
        fake_sw.call_log.assert_called_with("SetLabel", "A")
        fake_sw.call_log.assert_called_with(
            "SetPosition2", pytest.approx(0.01), pytest.approx(0.02), 0.0,
        )

    def test_auto_lettering_picks_next_unused_letter(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        tag_b, _ = _datum_tag(fake_sw, "db", label="B")
        _chain_datum_tags((tag_a, None), (tag_b, None))
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        new_tag, _ = _datum_tag(fake_sw, "tnew", label="C")
        fake_sw.ActiveDoc.set_return("InsertDatumTag2", new_tag)

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert result["data"]["label"] == "C"
        fake_sw.call_log.assert_called_with("SetLabel", "C")

    @pytest.mark.parametrize("fill_upto,expected", [
        ("H", "J"),  # A..H filled -- I is reserved, next is J
        ("N", "P"),  # A..H,J..N filled -- O is reserved, next is P
        ("P", "R"),  # A..H,J..N,P filled -- Q is reserved, next is R
    ])
    def test_auto_lettering_skips_reserved_letters(self, tool_sw, fill_upto, expected):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        used = [
            chr(c) for c in range(ord("A"), ord(fill_upto) + 1)
            if chr(c) not in {"I", "O", "Q"}
        ]
        tags = [_datum_tag(fake_sw, f"d{letter}", label=letter) for letter in used]
        _chain_datum_tags(*tags)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tags[0][0])
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        new_tag, _ = _datum_tag(fake_sw, "tnew", label=expected)
        fake_sw.ActiveDoc.set_return("InsertDatumTag2", new_tag)

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "x": 0, "y": 0,
        })

        assert result["success"] is True, result
        assert result["data"]["label"] == expected

    @pytest.mark.parametrize("reserved_letter", ["I", "O", "Q"])
    def test_explicit_reserved_letter_rejected(self, tool_sw, reserved_letter):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "label": reserved_letter,
            "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        # An explicit label is pure input-shape validation -- rejected before
        # `list_datums`'s document walk (GetFirstView) or InsertDatumTag2 run.
        assert not fake_sw.call_log.calls_to("GetFirstView")
        assert not fake_sw.call_log.calls_to("InsertDatumTag2")

    def test_label_too_long_rejected_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "label": "ABC", "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetFirstView")
        assert not fake_sw.call_log.calls_to("InsertDatumTag2")

    def test_style_maps_to_display_style_enum(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        tag, _ = _datum_tag(fake_sw, "t1", label="A")
        fake_sw.ActiveDoc.set_return("InsertDatumTag2", tag)

        result = dispatch("add_datum_feature", {
            "view_name": "Drawing View1", "entity": _entity(), "label": "A",
            "x": 0, "y": 0, "style": "square",
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetDisplayStyle", False, 1)


# Hardcoded, independent of `_GTOL_SYMBOLS` -- the dossier's own 14 `IGTOL`
# library tokens (docs/api/03-annotations.md's GD&T section: "ANGULAR, CIRC,
# CONC, CYL, FLAT, LPROF, PARA, PERP, POSI, SPROF, SRUN, STRAIGHT, SYMMETRY,
# TRUN"). Asserting against this literal table, rather than parametrizing
# directly over `_GTOL_SYMBOLS.items()`, is what makes AC1 ("all 14 symbols
# map to the dossier-documented values") an actual regression guard instead
# of a tautology that a mismatched production mapping couldn't fail.
_EXPECTED_GTOL_TOKENS = {
    "straightness": "STRAIGHT",
    "flatness": "FLAT",
    "circularity": "CIRC",
    "cylindricity": "CYL",
    "profile_of_a_line": "LPROF",
    "profile_of_a_surface": "SPROF",
    "angularity": "ANGULAR",
    "perpendicularity": "PERP",
    "parallelism": "PARA",
    "position": "POSI",
    "concentricity": "CONC",
    "symmetry": "SYMMETRY",
    "circular_runout": "SRUN",
    "total_runout": "TRUN",
}


class TestAddGtolSymbolMapping:
    def test_expected_table_covers_exactly_the_14_dossier_symbols(self):
        assert set(_EXPECTED_GTOL_TOKENS) == set(_GTOL_SYMBOLS)
        assert len(_EXPECTED_GTOL_TOKENS) == 14

    @pytest.mark.parametrize("symbol_key,token", sorted(_EXPECTED_GTOL_TOKENS.items()))
    def test_symbol_maps_to_dossier_token(self, tool_sw, symbol_key, token):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        datums = None if symbol_key in ("flatness", "straightness", "circularity", "cylindricity") \
            else ["A"]
        if datums:
            tag_a, _ = _datum_tag(fake_sw, "da", label="A")
            view1.set_return("v1.GetFirstDatumTag", tag_a)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": symbol_key,
            "tolerance": 0.4, "datums": datums,
        })

        assert result["success"] is True, result
        assert fake_sw.call_log.arg_of("SetFrameSymbols2", 1) == f"<IGTOL-{token}>"

    def test_unknown_symbol_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "bogus", "tolerance": 0.1,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertGtol")


class TestAddGtolFrameContent:
    """Acceptance criteria: the frame-content string is asserted byte-for-byte
    against the call log for at least 4 cases, including a composite frame."""

    def test_position_with_three_datums_and_mmc_on_tolerance(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        tag_b, _ = _datum_tag(fake_sw, "db", label="B")
        tag_c, _ = _datum_tag(fake_sw, "dc", label="C")
        _chain_datum_tags((tag_a, None), (tag_b, None), (tag_c, None))
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4, "material_condition": "MMC",
            "datums": [
                {"letter": "a", "modifier": "MMC"},
                {"letter": "b", "modifier": "LMC"},
                "c",
            ],
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        assert log.arg_of("SetFrameSymbols2", 0) == 1
        assert log.arg_of("SetFrameSymbols2", 1) == "<IGTOL-POSI>"
        assert log.arg_of("SetFrameSymbols2", 2) is False
        assert log.arg_of("SetFrameSymbols2", 3) == "<MOD-MMC>"
        log.assert_called_with(
            "SetFrameValues2", 1, "0.4", "", "A<MOD-MMC>", "B<MOD-LMC>", "C",
        )

    def test_flatness_form_tolerance_has_no_datums(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.05,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with(
            "SetFrameValues2", 1, "0.05", "", "", "", "",
        )

    def test_rfs_modifier_on_single_datum(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "perpendicularity",
            "tolerance": 0.1, "datums": [{"letter": "A", "modifier": "RFS"}],
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with(
            "SetFrameValues2", 1, "0.1", "", "A<MOD-RFS>", "", "",
        )

    def test_lmc_material_condition_on_tolerance_itself(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "perpendicularity",
            "tolerance": 0.1, "datums": ["A"], "material_condition": "LMC",
        })

        assert result["success"] is True, result
        # TolMC1 is SetFrameSymbols2's 4th positional arg (index 3) -- see
        # docs/api/03-annotations.md's SetFrameSymbols2 Parameters table.
        fake_sw.call_log.assert_called_with(
            "SetFrameSymbols2", 1, "<IGTOL-PERP>", False, "<MOD-LMC>", False, "", "", "", "",
        )

    def test_integral_tolerance_formats_without_trailing_zero(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "circularity",
            "tolerance": 5,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with(
            "SetFrameValues2", 1, "5", "", "", "", "",
        )

    def test_composite_lower_segment_may_carry_no_datums(self, tool_sw):
        """In a composite FCF the upper segment is the pattern-locating
        control (PLTZF) and carries the datum references; the lower
        feature-relating segment (FRTZF) legally carries none when it controls
        only the pattern-internal relationship. Applying the upper segment's
        at-least-one-datum rule to it rejects a standard ASME Y14.5 callout."""
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4, "datums": ["A"],
            "composite": {"tolerance": 0.1},
        })

        assert result["success"] is True, result
        values_calls = fake_sw.call_log.calls_to("SetFrameValues2")
        assert values_calls[1].args == (2, "0.1", "", "", "", "")

    def test_composite_lower_segment_still_rejects_datums_on_a_form_tolerance(self, tool_sw):
        """The form-tolerance prohibition is not relaxed alongside it: a
        flatness callout can never reference a datum, in either segment."""
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.4, "composite": {"tolerance": 0.1, "datums": ["A"]},
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertGtol")

    def test_composite_frame_writes_two_stacked_rows(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        tag_a, _ = _datum_tag(fake_sw, "da", label="A")
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=tag_a)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4, "datums": ["A"],
            "composite": {"tolerance": 0.1, "datums": ["A"]},
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        symbol_calls = log.calls_to("SetFrameSymbols2")
        values_calls = log.calls_to("SetFrameValues2")
        assert len(symbol_calls) == 2
        assert len(values_calls) == 2
        assert symbol_calls[0].args[0] == 1
        assert symbol_calls[0].args[1] == "<IGTOL-POSI>"
        assert symbol_calls[1].args[0] == 2
        assert symbol_calls[1].args[1] == ""
        assert values_calls[0].args == (1, "0.4", "", "A", "", "")
        assert values_calls[1].args == (2, "0.1", "", "A", "", "")
        assert result["data"]["composite_frame"]["gcs"] == ""
        assert result["data"]["composite_frame"]["tol1"] == "0.1"

        # Dossier: "Call order matters: SetFrameSymbols2 must be called
        # before SetFrameValues2 for a given frame" -- and each frame's
        # pair must be contiguous (frame 1 fully written before frame 2
        # starts), not interleaved.
        names = [
            n for n in log.ordered_names() if n in ("SetFrameSymbols2", "SetFrameValues2")
        ]
        assert names == [
            "SetFrameSymbols2", "SetFrameValues2", "SetFrameSymbols2", "SetFrameValues2",
        ]


class TestAddGtolDatumValidation:
    def test_position_without_datum_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertGtol")

    def test_flatness_with_datum_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.05, "datums": ["A"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertGtol")

    def test_missing_datum_letter_on_drawing_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4, "datums": ["Z"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "Z" in result["message"]
        assert not fake_sw.call_log.calls_to("InsertGtol")

    def test_unknown_material_condition_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.1, "material_condition": "bogus",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_too_many_datums_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "position",
            "tolerance": 0.4, "datums": ["A", "B", "C", "D"],
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"


class TestAddGtolLeaderAndPosition:
    def test_leader_true_selects_entity_before_insert(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.1,
        })

        assert result["success"] is True, result
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("InsertGtol")

    def test_leader_false_skips_selection(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.1, "leader": False,
        })

        assert result["success"] is True, result
        assert not fake_sw.call_log.calls_to("SelectByID2")
        assert fake_sw.call_log.calls_to("InsertGtol")

    def test_x_y_sets_position_via_annotation(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.1, "x": 15, "y": 25,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with(
            "SetPosition2", pytest.approx(0.015), pytest.approx(0.025), 0.0,
        )

    def test_projected_zone_calls_set_ptz_height2(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        view1 = _view(fake_sw, "v1", "Sheet1", first_datum_tag=None)
        fake_sw.ActiveDoc.set_return("GetFirstView", view1)
        gtol, _ann = _gtol(fake_sw, "g1")
        fake_sw.ActiveDoc.set_return("InsertGtol", gtol)

        result = dispatch("add_gtol", {
            "view_name": "Drawing View1", "entity": _entity(), "symbol": "flatness",
            "tolerance": 0.1, "projected_zone": 50,
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("SetPTZHeight2", 1, 1, True, "50")


class TestAddDatumTarget:
    def test_creates_datum_target_and_sets_position(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _prep_view(fake_sw)
        target, _ann = _datum_target(fake_sw, "dt1")
        fake_sw.ActiveDoc.Extension.set_return("InsertDatumTargetSymbol3", target)

        result = dispatch("add_datum_target", {
            "view_name": "Drawing View1", "entity": _entity(kind="face"),
            "label": "a1", "area_type": "circle", "size": 3, "x": 5, "y": 10,
        })

        assert result["success"] is True, result
        log = fake_sw.call_log
        log.assert_called_with(
            "InsertDatumTargetSymbol3", "a1", "", "", 1, False,
            pytest.approx(0.003), 0.0, "3", "", True, 0, 0, False, True, True, 0,
        )
        log.assert_called_with(
            "SetPosition2", pytest.approx(0.005), pytest.approx(0.01), 0.0,
        )

    def test_unknown_area_type_rejects_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("add_datum_target", {
            "view_name": "Drawing View1", "entity": _entity(kind="face"),
            "label": "a1", "area_type": "triangle", "size": 3, "x": 0, "y": 0,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("InsertDatumTargetSymbol3")
