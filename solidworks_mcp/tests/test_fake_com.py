"""
Tests for the recording fake-COM harness (`solidworks_mcp.testing.fake_com`).
"""

import pytest

from solidworks_mcp.testing.fake_com import (
    _MAX_CHAIN_DEPTH,
    Call,
    CallLog,
    FakeComHarnessError,
    FakeComObject,
    FakeSldWorks,
    _ScriptRegistry,
)


def root_object():
    """A fresh, standalone graph root with its own registry and log."""
    return FakeComObject(scripts=_ScriptRegistry(), log=CallLog(), path="root", name="root")


# ============================================================================
# Auto-vivification and the property-vs-method duality
# ============================================================================

class TestAutoVivify:
    def test_unknown_attribute_does_not_raise(self):
        obj = root_object()
        assert obj.Whatever is not None

    def test_deep_chain_auto_vivifies(self):
        obj = root_object()
        # doc.SketchManager.InsertSketch(True) style chaining
        result = obj.SketchManager.InsertSketch(True)
        assert result is not None

    def test_repeated_attribute_access_returns_same_child(self):
        obj = root_object()
        assert obj.SketchManager is obj.SketchManager

    def test_attribute_used_as_value_and_as_callable(self):
        obj = root_object()
        obj.set_return("GetTypeName2", "RefPlane")

        as_value = obj.GetTypeName2
        as_call = obj.GetTypeName2()

        assert as_value == "RefPlane"
        assert as_call == "RefPlane"
        assert callable(obj.GetTypeName2)

    def test_unscripted_attribute_is_callable_and_truthy(self):
        obj = root_object()
        feat = obj.FirstFeature
        assert callable(feat)
        assert bool(feat) is True
        assert feat is not None

    def test_explicitly_assigned_child_is_never_depth_capped(self):
        """The cap guards auto-vivification only -- a hand-assigned value is
        deliberate scripting, however deep it sits."""
        node = root_object()
        for _ in range(_MAX_CHAIN_DEPTH):
            node = node.Next  # now sitting exactly at the cap
        node.Terminator = None
        assert node.Terminator is None
        with pytest.raises(FakeComHarnessError):
            node.SomethingUnscripted


class TestRunawayChainCap:
    """`automation/features.py` walks `while feat is not None: feat =
    feat.GetNextFeature` with bare, uncalled access. No scripted value can
    make that terminate (`is None` is an identity check), so auto-vivify
    depth is capped instead of spinning until the process is killed."""

    def test_unguarded_walk_terminates_instead_of_hanging(self):
        obj = root_object()

        feat = obj.FirstFeature
        seen = 0
        while feat is not None:
            seen += 1
            assert seen <= _MAX_CHAIN_DEPTH + 2, "depth cap failed to bound the walk"
            try:
                feat = feat.GetNextFeature
            except FakeComHarnessError:
                break

        assert seen <= _MAX_CHAIN_DEPTH + 1

    def test_bare_except_at_the_call_site_still_catches_the_cap(self):
        """Production's walks break out via a bare `except:`, which catches
        `BaseException` -- that is what turns the cap into a clean loop exit
        rather than a crash escaping through the tool handler."""
        obj = root_object()
        node = obj
        for _ in range(_MAX_CHAIN_DEPTH + 1):
            try:
                node = node.GetNextFeature
            except:  # mirrors automation/features.py's walk exactly
                break
        else:
            pytest.fail("chain never hit the depth cap")


# ============================================================================
# set_return / set_sequence / set_raises
# ============================================================================

class TestSetReturn:
    def test_scripted_return_by_bare_name(self):
        obj = root_object()
        obj.set_return("CreateCircle", "circle-1")
        assert obj.SketchManager.CreateCircle(0.01, 0.02, 0, 0.03, 0.02, 0) == "circle-1"

    def test_scripted_return_by_type_qualified_name(self):
        obj = root_object()
        obj.tag("IDrawingDoc")
        view_obj = object()
        obj.set_return("IDrawingDoc.CreateDrawViewFromModelView3", view_obj)

        assert obj.CreateDrawViewFromModelView3("Sheet1", "*Front", 0, 0, 0) is view_obj

    def test_exact_path_key_is_most_specific(self):
        obj = root_object()
        obj.set_return("InsertSketch", "generic")
        obj.SketchManager.set_return("root.SketchManager.InsertSketch", "specific")

        assert obj.SketchManager.InsertSketch(True) == "specific"

    def test_set_return_is_reusable_across_multiple_calls(self):
        obj = root_object()
        obj.set_return("GetType", 1)
        assert obj.GetType() == 1
        assert obj.GetType() == 1


