# Drawing Packs

A **pack** is a declarative description of a whole drawing -- sheets, views,
annotations, tables, balloons, custom properties, and the export step -- as one
JSON document. The `create_drawing_pack` tool validates it, compiles it to an
ordered list of calls onto this project's own registered tools, and runs them
in the right order with rebuilds inserted at the points where SOLIDWORKS
requires one. It exists so a caller (an LLM or a script) doesn't have to
hand-sequence 15-20 raw tool calls per part and get the rebuild timing right
itself.

The format is defined by plain dataclasses in
[`solidworks_mcp/pack/spec.py`](../solidworks_mcp/pack/spec.py) (`PackSpec` /
`SheetSpec` / `ViewSpec` / `AnnotationSpec` / `TableSpec`) -- this document is a
guide to that format, not a second source of truth for it. `PackSpec.validate()`
does purely structural/referential checks (required fields per `kind`, duplicate
names, dangling `parent`/`view` references) with no SOLIDWORKS involved, so a
spec can be authored and checked entirely offline before ever touching COM.

## Units

Every length and position in a pack (`x`, `y`, `offset`, `radius`, `cut_points`,
...) is in whatever unit the connected session is currently set to via the
`set_units` tool (millimeters by default) -- the same convention every
individual drawing tool follows. `PackSpec` itself has no unit field; the
compiler passes positions straight through to the primitive tools, which do
the unit conversion at the COM boundary.

## Top-level shape

```jsonc
{
  "drawing_template": "C:\\Templates\\part_drawing.drwdot",  // required
  "output": "C:\\Output\\bracket.slddrw",                    // required; used by the final save_drawing step
  "sheets": [ /* one or more SheetSpec */ ]
}
```

Each sheet:

```jsonc
{
  "name": "Sheet1",                 // required; must be unique within the pack
  "model_path": "C:\\Parts\\bracket.sldprt",  // required
  "paper_size": "A3",               // default "A3"
  "scale": {"num": 1, "denom": 2},  // default 1:1
  "auto_arrange": true,             // default true -- see "auto_arrange" below
  "views": [ /* ViewSpec */ ],
  "annotations": [ /* AnnotationSpec */ ],
  "tables": [ /* TableSpec */ ],
  "properties": {"Description": "Mounting Bracket"}  // custom document properties
}
```

`properties` is written via `set_custom_properties`, which targets the
*document's* custom property manager, not a per-sheet one -- in a multi-sheet
pack, the last sheet that declares a given key wins for the whole document.

### `auto_arrange`

By default, the compiler runs `auto_arrange_views` after inserting a sheet's
views, which repacks every root view into a grid and **overwrites** the `x`/`y`
each view declared. Set a sheet's `auto_arrange` to `false` to keep your
declared placement -- required whenever an annotation's `x`/`y` is positioned
relative to a specific view location (see `multi_sheet_section_detail.json`
below, which places two views manually so `SectionA`/`DetailB` land where the
sheet expects them).

## Views (`ViewSpec`)

`kind` discriminates which fields apply:

| `kind` | Creates a named view? | Required fields (beyond `kind`) |
| --- | --- | --- |
| `model` | yes | `name`, `model_path` |
| `projected` | yes | `name`, `parent`, `direction` |
| `section` | yes | `name`, `parent`, `cut_points` |
| `detail` | yes | `name`, `parent`, `center_x`, `center_y`, `radius` |
| `broken_out` | yes | `name`, `parent`, `profile_points` |
| `break` | no (mutates `target` in place) | `target`, `position1`, `position2` |
| `crop` | no (mutates `target` in place) | `target`, `profile_points` |

`model` is the only kind that doesn't reference another view -- every
`projected`/`section`/`detail`/`broken_out` view's `parent` must name a view
already defined earlier in the same sheet (or another sheet's `model` view, for
cross-sheet detail/section references). `break`/`crop` don't create a new
addressable view; they modify the view named in `target`.

## Annotations (`AnnotationSpec`)

| `kind` | Required fields (beyond `kind`, `view`) |
| --- | --- |
| `note` | `text` |
| `gtol` | `entity`, `symbol`, `tolerance` |
| `datum_feature` | `entity`, `label` |
| `datum_target` | `entity`, `label`, `area_type`, `size` |
| `surface_finish` | `entity`, `symbol_type` |
| `balloon` | `entity` |

`entity` (not needed for `note`) attaches the annotation to something in
`view`: `{"kind": "edge" | "face" | "vertex" | "component", "x": ..., "y": ...}`
-- the same shape the COM-facing tools use to select via a sheet-space point.

