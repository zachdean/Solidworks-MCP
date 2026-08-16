---
interface: Multiple (IModelDocExtension, IView, IBomTableAnnotation, IDrawingDoc, ISheet, IRevisionTableAnnotation, IWeldmentCutListAnnotation, IHoleTableAnnotation, ITableAnnotation, IAnnotation)
min_methods: 14
status: complete
---

# Tables: BOM, balloons, hole tables, revision tables, weldment cut lists

Covers the table-annotation surface of the drawing API: inserting and reading Bill of
Materials (BOM) tables, inserting and configuring BOM balloons (manual and automatic),
inserting hole tables and revision tables, inserting weldment cut list tables, and the
`ITableAnnotation`/`IAnnotation` base-interface members every table type shares for
cell text access, row/column counts, and anchor/position control.

Several method names given by the source research issue turned out not to match the
current (SOLIDWORKS 2025) API surface. Each is documented below under its *real* name,
with the discrepancy called out explicitly in that record's Gotchas — summarized here
for a quick scan, following the same honesty convention established in
[`03-annotations.md`](03-annotations.md):

- `IView::InsertBOMBalloon` does not exist — `InsertBOMBalloon`/`InsertBOMBalloon2` live
  on `IModelDocExtension`, not `IView`. Confirmed by direct fetch of the `IView` URL
  returning no `helpContentData` title (a real 404, not a rendering artifact).
- `IView::AutoBalloon5` does not exist — the entire `AutoBalloon`/`AutoBalloon2`/`3`/`4`/`5`
  family lives on `IDrawingDoc`, not `IView`. Same 404 confirmation.
- `IDrawingDoc::InsertRevisionTable2` does not exist — the real, current method is
  `ISheet::InsertRevisionTable2`. Confirmed both by a direct 404 fetch of the
  `IDrawingDoc` URL and by a working fetch of the `ISheet` URL (title
  `"InsertRevisionTable2 Method (ISheet)"`), and independently corroborated by
  CodeStack's own worked macro, which calls `sheet.InsertRevisionTable2(...)`.
- `IModelDocExtension::InsertWeldmentCutlist` does not exist in any form (no
  `InsertWeldmentCutlist`, `InsertWeldmentCutList`, or `InsertCutList*` member on
  `IModelDocExtension` or `IDrawingDoc`). The real, current method for inserting a
  weldment cut list table is `IView::InsertWeldmentTable`, whose own worked example is
  titled "Insert Weldment Cut List Table" and whose return type is
  `WeldmentCutListAnnotation`. `IView::InsertWeldTable` is a different, unrelated
  method (a table of weld symbols, not a cut list) — see that record's Gotchas for the
  naming collision.
- `IBomTableAnnotation::GetTotalItemsCount` does not exist — confirmed by direct 404
  fetch. The real equivalent (inherited from the base `ITableAnnotation` interface) is
  the `TotalRowCount` property, documented below.
- `IBomTableAnnotation::SetItemNumber` does not exist — confirmed by direct 404 fetch,
  and independently corroborated by SOLIDWORKS forum threads stating there is no
  built-in API for renumbering BOM item numbers. A BOM table's "ITEM NO." column is an
  ordinary table cell; the real mechanism for changing it programmatically is
  `ITableAnnotation::Text2` (documented below), inherited by `IBomTableAnnotation`.
- `ITableAnnotation::GetCellText`/`SetCellText` do not exist — confirmed by direct 404
  fetch of both. The real, current cell-text accessor is the `Text`/`Text2` property
  pair (both real, documented below — `Text2` supersedes `Text` by adding an
  `IncludeHidden` parameter).
- `ITableAnnotation::Update` does not exist — confirmed by direct 404 fetch. Tables
  self-rebuild automatically whenever a cell's text changes; there is no explicit
  "commit" call. See `ITableAnnotation::Text2`'s Gotchas for the documented
  `IAnnotation::Visible = False` performance workaround for bulk cell edits instead.
- `ITableAnnotation::SetPosition` does not exist — confirmed by direct 404 fetch. Table
  position is set through the base annotation interface,
  `IAnnotation::SetPosition` (obtained via `ITableAnnotation::GetAnnotation`), not a
  table-specific method — documented below.
- `swTableAnnotationAnchorType_e` and `swHoleTableAnchorType_e` do not exist — confirmed
  absent from a full scan of the `SolidWorks.Interop.swconst` namespace index. Every
  `AnchorType` parameter/property across BOM, hole, weldment cut list, and revision
  tables (`IView::InsertBomTable6`, `IView::InsertHoleTable2`/`3`,
  `IView::InsertWeldmentTable`, `ISheet::InsertRevisionTable2`,
  `ITableAnnotation::AnchorType`) is explicitly documented as using the single enum
  `swBOMConfigurationAnchorType_e` instead — its name is BOM-specific but its actual
  use spans every table type.
- `swRevisionTableChangeType_e` does not exist — confirmed absent from the namespace
  index scan. `IRevisionTableAnnotation::AddRevision` takes a plain `String` (the
  revision designation itself, e.g. `"A"`), not an enum-typed "change type" — there is
  no enum in this area of the API.

