"""
Regression tests for the line format / drafting standard tools
(solidworks_mcp/tools/drawing_line_format.py: set_line_format,
get_line_format, apply_drafting_standard), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
same convention as test_tools_layers.py: exercise both the registry wiring
and the `DrawingOperations` automation methods, asserting COM call order/args
against the fake's call log.
"""

import json

from solidworks_mcp.constants_drawing import SwLineStyles, SwLineWeights
from solidworks_mcp.tools import dispatch


def _allow_selection(fake_sw, result=True):
    """Script `Extension.SelectByID2` to succeed (or fail), the shared
    entry point every entity-list `set_line_format` call resolves through."""
    fake_sw.ActiveDoc.Extension.set_return("SelectByID2", result)


class TestSetLineFormatEntityClass:
    def test_weight_and_style_set_document_defaults_in_order(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {
            "target": "visible", "weight": "thick", "style": "hidden",
        })

        assert result["success"] is True, result
        assert result["data"] == {"target": "visible", "weight": "thick", "style": "hidden"}
        calls = fake_sw.call_log.calls_to("SetUserPreferenceInteger")
        assert len(calls) == 2
        # weight (Thickness member, 0x35) is applied before style (Style
        # member, 0x36) -- see set_line_format's own body ordering.
        assert calls[0].args == (0x35, 0, int(SwLineWeights.swLW_THICK))
        assert calls[1].args == (0x36, 0, int(SwLineStyles.swLineHIDDEN))

    def test_each_entity_class_maps_to_its_own_preference_pair(self, tool_sw):
        fake_sw = tool_sw("drawing")
        expected = {
            "visible": (0x35, 0x36),
            "hidden": (0x37, 0x38),
            "section": (0x3D, 0x3E),
            "detail_circle": (0x3B, 0x3C),
            "dimension": (0x3F, 0x40),
            "construction": (0x41, 0x42),
        }
        for entity_class, (thickness_pref, style_pref) in expected.items():
            result = dispatch("set_line_format", {
                "target": entity_class, "weight": "normal", "style": "continuous",
            })
            assert result["success"] is True, result
            calls = fake_sw.call_log.calls_to("SetUserPreferenceInteger")
            assert calls[-2].args[0] == thickness_pref, entity_class
            assert calls[-1].args[0] == style_pref, entity_class

    def test_only_weight_given_leaves_style_untouched(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "hidden", "weight": "thin"})

        assert result["success"] is True, result
        assert result["data"] == {"target": "hidden", "weight": "thin"}
        calls = fake_sw.call_log.calls_to("SetUserPreferenceInteger")
        assert len(calls) == 1
        assert calls[0].args == (0x37, 0, int(SwLineWeights.swLW_THIN))

    def test_color_rejected_for_entity_class_target(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "visible", "color": "#FF0000"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "color" in result["message"]
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_default_style_rejected_for_entity_class_target(self, tool_sw):
        """DP_LineFont.htm documents every per-category style member as valid
        for swLineStyles_e 'except swLineDEFAULT' -- see the dossier's
        SetUserPreferenceInteger Gotchas."""
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "visible", "style": "default"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_unknown_style_lists_valid_styles(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "visible", "style": "dotted"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "continuous" in result["message"]
        assert "phantom" in result["message"]
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_unknown_entity_class_lists_valid_classes(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "bogus", "weight": "thin"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        for name in ("visible", "hidden", "section", "detail_circle", "dimension", "construction"):
            assert name in result["message"]
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_unknown_weight_lists_valid_weights(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "visible", "weight": "extra_thick"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "thick" in result["message"]
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_no_fields_given_is_invalid_input(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {"target": "visible"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_setuserpreferenceinteger_falsy_return_is_feature_error(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_return("SetUserPreferenceInteger", False)

        result = dispatch("set_line_format", {"target": "visible", "weight": "thin"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_style_failure_after_weight_succeeded_reports_weight_as_applied(self, tool_sw):
        """weight is applied first; if the follow-up style call then fails,
        the failure's own `data` must still say weight already landed --
        these are persistent document properties, not session state, so a
        caller retrying blind must not think nothing happened."""
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_sequence("SetUserPreferenceInteger", [True, False])

        result = dispatch("set_line_format", {
            "target": "visible", "weight": "thick", "style": "hidden",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["weight"] == "thick"
        assert "style" not in result["data"]


class TestGetLineFormat:
    def test_reads_back_weight_and_style_by_name(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_sequence(
            "GetUserPreferenceInteger",
            [int(SwLineStyles.swLineHIDDEN), int(SwLineWeights.swLW_THICK)],
        )

        result = dispatch("get_line_format", {"target": "hidden"})

        assert result["success"] is True, result
        assert result["data"]["target"] == "hidden"
        assert result["data"]["style"] == "hidden"
        assert result["data"]["weight"] == "thick"
        assert result["data"]["color"] is None
        calls = fake_sw.call_log.calls_to("GetUserPreferenceInteger")
        assert calls[0].args == (0x38, 0)  # style pref, read first
        assert calls[1].args == (0x37, 0)  # thickness pref, read second

    def test_unrecognized_code_falls_back_to_raw_int(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_sequence("GetUserPreferenceInteger", [99, 88])

        result = dispatch("get_line_format", {"target": "visible"})

        assert result["success"] is True, result
        assert result["data"]["style"] == 99
        assert result["data"]["weight"] == 88

    def test_entity_list_target_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("get_line_format", {"target": [{"kind": "edge", "x": 1, "y": 1}]})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetUserPreferenceInteger")

    def test_unknown_entity_class_lists_valid_classes(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("get_line_format", {"target": "nope"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "visible" in result["message"]


class TestSetLineFormatEntityList:
    def test_weight_style_color_applied_to_each_selected_entity(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _allow_selection(fake_sw)

        result = dispatch("set_line_format", {
            "target": [{"kind": "edge", "x": 1.0, "y": 2.0}, {"kind": "edge", "x": 3.0, "y": 4.0}],
            "weight": "thick2", "style": "chain_thick", "color": "#00FF00",
        })

        assert result["success"] is True, result
        assert result["data"]["applied"] == 2
        assert result["data"]["target_count"] == 2
        width_calls = fake_sw.call_log.calls_to("SetLineWidth")
        style_calls = fake_sw.call_log.calls_to("SetLineStyle")
        color_calls = fake_sw.call_log.calls_to("SetLineColor")
        assert len(width_calls) == len(style_calls) == len(color_calls) == 2
        assert width_calls[0].args == (int(SwLineWeights.swLW_THICK2),)
        # "chain_thick" -> Title-Cased display name "Chain Thick", per the
        # dossier's SetLineStyle Gotchas (StyleName is a display-name string).
        assert style_calls[0].args == ("Chain Thick",)
        # #00FF00 -> COLORREF 0x00BBGGRR = 0x00FF00 (green channel only).
        assert color_calls[0].args == (0x00FF00,)

    def test_view_name_activates_view_before_selecting(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _allow_selection(fake_sw)
        fake_sw.ActiveDoc.set_return("ActivateView", True)

        result = dispatch("set_line_format", {
            "target": [{"kind": "edge", "x": 1.0, "y": 1.0}],
            "weight": "thin", "view_name": "Drawing View1",
        })

        assert result["success"] is True, result
        fake_sw.call_log.assert_called_with("ActivateView", "Drawing View1")

    def test_selection_failure_is_skipped_and_reported_per_entity(self, tool_sw):
        fake_sw = tool_sw("drawing")
        _allow_selection(fake_sw, result=False)

        result = dispatch("set_line_format", {
            "target": [{"kind": "edge", "x": 1.0, "y": 1.0}],
            "weight": "thin",
        })

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["applied"] == 0
        assert result["data"]["entities"][0]["success"] is False
        assert not fake_sw.call_log.calls_to("SetLineWidth")

    def test_empty_entity_list_rejected(self, tool_sw):
        tool_sw("drawing")

        result = dispatch("set_line_format", {"target": [], "weight": "thin"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_malformed_entity_reference_rejected(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {
            "target": [{"kind": "bogus", "x": 1, "y": 1}], "weight": "thin",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_invalid_color_rejected_before_any_selection(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {
            "target": [{"kind": "edge", "x": 1, "y": 1}], "color": "not-a-color",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_unknown_style_rejected_before_any_selection(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("set_line_format", {
            "target": [{"kind": "edge", "x": 1, "y": 1}], "style": "dotted",
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "continuous" in result["message"]
        assert not fake_sw.call_log.calls_to("SelectByID2")


class TestApplyDraftingStandard:
    def test_applies_every_entry_and_reports_each(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "standard.json"
        standard.write_text(json.dumps({
            "visible": {"weight": "normal", "style": "continuous"},
            "hidden": {"weight": "thin", "style": "hidden"},
        }))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is True, result
        results = result["data"]["results"]
        assert set(results) == {"visible", "hidden"}
        assert results["visible"]["success"] is True
        assert results["hidden"]["success"] is True
        calls = fake_sw.call_log.calls_to("SetUserPreferenceInteger")
        assert len(calls) == 4

    def test_example_standard_file_parses_and_applies(self, tool_sw):
        """docs/drafting_standard.example.json is this format's own
        documentation -- it must exist and actually be usable."""
        tool_sw("drawing")
        from pathlib import Path
        example_path = Path(__file__).resolve().parents[2] / "docs" / "drafting_standard.example.json"
        assert example_path.exists(), example_path

        with open(example_path) as f:
            spec = json.load(f)
        assert set(spec) == {"visible", "hidden", "section", "detail_circle", "dimension", "construction"}

        result = dispatch("apply_drafting_standard", {"standard_file": str(example_path)})

        assert result["success"] is True, result
        assert set(result["data"]["results"]) == set(spec)
        assert all(r["success"] for r in result["data"]["results"].values())

    def test_unknown_entity_class_key_names_the_bad_key(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "bad.json"
        standard.write_text(json.dumps({"not_a_real_class": {"weight": "thin"}}))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "not_a_real_class" in result["message"]
        assert result["data"]["bad_key"] == "not_a_real_class"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_unknown_property_key_names_the_bad_key(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "bad.json"
        standard.write_text(json.dumps({"visible": {"weight": "thin", "color": "#FF0000"}}))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "color" in result["message"]
        assert result["data"]["bad_key"] == "color"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_bad_weight_value_rejected_before_any_entry_is_applied(self, tool_sw, tmp_path):
        """The values are resolved up front through the same
        `_resolve_class_line_format` `set_line_format` uses, so a typo in a
        later entry can't land the earlier entries' (persistent) document
        preferences first -- the "before any COM call" contract covers bad
        values, not just bad keys."""
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "bad.json"
        standard.write_text(json.dumps({
            "visible": {"weight": "normal"},
            "hidden": {"weight": "not_a_real_weight"},
        }))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert "not_a_real_weight" in result["message"]
        assert result["data"]["bad_key"] == "hidden"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_entry_with_neither_weight_nor_style_rejected(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "empty_entry.json"
        standard.write_text(json.dumps({"visible": {}}))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["bad_key"] == "visible"
        assert not fake_sw.call_log.calls_to("SetUserPreferenceInteger")

    def test_document_resolved_once_for_the_whole_file(self, tool_sw, tmp_path):
        """`get_drawing_doc` is three COM round-trips and the active document
        can't change between entries, so a six-class standard must not pay it
        six times."""
        fake_sw = tool_sw("drawing")
        standard = tmp_path / "standard.json"
        standard.write_text(json.dumps({
            "visible": {"weight": "normal"},
            "hidden": {"weight": "thin"},
            "section": {"weight": "thick"},
        }))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is True, result
        assert len(fake_sw.call_log.calls_to("SetUserPreferenceInteger")) == 3
        assert len(fake_sw.ActiveDoc.call_log.calls_to("GetType")) == 1

    def test_malformed_json_rejected(self, tool_sw, tmp_path):
        tool_sw("drawing")
        standard = tmp_path / "bad.json"
        standard.write_text("{not valid json")

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_missing_file_rejected(self, tool_sw, tmp_path):
        tool_sw("drawing")

        result = dispatch("apply_drafting_standard", {
            "standard_file": str(tmp_path / "does_not_exist.json"),
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"

    def test_partial_failure_reports_overall_failure(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.Extension.set_sequence("SetUserPreferenceInteger", [True, False])
        standard = tmp_path / "standard.json"
        standard.write_text(json.dumps({
            "visible": {"weight": "normal"},
            "hidden": {"weight": "thin"},
        }))

        result = dispatch("apply_drafting_standard", {"standard_file": str(standard)})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        results = result["data"]["results"]
        assert results["visible"]["success"] is True
        assert results["hidden"]["success"] is False
