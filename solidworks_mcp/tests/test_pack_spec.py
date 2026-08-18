"""
Regression tests for solidworks_mcp.pack.spec -- the declarative drawing-pack
spec dataclasses and their offline validator. No COM involved anywhere here
(see sw-wds.1); the compiler that lowers a validated PackSpec into ordered
DrawingOperations calls is a separate concern (sw-wds.2).
"""

import copy
import json
import pathlib

import jsonschema
import pytest

from solidworks_mcp.pack.spec import (
    AnnotationSpec,
    PackSpec,
    ScaleSpec,
    SheetSpec,
    TableSpec,
    ViewSpec,
    generate_schema,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "docs" / "packs"
SCHEMA_PATH = REPO_ROOT / "solidworks_mcp" / "pack" / "schema.json"

EXAMPLE_FILES = [
    EXAMPLES_DIR / "single_part.json",
    EXAMPLES_DIR / "assembly_with_bom.json",
    EXAMPLES_DIR / "multi_sheet_section_detail.json",
]


def _minimal_pack(**sheet_overrides) -> PackSpec:
    sheet = SheetSpec(name="Sheet1", model_path="C:\\p.sldprt", **sheet_overrides)
    return PackSpec(drawing_template="C:\\t.drwdot", output="C:\\o.slddrw", sheets=[sheet])


def _model_view(name="V1", **overrides) -> ViewSpec:
    kwargs = {"kind": "model", "name": name, "model_path": "C:\\p.sldprt"}
    kwargs.update(overrides)
    return ViewSpec(**kwargs)


class TestExamplePacks:
    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
    def test_example_loads_and_validates_clean(self, path):
        pack = PackSpec.from_json_file(str(path))
        assert pack.validate() == []

    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
    def test_example_round_trips_losslessly(self, path):
        """to_dict()/from_dict() must not lose data on a second trip --
        the example JSON itself may omit fields that carry defaults, so
        it's not compared directly against the fully-populated dict."""
        pack = PackSpec.from_json_file(str(path))
        once = pack.to_dict()
        twice = PackSpec.from_dict(once).to_dict()
        assert twice == once

    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
    def test_example_from_json_file_matches_from_dict(self, path):
        via_file = PackSpec.from_json_file(str(path))
        via_dict = PackSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert via_file.to_dict() == via_dict.to_dict()

    def test_all_three_examples_exist(self):
        assert len(EXAMPLE_FILES) == 3
        for path in EXAMPLE_FILES:
            assert path.is_file(), f"missing example pack: {path}"


class TestRoundTrip:
    def test_round_trip_empty_pack(self):
        pack = PackSpec(drawing_template="t.drwdot", output="o.slddrw", sheets=[])
        assert PackSpec.from_dict(pack.to_dict()).to_dict() == pack.to_dict()

    def test_round_trip_nested_sheet_and_view(self):
        pack = _minimal_pack(
            scale=ScaleSpec(num=1, denom=4),
            views=[_model_view(x=10, y=20)],
            annotations=[AnnotationSpec(kind="note", view="V1", text="hi", x=1, y=2)],
            tables=[TableSpec(kind="bom", view="V1")],
            properties={"Material": "Steel"},
        )
        restored = PackSpec.from_dict(pack.to_dict())
        assert restored.to_dict() == pack.to_dict()
        assert isinstance(restored.sheets[0].scale, ScaleSpec)
        assert isinstance(restored.sheets[0].views[0], ViewSpec)
        assert isinstance(restored.sheets[0].annotations[0], AnnotationSpec)
        assert isinstance(restored.sheets[0].tables[0], TableSpec)

    def test_to_dict_is_plain_json_serializable(self):
        pack = _minimal_pack(views=[_model_view()])
        json.dumps(pack.to_dict())  # must not raise

    def test_from_json_file(self, tmp_path):
        pack = _minimal_pack(views=[_model_view()])
        p = tmp_path / "pack.json"
        p.write_text(json.dumps(pack.to_dict()), encoding="utf-8")
        loaded = PackSpec.from_json_file(str(p))
        assert loaded.to_dict() == pack.to_dict()


class TestFromDictRejectsBadInput:
    """`generate_schema()` advertises `additionalProperties: false` and typed
    list fields, but nothing re-validates a spec against that schema server
    side -- so `from_dict` is the only thing standing between a malformed
    pack and a COM call. It used to accept both of these silently."""

    def test_unknown_field_is_rejected_not_dropped(self):
        with pytest.raises(TypeError, match="unknown field"):
            ScaleSpec.from_dict({"num": 2, "den": 1})

    def test_unknown_field_names_the_offender_and_the_alternatives(self):
        with pytest.raises(TypeError, match=r"ScaleSpec.*'den'.*denom"):
            ScaleSpec.from_dict({"num": 2, "den": 1})

    def test_unknown_nested_field_is_rejected(self):
        with pytest.raises(TypeError, match="unknown field"):
            PackSpec.from_dict({
                "drawing_template": "t.drwdot", "output": "o.slddrw",
                "sheets": [{"name": "S1", "model_path": "p.sldprt", "viewz": []}],
            })

    def test_dict_for_a_list_field_is_rejected(self):
        """`{"x": 1, "y": 2}` is iterable, so the unguarded comprehension
        turned it into `[["x"], ["y"]]` -- a 2-element list that sails
        through `validate()` and reaches CreateSectionViewAt5 as garbage."""
        with pytest.raises(TypeError, match="cut_points.*expected a list"):
            ViewSpec.from_dict({
                "kind": "section", "name": "S", "parent": "V1",
                "cut_points": {"x": 1, "y": 2},
            })

    def test_string_for_a_list_field_is_rejected(self):
        with pytest.raises(TypeError, match="profile_points.*expected a list"):
            ViewSpec.from_dict({
                "kind": "crop", "target": "V1", "profile_points": "abc",
            })

    def test_tuple_is_still_accepted_for_a_list_field(self):
        view = ViewSpec.from_dict({
            "kind": "crop", "target": "V1", "profile_points": ([0, 0], [1, 1]),
        })
        assert view.profile_points == [[0, 0], [1, 1]]


class TestSchema:
    def test_schema_json_is_valid_json(self):
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            schema = json.load(fh)
        assert schema["title"] == "PackSpec"

    def test_schema_json_is_valid_draft7_schema(self):
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft7Validator.check_schema(schema)

    def test_schema_json_matches_generator(self):
        """schema.json is generated, not hand-written -- this guards against
        the checked-in file drifting from the dataclasses it's derived from.
        Regenerate with scripts/generate_pack_schema.py."""
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            checked_in = json.load(fh)
        assert checked_in == generate_schema()

    def test_schema_covers_every_view_kind_field(self):
        schema = generate_schema()
        view_props = schema["$defs"]["ViewSpec"]["properties"]
        for expected in ("kind", "name", "parent", "target", "model_path", "cut_points", "profile_points"):
            assert expected in view_props

    def test_example_packs_validate_against_schema(self):
        schema = generate_schema()
        for path in EXAMPLE_FILES:
            data = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.validate(data, schema)

    def test_schema_rejects_unknown_properties(self):
        """additionalProperties: False on the dataclass-derived objects is
        what makes test_example_packs_validate_against_schema (and the
        round-trip AC) mean something -- otherwise a typo'd/extra key in an
        example pack would validate silently."""
        schema = generate_schema()
        data = json.loads((EXAMPLES_DIR / "single_part.json").read_text(encoding="utf-8"))
        data["totally_not_a_real_field"] = True
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)