`help.solidworks.com` blocks plain fetches (HTTP 403) without a browser-like
`User-Agent` header — see [`README.md`](README.md#canonical-source-urls) for the retry
convention used throughout. All non-existence claims above were verified with a
stricter two-part test (no `Function`/`Sub`/`Property <Name>(` syntax block **and** no
`"helpContentData":{"title":...}` on the fetched page) after discovering that the
page's embedded `"ErrorTitle":"This page cannot be found."` JSON string is present on
*every* page (part of a "next/previous topic" widget's own error-handling boilerplate)
and is therefore not by itself a reliable 404 signal.

## BOM tables

`IModelDocExtension::InsertBomTable3`/`IModelDocExtension::InsertBomTable4` and
`IView::InsertBomTable4`...`IView::InsertBomTable6` are **both real, current, and not
duplicates of each other** — they solve different problems:

- **`IModelDocExtension::InsertBomTable4`** is called on a **part or assembly
  document's** `IModelDocExtension` (via `IModelDoc2::Extension`), with no drawing view
  or sheet involved at all. SOLIDWORKS's own worked example
  ("Insert and Show BOM Table in Assembly") opens an `.sldasm` file directly and calls
  `swModelDocExt.InsertBomTable4(TemplateName, 0, 1, BomType, Configuration, False, swNumberingType_Detailed, True, True)`
  — there is no `AnchorType` parameter because there is no drawing sheet anchor point
  to attach to.
- **`IView::InsertBomTable6`** is called on a specific **drawing view's** `IView`, and
  is anchored either to the drawing sheet format's BOM anchor point
  (`UseAnchorPoint = True`) or to an explicit `X`/`Y` sheet-space location, via
  `AnchorType` (`swBOMConfigurationAnchorType_e`).

Use `IModelDocExtension::InsertBomTable4` when scripting from a part/assembly context
with no open drawing; use `IView::InsertBomTable6` when scripting from a drawing and
targeting a specific view.

### IModelDocExtension::InsertBomTable4

- **Interface:** IModelDocExtension
- **Method:** InsertBomTable4
- **Minimum SW version:** SOLIDWORKS 2024 FCS, Revision Number 32

**Signature:**

```vb
Function InsertBomTable4( _
   ByVal TemplateName As System.String, _
   ByVal X As System.Integer, _
   ByVal Y As System.Integer, _
   ByVal BomType As System.Integer, _
   ByVal ConfigurationName As System.String, _
   ByVal Hidden As System.Boolean, _
   ByVal IndentedNumberingType As System.Integer, _
   ByVal DetailedCutList As System.Boolean, _
   ByVal DissolvePartLevelRows As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| TemplateName | String | n/a | Yes | Path and name of the BOM table template (see Gotchas for the `.sldbomtbt` convention) | |
| X | Integer | **unspecified — see Gotchas** | Yes | X coordinate for BOM table placement | |
| Y | Integer | **unspecified — see Gotchas** | Yes | Y coordinate for BOM table placement | |
| BomType | Integer | n/a | Yes | Type of BOM table | `swBomType_e` |
| ConfigurationName | String | n/a | Yes | Name of the configuration for this BOM table — must be an explicit, valid configuration name; the system does **not** default to the Default configuration for an empty string (see Gotchas) | |
| Hidden | Boolean | n/a | Yes | `True` to hide the BOM table, `False` to show it | |
| IndentedNumberingType | Integer | n/a | Yes | Numbering type; valid only if `BomType = swBomType_e.swBomType_Indented` | `swNumberingType_e` |
| DetailedCutList | Boolean | n/a | Yes | `True` to show the detailed cut list, `False` to not | |
| DissolvePartLevelRows | Boolean | n/a | Yes | `True` to dissolve part-level rows, `False` to not; valid only if `DetailedCutList = True` | |

**Returns:** `System.Object`, actually an `IBomTableAnnotation`. No explicit failure
value documented; per Remarks, if `BomType` is parts-only or indented and
`ConfigurationName` is invalid, "the BOM is not created" (return value in that case is
unstated — treat as unverified and null-check).

**Prior selection required:** None — this is called directly on a part/assembly
document's `IModelDocExtension`, obtained via `IModelDoc2::Extension`. Unlike the
`IView` family below, it does not act on drawing-view or sheet selection state at all.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertBomTable4.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertBomTable3.html (predecessor, for the parameter-superset comparison — `InsertBomTable3` lacks `DissolvePartLevelRows` and returns a strongly-typed `BomTableAnnotation` rather than `System.Object`; SOLIDWORKS 2013 FCS, Revision 21.0)
- https://help.solidworks.com/2025/english/api/sldworksapi/Insert_and_Show_BOM_Table_in_Assembly_Example_VB.htm (worked VBA example, cited above, that settles the assembly-vs-drawing-view usage split — confirms this method is called on an assembly document's `Extension`, with `X=0, Y=1`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms `IView` independently has its own `InsertBomTable`...`InsertBomTable6` family — see next record)

**status:** verified

**Gotchas:**
- **`X`/`Y` are declared `System.Integer`, not `System.Double`** — unlike every other
  X/Y placement parameter in this dossier (`IView::InsertBomTable6`,
  `InsertHoleTable2/3`, `InsertWeldmentTable`, `ISheet::InsertRevisionTable2`, all of
  which use `System.Double`). The help page states no units for `X`/`Y` on this method
  at all, and given the anomalous `Integer` type, this dossier does **not** apply the
  README's meters-by-convention default here — treat the unit as unverified and
  confirm empirically before relying on a specific coordinate space (it may be a
  small-integer placement code rather than a metric coordinate, per the worked
  example's `X=0, Y=1` call).
- `TemplateName` follows the shared `.sldbomtbt` convention: BOM table templates live
  in `<SOLIDWORKS_install_dir>\lang\<language>\` with a `.sldbomtbt` extension (e.g.
  `bom-standard.sldbomtbt`), and "the template and table must be of the same type."
  The page does not state whether an empty string falls back to a default template or
  what happens with an invalid path — both are unverified; the worked example always
  passes an explicit full path.
- `ConfigurationName` must be an explicit, valid configuration name — passing `""`
  does **not** fall back to the Default configuration (explicit Remarks statement,
  contrast with some other SW API calls that do default empty strings).
- Supersedes `InsertBomTable`, `InsertBomTable2`, `InsertBomTable3` (all still present
  and independently fetchable/current per the `IModelDocExtension_members.html` index,
  but each a strict parameter-subset of `InsertBomTable4`) — always prefer
  `InsertBomTable4` for new code on this interface.
- Distinct from, and not a version-numbering overlap with, `IView::InsertBomTable4`
  (below) — the two interfaces maintain **independent** version-suffix sequences for
  methods with the same base name; `IModelDocExtension`'s sequence tops out at `4`,
  `IView`'s at `6`.

---

### IView::InsertBomTable6

- **Interface:** IView
- **Method:** InsertBomTable6
- **Minimum SW version:** SOLIDWORKS 2025 FCS, Revision Number 33 (brand new in the
  target release of this dossier)

**Signature:**

```vb
Function InsertBomTable6( _
   ByVal UseAnchorPoint As System.Boolean, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal AnchorType As System.Integer, _
   ByVal BomType As System.Integer, _
   ByVal Configuration As System.String, _
   ByVal TableTemplate As System.String, _
   ByVal Hidden As System.Boolean, _
   ByVal IndentedNumberingType As System.Integer, _
   ByVal DetailedCutList As System.Boolean, _
   ByVal DissolvePartLevelRows As System.Boolean, _
   ByVal DisplayAsOneItem As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseAnchorPoint | Boolean | n/a | Yes | If `True` and the sheet format's BOM anchor point exists, insert at that point; if `False`, use `X`/`Y` instead | |
| X | Double | meters | Yes | X coordinate for BOM table placement (used only if `UseAnchorPoint = False`) | |
| Y | Double | meters | Yes | Y coordinate for BOM table placement (used only if `UseAnchorPoint = False`) | |
| AnchorType | Integer | n/a | Yes | Anchor type | `swBOMConfigurationAnchorType_e` |
| BomType | Integer | n/a | Yes | Type of BOM table | `swBomType_e` |
| Configuration | String | n/a | Yes | Name of the configuration for this BOM table; do **not** specify a configuration if `BomType = swBomType_TopLevelOnly` — use `IBomFeature::GetConfigurations`/`SetConfigurations` instead (see Gotchas) | |
| TableTemplate | String | n/a | Yes | Path and filename of the `.sldbomtbt` template (see Gotchas) | |
| Hidden | Boolean | n/a | Yes | `True` to hide the BOM table, `False` to show it | |
| IndentedNumberingType | Integer | n/a | Yes | Numbering type; valid only for `BomType = swBomType_e.swBomType_Indented` | `swNumberingType_e` |
| DetailedCutList | Boolean | n/a | Yes | `True` to show the detailed cut list | |
| DissolvePartLevelRows | Boolean | n/a | Yes | `True` to dissolve part-level rows; valid only when `DetailedCutList = True` | |
| DisplayAsOneItem | Boolean | n/a | Yes | `True` to group into one item number, `False` to display separately | |

**Returns:** `System.Object`, actually an `IBomTableAnnotation`. No explicit failure
value documented.

**Prior selection required:** None as a hard precondition — called directly on the
target `IView` object (the drawing view to attach the BOM table to), not on
`ISelectionMgr` state. Contrast with the older `IDrawingDoc`-level annotation-import
methods elsewhere in this API family that read "the currently selected view" — this
method's target view is the `IView` instance itself.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBomTable6.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBomTable5.html (predecessor, for the parameter-superset comparison — `InsertBomTable5` lacks `DisplayAsOneItem`; SOLIDWORKS 2024 FCS, Revision 32)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms the full `InsertBomTable`...`InsertBomTable6` lineage on `IView`, independent of `IModelDocExtension`'s own `1`...`4` lineage)

**status:** verified

**Gotchas:**
- Brand new in SOLIDWORKS 2025 (FCS, Revision 33) — the newest of the six
  `IView::InsertBomTable*` overloads. Prefer it over `InsertBomTable5` and earlier for
  new tool-layer code targeting 2025+; note that a caller supporting older SW versions
  needs to fall back to `InsertBomTable5` (2024+) or earlier.
- `TableTemplate` follows the same `.sldbomtbt` path convention as
  `IModelDocExtension::InsertBomTable4` above — `<SOLIDWORKS_install_dir>\lang\<language>\*.sldbomtbt`,
  and "the template and table must be of the same type." Empty-string/invalid-path
  fallback behavior is not documented on this page either — unverified.
- If `BomType = swBomType_e.swBomType_TopLevelOnly`, do **not** pass `Configuration` —
  use `IBomFeature::GetConfigurations`/`SetConfigurations` afterward instead (explicit
  Remarks statement, not documented further in this dossier).
- Returns an `IBomTableAnnotation`, the interface documented next in this dossier — the
  natural next call is typically `.BomFeature` to reach the owning `IBomFeature`.

## Reading a BOM table's contents

### IBomTableAnnotation::GetComponentsCount2

- **Interface:** IBomTableAnnotation
- **Method:** GetComponentsCount2
- **Minimum SW version:** SOLIDWORKS 2011 SP03, Revision Number 19.3

**Signature:**

```vb
Function GetComponentsCount2( _
   ByVal RowIndex As System.Integer, _
   ByVal Configuration As System.String, _
   ByRef ItemNumber As System.String, _
   ByRef PartNumber As System.String _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| RowIndex | Integer | n/a | Yes | Row in the BOM table to get the component count for; 0-based | |
| Configuration | String | n/a | Yes | Configuration for which to get the count in top-level-only BOMs; pass `""` for parts-only and indented BOMs | |
| ItemNumber | String (by ref, out) | n/a | Yes | Returns the item number of the row | |
| PartNumber | String (by ref, out) | n/a | Yes | Returns the part number of the row | |

**Returns:** `Integer` — number of components in the specified row for the specified
configuration.

**Prior selection required:** None. Called directly on an `IBomTableAnnotation`
obtained from `InsertBomTable4`/`InsertBomTable6`'s return value (or
`IBomFeature::GetTableAnnotations`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBomTableAnnotation~GetComponentsCount2.html

**status:** verified

**Gotchas:**
- Per its own Remarks, call this method **before** `IBomTableAnnotation::IGetComponents2`
  (or the non-`I`-prefixed `GetComponents2` below) to size the array that method
  returns — it is the sizing/counting half of a two-call pattern, mirroring
  `ISelectionMgr::GetSelectedObjectCount2` → `GetSelectedObject6` elsewhere in this
  API.
- `ItemNumber`/`PartNumber` are `ByRef` out-parameters in addition to the `Integer`
  return value — a caller must declare `String` locals to receive them; COM interop
  callers cannot ignore these the way a purely-functional return would allow.
- `IBomTableAnnotation::GetTotalItemsCount` does **not** exist (see this dossier's
  intro discrepancy list) — this method, plus `ITableAnnotation::TotalRowCount`
  (documented later), are the real ways to reason about a BOM table's size.

---

### IBomTableAnnotation::GetComponents2

- **Interface:** IBomTableAnnotation
- **Method:** GetComponents2
- **Minimum SW version:** SOLIDWORKS 2011 SP03, Revision Number 19.3

**Signature:**

```vb
Function GetComponents2( _
   ByVal RowIndex As System.Integer, _
   ByVal Configuration As System.String _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| RowIndex | Integer | n/a | Yes | Row in the BOM table where to get the components; 0-based | |
| Configuration | String | n/a | Yes | Configuration for which to get components in top-level-only BOMs; pass `""` for parts-only and indented BOMs | |

**Returns:** `System.Object` — array of the components (`IComponent2`) in the
specified row for the specified configuration.

**Prior selection required:** None. Call `GetComponentsCount2` first to size the
expected array (see that record's Gotchas).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBomTableAnnotation~GetComponents2.html

**status:** verified

**Gotchas:**
- Supersedes the now-obsolete `GetComponents` (no `2` suffix) — always prefer the `2`
  variant for new code.
- There is also an `IGetComponents2` member on this interface (the interface-qualified
  COM dispatch variant of the same method, matching the `I`-prefix pattern seen
  elsewhere in this API, e.g. `ISelectionMgr`'s `IGetSelectedObject`) — not a distinct
  overload.
- Return type is a late-bound `System.Object` array — cast/iterate as an object array
  of `IComponent2`, not a strongly-typed array.

---

### IBomTableAnnotation::BomFeature

- **Interface:** IBomTableAnnotation
- **Method:** BomFeature (property, read-only)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Property BomFeature As BomFeature
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — read-only property) | n/a | n/a | n/a | Getter takes no arguments | |

**Returns:** `IBomFeature` — pointer to the BOM feature that owns this table
annotation. This is the link back from the annotation object to the feature-tree
object that controls indentation, configuration grouping, numbering type,
`KeepCurrentItemNumbers`, `SequenceStartNumber`, and other BOM-wide settings not
exposed on `IBomTableAnnotation` itself.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBomTableAnnotation~BomFeature.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBomFeature_members.html (confirms the feature-level member surface reachable from this property, including `KeepCurrentItemNumbers`, `SequenceStartNumber`, `GetConfigurations`/`SetConfigurations`, `NumberingTypeOnIndentedBOM`)

**status:** verified

**Gotchas:**
- This is the canonical way to reach `IBomFeature` from an already-held
  `IBomTableAnnotation` (e.g. the object returned by `InsertBomTable4`/`6`) — there is
  no reverse path documented from a bare `IBomFeature` back to a specific view's table
  annotation other than `IBomFeature::GetTableAnnotations`.
- `IBomFeature::KeepCurrentItemNumbers` and `SequenceStartNumber` are the closest real
  API surface to "control BOM item numbering programmatically" — relevant context for
  the `SetItemNumber` non-existence discrepancy noted in this dossier's intro.

## Balloons

`IView::InsertBOMBalloon` does not exist — confirmed absent from a direct fetch (no
`helpContentData` title). The real, current interface for manual BOM balloon insertion
is `IModelDocExtension`, which has three related members:
`InsertBOMBalloon` (original, all parameters explicit), and `InsertBOMBalloon2`
(current, takes an `IBalloonOptions` object — not to be confused with
`IAutoBalloonOptions`, the *automatic*-balloon options object documented below).

### IModelDocExtension::InsertBOMBalloon

- **Interface:** IModelDocExtension — requested as `IView::InsertBOMBalloon`, which
  does not exist (see the section intro above)
- **Method:** InsertBOMBalloon
- **Minimum SW version:** SOLIDWORKS 2010 FCS, Revision Number 18.0

**Signature:**

```vb
Function InsertBOMBalloon( _
   ByVal Style As System.Integer, _
   ByVal Size As System.Integer, _
   ByVal UpperTextStyle As System.Integer, _
   ByVal UpperText As System.String, _
   ByVal LowerTextStyle As System.Integer, _
   ByVal LowerText As System.String, _
   ByVal CustomSize As System.Double, _
   ByVal ShowQuantity As System.Boolean, _
   ByVal QuantityPlacement As System.Short, _
   ByVal QuantityDenotationText As System.String _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Style | Integer | n/a | Yes | Balloon style | `swBalloonStyle_e` |
| Size | Integer | n/a | Yes | Balloon fit/size | `swBalloonFit_e` |
| UpperTextStyle | Integer | n/a | Yes | Style for the upper text (see Remarks) | `swBalloonTextContent_e` |
| UpperText | String | n/a | Yes | Upper text of the balloon | |
| LowerTextStyle | Integer | n/a | Yes | Style for the lower text; valid only when `Style = swBS_SplitCirc` | `swBalloonTextContent_e` |
| LowerText | String | n/a | Yes | Lower text of the balloon; valid only when `Style = swBS_SplitCirc` | |
| CustomSize | Double | meters (unverified — not stated on page) | Yes | User-defined balloon size; valid only when `Size = swBF_UserDef` | |
| ShowQuantity | Boolean | n/a | Yes | `True` to show quantity, `False` to not | |
| QuantityPlacement | Short | n/a | Yes | `0` = Left, `1` = Right, `2` = Top, `3` = Bottom | |
| QuantityDenotationText | String | n/a | Yes | Denotation text for quantity | |

**Returns:** `System.Object`, actually an `INote` (a balloon is a specialized note in
this API — see `INote::IsBomBalloon`/`GetBomBalloonText`/`SetBomBalloonText`).

**Prior selection required:** Yes — select the item (component instance, or a BOM
table row/entity) to balloon before calling, via `SelectByID2` or
`ISelectionMgr::AddSelectionListObject`. The page does not spell out the exact
selection type filter; treat as unverified and confirm the `Type` string empirically
(likely `"COMPONENT"` for an assembly instance).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertBOMBalloon.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBOMBalloon.html (direct fetch confirms no `helpContentData` title — this member does not exist on `IView`)

**status:** verified

**Gotchas:**
- **`IView::InsertBOMBalloon` does not exist** — confirmed by direct fetch. Any
  tool-layer code targeting that name is targeting a method that was never real.
- See `INote::PropertyLinkedText` for the link-string syntax usable with
  `UpperTextStyle`/`LowerTextStyle = swBalloonTextContent_e.swBalloonTextCustomProperties`
  (not documented further in this dossier).
- Superseded in practice (though not formally deprecated) by `InsertBOMBalloon2`
  (below), which takes a single `IBalloonOptions` object instead of ten positional
  parameters — prefer `InsertBOMBalloon2` for new code; this record is kept because it
  is the name closest to the source research issue's request and remains a real,
  current, callable member.

---

### IModelDocExtension::InsertBOMBalloon2

- **Interface:** IModelDocExtension
- **Method:** InsertBOMBalloon2
- **Minimum SW version:** SOLIDWORKS 2012 FCS, Revision Number 20.0

**Signature:**

```vb
Function InsertBOMBalloon2( _
   ByVal BalloonOptions As BalloonOptions _
) As Note
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| BalloonOptions | IBalloonOptions | n/a | Yes | Balloon options object (its own interface, not documented in full in this dossier — see Gotchas) | |

**Returns:** `INote` — the newly created balloon note.

**Prior selection required:** Yes — per the page's own Remarks recipe: (1) select the
item for which to create a BOM balloon, (2) call
`IModelDocExtension::CreateBalloonOptions` to create an `IBalloonOptions` object, (3)
set properties on it, (4) call this method with that object.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertBOMBalloon2.html

**status:** verified

**Gotchas:**
- `IBalloonOptions` (created via `IModelDocExtension::CreateBalloonOptions`) is a
  **different object** from `IAutoBalloonOptions` (created via
  `IDrawingDoc::CreateAutoBalloonOptions`, used by `AutoBalloon5` below) — one
  configures a single manually-placed balloon, the other configures a bulk
  automatic-balloon pass over a whole view/sheet. Not to be confused; this dossier
  does not fetch `IBalloonOptions`'s own member list in depth since the task's
  acceptance criteria specifically call out `IAutoBalloonOptions` for detailed
  property documentation (see the `AutoBalloon5` record below).
- The interop assembly also exposes this same method under an alternate member
  spelling, `InsertBomBalloon2` (lowercase "om"), per the `IModelDocExtension_members`
  index — this dossier treats it as the same method, not a separate overload;
  unverified whether this is a genuine second COM dispatch entry or a display
  artifact of the help site's own indexing.

## Automatic balloons and IAutoBalloonOptions

`IView::AutoBalloon5` does not exist — confirmed absent from a direct fetch (no
`helpContentData` title). The entire `AutoBalloon`...`AutoBalloon5` family lives on
`IDrawingDoc`.

### IDrawingDoc::AutoBalloon5

- **Interface:** IDrawingDoc — requested as `IView::AutoBalloon5`, which does not exist
  (see the section intro above)
- **Method:** AutoBalloon5
- **Minimum SW version:** SOLIDWORKS 2012 FCS, Revision Number 20.0

**Signature:**

```vb
Function AutoBalloon5( _
   ByVal BalloonOptions As AutoBalloonOptions _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| BalloonOptions | IAutoBalloonOptions | n/a | Yes | Auto-balloon options object — see the property table below | |

**Returns:** `System.Object` — array of the newly created `INote` balloons.

**Prior selection required:** Yes. Select one or more drawing **views** or **sheets**
before calling — if a sheet is selected, BOM balloons are automatically inserted for
every view on that sheet. Recipe per the page's own Remarks: (1) select the
view(s)/sheet(s), (2) call `IDrawingDoc::CreateAutoBalloonOptions` to create an
`IAutoBalloonOptions` object, (3) set its properties (table below), (4) call this
method with that object.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AutoBalloon5.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~AutoBalloon5.html (direct fetch confirms no `helpContentData` title — this member does not exist on `IView`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AutoBalloon4.html (predecessor, for the parameter-list-vs-options-object comparison below)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAutoBalloonOptions_members.html (full property list backing the table below)

**status:** verified

**Gotchas:**
- **`IView::AutoBalloon5` does not exist** — confirmed by direct fetch. The entire
  "autoballoon family" (`AutoBalloon` through `AutoBalloon5`) lives on `IDrawingDoc`.
- `AutoBalloon4` (predecessor, still current/fetchable) takes ten explicit positional
  parameters instead of an options object:
  `AutoBalloon4(Layout, IgnoreMultiple, Style, Size, UpperTextContent, UpperText, LowerTextContent, LowerText, Layername, BalloonsToFaces) As System.Object`.
  Every one of `AutoBalloon4`'s positional parameters accepts `-1` to mean "use the
  document default" — `AutoBalloon5`'s options-object properties do not document an
  equivalent per-property "use default" sentinel except where individually noted
  below. Prefer `AutoBalloon5` for new code; `AutoBalloon4`'s per-parameter defaults
  are reachable via `IModelDocExtension::GetUserPreferenceInteger`/`SetUserPreferenceInteger`
  with keys like `swUserPreferenceIntegerValue_e.swDetailingAutoBalloonLayout`,
  `swDetailingBOMBalloonStyle`, `swDetailingBOMBalloonFit`, `swDetailingBOMUpperText`,
  `swDetailingBOMLowerText` (documented per-property below, from each property's own
  Remarks).
- `BalloonsToFaces` (an `AutoBalloon4` parameter, `True` = attach to faces, `False` =
  attach to edges) has no directly-named equivalent property on `IAutoBalloonOptions`
  in the member list fetched for this dossier except `LeaderAttachmentToFaces` (listed
  in the property table below but not individually fetched in this pass) — treat as
  the likely but unverified `AutoBalloon5` equivalent.

**`IAutoBalloonOptions` properties** (object created via
`IDrawingDoc::CreateAutoBalloonOptions`; each row below individually fetched and
verified against its own SOLIDWORKS 2025 help page, all SOLIDWORKS 2012 FCS Revision
20.0 unless noted):

| Property | Type | Meaning | Enum ref |
| --- | --- | --- | --- |
| `Layout` | Integer | Balloon layout style; `-1` uses the document default (get/set default via `swUserPreferenceIntegerValue_e.swDetailingAutoBalloonLayout`) | `swBalloonLayoutType_e` |
| `Style` | Integer | Balloon style; `-1` uses the document default (`swDetailingBOMBalloonStyle`) | `swBalloonStyle_e` |
| `Size` | Integer | Balloon fit/size; `-1` uses the document default (`swDetailingBOMBalloonFit`) | `swBalloonFit_e` |
| `CustomSize` | Double | User-defined balloon size; valid only when `Size = swBalloonFit_e.swBF_UserDef` | |
| `UpperTextContent` | Integer | Upper-text content style; `-1` uses the document default (`swDetailingBOMUpperText`) | `swBalloonTextContent_e` |
| `UpperText` | String | Upper text of the balloons — can only be **read/written** via `INote::GetBomBalloonText`/`SetBomBalloonText` *after* the balloon is inserted, not meaningfully pre-set on the options object itself | |
| `LowerTextContent` | Integer | Lower-text content style; valid only when `Style = swBalloonStyle_e.swBS_SplitCirc`; `-1` uses the document default (`swDetailingBOMLowerText`) | `swBalloonTextContent_e` |
| `LowerText` | String | Lower text of the balloons; valid only when `Style = swBS_SplitCirc`; same post-insertion `INote` accessor caveat as `UpperText` | |
| `ItemOrder` | Integer | Item ordering for sequential numbering | `swBalloonItemNumbersOrder_e` (not independently fetched in this pass) |
| `ItemNumberStart` | Integer | Starting item number for the auto-balloon pass | |
| `ItemNumberIncrement` | Integer | Item number increment between successive balloons | |
| `IgnoreMultiple` | Boolean | `True` to balloon only one instance of a repeated item, `False` to balloon every instance | |
| `EditBalloons` | Boolean | `True` to apply the edit-balloon behavior configured by `EditBalloonOption`, `False` to not | |
| `EditBalloonOption` | Integer | Edit-balloon behavior; valid only when `EditBalloons = True` | `swEditBalloonOption_e` (not independently fetched in this pass) |
| `InsertMagneticLine` | Boolean | (Listed in the interface's member index; not individually fetched this pass — meaning inferred from name only, unverified) | |
| `LeaderAttachmentToFaces` | Boolean | (Listed in the interface's member index; not individually fetched this pass — likely `AutoBalloon4`'s `BalloonsToFaces` equivalent, unverified) | |
| `Layername` | String | (Listed in the interface's member index; not individually fetched this pass) | |
| `ReverseDirection` | Boolean | (Listed in the interface's member index; not individually fetched this pass) | |
| `FirstItem` | Integer/String | (Listed in the interface's member index; not individually fetched this pass) | |

Source (property list and individually-verified rows above):
https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAutoBalloonOptions_members.html
and each property's own page under
`SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAutoBalloonOptions~<Property>.html`
(`Layout`, `Style`, `Size`, `CustomSize`, `UpperTextContent`, `LowerTextContent`,
`UpperText`, `LowerText`, `ItemOrder`, `ItemNumberStart`, `ItemNumberIncrement`,
`IgnoreMultiple`, `EditBalloons`, `EditBalloonOption` were each individually fetched
and verified; the last five rows are members-index-only and marked unverified above
per this dossier's honesty convention — they were not individually fetched this pass).

## Hole tables

### IView::InsertHoleTable2

- **Interface:** IView
- **Method:** InsertHoleTable2
- **Minimum SW version:** SOLIDWORKS 2011 SP02, Revision Number 19.2

**Signature:**

```vb
Function InsertHoleTable2( _
   ByVal UseAnchorPoint As System.Boolean, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal AnchorType As System.Integer, _
   ByVal StartValue As System.String, _
   ByVal TableTemplate As System.String _
) As HoleTableAnnotation
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseAnchorPoint | Boolean | n/a | Yes | If `True` and the sheet format anchor point exists, insert at that point; if `False`, use `X`/`Y` | |
| X | Double | meters | Yes | X coordinate for the anchor of this hole table | |
| Y | Double | meters | Yes | Y coordinate for the anchor of this hole table | |
| AnchorType | Integer | n/a | Yes | Anchor type — the page's own text names this `swBomConfigurationAnchorType_e`, i.e. the same shared table-anchor enum used by BOM/revision/weldment tables, **not** a hole-table-specific enum (see this dossier's intro discrepancy list re: `swHoleTableAnchorType_e`) | `swBOMConfigurationAnchorType_e` |
| StartValue | String | n/a | Yes | Starting value for datum tags — a letter A–Z if the template uses letter tags, a positive integer if it uses number tags | |
| TableTemplate | String | n/a | Yes | Path and filename of the hole table template (`.sldholtbt`, by analogy with the BOM/revision/weldment template extensions documented elsewhere in this dossier — not independently confirmed for hole tables this pass, unverified) | |

**Returns:** `IHoleTableAnnotation` (typed return, not `System.Object`).

**Prior selection required:** Yes — explicit, order-and-mark-sensitive, per the page's
own Remarks. Before calling, use `IModelDocExtension::SelectByID2` to select:

| Selection | Mark |
| --- | --- |
| Datum origin vertex | `1` |
| Hole edges and faces (for multiple holes) | `2` |

The datum tags this method inserts are positioned relative to the pre-selected datum
origin, and only appear next to holes that were pre-selected with `Mark = 2`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertHoleTable2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertHoleTable3.html (successor, documented next)

**status:** verified

**Gotchas:**
- This method inserts a table listing, per selected hole: datum tag, X-location of
  hole center, Y-location of hole center, and size — the page's own Remarks list is
  explicit about these four columns.
- Superseded by `InsertHoleTable3` (below, SOLIDWORKS 2019+) for new code — `2` is
  kept current and fetchable, and remains the simpler call when custom tag
  ordering/typing/manual-tag arrays aren't needed.
- The mark-based selection sequence (datum origin = mark 1, holes = mark 2) is
  materially different from most other Insert* calls in this dossier, which either
  need no prior selection (`InsertBomTable4`/`6`) or a single unmarked
  view/sheet selection (`AutoBalloon5`) — do not reuse a generic "select then call"
  wrapper without threading the marks through correctly.

---

### IView::InsertHoleTable3

- **Interface:** IView
- **Method:** InsertHoleTable3
- **Minimum SW version:** SOLIDWORKS 2019 FCS, Revision Number 27.0

**Signature:**

```vb
Function InsertHoleTable3( _
   ByVal UseAnchorPoint As System.Boolean, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal AnchorType As System.Integer, _
   ByVal StartValue As System.String, _
   ByVal Template As System.String, _
   ByVal TagOrder As System.Integer, _
   ByVal TagType As System.Integer, _
   ByVal ManualTags As System.Object _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseAnchorPoint | Boolean | n/a | Yes | Same as `InsertHoleTable2` | |
| X | Double | meters | Yes | Same as `InsertHoleTable2` | |
| Y | Double | meters | Yes | Same as `InsertHoleTable2` | |
| AnchorType | Integer | n/a | Yes | Same as `InsertHoleTable2` (`swBOMConfigurationAnchorType_e`, not a hole-specific enum) | `swBOMConfigurationAnchorType_e` |
| StartValue | String | n/a | Yes | Starting value for the specified `TagType` | |
| Template | String | n/a | Yes | Path and filename of the hole table template | |
| TagOrder | Integer | n/a | Yes | Tag numbering order | `swHoleTableTagOrder_e` |
| TagType | Integer | n/a | Yes | Tag type/style | `swHoleTableTagStyle_e` |
| ManualTags | Object | n/a | Yes | Array of custom tags; valid only if `TagType = swHoleTableTagStyle_e.swHoleTable_ManualTags` | |

**Returns:** `System.Object`, actually an `IHoleTableAnnotation`.

**Prior selection required:** Same mark-based datum-origin (mark 1) / hole-edges-and-faces
(mark 2) selection sequence as `InsertHoleTable2`, per this page's own Remarks (which
restate the same table verbatim).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertHoleTable3.html

**status:** verified

**Gotchas:**
- Adds `TagOrder`/`TagType`/`ManualTags` over `InsertHoleTable2` — a strict superset,
  use this version when custom/manual datum-tag control is needed (e.g. non-sequential
  or pre-assigned tag values via `ManualTags`).
- Return type is `System.Object` here (vs. `InsertHoleTable2`'s strongly-typed
  `HoleTableAnnotation`) — an inconsistency between the two overloads worth a cast
  either way; both actually return `IHoleTableAnnotation`.

---

### IHoleTableAnnotation::Sort

- **Interface:** IHoleTableAnnotation
- **Method:** Sort
- **Minimum SW version:** SOLIDWORKS 2012 FCS, Revision Number 20.0

**Signature:**

```vb
Function Sort( _
   ByVal ColumnIndex As System.Integer, _
   ByVal SortAscending As System.Boolean _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ColumnIndex | Integer | n/a | Yes | 0-based index of the column to sort by (see Gotchas — hole tables have a specific restriction) | |
| SortAscending | Boolean | n/a | Yes | `True` to sort ascending, `False` to sort descending | |

**Returns:** `Boolean` — `True` if sorted successfully, `False` if not.

**Prior selection required:** None beyond holding the `IHoleTableAnnotation` reference
(reachable via `IHoleTableAnnotation::HoleTable`'s owning table, or the return value of
`InsertHoleTable2`/`3` cast/queried to this interface).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IHoleTableAnnotation~Sort.html

**status:** verified

**Gotchas:**
- Per the page's own Remarks: "Hole tables must be sorted by the Tag column" —
  `ColumnIndex` other than the Tag column is expected to fail or be rejected; contrast
  with `IWeldmentCutListAnnotation::Sort` (documented below) which has the opposite
  restriction (any column *except* Item Number).
- `IHoleTableAnnotation::HoleTable` (property, not independently fetched in full this
  pass) returns a pointer to the underlying `IHoleTable` object — a separate,
  lower-level object from the `ITableAnnotation`-derived `IHoleTableAnnotation` itself.

## Revision tables

`IDrawingDoc::InsertRevisionTable2` does not exist — confirmed by direct fetch (no
`helpContentData` title). The real, current method is `ISheet::InsertRevisionTable2`.

### ISheet::InsertRevisionTable2

- **Interface:** ISheet — requested as `IDrawingDoc::InsertRevisionTable2`, which does
  not exist (see the section intro above)
- **Method:** InsertRevisionTable2
- **Minimum SW version:** SOLIDWORKS 2015 FCS, Revision Number 23.0

**Signature:**

```vb
Function InsertRevisionTable2( _
   ByVal UseAnchorPoint As System.Boolean, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal AnchorType As System.Integer, _
   ByVal TableTemplate As System.String, _
   ByVal Shape As System.Integer, _
   ByVal AutoUpdateZoomCells As System.Boolean _
) As RevisionTableAnnotation
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseAnchorPoint | Boolean | n/a | Yes | `True` to insert at the existing revision-table anchor point, `False` to anchor at `X`/`Y` | |
| X | Double | meters | Yes | X coordinate for placement (used only if `UseAnchorPoint = False`) | |
| Y | Double | meters | Yes | Y coordinate for placement (used only if `UseAnchorPoint = False`) | |
| AnchorType | Integer | n/a | Yes | Anchor type | `swBOMConfigurationAnchorType_e` |
| TableTemplate | String | n/a | Yes | Path and filename of the revision table template (`.sldrevtbt`, see Gotchas) | |
| Shape | Integer | n/a | Yes | Revision symbol shape | `swRevisionTableSymbolShape_e` |
| AutoUpdateZoomCells | Boolean | n/a | Yes | `True` to automatically update zone cells, `False` to not (parameter name is `AutoUpdateZoomCells` on the page itself — likely a documentation typo for "Zone", not "Zoom"; not independently corrected/confirmed) | |

**Returns:** `RevisionTableAnnotation`, or **`null` if a revision table already
exists** on this sheet — an explicit, documented failure mode distinct from most other
`Insert*` calls in this dossier, which mostly document no failure value at all.

**Prior selection required:** None beyond holding the target `ISheet` reference
(obtained via `IDrawingDoc::GetCurrentSheet`/`ISheet` accessors elsewhere in the
drawing API, not otherwise covered in this dossier).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISheet~InsertRevisionTable2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertRevisionTable2.html (direct fetch confirms no `helpContentData` title — this member does not exist on `IDrawingDoc`)
- https://www.codestack.net/solidworks-api/document/tables/insert-revision-table/ (independent corroboration — a worked macro calling `sheet.InsertRevisionTable2(True, 0, 0, ANCHOR_TYPE, TABLE_TEMPLATE, SHAPE, AUTO_UPDATE_ZONE_CELLS)`, matching this signature's parameter order and count)

**status:** verified

**Gotchas:**
- **`IDrawingDoc::InsertRevisionTable2` does not exist** — confirmed by direct fetch,
  and independently corroborated by CodeStack's own published macro calling this
  method on a `sheet` object, not a drawing-document object. Any tool-layer code
  targeting `IDrawingDoc` for this call is targeting a method that was never real.
- Revision table templates follow their own extension: by default, in
  `<install_dir>\lang\<language>\` with a `.sldrevtbt` extension (e.g. "standard
  revision block.sldrevtbt") — distinct from BOM's `.sldbomtbt` and weldment cut
  list's `.sldwldtbt` (see `IView::InsertWeldmentTable`'s Gotchas below).
- **Only one revision table per sheet** — calling this on a sheet that already has one
  returns `null` rather than erroring or replacing the existing table; a caller must
  check for an existing table first (e.g. via `ISheet`'s own accessors, not documented
  further in this dossier) or null-check the return.
- Per CodeStack's own writeup (not independently verified against the official help
  page in this pass): "only revision tables on the first sheet are supported" —
  flagged here as a secondary-source claim, treat as unverified until confirmed
  against the official page's own Remarks.

---

### IRevisionTableAnnotation::AddRevision

- **Interface:** IRevisionTableAnnotation
- **Method:** AddRevision
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Function AddRevision( _
   ByVal Revision As System.String _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Revision | String | n/a | Yes | The revision designation to add (e.g. `"A"`) — a plain string, **not** an enum-typed "change type" (see this dossier's intro re: `swRevisionTableChangeType_e` non-existence) | |

**Returns:** `Integer` — the new revision's row ID (an opaque row identifier usable
with `GetRevisionForId`/`GetRowNumberForId`/`DeleteRevision`, not necessarily the same
as the row's display index).

**Prior selection required:** None beyond holding the `IRevisionTableAnnotation`
reference (the return value of `ISheet::InsertRevisionTable2`, or reached via
`IRevisionTableAnnotation::RevisionTableFeature`/`ISheet::RevisionTable`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IRevisionTableAnnotation~AddRevision.html

**status:** verified

**Gotchas:**
- **There is no `swRevisionTableChangeType_e` enum** — this method's only content
  parameter is a free-form revision-designation string. Revision *descriptions* (the
  "what changed" text) are set as ordinary cell text afterward via
  `ITableAnnotation::Text2` (documented below), not via any parameter of
  `AddRevision` itself.
- The returned `Integer` is a row **ID**, not a row **number** — use
  `IRevisionTableAnnotation::GetRowNumberForId` to translate it to a display row index,
  and `GetIdForRowNumber` for the reverse lookup. Conflating the two is a likely
  off-by-semantics bug for a tool layer that assumes the return value is directly
  usable as a `Text2` row index.
- `IRevisionTableAnnotation::CurrentRevision` (property, not independently fetched in
  full this pass) is the likely accessor for "what is the latest revision letter/number
  right now" — relevant when a caller wants to auto-increment rather than pass an
  explicit `Revision` string.

## Weldment cut list tables

`IModelDocExtension::InsertWeldmentCutlist` does not exist in any spelling — confirmed
absent from both the `IModelDocExtension_members.html` and `IDrawingDoc_members.html`
indexes, and from a direct fetch of the exact requested URL (no `helpContentData`
title). The real, current method is `IView::InsertWeldmentTable`.

### IView::InsertWeldmentTable

- **Interface:** IView — requested as `IModelDocExtension::InsertWeldmentCutlist`,
  which does not exist in any form (see the section intro above)
- **Method:** InsertWeldmentTable
- **Minimum SW version:** SOLIDWORKS 2007 FCS, Revision Number 15.0

**Signature:**

```vb
Function InsertWeldmentTable( _
   ByVal UseAnchorPoint As System.Boolean, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal AnchorType As System.Integer, _
   ByVal Configuration As System.String, _
   ByVal TableTemplate As System.String _
) As WeldmentCutListAnnotation
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseAnchorPoint | Boolean | n/a | Yes | If `True` and the sheet format anchor point exists, insert at that point; if `False`, use `X`/`Y` | |
| X | Double | meters | Yes | X coordinate for placement; valid only if `UseAnchorPoint = False` | |
| Y | Double | meters | Yes | Y coordinate for placement; valid only if `UseAnchorPoint = False` | |
| AnchorType | Integer | n/a | Yes | Anchor type | `swBOMConfigurationAnchorType_e` |
| Configuration | String | n/a | Yes | Name of the "As Welded" configuration for the weldment cut list table | |
| TableTemplate | String | n/a | Yes | Path and filename of the template (see Gotchas) | |

**Returns:** `IWeldmentCutListAnnotation` (typed return).

**Prior selection required:** None beyond holding the target `IView` reference — called
directly on the drawing view, no `ISelectionMgr` selection required.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertWeldmentTable.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertWeldmentCutlist.html (direct fetch confirms no `helpContentData` title — this member does not exist)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms `InsertWeldmentTable` is the real member, alongside the unrelated `InsertWeldTable` — see Gotchas)

**status:** verified

**Gotchas:**
- **`IModelDocExtension::InsertWeldmentCutlist` does not exist under that name or any
  variant spelling** (`InsertWeldmentCutList`, `InsertCutList*`) on either
  `IModelDocExtension` or `IDrawingDoc` — confirmed by both a members-index scan and a
  direct 404 fetch. The real method's own worked example is literally titled "Insert
  Weldment Cut List Table," which is strong independent confirmation this is the
  correct real-name resolution, not just a plausible guess.
- **Do not confuse with `IView::InsertWeldTable`** (no "ment", singular "Weld") — a
  different, unrelated method on the same interface that inserts a table of weld
  *symbols* (returns `System.Boolean`, has extra `IncludeAnnotations`/`CombineSameType`
  parameters, no cut-list semantics at all). The two names are one word apart and easy
  to transpose in a tool-layer call site.
- The weldment cut-list table template installed with SOLIDWORKS is
  `<SOLIDWORKS_install_dir>\lang\<language>\cut list.sldwldtbt` — a third distinct
  template extension in this dossier (`.sldbomtbt` for BOM, `.sldrevtbt` for revision,
  `.sldwldtbt` for weldment cut list). Empty-string/invalid-path fallback behavior is
  not documented — unverified, same caveat as the BOM and revision template
  parameters.
- Returns `IWeldmentCutListAnnotation`, whose own `WeldmentCutListFeature` property
  (not independently fetched in full this pass beyond confirming its existence in the
  member index) is presumably the link back to the owning cut-list feature, mirroring
  `IBomTableAnnotation::BomFeature`.

---

### IWeldmentCutListAnnotation::Sort

- **Interface:** IWeldmentCutListAnnotation
- **Method:** Sort
- **Minimum SW version:** SOLIDWORKS 2012 FCS, Revision Number 20.0

**Signature:**

```vb
Function Sort( _
   ByVal ColumnIndex As System.Integer, _
   ByVal SortAscending As System.Boolean _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ColumnIndex | Integer | n/a | Yes | 0-based index of the column to sort by (see Gotchas — weldment cut lists have a specific restriction) | |
| SortAscending | Boolean | n/a | Yes | `True` to sort ascending, `False` to sort descending | |

**Returns:** `Boolean` — `True` if sorted successfully, `False` if not.

**Prior selection required:** None beyond holding the `IWeldmentCutListAnnotation`
reference (the return value of `InsertWeldmentTable`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldmentCutListAnnotation~Sort.html

**status:** verified

**Gotchas:**
- Per the page's own Remarks: "Weldment cut lists must be sorted by any column except
  Item Number" — the mirror-image restriction of `IHoleTableAnnotation::Sort` (which
  must sort *by* a fixed column, Tag). Passing `ColumnIndex` for the Item Number column
  here is expected to fail or be rejected.
- Same method name and signature shape (`ColumnIndex`, `SortAscending`) is reused
  verbatim across `IHoleTableAnnotation`, `IWeldmentCutListAnnotation`, and (by
  reasonable inference from the shared "Sorting Tables" help-page cross-reference on
  both fetched pages) likely other `ITableAnnotation`-derived interfaces not
  individually fetched in this dossier — but `Sort` is **not** itself a member of the
  base `ITableAnnotation` interface (confirmed absent from that interface's own member
  index); each derived interface apparently declares its own copy.

## Base table interface: ITableAnnotation and IAnnotation

`ITableAnnotation::GetCellText`/`SetCellText` and `ITableAnnotation::Update` do not
exist — both confirmed absent by direct fetch. `ITableAnnotation::SetPosition` also
does not exist as a table-specific method — position is set through the base
`IAnnotation` interface instead. All three real replacements are documented below.
`IBomTableAnnotation`, `IHoleTableAnnotation`, `IRevisionTableAnnotation`, and
`IWeldmentCutListAnnotation` (all documented above) each inherit every member
documented in this section.

### ITableAnnotation::Text2

- **Interface:** ITableAnnotation — requested as `GetCellText`/`SetCellText`, neither
  of which exists (see the section intro above)
- **Method:** Text2 (property, read/write)
- **Minimum SW version:** SOLIDWORKS 2018 FCS, Revision Number 26.0

**Signature:**

```vb
Property Text2( _
   ByVal Row As System.Integer, _
   ByVal Column As System.Integer, _
   ByVal IncludeHidden As System.Boolean _
) As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Row | Integer | n/a | Yes | 0-based row index | |
| Column | Integer | n/a | Yes | 0-based column index | |
| IncludeHidden | Boolean | n/a | Yes | `True` to get/set text in a hidden cell, `False` to not | |

**Returns:** `String` — the cell's driving text (the underlying parameter/link string,
e.g. a dimension-value or custom-property link — **not** necessarily what's visually
displayed; use `ITableAnnotation::DisplayedText2` for the rendered text).

**Prior selection required:** None beyond holding the `ITableAnnotation` (or derived
interface) reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~Text2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~GetCellText.html (direct fetch confirms no `helpContentData` title — this member does not exist)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~SetCellText.html (same negative result)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation_members.html (confirms the full member surface — `Text`/`Text2` present, `GetCellText`/`SetCellText`/`Update`/`SetPosition` absent)

**status:** verified

**Gotchas:**
- **`GetCellText`/`SetCellText` do not exist** — the real, current cell-text
  read/write mechanism across every table type in this dossier is this property pair
  (`Text`/`Text2`). This is also the real mechanism behind the
  `IBomTableAnnotation::SetItemNumber` non-existence discrepancy: setting a BOM row's
  item number programmatically means calling `Text2` (or `Text`) on that row's ITEM
  NO. column, not a dedicated setter.
- Editability varies by table type (per the page's own Remarks table): BOM and
  General tables have all cells editable; Hole tables only allow editing columns that
  aren't auto-generated (header row and custom columns); Revision tables have all
  cells editable.
- **Performance**: per this page's own Remarks, updating text in many cells of a large
  table is slow because the table rebuilds after each cell-text change. The documented
  workaround: set `IAnnotation::Visible = False` before a batch of `Text2` writes (the
  table does not rebuild while hidden), do all the writes, then restore visibility.
  This is the closest real equivalent to the requested-but-nonexistent
  `ITableAnnotation::Update` — there is no explicit "commit"/"update" call; the table
  self-rebuilds, and the only lever over that behavior is toggling `Visible`.
- Supersedes `Text` (below) by adding `IncludeHidden` — prefer `Text2` for new code.

---

### ITableAnnotation::Text

- **Interface:** ITableAnnotation
- **Method:** Text (property, read/write)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Property Text( _
   ByVal Row As System.Integer, _
   ByVal Column As System.Integer _
) As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Row | Integer | n/a | Yes | 0-based row index | |
| Column | Integer | n/a | Yes | 0-based column index | |

**Returns:** `String` — same "driving text, not displayed text" semantics as `Text2`;
use `ITableAnnotation::DisplayedText` for the rendered text.

**Prior selection required:** None beyond holding the interface reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~Text.html

**status:** verified

**Gotchas:**
- Predecessor to `Text2` — kept current and fetchable, but has no `IncludeHidden`
  parameter (always behaves as if `IncludeHidden = False`, unverified — not stated
  explicitly, inferred from the parameter's absence). Prefer `Text2` for new code that
  needs to touch hidden cells.
- Same editability-by-table-type and rebuild-performance caveats as `Text2` apply
  here — see that record's Gotchas.

---

### ITableAnnotation::RowCount

- **Interface:** ITableAnnotation
- **Method:** RowCount (property, read-only)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Property RowCount As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — read-only property) | n/a | n/a | n/a | Getter takes no arguments | |

**Returns:** `Integer` — number of **visible** rows in this table.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~RowCount.html

**status:** verified

**Gotchas:**
- Contrast with `TotalRowCount` (below) — `RowCount` counts only visible rows,
  `TotalRowCount` counts visible **and** hidden rows. A caller iterating cells with
  `IncludeHidden = True` on `Text2` should bound the loop with `TotalRowCount`, not
  `RowCount`, or hidden rows will be silently skipped.

---

### ITableAnnotation::ColumnCount

- **Interface:** ITableAnnotation
- **Method:** ColumnCount (property, read-only)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Property ColumnCount As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — read-only property) | n/a | n/a | n/a | Getter takes no arguments | |

**Returns:** `Integer` — number of columns in this table.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~ColumnCount.html

**status:** verified

**Gotchas:**
- No documented hidden-vs-visible distinction analogous to `RowCount`/`TotalRowCount`
  for columns on this page — `ColumnHidden` (a separate per-column property listed in
  the interface's member index, not independently fetched this pass) suggests columns
  can also be hidden, but whether `ColumnCount` includes hidden columns is unverified;
  confirm empirically before relying on it for a hidden-column-inclusive loop bound.

---

### ITableAnnotation::TotalRowCount

- **Interface:** ITableAnnotation — real equivalent of the requested
  `IBomTableAnnotation::GetTotalItemsCount`, which does not exist (see this dossier's
  intro discrepancy list)
- **Method:** TotalRowCount (property, read-only)
- **Minimum SW version:** SOLIDWORKS 2011 SP05, Revision Number 19.5

**Signature:**

```vb
Property TotalRowCount As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — read-only property) | n/a | n/a | n/a | Getter takes no arguments | |

**Returns:** `Integer` — total number of visible **and** hidden rows in this table.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~TotalRowCount.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBomTableAnnotation~GetTotalItemsCount.html (direct fetch confirms no `helpContentData` title — this member does not exist)

**status:** verified

**Gotchas:**
- **`IBomTableAnnotation::GetTotalItemsCount` does not exist** — confirmed by direct
  fetch. This inherited base-interface property, plus
  `IBomTableAnnotation::GetComponentsCount2` (per-row component counts, documented
  above), are the real ways to reason about BOM table size. `TotalRowCount` gives the
  table's total row count including hidden rows; it does not distinguish BOM
  "items" from raw table rows (a BOM row and a BOM item are not guaranteed 1:1 in an
  indented/detailed-cut-list BOM), so a caller specifically counting distinct item
  numbers should not treat `TotalRowCount` as an item count without also accounting
  for `IBomFeature::DetailedCutList`/`DissolvePartLevelRows` semantics.

---

### ITableAnnotation::Anchored

- **Interface:** ITableAnnotation
- **Method:** Anchored (property, read/write)
- **Minimum SW version:** SOLIDWORKS 2004 SP2, Revision Number 12.2

**Signature:**

```vb
Property Anchored As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — set via assignment) | Boolean | n/a | Yes (on set) | `True` to attach the table to the sheet's anchor point, `False` to detach | |

**Returns:** `Boolean` — `True` if the table is currently attached to the anchor,
`False` if not.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~Anchored.html

**status:** verified

**Gotchas:**
- Per the page's own Remarks: setting this to `True` snaps the table's origin to the
  anchor point "according to the anchor type of this table" — i.e. driven by
  `AnchorType` (below), not an independent position. If the drawing sheet format has
  no anchor point defined for this table's type, setting `Anchored = True` "has no
  effect" (silently — no error, no exception documented).
- The page's own "See Also" list explicitly cross-references `IAnnotation::SetPosition`
  — confirming, alongside the direct 404 for `ITableAnnotation::SetPosition`, that
  table positioning goes through the base annotation interface rather than a
  table-specific method (documented next).

---

### ITableAnnotation::AnchorType

- **Interface:** ITableAnnotation
- **Method:** AnchorType (property, read/write)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Property AnchorType As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — set via assignment) | Integer | n/a | Yes (on set) | Type of anchor | `swBOMConfigurationAnchorType_e` |

**Returns:** `Integer` — current anchor type, as `swBOMConfigurationAnchorType_e`.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~AnchorType.html

**status:** verified

**Gotchas:**
- This page's own Property Value text states the type is defined by
  `swBOMConfigurationAnchorType_e` **for `ITableAnnotation` generically** — i.e. every
  table type (BOM, hole, revision, weldment cut list, general) shares this one enum
  for anchor type, not a per-table-type enum. This is the direct confirming source for
  this dossier's resolution of the `swTableAnnotationAnchorType_e`/
  `swHoleTableAnchorType_e` non-existence discrepancy noted in the intro.

---

### IAnnotation::SetPosition

- **Interface:** IAnnotation — real equivalent of the requested
  `ITableAnnotation::SetPosition`, which does not exist (see the section intro above)
- **Method:** SetPosition
- **Minimum SW version:** SOLIDWORKS 2000 FCS

**Signature:**

```vb
Function SetPosition( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | X origin of the annotation | |
| Y | Double | meters | Yes | Y origin of the annotation | |
| Z | Double | meters | Yes | Z origin of the annotation | |

**Returns:** `Boolean` — `True` if the position was set, `False` if not successful.

**Prior selection required:** None beyond holding the `IAnnotation` reference, reached
from a table annotation via `ITableAnnotation::GetAnnotation` (a member confirmed
present in `ITableAnnotation`'s own index).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetPosition.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ITableAnnotation~SetPosition.html (direct fetch confirms no `helpContentData` title — this member does not exist on `ITableAnnotation`)

**status:** verified

**Gotchas:**
- **`ITableAnnotation::SetPosition` does not exist** — confirmed by direct fetch.
  Table position is set through the base `IAnnotation` interface, reached via
  `ITableAnnotation::GetAnnotation()`, exactly like the general annotation-position
  pattern documented in [`03-annotations.md`](03-annotations.md) for notes, GD&T
  frames, and other annotation types.
  For a **table** specifically, the page's own per-annotation-type Remarks table
  states the X/Y/Z origin's meaning is "determined by `ITableAnnotation::AnchorType`"
  — i.e. which corner/point of the table the X/Y/Z coordinate refers to depends on the
  table's current `AnchorType` value, not a fixed corner.
- Calling `SetPosition` while `ITableAnnotation::Anchored = True` is not documented as
  an error, but per `Anchored`'s own Remarks, an anchored table's origin snaps back to
  the sheet anchor point — a caller wanting explicit X/Y/Z control should set
  `Anchored = False` first, or the `SetPosition` call's effect may be immediately
  overridden by the anchor snap. Unverified interaction order; confirm empirically.
- This is the same `IAnnotation::SetPosition` family referenced (as `SetPosition2`/`3`
  for other annotation types) in `03-annotations.md` — this dossier documents only the
  base, unsuffixed `SetPosition` overload, which is the one the table-annotation
  Remarks table explicitly names.

## Enums

#### swBomType_e

Consumed by `InsertBomTable4`/`InsertBomTable6`'s `BomType` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swBomType_PartsOnly | 1 | Parts-only BOM |
| swBomType_TopLevelOnly | 2 | Top-level-only BOM |
| swBomType_Indented | 3 | Indented BOM |
| swBomType_Flattened | 4 | Flattened BOM |

No further per-member description text beyond the number is given on the page itself
(names are self-explanatory; no page text quoted beyond the numeric values).

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBomType_e.html

#### swBOMConfigurationAnchorType_e

Consumed by `AnchorType` across every table type in this dossier —
`ITableAnnotation::AnchorType`, `InsertBomTable6`, `InsertHoleTable2`/`3`,
`InsertWeldmentTable`, and `ISheet::InsertRevisionTable2` all cite this one enum by
name, despite `swHoleTableAnchorType_e` and `swTableAnnotationAnchorType_e` (the
task-spec-requested, table-type-specific names) not existing (see this dossier's intro
discrepancy list).

| Value | Number | Meaning |
| --- | --- | --- |
| swBOMConfigurationAnchor_TopLeft | 1 | Upper-left corner |
| swBOMConfigurationAnchor_TopRight | 2 | Upper-right corner |
| swBOMConfigurationAnchor_BottomLeft | 3 | Lower-left corner |
| swBOMConfigurationAnchor_BottomRight | 4 | Lower-right corner |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBOMConfigurationAnchorType_e.html

#### swNumberingType_e

Consumed by `InsertBomTable4`/`6`'s `IndentedNumberingType` parameter (valid only when
`BomType = swBomType_Indented`) and `IBomFeature::NumberingTypeOnIndentedBOM`.

| Value | Number | Meaning |
| --- | --- | --- |
| swNumberingType_None | 0 | No numbering |
| swNumberingType_Detailed | 1 | Detailed numbering |
| swNumberingType_Flat | 2 | Flat numbering |

No further per-member description text beyond the number is given on the page itself.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swNumberingType_e.html

#### swBalloonStyle_e

Consumed by `InsertBOMBalloon`'s `Style` parameter and `IAutoBalloonOptions::Style`.

| Value | Number | Meaning |
| --- | --- | --- |
| swBS_None | 0 | No balloon style |
| swBS_Circular | 1 | Circular |
| swBS_Triangle | 2 | Triangle |
| swBS_Hexagon | 3 | Hexagon |
| swBS_Box | 4 | Box |
| swBS_Diamond | 5 | Diamond |
| swBS_Pentagon | 6 | Can be used for label location selection "Circular Split Line" |
| swBS_SplitCirc | 7 | Not valid for notes; only valid for balloons |
| swBS_FlagPentagon | 8 | Flag pentagon |
| swBS_FlagTriangle | 9 | Flag triangle |
| swBS_Underline | 10 | Underline |
| swBS_Square | 11 | Square |
| swBS_SCircle | 12 | S-circle |
| swBS_Inspection | 13 | Inspection |
| swBS_ArcBracket | 14 | Arc bracket |
| swBS_RectBracket | 15 | Rectangular bracket |
| swBS_ArclenSym | 16 | Arc-length symbol |
| swBS_FixedSym | 17 | Fixed symbol |
| swBS_DoubleArrow | 18 | Double arrow |
| swBS_SplitSquare | 19 | Can be used for label location selection "Square Split Line" |
| swBS_Verbose | 20 | Verbose |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBalloonStyle_e.html

#### swBalloonFit_e

Consumed by `InsertBOMBalloon`'s `Size` parameter and `IAutoBalloonOptions::Size`.

| Value | Number | Meaning |
| --- | --- | --- |
| swBF_Tightest | 0 | Not available for a label location |
| swBF_1Char | 1 | Fits 1 character |
| swBF_2Chars | 2 | Fits 2 characters |
| swBF_3Chars | 3 | Fits 3 characters |
| swBF_4Chars | 4 | Fits 4 characters |
| swBF_5Chars | 5 | Fits 5 characters |

`swBF_UserDef` (referenced by `IAutoBalloonOptions::CustomSize`'s and
`InsertBOMBalloon`'s `CustomSize` parameter's own Remarks/Gotchas as the value that
enables a user-defined size) does not appear in the fetched Members table above — its
existence is corroborated by both `CustomSize` property pages citing it by name, but
its numeric value was not independently confirmed on the enum's own page in this pass;
treat the value as unverified even though the member name itself is real.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBalloonFit_e.html

#### swBalloonTextContent_e

Consumed by `InsertBOMBalloon`'s `UpperTextStyle`/`LowerTextStyle` parameters and
`IAutoBalloonOptions::UpperTextContent`/`LowerTextContent`.

| Value | Number | Meaning |
| --- | --- | --- |
| swBalloonTextCustom | 0 | No description on page beyond the number |
| swBalloonTextItemNumber | 1 | No description on page beyond the number |
| swBalloonTextQuantity | 2 | No description on page beyond the number |
| swBalloonTextCustomProperties | 3 | No description on page beyond the number (see `INote::PropertyLinkedText` for link-string syntax, per `InsertBOMBalloon`'s own Remarks) |
| swBalloonTextComponentReference | 4 | No description on page beyond the number |
| swBalloonTextSpoolReference | 5 | No description on page beyond the number |
| swBalloonTextPartNumberBOM | 6 | No description on page beyond the number |
| swBalloonTextFileName | 7 | No description on page beyond the number |
| swBalloonTextCutlistProperties | 8 | No description on page beyond the number |
| swBalloonTextViewSheet | 9 | No description on page beyond the number |
| swBalloonTextViewSheetWithLabel | 10 | No description on page beyond the number |
| swBalloonTextViewZone | 11 | No description on page beyond the number |
| swBalloonTextViewViewLetter | 12 | No description on page beyond the number |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBalloonTextContent_e.html

#### swBalloonLayoutType_e

Consumed by `AutoBalloon4`'s `Layout` parameter and `IAutoBalloonOptions::Layout`.

| Value | Number | Meaning |
| --- | --- | --- |
| swDetailingBalloonLayout_Square | 1 | In a box around the drawing view |
| swDetailingBalloonLayout_Circle | 2 | In a circle around the drawing view |
| swDetailingBalloonLayout_Top | 3 | Along the top edge of the drawing view |
| swDetailingBalloonLayout_Bottom | 4 | Along the bottom edge of the drawing view |
| swDetailingBalloonLayout_Right | 5 | Along the right edge of the drawing view |
| swDetailingBalloonLayout_Left | 6 | Along the left edge of the drawing view |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBalloonLayoutType_e.html

#### swTableAnnotationType_e

Consumed by `ITableAnnotation::Type` (read-only property identifying what kind of
table a given `ITableAnnotation` is — not independently documented as its own H3
record in this dossier, but its backing enum is captured here since every table type
covered above maps to one of these values).

| Value | Number | Meaning |
| --- | --- | --- |
| swTableAnnotation_General | 0 | General table |
| swTableAnnotation_HoleChart | 1 | Hole table |
| swTableAnnotation_BillOfMaterials | 2 | BOM table |
| swTableAnnotation_RevisionBlock | 3 | Revision table |
| swTableAnnotation_WeldmentCutList | 4 | Weldment cut list table |
| swTableAnnotation_TitleBlock | 5 | Title block table |
| swTableAnnotation_WeldTable | 6 | Weld table (the `InsertWeldTable` table, distinct from the weldment cut list — see `InsertWeldmentTable`'s Gotchas) |
| swTableAnnotation_BendTable | 7 | Bend table |
| swTableAnnotation_PunchTable | 8 | Punch table |
| swTableAnnotation_GeneralTolerance | 9 | General tolerance table |
| swTableAnnotation_FamilyTable | 10 | Family table |

This enum is independent, additional confirmation of the `InsertWeldmentTable` /
`InsertWeldTable` naming resolution above: the API has separate, numbered enum members
for "weldment cut list" (4) and "weld table" (6) as genuinely distinct table types.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swTableAnnotationType_e.html

#### Enums requested but not found in the current API

Three enum names given by the source research issue were confirmed absent from a full
scan of the `SolidWorks.Interop.swconst` namespace index page (which lists every
`sw*_e` enum name in the assembly) — not merely absent from a guessed URL, but absent
from the authoritative full enum listing:

- **`swTableAnnotationAnchorType_e`** — does not exist. Every table type's anchor type
  is `swBOMConfigurationAnchorType_e` instead (documented above), confirmed directly by
  `ITableAnnotation::AnchorType`'s own Property Value text.
- **`swHoleTableAnchorType_e`** — does not exist, for the same reason —
  `IView::InsertHoleTable2`/`3`'s own `AnchorType` parameter documentation explicitly
  cites `swBomConfigurationAnchorType_e`, not a hole-specific enum.
- **`swRevisionTableChangeType_e`** — does not exist. There is no "change type" concept
  in the real revision-table API surface; `IRevisionTableAnnotation::AddRevision`
  takes a plain `String` revision designation (documented above), and revision
  *description* text is set as ordinary table cell text via `ITableAnnotation::Text2`,
  not through any enum-typed parameter.

Source (negative — namespace index):
https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst_namespace.html
