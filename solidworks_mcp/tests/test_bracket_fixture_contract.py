"""Tests for the shared bracket-fixture helpers extracted in sw-ja4.

`solidworks_mcp/testing/bracket_geometry.py` and `pack_examples.py` are the
one place `scripts/make_test_geometry.py`, `scripts/validate_on_windows.py`,
and `solidworks_mcp/tests/integration/` agree on the generated fixture's
geometry and on how a shipped `docs/packs/` example gets retargeted at it.
Every consumer only runs on Windows with SolidWorks attached, so without
these the extracted helpers would have no coverage on any platform CI
actually runs.
"""
from __future__ import annotations

import json

import pytest

from solidworks_mcp.testing import bracket_geometry as geom
from solidworks_mcp.testing.pack_examples import PACKS_DIR, load_example_pack


class TestGeometryContract:
    def test_halves_are_derived_from_the_base_dimensions(self):
        # The whole point of the module: consumers can't drift from the
        # generator by hardcoding a stale half.
        assert geom.HALF_WIDTH_MM == geom.BASE_WIDTH_MM / 2
        assert geom.HALF_DEPTH_MM == geom.BASE_DEPTH_MM / 2

    def test_the_untouched_corners_avoid_the_fillet_and_chamfer(self):
        # make_test_geometry fillets (+X, +Z) and chamfers (-X, -Z); the
        # picking targets must be the other two corners.
        assert geom.CORNER_BOTTOM_RIGHT == (geom.HALF_WIDTH_MM, -geom.HALF_DEPTH_MM)
        assert geom.CORNER_TOP_LEFT == (-geom.HALF_WIDTH_MM, geom.HALF_DEPTH_MM)

    def test_the_face_center_clears_every_mounting_hole(self):
        hole_x = geom.HALF_WIDTH_MM - geom.HOLE_INSET_MM
        hole_z = geom.HALF_DEPTH_MM - geom.HOLE_INSET_MM
        center_x, center_z = geom.FACE_CENTER
        assert abs(center_x - hole_x) > geom.HOLE_RADIUS_MM
        assert abs(center_z - hole_z) > geom.HOLE_RADIUS_MM

    @pytest.mark.parametrize("kind", ["vertex", "edge", "face"])
    def test_entity_translates_view_local_coordinates_into_sheet_space(self, kind):
        assert geom.entity(kind, 5.0, -3.0) == {
            "kind": kind,
            "x": geom.PART_VIEW_X + 5.0,
            "y": geom.PART_VIEW_Y - 3.0,
        }

    def test_the_two_view_origins_do_not_overlap(self):
        # The part and assembly views share a sheet in the validation sweep.
        assert (geom.PART_VIEW_X, geom.PART_VIEW_Y) != (geom.ASSEMBLY_VIEW_X, geom.ASSEMBLY_VIEW_Y)


class TestLoadExamplePack:
    def test_retargets_output_model_paths_and_drops_annotations(self, tmp_path):
        output = tmp_path / "out.slddrw"
        spec = load_example_pack(
            "assembly_with_bom",
            model_path="C:/models/bracket_assembly.sldasm",
            output_path=output,
            drawing_template="C:/templates/drawing.drwdot",
        )

        assert spec["output"] == str(output)
        assert spec["drawing_template"] == "C:/templates/drawing.drwdot"
        sheet = spec["sheets"][0]
        assert sheet["model_path"] == "C:/models/bracket_assembly.sldasm"
        assert sheet["views"][0]["model_path"] == "C:/models/bracket_assembly.sldasm"
        assert sheet["annotations"] == []

    def test_retargets_every_sheet_and_every_model_view(self, tmp_path):
        # multi_sheet_section_detail has two sheets, each with a model view
        # and a derived one. Leaving any model view on the example's
        # placeholder path would fail on a machine that has no such file;
        # the derived views have no model_path and must not gain one.
        spec = load_example_pack(
            "multi_sheet_section_detail",
            model_path="C:/models/bracket.sldprt",
            output_path=tmp_path / "o.slddrw",
        )

        assert len(spec["sheets"]) > 1, "fixture should exercise more than one sheet"
        derived_views = 0
        for sheet in spec["sheets"]:
            assert sheet["model_path"] == "C:/models/bracket.sldprt"
            assert sheet["annotations"] == []
            for view in sheet["views"]:
                if "model_path" in view:
                    assert view["model_path"] == "C:/models/bracket.sldprt"
                else:
                    derived_views += 1
        assert derived_views, "derived views should keep deriving from their parent view"

    def test_keeps_the_examples_own_template_when_none_is_found(self, tmp_path):
        # find_template() returns None off Windows / on an install with no
        # matching template; the example's own value has to survive that.
        original = json.loads((PACKS_DIR / "assembly_with_bom.json").read_text(encoding="utf-8"))
        spec = load_example_pack(
            "assembly_with_bom", model_path="m.sldasm", output_path=tmp_path / "o.slddrw",
        )
        assert spec["drawing_template"] == original["drawing_template"]

    def test_keeps_the_sheet_tables_that_need_no_entity_picks(self, tmp_path):
        spec = load_example_pack(
            "assembly_with_bom", model_path="m.sldasm", output_path=tmp_path / "o.slddrw",
        )
        assert spec["sheets"][0].get("tables"), "the BOM table should survive retargeting"

    def test_never_writes_back_to_the_shipped_example(self, tmp_path):
        example = PACKS_DIR / "assembly_with_bom.json"
        before = example.read_text(encoding="utf-8")

        spec = load_example_pack(
            "assembly_with_bom", model_path="m.sldasm", output_path=tmp_path / "o.slddrw",
        )
        spec["sheets"][0]["name"] = "mutated by the caller"

        assert example.read_text(encoding="utf-8") == before
        # And each call re-parses, so one caller's mutation can't leak.
        fresh = load_example_pack(
            "assembly_with_bom", model_path="m.sldasm", output_path=tmp_path / "o.slddrw",
        )
        assert fresh["sheets"][0]["name"] != "mutated by the caller"