class TestValidateErrorClasses:
    def test_unknown_view_kind(self):
        pack = _minimal_pack(views=[ViewSpec(kind="wat", name="V1")])
        errors = pack.validate()
        assert any("unknown view kind" in e for e in errors)

    def test_section_parent_not_defined_earlier(self):
        pack = _minimal_pack(
            views=[
                ViewSpec(
                    kind="section",
                    name="Sec1",
                    parent="Ghost",
                    cut_points=[[0, 0], [0, 1]],
                    x=1,
                    y=1,
                )
            ]
        )
        errors = pack.validate()
        assert any("parent view 'Ghost' is not defined earlier" in e for e in errors)

    def test_detail_parent_not_defined_earlier(self):
        pack = _minimal_pack(
            views=[
                ViewSpec(
                    kind="detail",
                    name="Det1",
                    parent="Ghost",
                    center_x=0,
                    center_y=0,
                    radius=1,
                    x=1,
                    y=1,
                )
            ]
        )
        errors = pack.validate()
        assert any("parent view 'Ghost' is not defined earlier" in e for e in errors)

    def test_parent_defined_later_in_same_sheet_still_fails(self):
        """Order matters -- a parent listed later in the same sheet's view
        list does not count as 'defined earlier'."""
        pack = _minimal_pack(
            views=[
                ViewSpec(kind="section", name="Sec1", parent="V1", cut_points=[[0, 0], [0, 1]], x=1, y=1),
                _model_view("V1"),
            ]
        )
        errors = pack.validate()
        assert any("parent view 'V1' is not defined earlier" in e for e in errors)

    def test_duplicate_view_names(self):
        pack = _minimal_pack(views=[_model_view("V1"), _model_view("V1")])
        errors = pack.validate()
        assert any("duplicate view name 'V1'" in e for e in errors)

    def test_duplicate_sheet_names(self):
        pack = PackSpec(
            drawing_template="t.drwdot",
            output="o.slddrw",
            sheets=[
                SheetSpec(name="Sheet1", model_path="p.sldprt"),
                SheetSpec(name="Sheet1", model_path="p.sldprt"),
            ],
        )
        errors = pack.validate()
        assert any("duplicate sheet name 'Sheet1'" in e for e in errors)

    def test_annotation_targets_undefined_view(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[AnnotationSpec(kind="note", view="Ghost", text="hi", x=0, y=0)],
        )
        errors = pack.validate()
        assert any("targets undefined view 'Ghost'" in e for e in errors)

    def test_gtol_references_undefined_datum(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="gtol",
                    view="V1",
                    entity={"kind": "face", "x": 0, "y": 0},
                    symbol="position",
                    tolerance=0.1,
                    datums=["Z"],
                )
            ],
        )
        errors = pack.validate()
        assert any("GTOL references undefined datum 'Z'" in e for e in errors)

    def test_gtol_datum_reference_as_object_with_letter(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="gtol",
                    view="V1",
                    entity={"kind": "face", "x": 0, "y": 0},
                    symbol="position",
                    tolerance=0.1,
                    datums=[{"letter": "Z", "modifier": "MMC"}],
                )
            ],
        )
        errors = pack.validate()
        assert any("GTOL references undefined datum 'Z'" in e for e in errors)

    def test_gtol_datum_defined_later_in_same_sheet_still_fails(self):
        """Order matters here too -- a datum_feature listed after the GTOL
        that references it does not count as 'defined'. The requirement text
        says 'undefined datum', but the compiler lowers annotations in list
        order and add_gtol requires the letter to already exist on the
        drawing, so 'not yet defined' is treated as undefined."""
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="gtol",
                    view="V1",
                    entity={"kind": "face", "x": 0, "y": 0},
                    symbol="position",
                    tolerance=0.1,
                    datums=["A"],
                ),
                AnnotationSpec(
                    kind="datum_feature",
                    view="V1",
                    entity={"kind": "edge", "x": 0, "y": 0},
                    label="A",
                    x=0,
                    y=0,
                ),
            ],
        )
        errors = pack.validate()
        assert any("GTOL references undefined datum 'A'" in e for e in errors)

    def test_gtol_datum_defined_earlier_is_valid(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="datum_feature",
                    view="V1",
                    entity={"kind": "edge", "x": 0, "y": 0},
                    label="A",
                    x=0,
                    y=0,
                ),
                AnnotationSpec(
                    kind="gtol",
                    view="V1",
                    entity={"kind": "face", "x": 0, "y": 0},
                    symbol="position",
                    tolerance=0.1,
                    datums=["A"],
                ),
            ],
        )
        assert pack.validate() == []

    def test_balloon_with_no_bom_on_sheet(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="balloon",
                    view="V1",
                    entity={"kind": "component", "x": 0, "y": 0},
                    x=0,
                    y=0,
                )
            ],
        )
        errors = pack.validate()
        assert any("balloon has no BOM table" in e for e in errors)

    def test_balloon_with_bom_on_sheet_is_valid(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[
                AnnotationSpec(
                    kind="balloon",
                    view="V1",
                    entity={"kind": "component", "x": 0, "y": 0},
                    x=0,
                    y=0,
                )
            ],
            tables=[TableSpec(kind="bom", view="V1")],
        )
        assert pack.validate() == []

    def test_missing_required_field_on_view(self):
        # No model_path on the view *or* the sheet -- the sheet-level value
        # is a legitimate fallback (see TestSheetModelPathFallback), so it
        # has to be absent from both for this to be an error.
        sheet = SheetSpec(name="Sheet1", views=[ViewSpec(kind="model", name="V1")])
        pack = PackSpec(drawing_template="C:\\t.drwdot", output="C:\\o.slddrw", sheets=[sheet])
        errors = pack.validate()
        assert any("missing required field 'model_path'" in e for e in errors)

    def test_missing_required_field_on_view_with_no_sheet_fallback(self):
        """A required view field the sheet cannot supply is still caught."""
        pack = _minimal_pack(views=[ViewSpec(kind="section", name="S1", parent="V1")])
        errors = pack.validate()
        assert any("missing required field 'cut_points'" in e for e in errors)

    def test_missing_required_field_on_pack(self):
        pack = PackSpec(drawing_template="", output="", sheets=[])
        errors = pack.validate()
        assert any("missing required field 'drawing_template'" in e for e in errors)
        assert any("missing required field 'output'" in e for e in errors)

    def test_missing_required_field_on_sheet(self):
        pack = PackSpec(
            drawing_template="t.drwdot",
            output="o.slddrw",
            sheets=[SheetSpec(name="Sheet1", model_path="")],
        )
        errors = pack.validate()
        assert any("missing required field 'model_path'" in e for e in errors)

    def test_unknown_annotation_kind(self):
        pack = _minimal_pack(
            views=[_model_view("V1")],
            annotations=[AnnotationSpec(kind="sparkle", view="V1")],
        )
        errors = pack.validate()
        assert any("unknown annotation kind" in e for e in errors)

    def test_unknown_table_kind(self):
        pack = _minimal_pack(tables=[TableSpec(kind="mystery")])
        errors = pack.validate()
        assert any("unknown table kind" in e for e in errors)

    def test_table_targets_undefined_view(self):
        pack = _minimal_pack(tables=[TableSpec(kind="bom", view="Ghost")])
        errors = pack.validate()
        assert any("targets undefined view 'Ghost'" in e for e in errors)

    def test_broken_out_requires_exactly_one_of_depth_and_depth_reference(self):
        pack = _minimal_pack(
            views=[
                _model_view("V1"),
                ViewSpec(
                    kind="broken_out",
                    name="BO1",
                    parent="V1",
                    profile_points=[[0, 0], [1, 0], [1, 1]],
                    depth=5,
                    depth_reference={"kind": "face", "x": 0, "y": 0},
                ),
            ]
        )
        errors = pack.validate()
        assert any("exactly one of 'depth'/'depth_reference'" in e for e in errors)