class TestSetSequence:
    def test_successive_calls_return_successive_values(self):
        obj = root_object()
        feat2 = object()
        obj.set_sequence("GetNextFeature", ["feat2", feat2, None])

        assert obj.GetNextFeature() == "feat2"
        assert obj.GetNextFeature() is feat2
        assert obj.GetNextFeature() is None

    def test_sequence_exhaustion_raises_harness_error(self):
        obj = root_object()
        obj.set_sequence("Foo", [1])
        obj.Foo()
        with pytest.raises(FakeComHarnessError):
            obj.Foo()

    def test_sequence_exhaustion_survives_an_except_exception_call_site(self):
        """The whole point of `FakeComHarnessError` being a `BaseException`:
        `automation/` wraps every COM call in `except Exception`, which would
        otherwise turn an exhausted script into a plausible error-path result
        and a test that passes for the wrong reason."""
        obj = root_object()
        obj.set_sequence("Foo", [])
        with pytest.raises(FakeComHarnessError):
            try:
                obj.Foo()
            except Exception:  # mirrors the automation layer's call sites
                pytest.fail("harness error was swallowed by `except Exception`")

    def test_property_style_peek_does_not_consume_sequence(self):
        obj = root_object()
        obj.set_sequence("Foo", ["a", "b"])

        # Touching the attribute without calling it should not advance the
        # sequence.
        assert obj.Foo == "a"
        assert obj.Foo == "a"
        assert obj.Foo() == "a"
        assert obj.Foo() == "b"


class TestSetRaises:
    def test_raises_on_call(self):
        obj = root_object()
        obj.SketchManager.set_raises("InsertSketch", RuntimeError("no active sketch"))

        with pytest.raises(RuntimeError, match="no active sketch"):
            obj.SketchManager.InsertSketch(True)

    def test_raises_does_not_fire_on_bare_attribute_access(self):
        obj = root_object()
        obj.set_raises("Foo", RuntimeError("boom"))
        # Merely referencing the attribute should not raise -- only calling it.
        _ = obj.Foo


# ============================================================================
# CallLog
# ============================================================================

class TestCallLog:
    def test_records_positional_args_in_order(self):
        obj = root_object()
        obj.SketchManager.CreateLine(0.01, 0.02, 0, 0.03, 0.02, 0)

        call = obj.call_log.assert_called_with("CreateLine", 0.01, 0.02, 0, 0.03, 0.02, 0)
        assert isinstance(call, Call)
        assert call.args == (0.01, 0.02, 0, 0.03, 0.02, 0)

    def test_arg_of(self):
        obj = root_object()
        obj.SketchManager.CreateCircle(0.025, 0.05, 0, 0.05, 0.05, 0)
        assert obj.call_log.arg_of("CreateCircle", 0) == 0.025
        assert obj.call_log.arg_of("CreateCircle", 1) == 0.05

    def test_ordered_names_reflects_call_order_not_attribute_access_order(self):
        obj = root_object()
        obj.SketchManager.InsertSketch(True)
        obj.SketchManager.CreateCircle(0, 0, 0, 1, 0, 0)

        assert obj.call_log.ordered_names() == ["InsertSketch", "CreateCircle"]

    def test_calls_to_only_returns_actual_invocations(self):
        obj = root_object()
        _ = obj.Name  # bare attribute access, never called
        obj.Name()

        matches = obj.call_log.calls_to("Name")
        assert len(matches) == 1
        assert matches[0].args == ()

    def test_assert_called_with_raises_when_never_called(self):
        obj = root_object()
        with pytest.raises(AssertionError):
            obj.call_log.assert_called_with("Never", 1, 2)

    def test_assert_called_with_raises_on_arg_mismatch(self):
        obj = root_object()
        obj.Foo(1, 2)
        with pytest.raises(AssertionError):
            obj.call_log.assert_called_with("Foo", 9, 9)

    def test_attribute_only_access_is_recorded_with_none_args(self):
        obj = root_object()
        _ = obj.SketchManager
        access = [c for c in obj.call_log.calls if c.name == "SketchManager"][0]
        assert access.args is None
        assert access.kwargs is None


# ============================================================================
# Property set (`app.Visible = True`)
# ============================================================================

class TestPropertySet:
    def test_setattr_then_getattr_roundtrips_raw_value(self):
        obj = root_object()
        obj.Visible = True
        assert obj.Visible is True