## Tables (`TableSpec`)

| `kind` | Required fields (beyond `kind`) |
| --- | --- |
| `bom` | `view` |
| `hole` | `view` |
| `revision` | (none) |
| `weldment_cutlist` | `view` |

**Known limitation:** a `hole` table has no spec field for its required datum
origin, so `create_drawing_pack` always anchors it at the view origin `(0, 0)`
-- a real per-hole-table datum still requires editing the table afterward with
`set_table_anchor`.

## Execution order

For each sheet, in the order the compiler emits steps:

1. Create the sheet (`add_sheet`) -- the first sheet is a rename
   (`rename_sheet`) of the template's own default sheet instead, since that
   sheet already exists once the template loads.
2. `set_sheet_properties` / `set_sheet_scale`.
3. Insert every view (`insert_model_view`, `insert_projected_view`, ...),
   parents before children.
4. `auto_arrange_views`, unless the sheet set `auto_arrange: false`.
5. **Rebuild** (`rebuild_document`, forced) -- dimension values and view
   geometry are stale until this runs.
6. Insert annotations.
7. Insert tables.
8. **Rebuild** again -- BOM quantities and balloon numbers are stale until
   this runs.
9. `update_table`, then balloons (`auto_balloon_view`/`add_balloon`).
10. `set_custom_properties`.

Once every sheet is processed, `save_drawing` runs once against `output`.

`create_drawing_pack` takes two extra options: `on_error` (`"abort"`, the
default -- stop at the first failed step; or `"continue"` -- run every
remaining step and report every failure) and `dry_run` (`true` to compile and
return the step list under `data.steps` without executing anything, useful for
inspecting what a spec *would* do before running it against a real session).

## `create_drawing_pack` vs. the individual primitives

Use `create_drawing_pack` when you're building a sheet (or a whole
multi-sheet drawing) from scratch and can describe the end state
declaratively -- it gets the rebuild phasing and per-sheet ordering right for
you, and `dry_run` lets you review the exact call sequence before it touches a
real document.

Reach for the individual tools (`add_sheet`, `insert_model_view`, `add_note`,
`rebuild_document`, ...) directly instead when:

- You're making a one-off edit to a drawing that already exists (e.g. adding
  one more balloon, or repositioning a single table) -- there's no whole-sheet
  spec to write for that.