class TestValidatePassingCases:
    def test_valid_break_and_crop_reference_existing_target(self):
        pack = _minimal_pack(
            views=[
                _model_view("V1"),
                ViewSpec(kind="break", target="V1", position1=10, position2=20),
                ViewSpec(kind="crop", target="V1", profile_points=[[0, 0], [1, 0], [1, 1]]),
            ]
        )
        assert pack.validate() == []

    def test_valid_projected_and_broken_out_chain(self):
        pack = _minimal_pack(
            views=[
                _model_view("V1"),
                ViewSpec(kind="projected", name="V2", parent="V1", direction="up"),
                ViewSpec(
                    kind="broken_out",
                    name="BO1",
                    parent="V2",
                    profile_points=[[0, 0], [1, 0], [1, 1]],
                    depth=5,
                ),
            ]
        )
        assert pack.validate() == []

    def test_empty_pack_with_no_sheets_is_valid(self):
        pack = PackSpec(drawing_template="t.drwdot", output="o.slddrw", sheets=[])
        assert pack.validate() == []

    def test_multiple_sheets_scoped_view_namespaces_independently(self):
        """The same view name may be reused across different sheets --
        duplicate-name checking is scoped per sheet, not pack-wide."""
        pack = PackSpec(
            drawing_template="t.drwdot",
            output="o.slddrw",
            sheets=[
                SheetSpec(name="Sheet1", model_path="p.sldprt", views=[_model_view("V1")]),
                SheetSpec(name="Sheet2", model_path="p.sldprt", views=[_model_view("V1")]),
            ],
        )
        assert pack.validate() == []


