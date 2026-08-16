"""
Regression tests for solidworks_mcp.automation.features (FeatureOperations),
exercised through `SolidWorksAutomation` bound to the fake COM harness.

extrude_sketch/cut_extrude both route through `_close_and_select_sketch` ->
`_find_last_sketch`, which walks `doc.FirstFeature` / `feat.GetNextFeature`
with bare attribute access (`while feat is not None`). `FakeComObject`
cannot satisfy `is None` on a bare, unscripted access (see
testing/fake_com.py's module docstring), so a scripted sketch feature must
be installed via raw property assignment (`doc.FirstFeature = feat1`, which
stores the literal value rather than a wrapper) -- not `set_return`, which
only resolves for explicit `()` calls or `==`/`bool()` comparisons.

# KNOWN (production, not the harness): `_find_last_sketch`/`_get_sketch_info`
# and `list_features` walk `FirstFeature`/`GetNextFeature` with bare,
# uncalled attribute access and no `callable(...)` guard, whereas
# `server.py::_list_features_fixed` guards the same walk with
# `feat = feat.GetNextFeature; if callable(feat): feat = feat()`. This
# module's own v4.0 header notes FirstFeature/GetNextFeature are a property
# in some SolidWorks versions and a method in others -- on a version where
# they're method-like, these unguarded walks would get back a bound method
# (never `None`) and never terminate. Not fixed here per this task's scope.
# Against the fake, the same walk is bounded by `_MAX_CHAIN_DEPTH` (it exits
# via the walk's bare `except:`), so it fails fast instead of hanging;
# `_install_profile_sketch` below scripts a real, terminating one-sketch tree.
"""

import pytest

from solidworks_mcp.testing.fake_com import FakeComObject


def _install_profile_sketch(fake_sw, name="Sketch1"):
    """Wire `doc.FirstFeature` to a single ProfileFeature named `name`,
    terminating the GetNextFeature walk after one iteration."""
    doc = fake_sw.ActiveDoc
    feat1 = fake_sw.new_object("feat1")
    feat1.GetTypeName2 = "ProfileFeature"
    feat1.Name = name
    feat1.GetNextFeature = None
    doc.FirstFeature = feat1
    doc.Extension.set_return("SelectByID2", True)
    return feat1


class TestExtrudeSketch:
    def test_happy_path_converts_mm_to_meters(self, automation, fake_sw):
        _install_profile_sketch(fake_sw)
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureExtrusion2", object())

        result = automation.extrude_sketch(depth=10, unit="mm")

        assert result["success"] is True
        assert result["data"]["sketch_name"] == "Sketch1"
        # D1 (depth) is the 6th positional arg to FeatureExtrusion2.
        assert fake_sw.call_log.arg_of("FeatureExtrusion2", 5) == pytest.approx(0.01)

    def test_no_sketch_found_fails(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.FirstFeature = None  # no ProfileFeature in the tree

        result = automation.extrude_sketch(depth=10, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "No sketch found" in result["message"]

    def test_com_returns_none_for_all_extrude_methods_fails(self, automation, fake_sw):
        _install_profile_sketch(fake_sw)
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureExtrusion2", None)
        doc.FeatureManager.set_return("FeatureExtrusion3", None)

        result = automation.extrude_sketch(depth=10, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestCutExtrude:
    def test_happy_path_converts_mm_to_meters(self, automation, fake_sw):
        _install_profile_sketch(fake_sw)
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureCut3", object())

        result = automation.cut_extrude(depth=10, unit="mm")

        assert result["success"] is True
        # D1 (depth) is the 6th positional arg to FeatureCut3.
        assert fake_sw.call_log.arg_of("FeatureCut3", 5) == pytest.approx(0.01)

    def test_com_returns_none_for_all_cut_methods_fails(self, automation, fake_sw):
        _install_profile_sketch(fake_sw)
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureCut3", None)
        doc.FeatureManager.set_return("FeatureCut4", None)

        result = automation.cut_extrude(depth=10, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"


class TestFilletEdges:
    def test_happy_path_converts_mm_to_meters(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureFillet3", object())

        result = automation.fillet_edges(radius=2, unit="mm")

        assert result["success"] is True
        # Radius is the 2nd positional arg to FeatureFillet3.
        assert fake_sw.call_log.arg_of("FeatureFillet3", 1) == pytest.approx(0.002)

    def test_com_returns_none_for_all_fillet_methods_fails(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.FeatureManager.set_return("FeatureFillet3", None)
        doc.FeatureManager.set_return("SimpleFillet", None)

        result = automation.fillet_edges(radius=2, unit="mm")

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