# ============================================================================
# FakeSldWorks factory
# ============================================================================

class TestFakeSldWorksPart:
    def test_builds_active_doc_with_plausible_graph(self):
        app = FakeSldWorks("part")
        doc = app.ActiveDoc

        assert doc.GetType() == 1
        assert doc.Extension is not None
        assert doc.SelectionManager is not None
        assert doc.FeatureManager is not None
        assert doc.SketchManager is not None

    def test_first_feature_defaults_to_none(self):
        app = FakeSldWorks("part")
        # Explicit call form always resolves to the raw scripted value.
        assert app.ActiveDoc.FirstFeature() is None
        # Bare access hands back the dual-purpose wrapper; compare with ==.
        assert app.ActiveDoc.FirstFeature == None  # noqa: E711

    def test_default_feature_walk_terminates_without_scripting(self):
        """Mirrors server.py::_list_features_fixed's exact idiom: bare
        FirstFeature access (no callable-check) followed by a
        callable-checked GetNextFeature walk. Must not infinite-loop even
        with zero scripting beyond FakeSldWorks()'s own defaults."""
        app = FakeSldWorks("part")
        doc = app.ActiveDoc

        try:
            feat = doc.FirstFeature
        except AttributeError:
            feat = doc.FirstFeature()

        seen = 0
        while feat is not None:
            seen += 1
            assert seen < 10  # guard against a real hang if this regresses
            try:
                feat = feat.GetNextFeature
                if callable(feat):
                    feat = feat()
            except Exception:
                break

        assert seen <= 1

    def test_feature_walk_can_be_scripted(self):
        app = FakeSldWorks("part")
        doc = app.ActiveDoc
        feat1 = app.new_object("feat1")
        feat1.set_return("Name", "Boss-Extrude1")

        doc.set_sequence("FirstFeature", [feat1])
        feat1.set_sequence("GetNextFeature", [None])

        names = []
        feat = doc.FirstFeature()
        while feat is not None:
            names.append(feat.Name)
            feat = feat.GetNextFeature()

        assert names == ["Boss-Extrude1"]


class TestFakeSldWorksAssembly:
    def test_get_type_is_assembly(self):
        app = FakeSldWorks("assembly")
        assert app.ActiveDoc.GetType() == 2


class TestFakeSldWorksDrawing:
    def test_drawing_specific_members(self):
        app = FakeSldWorks("drawing")
        doc = app.ActiveDoc

        assert doc.GetType() == 3
        assert doc.GetSheetNames() == ["Sheet1"]
        assert doc.IGetViews() == []
        sheet = doc.GetCurrentSheet()
        assert sheet is not None

    def test_custom_sheet_names(self):
        app = FakeSldWorks("drawing", sheet_names=["Sheet1", "Sheet2"])
        assert app.ActiveDoc.GetSheetNames() == ["Sheet1", "Sheet2"]

    def test_invalid_doc_type_raises(self):
        with pytest.raises(ValueError):
            FakeSldWorks("blueprint")


# ============================================================================
# Realistic tool-shaped scenario (mirrors sketches.py draw_circle / server.py
# _list_features_fixed idioms)
# ============================================================================

class TestToolShapedUsage:
    def test_unit_conversion_style_call(self):
        """Mirrors automation/sketches.py::draw_circle: values passed to the
        COM call must already be in meters."""
        app = FakeSldWorks("part")
        doc = app.ActiveDoc

        radius_mm = 25
        radius_m = radius_mm * 0.001
        doc.SketchManager.CreateCircle(0, 0, 0, radius_m, 0, 0)

        assert doc.call_log.arg_of("CreateCircle", 3) == pytest.approx(0.025)

    def test_property_or_method_get_type_name_idiom(self):
        """Mirrors server.py::_list_features_fixed's
        `feat_type = feat.GetTypeName2; if callable(feat_type): feat_type = feat_type()`."""
        app = FakeSldWorks("part")
        feat = app.new_object("feat")
        feat.set_return("GetTypeName2", "RefPlane")

        feat_type = feat.GetTypeName2
        if callable(feat_type):
            feat_type = feat_type()

        assert feat_type == "RefPlane"

    def test_error_path_via_none_return(self):
        """Mirrors sketches.py: `if line is None: return error`."""
        app = FakeSldWorks("part")
        app.ActiveDoc.SketchManager.set_return("CreateLine", None)

        line = app.ActiveDoc.SketchManager.CreateLine(0, 0, 0, 1, 1, 0)
        assert line is None