class TestNoComImport:
    def test_spec_module_does_not_import_com_backend(self):
        spec_path = REPO_ROOT / "solidworks_mcp" / "pack" / "spec.py"
        text = spec_path.read_text(encoding="utf-8")
        assert "com_backend" not in text

    def test_spec_module_has_no_pywin32_or_com_backend_imports(self):
        import sys

        import solidworks_mcp.pack.spec as spec_mod

        module_names = {
            getattr(v, "__name__", "") for v in vars(spec_mod).values() if isinstance(v, type(sys))
        }
        assert not any("com_backend" in name or "win32" in name for name in module_names)


def test_validate_does_not_mutate_pack():
    pack = PackSpec.from_dict(json.loads((EXAMPLES_DIR / "single_part.json").read_text(encoding="utf-8")))
    before = copy.deepcopy(pack.to_dict())
    pack.validate()
    assert pack.to_dict() == before


class TestSheetModelPathFallback:
    """`SheetSpec.model_path` is a required field that nothing consumed: a
    caller who set it there (the obvious place) and omitted it on the model
    view got "missing required field 'model_path'" naming the *view*, while
    the value they did supply was discarded."""

    def test_model_view_may_omit_model_path_when_the_sheet_sets_it(self):
        pack = _minimal_pack(views=[ViewSpec(kind="model", name="V1")])
        assert pack.sheets[0].model_path  # supplied by _minimal_pack
        assert pack.validate() == []

    def test_view_model_path_still_wins_over_the_sheet(self):
        from solidworks_mcp.pack import compile as pack_compile

        pack = _minimal_pack(
            views=[ViewSpec(kind="model", name="V1", model_path="C:\\other.sldprt")]
        )
        step = next(s for s in pack_compile(pack) if s.tool == "insert_model_view")
        assert step.args["model_path"] == "C:\\other.sldprt"

    def test_sheet_model_path_reaches_the_compiled_step(self):
        from solidworks_mcp.pack import compile as pack_compile

        pack = _minimal_pack(views=[ViewSpec(kind="model", name="V1")])
        step = next(s for s in pack_compile(pack) if s.tool == "insert_model_view")
        assert step.args["model_path"] == pack.sheets[0].model_path