- The sequence you need branches on something a static spec can't express
  (e.g. "insert a section view only if the model has an internal cavity,
  determined by inspecting the model first").
- You're exploring interactively and want to see each step's result before
  deciding the next one, rather than committing to a full plan up front.

The two compose: a pack can be built with `create_drawing_pack`, and then
touched up afterward with individual tool calls (or vice versa -- hand-build a
sheet, then use `dry_run` against a spec that describes further sheets you
want appended the same way).

## Worked examples

All three live under [`docs/packs/`](packs/) as complete, valid `PackSpec`
JSON files.

### `single_part.json` -- one part, three orthographic views, GD&T

A single sheet with a front view plus two projected views (top, right), a
general note, a datum feature, and a flatness callout.

```json
{
  "drawing_template": "C:\\Templates\\part_drawing.drwdot",
  "output": "C:\\Output\\bracket.slddrw",
  "sheets": [
    {
      "name": "Sheet1",
      "model_path": "C:\\Parts\\bracket.sldprt",
      "paper_size": "A3",
      "scale": {"num": 1, "denom": 2},
      "views": [
        {
          "kind": "model",
          "name": "FrontView",
          "model_path": "C:\\Parts\\bracket.sldprt",
          "orientation": "*Front",
          "x": 100,
          "y": 150
        },
        {
          "kind": "projected",
          "name": "TopView",
          "parent": "FrontView",
          "direction": "up",
          "offset": 60
        },
        {
          "kind": "projected",
          "name": "RightView",
          "parent": "FrontView",
          "direction": "right",
          "offset": 60
        }
      ],
      "annotations": [
        {
          "kind": "note",
          "view": "FrontView",
          "x": 200,
          "y": 20,
          "text": "ALL DIMENSIONS IN MM\nUNLESS OTHERWISE SPECIFIED"
        },
        {
          "kind": "datum_feature",
          "view": "FrontView",
          "entity": {"kind": "edge", "x": 90, "y": 140},
          "label": "A",
          "x": 95,
          "y": 130
        },
        {
          "kind": "gtol",
          "view": "FrontView",
          "entity": {"kind": "face", "x": 100, "y": 150},
          "symbol": "flatness",
          "tolerance": 0.05,
          "x": 110,
          "y": 155
        }
      ],
      "tables": [],
      "properties": {
        "Description": "Mounting Bracket"
      }
    }
  ]
}
```

### `assembly_with_bom.json` -- assembly, isometric view, balloons, BOM

One isometric view of an assembly, three component balloons, and a top-level
BOM table.

```json
{
  "drawing_template": "C:\\Templates\\asm_drawing.drwdot",
  "output": "C:\\Output\\gearbox_asm.slddrw",
  "sheets": [
    {
      "name": "Sheet1",
      "model_path": "C:\\Assemblies\\gearbox.sldasm",
      "paper_size": "B",
      "scale": {"num": 1, "denom": 1},
      "views": [
        {
          "kind": "model",
          "name": "IsoView",
          "model_path": "C:\\Assemblies\\gearbox.sldasm",
          "orientation": "*Isometric",
          "x": 150,
          "y": 150
        }
      ],
      "annotations": [
        {
          "kind": "balloon",
          "view": "IsoView",
          "entity": {"kind": "component", "x": 120, "y": 140},
          "x": 100,
          "y": 170,
          "style": "circular",
          "text_content": "item_number"
        },
        {
          "kind": "balloon",
          "view": "IsoView",
          "entity": {"kind": "component", "x": 160, "y": 160},
          "x": 190,
          "y": 190,
          "style": "circular",
          "text_content": "item_number"
        },
        {
          "kind": "balloon",
          "view": "IsoView",
          "entity": {"kind": "component", "x": 140, "y": 120},
          "x": 130,
          "y": 90,
          "style": "circular",
          "text_content": "item_number"
        }
      ],
      "tables": [
        {
          "kind": "bom",
          "view": "IsoView",
          "name": "BomTable1",
          "x": 220,
          "y": 250,
          "bom_type": "top_level"
        }
      ],
      "properties": {
        "Description": "Gearbox Assembly"
      }
    }
  ]
}
```

### `multi_sheet_section_detail.json` -- two sheets, section + detail views

Demonstrates `auto_arrange: false` (both sheets place their views by hand) and
cross-sheet structure: sheet 1 has a front view plus a full section view;
sheet 2 has a top view plus a circular detail view.

```json
{
  "drawing_template": "C:\\Templates\\part_drawing.drwdot",
  "output": "C:\\Output\\housing.slddrw",
  "sheets": [
    {
      "name": "Sheet1",
      "model_path": "C:\\Parts\\housing.sldprt",
      "paper_size": "A2",
      "scale": {"num": 1, "denom": 1},
      "auto_arrange": false,
      "views": [
        {
          "kind": "model",
          "name": "FrontView",
          "model_path": "C:\\Parts\\housing.sldprt",
          "orientation": "*Front",
          "x": 120,
          "y": 150
        },
        {
          "kind": "section",
          "name": "SectionA",
          "parent": "FrontView",
          "cut_points": [[80, 100], [80, 220]],
          "x": 260,
          "y": 150,
          "label": "A",
          "section_type": "full"
        }
      ],
      "annotations": [],
      "tables": [],
      "properties": {}
    },
    {
      "name": "Sheet2",
      "model_path": "C:\\Parts\\housing.sldprt",
      "paper_size": "A2",
      "scale": {"num": 2, "denom": 1},
      "auto_arrange": false,
      "views": [
        {
          "kind": "model",
          "name": "TopView",
          "model_path": "C:\\Parts\\housing.sldprt",
          "orientation": "*Top",
          "x": 120,
          "y": 150
        },
        {
          "kind": "detail",
          "name": "DetailB",
          "parent": "TopView",
          "center_x": 140,
          "center_y": 160,
          "radius": 8,
          "x": 260,
          "y": 150,
          "label": "B",
          "style": "circle"
        }
      ],
      "annotations": [],
      "tables": [],
      "properties": {}
    }
  ]
}
```

## Tools referenced in this document

<!-- registered-tools:start -->
`create_drawing_pack`, `add_sheet`, `rename_sheet`, `set_sheet_properties`,
`set_sheet_scale`, `insert_model_view`, `insert_projected_view`,
`auto_arrange_views`, `rebuild_document`, `update_table`, `auto_balloon_view`,
`add_balloon`, `set_custom_properties`, `save_drawing`, `set_table_anchor`,
`set_units`, `add_note`.
<!-- registered-tools:end -->