class TestAutoArrangeOptOut:
    """`auto_arrange_views` repacks every root view via `IView::Position`,
    overwriting each ViewSpec's declared x/y. It stays on by default, but a
    pack that places views by hand must be able to turn it off."""

    def _tools(self, pack):
        from solidworks_mcp.pack import compile as pack_compile

        return [s.tool for s in pack_compile(pack)]

    def test_auto_arrange_runs_by_default(self):
        pack = _minimal_pack(views=[_model_view()])
        assert pack.sheets[0].auto_arrange is True
        assert "auto_arrange_views" in self._tools(pack)

    def test_auto_arrange_can_be_turned_off(self):
        pack = _minimal_pack(views=[_model_view(x=10, y=20)])
        pack.sheets[0].auto_arrange = False
        assert "auto_arrange_views" not in self._tools(pack)

    def test_opting_out_keeps_every_other_step(self):
        pack = _minimal_pack(views=[_model_view(x=10, y=20)])
        with_arrange = self._tools(pack)
        pack.sheets[0].auto_arrange = False
        without = self._tools(pack)
        assert [t for t in with_arrange if t != "auto_arrange_views"] == without

    def test_auto_arrange_round_trips_through_json(self):
        pack = _minimal_pack(views=[_model_view()])
        pack.sheets[0].auto_arrange = False
        assert PackSpec.from_dict(pack.to_dict()).sheets[0].auto_arrange is False
