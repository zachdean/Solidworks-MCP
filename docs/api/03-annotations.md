---
interface: Multiple (IModelDocExtension, ISelectionMgr, IModelDoc2, IDrawingDoc, IView, IDisplayDimension, IDimension, IGtol, IGtolFrame, IDatumTag, IWeldSymbol, IAnnotation)
min_methods: 18
status: complete
---

# Annotations, dimensions, and GD&T

Covers the selection primitives that every annotation/dimension/GD&T operation in this
API depends on (this is the most selection-dependent slice of the SolidWorks API — the
tool layer built from this dossier does select-then-act atomically, so every record
below states its **Prior selection required** explicitly), plus model-annotation import
and autodimension, dimension creation and value/text access, notes, GD&T feature
control frames, datum features, surface finish and weld symbols, center marks and
centerlines, and generic annotation-object manipulation (position, leader, layer).

Several method and enum names given by the source research issue turned out not to
match the current (SOLIDWORKS 2025) API surface. Each is documented below under its
*real* name, with the discrepancy called out explicitly in that record's Gotchas —
summarized here for a quick scan, following the same honesty convention established in
[`02-views.md`](02-views.md):

- `ISelectionMgr::AddSelection2` does not exist — the real method for adding an object
  to a selection list from a held COM pointer is `ISelectionMgr::AddSelectionListObject`.
- `IView::InsertModelAnnotations3` and `IModelDocExtension::InsertModelAnnotations3` do
  not exist — the real, current member is `IDrawingDoc::InsertModelAnnotations3`
  (superseded by `IDrawingDoc::InsertModelAnnotations4` as of SOLIDWORKS 2024). A third,
  narrower, brand-new-in-2025 mechanism, `IView::ImportAnnotations`, also exists and is
  documented alongside them.
- `IView::IAutodimScheme` does not exist — the real, current, and apparently sole member
  of the "autodimension family" on drawings is `IDrawingDoc::AutoDimension` (no
  `AutoDimension2`/`3`).
- `IModelDocExtension::AddDimension2` does not exist — the "2" variant lives on
  `IModelDoc2`, not `IModelDocExtension`; only the extension-line variant
  (`AddDimension`, unsuffixed) lives on `IModelDocExtension`.
- The task named no specific ordinate-dimension method; the real, current, selection-driven
  method is `IModelDocExtension::AddOrdinateDimension` (supersedes obsolete
  `IDrawingDoc::AddOrdinateDimension2`), plus a separate non-associative,
  no-selection-required `IDrawingDoc::CreateOrdinateDim4`.
- `IModelDocExtension::CreateText3` does not exist — the real, current method is
  `IDrawingDoc::CreateText2` (`IDrawingDoc::CreateText`, unsuffixed, is Obsolete).
- `IModelDocExtension::CreateGTOL` does not exist — the real method is
  `IModelDoc2::InsertGtol`, an empty-shell factory whose content is filled in
  afterward via either the legacy `IGtol::SetFrameSymbols2`/`SetFrameValues2` pair or
  the SOLIDWORKS-2022+-format `IGtolFrame::SetSymbolXml`.
- `IModelDocExtension::CreateDatumTag` does not exist — the real method is
  `IModelDoc2::InsertDatumTag2`.
- `IModelDocExtension::CreateDatumTargetSym` does not exist — the real method is
  `IModelDocExtension::InsertDatumTargetSymbol3`.
- `IModelDocExtension::CreateSurfaceFinishSymbol2` does not exist — the real method is
  `IModelDocExtension::InsertSurfaceFinishSymbol3` (obsolete predecessor:
  `IModelDoc2::InsertSurfaceFinishSymbol2`).
- `IModelDocExtension::CreateWeldSymbol2` does not exist — the real method is
  `IModelDoc2::InsertWeldSymbol3` plus `IWeldSymbol::SetText` (obsolete predecessor:
  `IModelDoc2::InsertWeldSymbol2`).
- `IView::InsertCenterMark2` does not exist — `IView` has no `InsertCenterMark` member
  at all. The real method is `IDrawingDoc::InsertCenterMark3`.
- `swTextAlign_e` does not exist — the real enum is `swTextJustification_e`.
- `swGtolShape_e` does not exist — a GD&T frame's geometric characteristic symbol is a
  free-form `<LibraryName-SymbolName>` bracket-token string (or, in the current XML
  format, a bare `LibraryName-SymbolName` element value), not an enum.
- `swDatumTagStyle_e` does not exist — the real enum is `swDatumDisplayType_e`.
- `swWeldSymbolType_e` does not exist — the weld symbol's type/name (`BUTT`, `FILL`,
  `PLUG`, etc.) is a fixed ISO string set, not an enum; the real weld-related enum in
  this dossier's scope is `swWeldSymbolContourTypes_e` (contour, not type).
- `swInsertAnnotation_e`, `swImportModelItemsSource_e`, `swAutodimScheme_e`,
  `swAutodimEntities_e`, `swDimensionType_e`, `swCenterMarkStyle_e`, and `swSFSymType_e`
  are all real and confirmed exactly as requested.

`help.solidworks.com` blocks plain fetches (HTTP 403, or an empty client-rendered
shell) without a browser-like `User-Agent` header — see
[`README.md`](README.md#canonical-source-urls) for the retry convention. One section
below (Annotation object manipulation) could not get a rendered page from any source
this pass despite that workaround and is marked `status: unverified` throughout, with
the access failure noted explicitly in each record.

## Selection primitives

The methods in this section are the "select" half of the atomic select-then-act
pattern the tool layer uses for every annotation/dimension/GD&T operation below —
almost every `Create*`/`Insert*`/`Add*` call downstream in this dossier reads its
target off `ISelectionMgr`'s current selection list rather than taking a geometry
parameter directly.

**`ISelectionMgr::AddSelection2` does not exist.** A direct fetch of its expected
help-page URL returns the help site's own `"This page cannot be found."` / `"File does
not exist"` payload (a definitive negative from the site's content-lookup system, not a
network block), and a full-text scan of the `ISelectionMgr_members.html` index for
`AddSelection*` turns up only `AddSelectionListObject` and `AddSelectionListObjects` —
there is no `AddSelection`/`AddSelection2` member on this interface at all, in any
generation. `AddSelectionListObject` (documented below) is the real, current method
for adding an object to a selection list without pre-selecting it in the UI.

### IModelDocExtension::SelectByID2

- **Interface:** IModelDocExtension
- **Method:** SelectByID2
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function SelectByID2( _
   ByVal Name As System.String, _
   ByVal Type As System.String, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double, _
   ByVal Append As System.Boolean, _
   ByVal Mark As System.Integer, _
   ByVal Callout As Callout, _
   ByVal SelectOption As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name of the object to select, or `""`. Case-sensitive, must be an exact/fully-qualified match (e.g. `"D1@Sketch2@Part1.SLDPRT"`, not `"D1@Sketch2"`) for automatically-named objects like dimensions and drawing views. Pass `""` if the name is unknown or the object isn't auto-named | |
| Type | String | n/a | Yes | Type of object to select, uppercase, as one of the string constants defined by `swSelectType_e` (see the Type-string table below), or `""` for no type filtering. If specified, this method returns `False` when it can't find a matching object of that type | `swSelectType_e` |
| X | Double | meters | Yes | X selection location, or `0` | |
| Y | Double | meters | Yes | Y selection location, or `0` | |
| Z | Double | meters | Yes | Z selection location, or `0` | |
| Append | Boolean | n/a | Yes | Selection-list append/toggle behavior — see the truth table in Gotchas | |
| Mark | Integer | n/a | Yes | A caller-chosen tag value attached to this selection, consumed by other functions requiring ordered/grouped selection (e.g. `4` when selecting multiple edges/sketch segments for a sweep path, `2` for loft guide curves; see `IDrawingDoc::AutoDimension`'s `swAutodimMark_e` usage below for a drawing-specific example) | |
| Callout | Callout | n/a | Yes | Pointer to the associated `ICallout`, or `Nothing`/`null` if none | |
| SelectOption | Integer | n/a | Yes | `swSelectOptionDefault` (Shift key not simulated) or `swSelectOptionExtensive` (Shift key simulated, i.e. additive selection) | `swSelectOption_e` |

**Returns:** `Boolean` — `True` if the item was successfully selected, `False` if not
(including: `Type` was specified but no matching object was found).

**Prior selection required:** None to call it — this method establishes selection,
it doesn't consume prior selection state. However, the target `IModelDoc2` this is
called on must be an **open and visible document** (not e.g. an unopened assembly
component's model doc obtained via `IComponent2::GetModelDoc`) — for an in-context
target, use a fully-qualified `Name` like `"Plane4@Part1-1@Assem1"` instead.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SelectByID2.html
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSelectType_e.html (Type-string table below, extracted from this page's own Remarks section)

**status:** verified

**Gotchas:**
- **`Append` truth table**, quoted from the page's own Remarks:

  | Append | If entity is... | Then... |
  | --- | --- | --- |
  | `True` | Not already selected | Entity is appended to the current selection list |
  | `True` | Already selected | Entity is removed from the current selection list (i.e. `True` is a *toggle*, not a pure add) |
  | `False` | Not already selected | Current selection is cleared, then the entity is put on the list |
  | `False` | Already selected | Current selection list remains the same |

  A select-then-act wrapper that always wants "select exactly this one thing" should
  pass `Append = False`; a wrapper building up a multi-entity selection should pass
  `Append = True` and must be aware that re-selecting an already-selected entity
  *deselects* it.
- **`Name` is not for faces/edges/vertices** — the page explicitly says so. For those,
  pass `Type` and rely on `X`/`Y`/`Z` (a ray-traced pick point), or, if the caller
  already holds an `IFace2`/`IEdge`/`IVertex` object, call `IEntity::Select4` directly
  instead of round-tripping through a point pick.
- **Coordinate space depends on whether `Name` is used**: if `Name` is provided, `X`/`Y`/`Z`
  must be in the coordinate space of the context where the named item was created —
  not model space. If `Name` is empty (selecting by type + point only), `X`/`Y`/`Z` are
  in model space. For selections that don't need a point at all, pass `(0, 0, 0)`.
- **`Type` string casing/behavior may shift with context**: e.g. a sketch point in the
  *active* sketch is `"SKETCHPOINT"`, but the same point when its sketch isn't active
  (or the point is the origin) must be selected as `"EXTSKETCHPOINT"` instead — passing
  the wrong one for the current state returns `False` rather than silently succeeding.
- Units for `X`/`Y`/`Z` are not stated explicitly on the page; `meters` follows this
  dossier's API-wide convention (see [`README.md`](README.md#units-convention)).

**Drawing-relevant `Type` strings** (from `swSelectType_e`'s own Remarks table, which
maps each enum member to the literal case-sensitive string `SelectByID2`'s `Type`
parameter actually expects — these strings are **not** simply the enum member name
with the `swSel` prefix stripped, e.g. `swSelWELDS` → `"WELD"`, not `"WELDSYMBOL"`):

| `swSelectType_e` member | `Type` string | Underlying interface |
| --- | --- | --- |
| `swSelDRAWINGVIEWS` | `"DRAWINGVIEW"` | `IView` |
| `swSelDIMENSIONS` | `"DIMENSION"` | `IDisplayDimension` |
| `swSelNOTES` | `"NOTE"` | `INote` |
| `swSelGTOLS` | `"GTOL"` | `IGtol` |
| `swSelDATUMTAGS` | `"DATUMTAG"` | `IDatumTag` |
| `swSelDTMTARGS` | `"DTMTARG"` | `IDatumTargetSym` |
| `swSelSFSYMBOLS` | `"SFSYMBOL"` | `ISFSymbol` |
| `swSelWELDS` | `"WELD"` | `IWeldSymbol` |
| `swSelDOWELSYMS` | `"DOWELSYM"` | `IDowelSymbol` |
| `swSelCENTERMARKS` | `"CENTERMARKS"` | Not supported (per the page itself) |
| `swSelCENTERMARKSYMS` | `"CENTERMARKSYMS"` | — |
| `swSelCENTERLINES` | `"CENTERLINE"` | — |
| `swSelBREAKLINES` | `"BREAKLINE"` | `IBreakLine` |
| `swSelSECTIONLINES` | `"SECTIONLINE"` | `IDrSection` |
| `swSelDETAILCIRCLES` | `"DETAILCIRCLE"` | `IDetailCircle` |
| `swSelARROWS` | `"VIEWARROW"` | `IProjectionArrow` |
| `swSelANNOTATIONTABLES` | `"ANNOTATIONTABLES"` | `ITableAnnotation` / `ITitleBlockTableAnnotation` |
| `swSelHOLETABLEFEATS` | `"HOLETABLE"` | `IHoleTable` |
| `swSelREVISIONTABLE` | `"REVISIONTABLE"` | — |
| `swSelREVISIONCLOUDS` | `"REVISIONCLOUD"` | — |
| `swSelTITLEBLOCK` | `"TITLEBLOCK"` | `ITitleBlock` |
| `swSelSHEETS` | `"SHEET"` | `ISheet` |
| `swSelEDGES` | `"EDGE"` | `IEdge` |
| `swSelFACES` | `"FACE"` | `IFace2` |
| `swSelVERTICES` | `"VERTEX"` | `IVertex` |
| `swSelSKETCHSEGS` | `"SKETCHSEGMENT"` | `ISketchSegment` |
| `swSelSKETCHPOINTS` | `"SKETCHPOINT"` | `ISketchPoint` |
| `swSelEXTSKETCHPOINTS` | `"EXTSKETCHPOINT"` | `ISketchPoint` or origin point — use when the sketch isn't active or the point is the origin, see Gotchas above |
| `swSelCOMPONENTS` | `"COMPONENT"` | `IComponent2` |

This table was independently re-verified against a fresh direct fetch of the
`swSelectType_e` page (same `curl` + browser `User-Agent` technique used throughout
this dossier); every row above matches the page's own `Enum = value, // "TYPE"`
listing except `swSelDOWELSYMS`, where an earlier pass mistranscribed the string as
`"DOWLELSYM"` — the real, correctly-spelled string is `"DOWELSYM"`, now corrected
above.

Full list has 145 members total (only those with a documented `Type` string and
plausible drawing/annotation relevance are reproduced above); see the enum's own
page for the complete set including 3D/routing/simulation-specific members out of
scope for this dossier.

---

### ISelectionMgr::AddSelectionListObject

- **Interface:** ISelectionMgr
- **Method:** AddSelectionListObject
- **Minimum SW version:** SOLIDWORKS 2012 FCS, Revision Number 20.0

**Signature:**

```vb
Function AddSelectionListObject( _
   ByVal Object As System.Object, _
   ByVal SelectData As System.Object _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Object | Object | n/a | Yes | The object to add to the selection list (a COM entity pointer such as `IFace2`, `IEdge`, `IAnnotation`, etc.) | |
| SelectData | Object (`ISelectData`) | n/a | Yes | Selection metadata (mark, callout, select option, etc.), obtained from `ISelectionMgr::CreateSelectData` | |

**Returns:** `Boolean` — `True` if successful, `False` if not.

**Prior selection required:** None as a precondition — but this method is meant to
be used as part of a specific sequence (see Gotchas) that lets a caller build a
selection list programmatically from object pointers it already holds, **without**
pre-selecting those objects in the SolidWorks UI the way `SelectByID2` does.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISelectionMgr~AddSelectionListObject.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISelectionMgr~AddSelection2.html (fetched directly; returns the help site's own `"This page cannot be found."` content-lookup error, confirming this member does not exist)
- https://help.solidworks.com/2025/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.iselectionmgr_members.html (full-text scan for `AddSelection*` confirms only `AddSelectionListObject`/`AddSelectionListObjects` exist on this interface)

**status:** verified

**Gotchas:**
- **`ISelectionMgr::AddSelection2` does not exist** — see this section's intro note
  above. Any tool-layer code referencing it by that name is targeting a method that
  was never real in the current (or any archived-page-visible) SOLIDWORKS API.
- Per the page's own Remarks, the intended sequence for adding objects without UI
  pre-selection is: (1) `ISelectionMgr::SuspendSelectionList` to preserve the current
  selection list and start a fresh one, (2) call `AddSelectionListObject` (this
  method) or `AddSelectionListObjects` (plural, batched) to populate the new list,
  (3) do whatever needs the new selection, (4) `ISelectionMgr::ResumeSelectionList`
  to restore the original list. Skipping the suspend/resume bracket means this call
  mutates whatever selection list is currently live.
- `SelectData` must come from `ISelectionMgr::CreateSelectData` — it cannot be
  synthesized as a bare struct/dictionary from a scripting layer.
- Contrast with `SelectByID2`: that method drives UI-visible pre-selection by
  name/type/point; this method is the "I already have the COM object pointer, just
  put it on the selection list silently" path — pick based on whether the caller
  already holds a bound entity object or only a name/type/point description.

---

### ISelectionMgr::GetSelectedObjectCount2

- **Interface:** ISelectionMgr
- **Method:** GetSelectedObjectCount2
- **Minimum SW version:** SOLIDWORKS 2006 FCS, Revision Number 14.0

**Signature:**

```vb
Function GetSelectedObjectCount2( _
   ByVal Mark As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Mark | Integer | n/a | Yes | `-1` = count all selections regardless of mark; `0` = count only unmarked selections; any other value = count only selections tagged with that specific mark value (the same `Mark` passed to `SelectByID2`) | |

**Returns:** `Integer` — number of selected objects matching the `Mark` filter.

**Prior selection required:** None to call the method itself — it reads whatever is
currently on the selection list (possibly zero items). This is the standard way a
select-then-act tool verifies a selection actually landed before proceeding to
`GetSelectedObject6`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISelectionMgr~GetSelectedObjectCount2.html

**status:** verified

**Gotchas:**
- The page's only Remark: "This method can be used to determine if a valid selection
  was made" — i.e. the canonical guard before calling `GetSelectedObject6`, since
  that method can return `Nothing`/`null` on an empty or unsupported-type selection.
- `Mark` filtering here must match whatever `Mark` value was passed to the original
  `SelectByID2`/`AddSelectionListObject` call for the objects a caller cares about —
  passing `-1` is the safe default when the wrapper doesn't track marks itself.

---

### ISelectionMgr::GetSelectedObject6

- **Interface:** ISelectionMgr
- **Method:** GetSelectedObject6
- **Minimum SW version:** SOLIDWORKS 2006 FCS, Revision Number 14.0

**Signature:**

```vb
Function GetSelectedObject6( _
   ByVal Index As System.Integer, _
   ByVal Mark As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Index | Integer | n/a | Yes | 1-based index within the current selection list, ranging from `1` to `ISelectionMgr::GetSelectedObjectCount2`'s result; `-1` has special meaning (see Gotchas) | |
| Mark | Integer | n/a | Yes | Same three-way convention as `GetSelectedObjectCount2`'s `Mark`: `-1` = all, `0` = unmarked only, other = that specific mark. Ignored entirely when `Index = -1` | |

**Returns:** `System.Object` — the selected object, late-bound as whatever concrete
type corresponds to its `swSelectType_e` selection type (e.g. `IFace2`, `IEdge`,
`IDisplayDimension`, `INote`). **`Nothing`/`null` is returned if the type is not
supported or if nothing is selected** — always null-check before use, especially
after only a `GetSelectedObjectCount2 > 0` check without a matching `Mark`.

**Prior selection required:** Yes — a non-empty selection list (verify with
`GetSelectedObjectCount2` first); this method only reads existing selection state,
it never selects anything itself.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISelectionMgr~GetSelectedObject6.html

**status:** verified

**Gotchas:**
- **Context-dependent return type**, quoted from the page's own Remarks table:
  - If a reference surface is selected → returns the reference surface **face(s)**,
    not the whole reference-surface feature.
  - If a dimension is selected → returns an **`IDisplayDimension`** object, not the
    lower-level `IDimension` — a caller needing the driving `IDimension` must go
    through `IDisplayDimension::GetDimension2` (see the dimension records below).
  - If `ISelectionMgr` was obtained from a **drawing** document → a selected component
    returns an `IDrawingComponent`; if obtained from a **part/assembly** document → it
    returns an `IComponent2` instead. Same underlying selection, different wrapper
    type depending on which document's `ISelectionMgr` made the call.
- **`Index = -1` is a distinct special mode**, not "last item": it means "select
  whatever is dynamically highlighted right now if dynamic highlighting is turned
  on" and the `Mark` parameter is ignored entirely in that mode. This is easy to
  trigger by accident with an off-by-one bug — a select-then-act wrapper should treat
  `Index <= 0` as a hard error rather than silently falling into dynamic-highlight mode.
- To retrieve the object's `IAnnotation` wrapper (needed by `IAnnotation::SetPosition2`/
  `SetLeader3`/`Layer` documented later in this dossier), call the returned object's
  own `.GetAnnotation()` accessor — `GetSelectedObject6` does not return `IAnnotation`
  directly for annotation selections.

---

### IModelDoc2::ClearSelection2

- **Interface:** IModelDoc2
- **Method:** ClearSelection2
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS, Revision Number 10.0

**Signature:**

```vb
Sub ClearSelection2( _
   ByVal All As System.Boolean _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| All | Boolean | n/a | Yes | `True` clears the entire existing selection list; `False` clears only the items in the *active* selection list (see Gotchas) | |

**Returns:** None (`Sub`) — no success/failure signal.

**Prior selection required:** None — safe to call unconditionally, including when
nothing is selected (no-op in that case). This is the standard cleanup call at the
end (or start) of a select-then-act sequence to guarantee the tool layer isn't
leaking selection state into the next operation.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~ClearSelection2.html

**status:** verified

**Gotchas:**
- **`All = False`'s "active selection list" behavior is conditional**, quoted from the
  page's own Remarks: "`False` only works if the current PropertyManager page
  contains a selection list; otherwise, this method clears all selections." That is —
  outside of an open PropertyManager page with its own selection list (the common
  case for a headless/automation tool layer), `False` and `True` behave identically
  (both clear everything). A select-then-act wrapper that always wants a full reset
  should just pass `True` unconditionally rather than relying on this conditional
  fallback.
- This is a `Sub`, not a `Function` — no return value to check; there is no
  documented failure mode.

---

### IView::GetVisibleEntities2

- **Interface:** IView
- **Method:** GetVisibleEntities2
- **Minimum SW version:** SOLIDWORKS 2014 FCS, Revision Number 22.0

**Signature:**

```vb
Function GetVisibleEntities2( _
   ByVal LpViewComponent As Component2, _
   ByVal EntityType As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| LpViewComponent | Component2 | n/a | Yes | The component, within this drawing view, to get visible entities from | |
| EntityType | Integer | n/a | Yes | Type of entity to enumerate (edges, faces, silhouette edges, etc.) | `swViewEntityType_e` |

**Returns:** `System.Object` — an array of the visible entities of `EntityType`
belonging to `LpViewComponent` in this view. "Visible" means not completely
obscured by other entities in the view (per the page's own Remarks).

**Prior selection required:** None — this is a read-only enumeration call, not a
selection operation. It's the pickable-entity-discovery counterpart to
`SelectByID2`/`AddSelectionListObject`: a tool layer can call this first to find
candidate entities in a view, then feed one of the returned entity pointers into
`ISelectionMgr::AddSelectionListObject` (via `ISelectData`) to actually select it
for a subsequent Create/Insert call — `GetVisibleEntities2` itself does not touch
`ISelectionMgr` state.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetVisibleEntities2.html

**status:** verified

**Gotchas:**
- Supersedes the now-obsolete `IView::GetVisibleEntities` (no `2` suffix); the
  documented difference is that v2 additionally supports silhouette edges
  (`EntityType = swViewEntityType_e.swViewEntityType_SilhouetteEdge`) — v1 does not.
  Always use v2 for new code.
- `LpViewComponent` must be a component *within this view* — this is not a
  whole-view or whole-document enumeration; for an assembly drawing view with
  multiple components, call once per component of interest.
- Return type is a late-bound `System.Object` array (same pattern as
  `InsertModelAnnotations3`/`4` below) — cast/iterate as an object array, not a
  strongly-typed entity array.

## Model annotation import & autodimension

`IView::InsertModelAnnotations3` and `IModelDocExtension::InsertModelAnnotations3`
(the two names given by the source research issue) do not exist. Direct fetches of
both exact URLs return the help site's own `"File does not exist"` JSON payload (not
a network block — `curl` with a browser `User-Agent` returns HTTP 200 with that error
embedded in the page's `__NEXT_DATA__` JSON). A member-index scan of `IDrawingDoc`
turned up the real family: `InsertModelAnnotations` → `InsertModelAnnotations2` →
`InsertModelAnnotations3` → `InsertModelAnnotations4`, all on `IDrawingDoc`, not
`IView` or `IModelDocExtension`. `InsertModelAnnotations3` (requested) and
`InsertModelAnnotations4` (current, SOLIDWORKS 2024+) are both documented below since
either may be encountered in the wild. A third, unrelated-but-overlapping mechanism —
`IView::ImportAnnotations`, brand new in SOLIDWORKS 2025 — is also documented, since it
is the one member of this group that actually does live on `IView`.

### IDrawingDoc::InsertModelAnnotations3

- **Interface:** IDrawingDoc
- **Method:** InsertModelAnnotations3 — requested as `IView::InsertModelAnnotations3`
  and `IModelDocExtension::InsertModelAnnotations3`, neither of which exists (see the
  section intro above)
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function InsertModelAnnotations3( _
   ByVal Option As System.Integer, _
   ByVal Types As System.Integer, _
   ByVal AllViews As System.Boolean, _
   ByVal DuplicateDims As System.Boolean, _
   ByVal HiddenFeatureDims As System.Boolean, _
   ByVal UsePlacementInSketch As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Option | Integer | n/a | Yes | Source of dimensions (see Remarks on the page — a pre-2008-SP3 documentation bug swapped members 1 and 2; the enum's own current page has the corrected mapping) | `swImportModelItemsSource_e` |
| Types | Integer | n/a | Yes | Bitwise OR of annotation types to insert | `swInsertAnnotation_e` |
| AllViews | Boolean | n/a | Yes | `True` to insert annotations in all views in the drawing, `False` to insert only in the selected view | |
| DuplicateDims | Boolean | n/a | Yes | `True` to eliminate duplicate dimensions, `False` to allow duplicates | |
| HiddenFeatureDims | Boolean | n/a | Yes | `True` to insert dimensions from hidden features, `False` to skip them | |
| UsePlacementInSketch | Boolean | n/a | Yes | `True` to insert dimensions using their placement in the originating sketch, `False` otherwise | |

**Returns:** `System.Object` — an array of the inserted `IAnnotation` objects.

**Prior selection required:** The method's own one-line description reads "Inserts
model annotations into this drawing document's **currently selected drawing view**" —
select the target drawing view (`SelectByID2` with `Type="DRAWINGVIEW"`) before calling,
unless `AllViews = True`, in which case no view selection is needed and every view in
the drawing is processed. The page does not clarify whether "currently selected" means
an `ISelectionMgr` selection specifically or the last-activated view — treat
`SelectByID2`-based selection as the safe, verified path and confirm the
activated-view-only behavior empirically if a caller needs it.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertModelAnnotations3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms interface placement and the full `InsertModelAnnotations`/`2`/`3`/`4` lineage)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertModelAnnotations3.html (direct fetch returns the help site's file-not-found JSON, confirming non-existence on `IView`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertModelAnnotations3.html (same negative result for `IModelDocExtension`)

**status:** verified

**Gotchas:**
- Neither `IView::InsertModelAnnotations3` nor `IModelDocExtension::InsertModelAnnotations3`
  exists — confirmed by direct fetch returning the help site's own structured
  "File does not exist" error for both. The real member is on `IDrawingDoc`, and is
  superseded by `InsertModelAnnotations4` (below) as of SOLIDWORKS 2024.
- `Option`'s value meanings were **incorrectly documented in SOLIDWORKS API Help
  published before SOLIDWORKS 2008 SP3** — the page states this directly with an
  explicit incorrect/correct table swapping what members `1` and `2` mean. Treat any
  pre-2008-SP3 secondary source describing `Option`'s values with different numbers as
  wrong; the corrected mapping matches `swImportModelItemsSource_e`'s own current page
  (documented in this dossier's Enums section).
- `Types` is a **bitwise OR** of `swInsertAnnotation_e` members, not a single value.

---

### IDrawingDoc::InsertModelAnnotations4

- **Interface:** IDrawingDoc
- **Method:** InsertModelAnnotations4
- **Minimum SW version:** SOLIDWORKS 2024 FCS, Revision Number 32

**Signature:**

```vb
Function InsertModelAnnotations4( _
   ByVal Option As System.Integer, _
   ByVal Types As System.Integer, _
   ByVal AllViews As System.Boolean, _
   ByVal DuplicateDims As System.Boolean, _
   ByVal HiddenFeatureDims As System.Boolean, _
   ByVal UsePlacementInSketch As System.Boolean, _
   ByVal InsertAllAnnotations As System.Boolean, _
   ByVal InsertAllReferenceGeometry As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Option | Integer | n/a | Yes | Source of dimensions | `swImportModelItemsSource_e` |
| Types | Integer | n/a | Yes | Annotation types to insert; only valid if `InsertAllAnnotations` and `InsertAllReferenceGeometry` are both `False` | `swInsertAnnotation_e` |
| AllViews | Boolean | n/a | Yes | `True` to insert in all views, `False` for the selected view only | |
| DuplicateDims | Boolean | n/a | Yes | `True` to eliminate duplicate dimensions | |
| HiddenFeatureDims | Boolean | n/a | Yes | `True` to insert dimensions from hidden features | |
| UsePlacementInSketch | Boolean | n/a | Yes | `True` to insert dimensions as placed in sketch | |
| InsertAllAnnotations | Boolean | n/a | Yes | `True` to insert all annotations, ignoring `Types` | |
| InsertAllReferenceGeometry | Boolean | n/a | Yes | `True` to insert all reference geometry, ignoring `Types` | |

**Returns:** `System.Object` — array of inserted `IAnnotation` objects.

**Prior selection required:** Same as `InsertModelAnnotations3` — the currently
selected/active drawing view, unless `AllViews = True`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertModelAnnotations4.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertModelAnnotations3.html (predecessor, for the parameter-superset comparison)

**status:** verified

**Gotchas:**
- This is the current (2024+) member; prefer it over `InsertModelAnnotations3` for new
  tool-layer code. It's a strict superset of v3's parameter list, adding
  `InsertAllAnnotations` and `InsertAllReferenceGeometry` — when either is `True`,
  `Types` is ignored entirely.
- Same `Option`/`swImportModelItemsSource_e` pre-2008-SP3 documentation-bug caveat as
  v3 applies here too (same enum, same parameter position).

---

### IView::ImportAnnotations

- **Interface:** IView
- **Method:** ImportAnnotations
- **Minimum SW version:** SOLIDWORKS 2025 FCS, Revision Number 33

**Signature:**

```vb
Sub ImportAnnotations( _
   ByVal IncludeDesignAnnotations As System.Boolean, _
   ByVal IncludeCosmeticThreads As System.Boolean, _
   ByVal IncludeDimXpertAnnotations As System.Boolean, _
   ByVal IncludeHiddenFeatureItems As System.Boolean, _
   ByVal Include3DViewAnnotations As System.Boolean _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| IncludeDesignAnnotations | Boolean | n/a | Yes | `True` to import design annotations | |
| IncludeCosmeticThreads | Boolean | n/a | Yes | `True` to import cosmetic threads | |
| IncludeDimXpertAnnotations | Boolean | n/a | Yes | `True` to import DimXpert annotations | |
| IncludeHiddenFeatureItems | Boolean | n/a | Yes | `True` to import hidden feature items | |
| Include3DViewAnnotations | Boolean | n/a | Yes | `True` to import 3D view annotations | |

**Returns:** None (`Sub`) — contrast with `InsertModelAnnotations3`/`4`, which return
an array of the created `IAnnotation` objects.

**Prior selection required:** None beyond holding the `IView` reference itself — this
method operates on "this drawing view" (the `IView` object the call is made on), not
on `ISelectionMgr` state or a "currently selected" view. This is a meaningfully
different selection model from `InsertModelAnnotations3`/`4`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~ImportAnnotations.html

**status:** verified

**Gotchas:**
- Brand new in SOLIDWORKS 2025 (FCS, Revision 33) — the newest of the three
  annotation-import mechanisms documented in this section. Unlike
  `InsertModelAnnotations3`/`4` (`IDrawingDoc`-scoped, act on "the currently selected
  view"), this is called directly on a specific `IView` object, sidestepping any
  selection-state ambiguity.
- Coarser-grained than `swInsertAnnotation_e`'s per-type bitmask — this method only
  offers 5 category toggles, not per-annotation-type control (dimensions vs. GTols vs.
  notes). A tool layer needing type-level control must use `InsertModelAnnotations4`
  instead.
- Not documented whether calling this on a view from a document opened under an older
  SW version behaves any differently — unverified, treat as applying uniformly.

---

### IDrawingDoc::AutoDimension

- **Interface:** IDrawingDoc
- **Method:** AutoDimension — requested as "`IView::IAutodimScheme` /
  `IDrawingDoc::AutoDimension` family"; `IView::IAutodimScheme` does not exist (see
  Gotchas). `AutoDimension` is the real, current, and sole member of this "family" —
  there is no `AutoDimension2`/`3`.
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function AutoDimension( _
   ByVal EntitiesToDimension As System.Integer, _
   ByVal HorizontalScheme As System.Integer, _
   ByVal HorizontalPlacement As System.Integer, _
   ByVal VerticalScheme As System.Integer, _
   ByVal VerticalPlacement As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| EntitiesToDimension | Integer | n/a | Yes | Which entities to dimension | `swAutodimEntities_e` |
| HorizontalScheme | Integer | n/a | Yes | Horizontal dimensioning scheme | `swAutodimScheme_e` |
| HorizontalPlacement | Integer | n/a | Yes | Placement relative to the drawing view | `swAutodimHorizontalPlacement_e` |
| VerticalScheme | Integer | n/a | Yes | Vertical dimensioning scheme | `swAutodimScheme_e` |
| VerticalPlacement | Integer | n/a | Yes | Placement relative to the drawing view | `swAutodimVerticalPlacement_e` |

**Returns:** `Integer` — `swAutodimStatusSuccess` (from `swAutodimStatus_e`) if the
view was automatically dimensioned; other values indicate specific failure reasons.
`swAutodimStatus_e` itself was not independently fetched in this research pass (out of
the task's requested enum list) — treat any non-success code as unverified until that
enum's own page is checked.

**Prior selection required:** Yes, multi-part and mark-based — this is one of the most
selection-dependent methods in this dossier:
1. **The drawing view to autodimension**: select the view itself (no mark needed), or
   select entities within it (the view is inferred), or, if nothing is selected, the
   method defaults to the first view in the drawing.
2. **Horizontal/vertical dimensioning datums** (optional): select a vertical
   edge/sketch line/vertex/sketch point and mark it with
   `swAutodimMark_e.swAutodimMarkHorizontalDatum` for the horizontal scheme's baseline;
   select a horizontal edge/sketch line/vertex/sketch point and mark it with
   `swAutodimMark_e.swAutodimMarkVerticalDatum` for the vertical scheme's baseline. A
   single vertex/sketch point marked `swAutodimMark_e.swAutodimMarkOriginDatum` can
   supply both datums at once. If no datum is selected, the method defaults to the
   view's left-most and bottom-most entities.
3. **Entities to dimension**: when `EntitiesToDimension` is
   `swAutodimEntitiesSelected` or `swAutodimEntitiesBasedOnPreselect`, select the
   target entities (lines, points, vertices, faces, sketch entities) and mark each
   with `swAutodimMark_e.swAutodimMarkEntities`.

A single call to `AutoDimension` may therefore need a selection list built from as
many as 4 distinct `Mark` values (unmarked/`0` for the view,
`swAutodimMarkHorizontalDatum`, `swAutodimMarkVerticalDatum`/`swAutodimMarkOriginDatum`,
and `swAutodimMarkEntities`) via repeated `SelectByID2(..., Append:=True, Mark:=...)`
calls before this one call — materially more complex selection setup than most other
methods in this dossier.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AutoDimension.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms no `IAutodimScheme` member — or any `Autodim*`-named member at all — exists on `IView`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms `AutoDimension` is the only `Autodim*`-named member on `IDrawingDoc` — no `AutoDimension2`/`3`)

**status:** verified

**Gotchas:**
- `IView::IAutodimScheme` does not exist — confirmed absent from the fetched `IView`
  member index. `IDrawingDoc::AutoDimension` is the entire "autodimension family" in
  the current API.
- A sketch-scoped sibling exists — `ISketch::AutoDimension2` — sharing the
  `swAutodimScheme_e`/`swAutodimEntities_e` enums but operating on a sketch instead of
  a drawing view; not documented in this drawing-focused dossier.
- `swAutodimSchemeCenterline` (value `4`, in `swAutodimScheme_e`) is explicitly
  documented as "Not supported in sketches or drawings; do not use" — despite existing
  as a named member, passing it is expected to fail or be meaningless.
- `HorizontalPlacement`/`VerticalPlacement` use two entirely separate enums
  (`swAutodimHorizontalPlacement_e` / `swAutodimVerticalPlacement_e`) from
  `swAutodimScheme_e` — neither was independently fetched in this research pass; do
  not assume their members mirror `swAutodimScheme_e`.

## Dimensions

`IModelDocExtension::AddDimension2` does not exist — despite the naming pattern
elsewhere in this API, the "2" variant lives on `IModelDoc2`, not
`IModelDocExtension`; only the extension-line variant (`AddDimension`, unsuffixed)
lives on `IModelDocExtension`. Confirmed by a direct 404-equivalent fetch, not
inferred.

### IModelDocExtension::AddDimension

- **Interface:** IModelDocExtension
- **Method:** AddDimension
- **Minimum SW version:** SOLIDWORKS 2015 FCS (Revision Number 23.0)

**Signature:**

```vb
Function AddDimension( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double, _
   ByVal Direction As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | X coordinate of display dimension text | |
| Y | Double | meters | Yes | Y coordinate of display dimension text | |
| Z | Double | meters | Yes | Z coordinate of display dimension text | |
| Direction | Integer | n/a | Yes | Direction of dimensioning extension line (parts) or rapid-dimensioning quadrant (drawings) | `swSmartDimensionDirection_e` |

**Returns:** `Object`, actually an `IDisplayDimension`. The help page documents no
explicit failure value — if `X`/`Y`/`Z` are inappropriate for `Direction`, the page
states the call "fails to add the display dimension" but does not say what it returns
in that case.

**Prior selection required:** Yes — explicit, order-sensitive. Before calling, select
the entities to dimension **by location, not by name**, via
`IModelDocExtension::SelectByID2`: for an angular dimension between two lines, (1)
call `SelectByID2` on the first sketch segment, passing its X/Y/Z coordinates and
leaving the object-**Name** argument empty, then (2) call `SelectByID2` on the vertex
of the angle, again by X/Y/Z coordinates with an empty Name. Passing a name instead of
coordinates makes `SelectByID2` pick a random point on the line, producing
unpredictable dimension results. Only use this method if the pre-selected entities do
**not** unambiguously define what to dimension (i.e. an extension line is needed) —
otherwise use `IModelDoc2::AddDimension2` instead.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~AddDimension.html

**status:** verified

**Gotchas:**
- This is the *extension-line* variant, distinct from `IModelDoc2::AddDimension2` (no
  extension line needed) — they live on different interfaces and are not sequential
  overloads of the same name despite the numbering suggesting otherwise;
  `AddDimension` (on `IModelDocExtension`) actually shipped years *after*
  `AddDimension2` (on `IModelDoc2`, since SW 2001Plus) — verified by comparing the two
  pages' Availability lines.
- To flip an angular dimension to its supplementary angle, use
  `IDisplayDimension::SupplementaryAngle` (not documented in this dossier).
- Only call this on a visible document — check `ISldWorks::Visible` first.
- Call `ISldWorks::SetUserPreferenceToggle` with
  `swUserPreferenceToggle_e.swInputDimValOnCreate` beforehand to suppress SolidWorks'
  modal "enter dimension value" dialog, which otherwise blocks headless/automated use.

---

### IModelDoc2::AddDimension2

- **Interface:** IModelDoc2
- **Method:** AddDimension2 — requested as `IModelDocExtension::AddDimension2`, which
  does not exist (see the section intro above)
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function AddDimension2( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | Dimension text location | |
| Y | Double | meters | Yes | Dimension text location | |
| Z | Double | meters | Yes | Dimension text location | |

**Returns:** `Object`, the newly created dimension (an `IDisplayDimension`). No
documented failure value.

**Prior selection required:** Yes. Select the entities to dimension via
`IModelDocExtension::SelectByID2`, **by location (X/Y/Z coordinates), not by object
name** — if an object name is passed instead, `SelectByID2` ignores the coordinates
and picks a line endpoint at random, giving unpredictable results. The selected
entities must **unambiguously** define what's being dimensioned with no extension
line needed; if they don't, use `IModelDocExtension::AddDimension` instead (it takes
an extra `Direction` parameter for the extension line).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~AddDimension2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~AddDimension2.html (confirms no such member exists on `IModelDocExtension` — the page 404s with `helpContentData.ErrorTitle: "This page cannot be found."`; the extension-line dimension method on that interface is unsuffixed `AddDimension`, not `AddDimension2`)

**status:** verified

**Gotchas:**
- **`IModelDocExtension::AddDimension2` does not exist** — despite the naming pattern
  elsewhere in this API, the "2" variant here lives on `IModelDoc2`, not
  `IModelDocExtension`. Confirmed by a direct 404 fetch, not inferred.
- Same visibility/dialog-suppression caveats as `IModelDocExtension::AddDimension`
  above (`ISldWorks::Visible`, `swUserPreferenceToggle_e.swInputDimValOnCreate`).
- To flip an angular dimension to its supplementary angle, use
  `IDisplayDimension::SupplementaryAngle`.

---

### IModelDoc2::AddHorizontalDimension2

- **Interface:** IModelDoc2
- **Method:** AddHorizontalDimension2
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function AddHorizontalDimension2( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | Dimension text location | |
| Y | Double | meters | Yes | Dimension text location | |
| Z | Double | meters | Yes | Dimension text location | |

**Returns:** `Object`, the newly created dimension (`IDisplayDimension`). No
documented failure value.

**Prior selection required:** Yes — select the entities whose horizontal distance is
to be dimensioned (e.g. two vertices, or a vertex and an edge) via `SelectByID2` or
`ISelectionMgr::AddSelectionListObject` before calling. The help page does not
restate the by-location-not-name caveat here, but per the sibling
`AddDimension`/`AddDimension2` records above, prefer coordinate-based selection over
name-based to get predictable results.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~AddHorizontalDimension2.html

**status:** verified

**Gotchas:**
- Superseded name pattern: there is no `AddHorizontalDimension` (unsuffixed) — `2` is
  the only/current form referenced in the page's own "See Also" list alongside
  `IAddHorizontalDimension2` (the interface-qualified COM dispatch variant, not a
  separate method).

---

### IModelDoc2::AddVerticalDimension2

- **Interface:** IModelDoc2
- **Method:** AddVerticalDimension2
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function AddVerticalDimension2( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | Dimension text location | |
| Y | Double | meters | Yes | Dimension text location | |
| Z | Double | meters | Yes | Dimension text location | |

**Returns:** `Object`, the newly created dimension (`IDisplayDimension`). No
documented failure value.

**Prior selection required:** Yes — select the entities whose vertical distance is to
be dimensioned via `SelectByID2`/`AddSelectionListObject` before calling. Same
by-location preference as `AddHorizontalDimension2`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~AddVerticalDimension2.html

**status:** verified

**Gotchas:**
- Same pattern as `AddHorizontalDimension2` — no unsuffixed predecessor exists.

---

### IDisplayDimension::GetDimension2

- **Interface:** IDisplayDimension
- **Method:** GetDimension2
- **Minimum SW version:** SOLIDWORKS 2008 FCS (Revision Number 16.0)

**Signature:**

```vb
Function GetDimension2( _
   ByVal Index As System.Integer _
) As Dimension
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Index | Integer | n/a | Yes | `0` for the first chamfer display dimension, `1` for the second; ignored (pass `0`) for any non-chamfer display dimension | |

**Returns:** `IDimension` — the underlying model dimension that this display
dimension presents. SolidWorks can show one model `Dimension` in multiple
views/sheets as multiple `DisplayDimension` objects; this call gets from the shown
display dimension back to its one underlying value-holding `Dimension`.

**Prior selection required:** None beyond already holding an `IDisplayDimension`
reference — this is not a selection-based call. Obtain the `IDisplayDimension` either
as the return value of a creation call (`AddDimension2`, `AddDimension`,
`AddHorizontalDimension2`, etc.) or, for a dimension already in the model/drawing, by
selecting it in the graphics area (`SelectByID2` with `Type="DIMENSION"`) and then
calling `ISelectionMgr::GetSelectedObject6`, which returns the `IDisplayDimension`
directly. For a chamfer dimension specifically, call this method **twice** (once with
`Index=0`, once with `Index=1`) to get both underlying dimensions.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~GetDimension2.html

**status:** verified

**Gotchas:**
- `Index` is meaningful for chamfer display dimensions only; every other display
  dimension type ignores it.

---

### IDisplayDimension::Type2

- **Interface:** IDisplayDimension
- **Property:** Type2 (read-only)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

Fetched independently (sw-1xx.2) while resolving whether `add_dimension`'s
"smart"/"radial"/"diameter"/"angular" types (all routed through the single
generic `IModelDoc2::AddDimension2` — see that record's own Gotchas) have any
way to read back what dimension type SolidWorks actually produced. They do:
this property.

**Signature:**

```vb
ReadOnly Property Type2 As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none — read-only property)* | | | | | |

**Returns:** `Integer` — the type of this display dimension, per the page's own
one-line description ("Gets the type of dimension").

**Prior selection required:** None — a plain property read on an already-held
`IDisplayDimension` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~Type2.html

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- Enum ref: `swDimensionType_e` (documented in this dossier's Enums section) —
  the same enum `_DIMENSION_TYPES`' `dim_type_enum` values are drawn from, so a
  caller can compare the two directly.
- Not to be confused with `IDimension::GetType` (a *method*, not a property, on
  the underlying model `IDimension` rather than the display dimension), whose
  return value is `swDimensionParamType_e` — a different enum, not fetched in
  this dossier (out of scope; flagged only so it isn't reached for by mistake
  in place of `Type2`).
- Per the page's own Remarks: call `IModelDoc2::GraphicsRedraw2` after anything
  that might have changed the dimension's type-relevant display state (e.g.
  `Diametric`, below) before relying on a freshly-read `Type2`.

---

### IDisplayDimension::Diametric

- **Interface:** IDisplayDimension
- **Property:** Diametric
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

Fetched independently (sw-1xx.2), alongside `Type2` above — this is the
documented mechanism for choosing radius vs. diameter display on a
radial-capable dimension, resolving what an earlier draft of this dossier's
`add_dimension` design had called an unavoidable ambiguity (`AddDimension2`
alone cannot pick radial vs. diameter at creation time — this property corrects
it afterward).

**Signature:**

```vb
Property Diametric As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Boolean | n/a | Yes | `True` to display as diameter/doubled-distance, `False` for radial/single-distance | |

**Returns:** `Boolean` (getter) — the dimension's current radial/diameter display state.

**Prior selection required:** None — read/write directly on an already-held
`IDisplayDimension` reference (e.g. the object `AddDimension2` just returned).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~Diametric.html

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- Per the page's own Remarks: depending on this display dimension's underlying
  type, this property toggles between *radial and diameter* display dimensions,
  or between *radial linear and diametric linear* display dimensions — it "does
  not affect other types of dimensions" (e.g. setting it on an angular or
  linear dimension is a documented no-op, not an error — `add_dimension` relies
  on this to make setting it best-effort/non-fatal for `"smart"`-routed results
  that didn't come out radial-capable).
- The page's own "See Also" names `IModelDocExtension::AddSpecificDimension`
  ("Use ... to create single or doubled distance display dimensions") as an
  alternative, more direct creation path — not fetched in this dossier (out of
  scope for this issue; `add_dimension` uses the create-then-correct sequence
  documented here instead).
- Per the page's own Remarks: call `IModelDoc2::GraphicsRedraw2` after setting
  this property to see the change reflected in the graphics window.

---

### IDimension::SetValue3

- **Interface:** IDimension
- **Method:** SetValue3
- **Minimum SW version:** SOLIDWORKS 2004 FCS (Revision Number 12.0)

**Signature:**

```vb
Function SetValue3( _
   ByVal NewValue As System.Double, _
   ByVal WhichConfigurations As System.Integer, _
   ByVal Config_names As System.Object _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| NewValue | Double | **document (display) units** — see Gotchas | Yes | Value to set for this dimension | |
| WhichConfigurations | Integer | n/a | Yes | Which configuration(s) to set the value in | `swSetValueInConfiguration_e` |
| Config_names | Object | n/a | Only if `WhichConfigurations = swSetValue_InSpecificConfigurations` | A single `BSTR` or `BSTR` array of configuration names | |

**Returns:** `Integer` error code as defined by `swSetValueReturnStatus_e` (not itself
fetched in this pass — treat any non-success code as unverified until the enum is
cross-checked).

**Prior selection required:** None — operates directly on the `IDimension` object
reference returned by `IDisplayDimension::GetDimension2` (or equivalent), not on the
current `ISelectionMgr` selection.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~SetValue3.html

**status:** verified

**Gotchas:**
- **Explicit exception to this API's meters/radians convention:** the help page
  states `NewValue` is "in the units of the owning document" (i.e. the document's
  display units — mm/in/deg as configured in Document Properties), **not**
  meters/radians. `IDimension::SetSystemValue3` (below) is the confirmed
  meters/radians equivalent — the naming split (`Value` = document units,
  `SystemValue` = database/meters-radians units) matches the same
  `Value`/`SystemValue` naming pattern used elsewhere in the SolidWorks API.
- **sw-1xx.2: prefer `SetSystemValue3` over this method in the tool layer.** This
  project's public tool boundary converts the caller's unit to meters via
  `self._units` (see `README.md`'s units convention) — `SetValue3`'s document-unit
  target would require reading the *document's own* display unit (which may not
  match `self._units.default_unit`) before conversion, an extra COM round trip
  this dossier's other write paths don't need. `set_dimension_value` in the tool
  layer therefore calls `SetSystemValue3`, not this method.
- Angular dimensions: it's unclear from this page alone whether "document units" for
  an angular `IDimension` means degrees or radians — unverified. Moot for this
  dossier's tool layer per the previous Gotcha (`SetSystemValue3` is used instead,
  confirmed in meters for linear values; its own page does not separately clarify
  the angular case either, so treat an angular dimension's `SetSystemValue3` unit
  as unverified-but-assumed-radians pending empirical confirmation).

---

### IDimension::SetSystemValue3

- **Interface:** IDimension
- **Method:** SetSystemValue3
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Function SetSystemValue3( _
   ByVal NewValue As System.Double, _
   ByVal WhichConfigurations As System.Integer, _
   ByVal Config_names As System.Object _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| NewValue | Double | **meters** | Yes | Dimension value in system units, per the page's own one-line description | |
| WhichConfigurations | Integer | n/a | Yes | Configuration(s) to set the value in — same enum as `SetValue3` | `swSetValueInConfiguration_e` |
| Config_names | Object | n/a | Only if `WhichConfigurations = swSetValue_InSpecificConfigurations` | A single `BSTR` or `BSTR` array of configuration names | |

**Returns:** `Integer` status code.

**Prior selection required:** None — operates directly on the `IDimension` object
reference, same as `SetValue3`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~SetSystemValue3.html

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- **Confirmed meters, unlike `SetValue3`:** the page's own one-line description
  reads "Sets the value of this dimension in **system units (meters)** in the
  specified configuration" — this dossier's `SetValue3` Gotcha's inference is now
  confirmed, not just presumed.
- `WhichConfigurations` reuses `swSetValueInConfiguration_e`, the same enum as
  `SetValue3` (not a separate `SystemValue`-specific enum).
- Per the page's Remarks: `WhichConfigurations` is ignored entirely if the part has
  only one configuration; `Config_names` is only consulted when
  `WhichConfigurations = swSetValue_InSpecificConfigurations`.
- This method can set a **read-only** dimension's value (per the page's Remarks) —
  check `IDimension::ReadOnly` first if that distinction matters to a caller
  (not itself documented in this dossier).
- Return status is `swSetValueReturnStatus_e` (documented in the Enums section) —
  `0` (`swSetValue_Successful`) is the only success value; every other member is a
  specific, named failure reason worth surfacing verbatim rather than collapsing to
  a generic error.

---

### IDimension::GetSystemValue3

- **Interface:** IDimension
- **Method:** GetSystemValue3
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Function GetSystemValue3( _
   ByVal WhichConfigurations As System.Integer, _
   ByVal Config_names As System.Object _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| WhichConfigurations | Integer | n/a | Yes | Configuration to read the value from | `swInConfigurationOpts_e` |
| Config_names | Object | n/a | Only if `WhichConfigurations = swSpecifyConfiguration` | Name(s) of the configuration | |

**Returns:** `Object`, actually a `Double` — the dimension's value in system units
(meters), per the page's own one-line description ("Gets the value of the current
dimension in system units in the named configuration").

**Prior selection required:** None — operates directly on the `IDimension` object
reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~GetSystemValue3.html

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- **`WhichConfigurations` here is a *different* enum than `SetSystemValue3`'s
  parameter of the same name** — the setter takes `swSetValueInConfiguration_e`,
  this getter takes `swInConfigurationOpts_e` (also documented in the Enums
  section). The two enums happen to agree on `1` meaning "this configuration only"
  (`swSetValue_InThisConfiguration` / `swThisConfiguration`), which is what this
  dossier's tool layer standardizes on for both directions, but do not assume the
  rest of the members line up positionally.
- No documented failure value distinct from a real `0.0` reading — a caller cannot
  tell "value is zero" from "read failed" off the return alone.

---

### IDimension::FullName

- **Interface:** IDimension
- **Property:** FullName (read-only)
- **Minimum SW version:** unverified — no explicit Availability line was present on
  the fetched page content for this property.

**Signature:**

```vb
ReadOnly Property FullName As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none — read-only property)* | | | | | |

**Returns:** `String` — `<Dimension Name>@<Feature Name>@<Model>`, e.g.
`"D1@Sketch1@Part4.Part"`. `<Dimension Name>` alone is `IDimension::Name` (the bare,
not-necessarily-unique-across-the-document name); `FullName` is the fully-qualified
form this dossier's `SelectByID2` record documents as the expected `Name` argument
format for re-selecting a dimension by name (e.g. `"D1@Sketch2@Part1.SLDPRT"` in that
record's own parameter table).

**Prior selection required:** None — a plain property read on an already-held
`IDimension` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~FullName.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDimension~Name.html (the bare, non-qualified name `FullName` is built from)

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- This dossier's tool layer uses `FullName` (not the bare `Name`) as the identifier
  it returns from a dimension-creating call and accepts as `dimension_name` into
  `set_dimension_value`/`set_dimension_text` — it round-trips cleanly through
  `SelectByID2`'s `Name` argument for a drawing dimension, while the bare `Name`
  alone is ambiguous across features/models sharing a dimension label like `"D1"`.

---

### IDisplayDimension::SetText

- **Interface:** IDisplayDimension
- **Method:** SetText
- **Minimum SW version:** unverified — no explicit Availability line was present on
  the fetched page content for this method.

**Signature:**

```vb
Sub SetText( _
   ByVal WhichText As System.Integer, _
   ByVal Text As System.String _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| WhichText | Integer | n/a | Yes | Which text slot to set | `swDimensionTextParts_e` |
| Text | String | n/a | Yes | Text to place above the dimension line | |

**Returns:** None (`Sub`).

**Prior selection required:** None — operates on the `IDisplayDimension` object
reference directly, not on the current `ISelectionMgr` selection.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~SetText.html

**status:** verified

**Gotchas:**
- Passing `swDimensionTextParts_e.swDimensionTextAll` replaces the **entire**
  dimension text: SolidWorks puts the input string into the prefix slot, clears the
  suffix and callout text, and turns off the numeric dimension value display (see
  `IDisplayDimension::ShowDimensionValue`, not documented in this dossier) — a
  full-text overwrite silently also disables the live value.
- Call `IModelDoc2::GraphicsRedraw2` afterward — the graphics window does not
  auto-refresh to show the new text.
- Does **not** support hole callouts — calling this on a hole-callout display
  dimension is explicitly unsupported per the page's NOTE.
- Related but separate: `IDisplayDimension::SetLowerText`/`GetLowerText` control the
  text *below* the dimension line (not documented in this dossier).

---

### IDisplayDimension::GetText

- **Interface:** IDisplayDimension
- **Method:** GetText
- **Minimum SW version:** unverified — no explicit Availability line was present on
  the fetched page content for this method.

**Signature:**

```vb
Function GetText( _
   ByVal WhichText As System.Integer _
) As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| WhichText | Integer | n/a | Yes | Which text slot to read | `swDimensionTextParts_e` |

**Returns:** `String` — the text above the dimension line for the requested slot.

**Prior selection required:** None — operates on the `IDisplayDimension` object
reference directly.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~GetText.html

**status:** verified

**Gotchas:**
- Unlike `SetText`, `swDimensionTextParts_e.swDimensionTextAll` is **explicitly not a
  valid value** for `GetText`'s `WhichText` parameter — the get/set pair is
  asymmetric.
- Does not support hole callouts (same NOTE as `SetText`).

---

### IModelDocExtension::AddOrdinateDimension

- **Interface:** IModelDocExtension
- **Method:** AddOrdinateDimension
- **Minimum SW version:** SOLIDWORKS 2007 FCS (Revision Number 15.0)

**Signature:**

```vb
Function AddOrdinateDimension( _
   ByVal DimType As System.Integer, _
   ByVal LocX As System.Double, _
   ByVal LocY As System.Double, _
   ByVal LocZ As System.Double _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| DimType | Integer | n/a | Yes | Ordinate dimension type | `swAddOrdinateDims_e` |
| LocX | Double | meters | Yes | X location for the dimension | |
| LocY | Double | meters | Yes | Y location for the dimension | |
| LocZ | Double | meters | Yes | Z location for the dimension | |

**Returns:** `Integer` error code as defined by `swCreateOrdDimError_e` (not fetched
in this pass — treat non-zero/non-success codes as unverified until that enum is
checked).

**Prior selection required:** Yes — multi-step, order-sensitive. First, select the
base entity (e.g. a vertex or edge) to act as the **datum point** for the ordinate
dimension group, then select any additional entities to include in that same group,
before calling this method. Selections made **after** the call continue to add more
ordinate dimensions to the same group — the selection/call sequence is "select datum
+ select group members, call once for the first member, then keep selecting to extend
the group," not strictly "select-then-act once." Call `IModelDoc2::SetPickMode`
afterward to leave ordinate group-building mode and return to the default selection
mode. To add dimensions to a group created in an earlier call, use
`IModelDoc2::EditOrdinate` instead of calling this again.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~AddOrdinateDimension.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AddOrdinateDimension2.html (corroborates supersession — see Gotchas)

**status:** verified

**Gotchas:**
- **Supersedes `IDrawingDoc::AddOrdinateDimension2`**, which the 2025 help page marks
  "Obsolete. Superseded by IModelDocExtension::AddOrdinateDimension" — confirmed by
  directly fetching the obsolete page, not inferred. Its signature was identical
  (`DimType, LocX, LocY, LocZ`) apart from moving from `IDrawingDoc` to
  `IModelDocExtension`; do not implement against the obsolete `IDrawingDoc` version.
- This method's selection-continuation behavior (selections after the call keep
  adding to the group) is a genuine exception to a clean select-then-act model — the
  tool layer will need to explicitly call `SetPickMode` to close out a group rather
  than assuming one call is atomic.
- Distinct from `IDrawingDoc::CreateOrdinateDim4` (below), which creates a **single,
  non-associative** ordinate dimension from explicit point/vector arrays instead of a
  selection-built, geometry-associative group.

---

### IModelDoc2::SetPickMode

- **Interface:** IModelDoc2
- **Method:** SetPickMode
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS, Revision Number 10.0

Fetched independently (sw-1xx.2) — the `AddOrdinateDimension` record above (and the
working agreement's "signatures come from the dossier, fetched when missing rather
than guessed") requires this method's actual signature before a tool layer can call
it, not just its existence.

**Signature:**

```vb
Sub SetPickMode()
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none — zero-argument `Sub`)* | | | | | |

**Returns:** None (`Sub`).

**Prior selection required:** None documented — the page's only description is
"Returns the user to the default selection mode."

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~SetPickMode.html

**status:** verified (fetched sw-1xx.2)

**Gotchas:**
- Confirmed zero-argument — the page's own VB/C#/C++ syntax blocks all show no
  parameters. A tool layer calling it with any argument would be guessing past what's
  documented.

---

### IDrawingDoc::CreateOrdinateDim4

- **Interface:** IDrawingDoc
- **Method:** CreateOrdinateDim4
- **Minimum SW version:** SOLIDWORKS 2000 FCS (Revision Number 8.0)

**Signature:**

```vb
Function CreateOrdinateDim4( _
   ByVal P0 As System.Object, _
   ByVal P1 As System.Object, _
   ByVal P2 As System.Object, _
   ByVal P3 As System.Object, _
   ByVal P4 As System.Object, _
   ByVal P5 As System.Object, _
   ByVal Val As System.Double, _
   ByVal Angle As System.Double, _
   ByVal TextHeight As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| P0 | Object (double[3]) | meters | Yes | Dimension point (x,y,z) | |
| P1 | Object (double[3]) | n/a (unit vector) | Yes | Unit vector giving the ordinate dimension's direction | |
| P2 | Object (double[3]) | meters | Yes | Extension line start point (x,y,z) | |
| P3 | Object (double[3]) | meters | Yes | Extension line end point (x,y,z) | |
| P4 | Object (double[3]) | n/a (unit vector) | Yes | Unit vector giving the text orientation, e.g. `(1,0,0)` = horizontal, left-to-right | |
| P5 | Object (double[3]) | meters | Yes | Text position (x,y,z) | |
| Val | Double | meters (page does not state units explicitly; meters follows this API's global convention — see Gotchas) | Yes | Value for the ordinate dimension | |
| Angle | Double | radians | Yes | Inclination angle of the text (character slant) | |
| TextHeight | Double | meters | Yes | Text height | |

**Returns:** `Object`, a display dimension (`IDisplayDimension`). No documented
failure value.

**Prior selection required:** **None.** This is the one dimension-creation method in
this section that does *not* consume the current `ISelectionMgr` selection — every
geometric input is passed explicitly as a point/vector array argument instead.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateOrdinateDim4.html

**status:** verified

**Gotchas:**
- The page explicitly calls this "a non-associative ordinate dimension" and states
  "the dimension is not related to the geometry" — the points define a dimension
  between arbitrary coordinates, not a live-linked reference to a specific
  edge/vertex. If the tool layer needs a dimension that updates when the model
  changes, use `IModelDocExtension::AddOrdinateDimension` (selection-based,
  associative) instead.
- `Val` units are not explicitly stated on the page (unlike `TextHeight`, which is
  explicitly "in meters"); meters is assumed here only by this API's global
  meters/radians convention, not a direct page statement — flag as a soft-unverified
  assumption if a caller hits unexpected scaling.

## Text and notes

`IModelDocExtension::CreateText3` does not exist — confirmed two independent ways: it
is absent from the fetched `IModelDocExtension_members.html` index, and a direct fetch
of its exact URL returns the help site's own file-not-found JSON. Text/note creation
at an explicit sheet location lives on `IDrawingDoc`, and the current overload is
`CreateText2`.

### IDrawingDoc::CreateText2

- **Interface:** IDrawingDoc
- **Method:** CreateText2 — requested as `IModelDocExtension::CreateText3`, which does
  not exist (see the section intro above)
- **Minimum SW version:** not stated on the fetched page (no Availability section
  present); pages for `CreateText2` exist in the archived 2012 API Help index, so
  present since at least SOLIDWORKS 2012.

**Signature:**

```vb
Function CreateText2( _
   ByVal TextString As System.String, _
   ByVal TextX As System.Double, _
   ByVal TextY As System.Double, _
   ByVal TextZ As System.Double, _
   ByVal TextHeight As System.Double, _
   ByVal TextAngle As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| TextString | String | n/a | Yes | User input text for the note | |
| TextX | Double | meters | Yes | X location of the upper-left corner of the text's bounding box, relative to the lower-left corner of the drawing sheet (per Remarks) | |
| TextY | Double | meters | Yes | Y location of the upper-left corner of the text's bounding box | |
| TextZ | Double | meters | Yes | Z location; sheet space is 2D so this is very likely an inert placement coordinate by analogy with every other sheet-space Z parameter in this API, but this specific page does not state that explicitly | |
| TextHeight | Double | meters | Yes | Text height (page states "in meters" explicitly) | |
| TextAngle | Double | radians | Yes | Text angle for rotated text (page states "in radians" explicitly) | |

**Returns:** `System.Object` — "Newly created note" (an `INote`) on success. Failure
return not documented; treat `Nothing`/null as failure until confirmed live.

**Prior selection required:** None. Called directly on `IDrawingDoc` with explicit
`TextX`/`TextY`/`TextZ` — unlike `IModelDoc2::InsertNote` (a more general,
part/assembly/drawing-agnostic alternative for note creation, not independently
documented in this dossier), this method does not read `ISelectionMgr` state for
leader attachment.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateText2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms `IDrawingDoc` has exactly `CreateText` obsolete / `CreateText2` current — no `CreateText3`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension_members.html (confirms `IModelDocExtension` has zero `CreateText*` members — only unrelated `CreateTexture`/`GetTexture`/etc.)
- Direct fetch of the constructed `IModelDocExtension~CreateText3.html` URL returned the server's own JSON error: `"...Error checking file existence: File does not exist..."` — a genuine content-negative signal, not a network/access failure.

**status:** verified

**Gotchas:**
- **`IModelDocExtension::CreateText3` does not exist**, confirmed two independent ways
  (member-index absence + the server's own file-not-found JSON). Text/note creation
  at an explicit sheet location lives on `IDrawingDoc`, and the current overload is
  `CreateText2` — documented here in `CreateText3`'s place.
- **`$PRP`/`$PRPSHEET` linked-note-text syntax — this dossier's critical acceptance
  criterion. Fully confirmed from official pages:**
  - Exact token form: `$PRP:"PropertyName"` — dollar sign, `PRP`, colon, no space,
    then the property name in **straight** double quotes. Curved/smart quotes are
    explicitly called out (Design Help) as causing SOLIDWORKS to read the text
    literally instead of resolving the link.
  - All four documented prefixes, from the official "Link to Property" page's own
    table:

    | Prefix | Evaluated from |
    | --- | --- |
    | `$PRP:` | Current document (the drawing itself — its own custom/document properties) |
    | `$PRPSHEET:` | The model in the view specified in Sheet Properties → "Use custom property values from model shown in." If that setting is "Default": for view-attached notes, the model in the drawing view the note belongs to; for sheet/sheet-format notes, the first view in the FeatureManager tree |
    | `$PRPVIEW:` | The model in the specific drawing view the note is attached to |
    | `$PRPMODEL:` | The component the annotation is attached to (assembly context) |

  - Official worked example ("Linking Notes to Document Properties"), one note
    mixing literal text and two links:
    ```
    SHEET $PRP:"SW-Current Sheet" OF $PRP:"SW-Total Sheets"
    ```
    renders as `SHEET 1 OF 2` on the first sheet of a two-sheet drawing.
  - Official API-level confirmation, from `INote::PropertyLinkedText`'s own help page,
    contrasting the unresolved link string against its resolved display value:
    ```
    PropertyLinkedText = Date: ($PRPVIEW:"SW-Long Date")
    GetText (resolved)  = Date: (Monday, December 16, 2016)
    ```
  - **Quoting inside a COM string literal is a property of the calling language, not
    of SolidWorks** — the literal `"` characters must survive into the actual string
    value SolidWorks parses:
    - **VBA**: double the quote to embed one literal `"`:
      `swNote.PropertyLinkedText = "Weight: $PRP:""SW-Mass"""` → runtime value
      `Weight: $PRP:"SW-Mass"`
    - **C#**: `swNote.PropertyLinkedText = "Weight: $PRP:\"SW-Mass\"";` or a verbatim
      string `@"Weight: $PRP:""SW-Mass""";`
  - **Confirmed API mechanism: `INote::PropertyLinkedText`** (get/set `String`
    property on the `Note`/`INote` object returned by `CreateText2`), documented
    verbatim as "Gets or sets the text for the note using the values of the
    properties linked to the note." This is the confirmed way to author `$PRP`-style
    linked text via the API:
    ```vb
    Dim swNote As SldWorks.Note
    Set swNote = swDraw.CreateText2("", 0.05, 0.05, 0, 0.0035, 0)
    swNote.PropertyLinkedText = "Weight: $PRP:""SW-Mass"""
    ```
  - **Not confirmed either way: whether passing a `$PRP:"..."` string directly as
    `CreateText2`'s `TextString` argument at creation time also triggers link
    parsing**, versus being taken as inert literal text. Treat the verified, safe
    workflow as: create the note first, then set `.PropertyLinkedText` on the
    returned object.
  - `$PRP` vs `$PRPSHEET`: `$PRP:"Weight"` reads a custom property defined **on the
    drawing document itself**; `$PRPSHEET:"Weight"` reads the same-named property
    **on the model referenced by the current sheet's "model shown in" setting**
    (drawing-scoped vs. model-scoped). This is why `$PRPSHEET` is the one commonly
    used in title blocks for part properties like mass/material that live on the
    part, not the drawing.
  - Unresolvable property → note displays `ERROR!<variable name>` (visibility toggled
    via View > Annotation Link Errors — not an API-surfaced exception).

---

### IDrawingDoc::CreateText

- **Interface:** IDrawingDoc
- **Method:** CreateText
- **Minimum SW version:** not stated; explicitly marked obsolete on its own page.

**Signature:**

```vb
Function CreateText( _
   ByVal TextString As System.String, _
   ByVal TextX As System.Double, _
   ByVal TextY As System.Double, _
   ByVal TextZ As System.Double, _
   ByVal TextHeight As System.Double, _
   ByVal TextAngle As System.Double _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| TextString | String | n/a | Yes | Text for the note (page has no per-parameter Remarks at all, just the bare syntax block) | |
| TextX | Double | meters (by analogy with `CreateText2`; not restated) | Yes | X location | |
| TextY | Double | meters (by analogy) | Yes | Y location | |
| TextZ | Double | meters (by analogy) | Yes | Z location | |
| TextHeight | Double | meters (by analogy) | Yes | Text height | |
| TextAngle | Double | radians (by analogy) | Yes | Text angle | |

**Returns:** `System.Boolean` — success flag only. Unlike `CreateText2`, it does
**not** return the created note object.

**Prior selection required:** None — same calling pattern as `CreateText2`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateText.html (verbatim page text: "Obsolete. Superseded by IDrawingDoc::CreateText2.")
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateText2.html

**status:** verified

**Gotchas:**
- Identical 6-parameter signature/order to `CreateText2`; the only functional
  difference is the return type. `CreateText`'s bare `Boolean` gives no handle to the
  created note — which makes it **unusable** for the `$PRP` property-link workflow
  above, since that requires calling `.PropertyLinkedText` on the returned note
  object afterward. This is why `CreateText2` is the one that matters for a tool
  layer, not `CreateText`.
- Neither page's Remarks mention `$PRP` at all — property-link capability is a
  general feature of note-text parsing (via `INote::PropertyLinkedText`), not
  something either `CreateText` variant opts in/out of via a parameter.

### Note enumeration and editing (sw-1xx.3)

Fetched for `list_notes`/`edit_note`'s requirements. **Every direct
`help.solidworks.com` fetch attempted for this addendum returned the same HTTP 403
this dossier's intro and `IDrawingDoc::CreateText2`'s own record already document for
this research environment** — tried against `IView::GetAnnotations` (a 2024/2025
member that search hits confirm exists, but whose page content 403'd both times),
`INote::SetText`, `Get_Annotations_Example_VB.htm`, and
`get_all_notes_in_drawing_template_example_vb.htm` alike, ruling out a
URL-pattern-specific block. This record instead documents the **legacy,
independently-corroborated `GetFirst`/`GetNext` walk**, quoted via search-engine
snippets of two convergent official pages (page content itself not directly
fetchable) — the official "Get All Notes in Drawing Template Example (VBA)" page:

```vb
Set swView = swDraw.GetFirstView   ' "This is the drawing template"
Set swNote = swView.GetFirstNote
Do While Not swNote Is Nothing
    Set swAnn = swNote.GetAnnotation
    Debug.Print " " & swNote.GetName
    Debug.Print " " & swNote.GetText
    Set swNote = swNote.GetNext
Loop
```

- **Interface:** IView (`GetFirstNote`) / INote (`GetNext`)
- **Method:** GetFirstNote + GetNext — requested/assumed as `IView::GetAnnotations`
  (a real, current member, but its page 403'd every attempted fetch, so this dossier
  falls back to the older, search-corroborated pair instead of guessing
  `GetAnnotations`' parameters)
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetFirstNote() As System.Object   ' IView, returns first INote or Nothing
Function GetNext() As System.Object        ' INote, returns next sibling INote or Nothing
```

**Parameters:** neither method takes any.

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | | n/a | | Both are zero-arg accessors | |

**Returns:** `System.Object` — an `INote`, or `Nothing`/`None` past the last note in
the chain (per the quoted example's `Do While Not swNote Is Nothing` termination).

**Prior selection required:** None — both are read directly off an already-held
`IView`/`INote` reference.

**Source URL(s):**
- https://help.solidworks.com/2016/english/api/sldworksapi/get_all_notes_in_drawing_template_example_vb.htm (attempted, 403; content via search snippet)
- https://help.solidworks.com/2025/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~GetAnnotations.html (the modern alternative attempted first; 403, not used)

**status:** unverified — corroborated only via search-engine snippets of the official
page, not a direct page read; the exact call syntax (parens vs. bare property, per
this API's general property/method inconsistency already noted elsewhere in this
project) is not independently confirmed.

**Gotchas:**
- **`IDrawingDoc::GetFirstView`** returns, per the quoted example's own inline
  comment, the **sheet's own pseudo/template view** first — this is where
  sheet-level/title-block notes (including `$PRP`/`$PRPSHEET`-linked ones) live, not
  on any of the sheet's "real" geometry views. `IView::GetNextView` then walks every
  remaining view **across the whole document** (every real view, then the next
  sheet's own pseudo-view, and so on) — confirmed by a second, convergent official
  example ("Change Note Text Example (VBA)"):
  ```vb
  While Not swView Is Nothing
      Set swNote = swView.GetFirstNote
      While Not swNote Is Nothing
          ' ... (see INote::GetText/SetText record below for the compound-note branch)
          Set swNote = swNote.GetNext
      Wend
      Set swView = swView.GetNextView
  Wend
  ```
  This project's own `list_views`/`_sheet_view_fill_state` (`02-views.md`) already
  distinguish a pseudo-view from a real one via `IView::Type == swDrawingSheet`
  (`SwDrawingViewTypes.swDrawingSheet`), reused by `list_notes`/`edit_note` to tag
  which walked "view" is actually a sheet.
- **`GetFirstNote` lives on `IView`, not `INote`** (`view.GetFirstNote`, not
  `note.GetFirstNote`) — only the chain-walk `GetNext` is on `INote` itself.
- **`INote::GetAnnotation`** (used in the quoted example) returns the note's
  `IAnnotation` wrapper — the same object `SetPosition2`/`SetLeader3`/`Layer`
  (documented above) act on.

---

### IAnnotation::GetName (sw-1xx.3)

- **Interface:** IAnnotation
- **Method:** GetName — companion `SetName` also exists (per the official "Get and
  Set Names of Note Example (VBA)" page title)
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetName() As System.String
Function SetName(ByVal Name As System.String) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name (SetName) | String | n/a | Yes | New name for the annotation | |

**Returns:** `GetName` — `String`, the annotation's current name (e.g. `"Note1"`).
`SetName` — `Boolean`, success flag (failure mode not stated in any accessible
source).

**Prior selection required:** None — read/write directly on an already-held
`IAnnotation` reference (e.g. from `INote::GetAnnotation`).

**Source URL(s):**
- https://help.solidworks.com/2019/english/api/sldworksapi/get_and_set_names_of_note_example_vb.htm (attempted, 403; title/content summary via search snippet only)

**status:** unverified — corroborated only via a search-engine summary of the
official page's title and content, not a direct page read. This is what
`list_notes`'/`edit_note`'s `note_name` matches against.

---

### IAnnotation::GetPosition (sw-1xx.3)

- **Interface:** IAnnotation
- **Method:** GetPosition — the read counterpart of `IAnnotation::SetPosition2`
  (documented above)
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetPosition() As System.Object
```

**Parameters:** none.

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | | n/a | | Zero-arg accessor | |

**Returns:** `System.Object` — an array of 3 doubles, the annotation's X/Y/Z origin
in meters (unit inferred by symmetry with `SetPosition2`'s confirmed meters
parameters, documented above — not independently restated on this method's own page,
which 403'd on every fetch attempt).

**Prior selection required:** None — read directly off an already-held
`IAnnotation` reference.

**Source URL(s):**
- https://help.solidworks.com/2022/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IAnnotation~GetPosition.html (attempted, 403; content via search snippet only)

**status:** unverified — corroborated only via a search-engine summary, not a direct
page read; the meters unit is an inference by symmetry with `SetPosition2`, not an
independently confirmed statement from this method's own page.

---

### IAnnotation::SetLeaderAttachmentPointAtIndex (sw-1xx.3)

- **Interface:** IAnnotation
- **Method:** SetLeaderAttachmentPointAtIndex
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function SetLeaderAttachmentPointAtIndex( _
   ByVal Index As System.Integer, _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Index | Integer | n/a | Yes | Index of the leader point to set (a multi-point leader, e.g. GTol all-around, has more than one) | |
| X | Double | meters (by analogy with every other sheet/model-space coordinate in this API — not independently restated on the page snippet) | Yes | X coordinate of the leader attachment point | |
| Y | Double | meters (by analogy) | Yes | Y coordinate | |
| Z | Double | meters (by analogy) | Yes | Z coordinate | |

**Returns:** `Boolean` — `True` if the leader attached successfully, `False` if not
(failure cause not stated in any accessible source).

**Prior selection required:** None via `ISelectionMgr` — invoked directly on an
already-held `IAnnotation` reference with an **explicit coordinate**, not a picked
entity. This is the key gotcha: despite the name's resemblance to the
selection-driven "attach to this picked entity" pattern used elsewhere in this
dossier (`InsertGtol`, `InsertDatumTargetSymbol3`), it is not selection-based — the
tool layer's `add_note` therefore accepts an explicit leader attachment point
(`leader["x"]`/`["y"]`/`["z"]`, caller's unit), not an entity reference.

**Source URL(s):**
- https://help.solidworks.com/2018/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetLeaderAttachmentPointAtIndex.html (attempted, 403; signature via search snippet only, which quoted a real worked-example call: `swAnnot.SetLeaderAttachmentPointAtIndex(0, 0.687021207260901, 0.599975917260352, 250.03275)`)

**status:** unverified — corroborated only via a search-engine snippet quoting a
real call site (confirming parameter count/order), not a direct page read; the
meters unit on X/Y/Z is an inference by analogy, not independently confirmed.

---

### INote::GetText + SetText (sw-1xx.3)

- **Interface:** INote
- **Method:** GetText / SetText, plus the compound-note family
  (`IsCompoundNote`/`GetTextCount`/`GetTextAtIndex`/`SetTextAtIndex`)
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetText() As System.String
Function SetText(ByVal Text As System.String) As System.Boolean
Function IsCompoundNote() As System.Boolean
Function GetTextCount() As System.Integer
Function GetTextAtIndex(ByVal Index As System.Integer) As System.String
Function SetTextAtIndex(ByVal Index As System.Integer, ByVal Text As System.String) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Text (SetText/SetTextAtIndex) | String | n/a | Yes | New note text. A literal line-feed character (`vbLf`/`Chr(10)`) inside the string starts a new line -- confirmed via a search-summarized official example pattern (`"First Line" & vbLf & "Second Line"`). Python's `\n` **is** `Chr(10)`, so this project's `add_note`/`edit_note` `text` argument needs no transformation, passed straight through. | |
| Index (GetTextAtIndex/SetTextAtIndex) | Integer | n/a | Yes | 1-based run index, per the official "Change Note Text Example (VBA)" page's own loop (`For i = 1 To nTextCount`) | |

**Returns:** `GetText`/`GetTextAtIndex` — `String`. `SetText`/`SetTextAtIndex` —
`Boolean` success flag. `IsCompoundNote` — `Boolean`, `True` for a note built from
multiple independently-formatted/linked text runs (e.g. mixing literal text with
more than one `$PRP`-style link in the same note). `GetTextCount` — `Integer`, the
number of runs (only meaningful when `IsCompoundNote` is `True`).

**Prior selection required:** None — read/write directly on an already-held `INote`
reference.

**Source URL(s):**
- https://help.solidworks.com/2024/English/api/sldworksapi/Change_Note_Text_Example_VB.htm (attempted, 403; quoted verbatim via search snippet):
  ```vb
  If swNote.IsCompoundNote Then
      nTextCount = swNote.GetTextCount
      For i = 1 To nTextCount
          sNoteText = swNote.GetTextAtIndex(i)
          DoReplaceString sNoteText
          swNote.SetTextAtIndex i, sNoteText
      Next i
  Else
      sNoteText = swNote.GetText
      DoReplaceString sNoteText
      swNote.SetText sNoteText
  End If
  ```

**status:** unverified — corroborated only via a search-engine snippet quoting the
official example verbatim, not a direct page read. A tool layer only creating
single-run notes via `CreateText2` (sw-1xx.3's scope) does not need the compound
branch, but `list_notes`/`edit_note` should not assume every note it walks is
simple — `_describe_note` reports `is_compound` for that reason.

**Gotchas:**
- **`<FONT>` inline bold/italic/underline instruction** — confirmed via a direct,
  successful fetch of an independent secondary source (not help.solidworks.com, so
  not subject to the WAF block above):
  https://www.codestack.net/solidworks-api/document/notes/format-note-text/. Quoted
  verbatim from that page: the `<FONT>` instruction "has 2 attributes" — `effect`
  (`U` underline / `RU` remove underline) and `style` (`B` bold / `RB` remove bold /
  `I` italic / `RI` remove italic) — and "All the text after the `<FONT>`
  instruction will be formatted according to the value of `effect` and `style`"
  until the next `<FONT>` tag. Worked example from that page:
  ```
  <FONT effect=U>First Line Underline
  <FONT style=B effect=RU>Second Line Bold
  <FONT style=RB><FONT style=I>Third Line Italic
  ```
  Each dimension (bold vs. italic vs. underline) is independent — chaining
  `<FONT style=B><FONT style=I>` at the start of a string is this dossier's inferred
  way to request **both** bold and italic together (the page's own examples never
  combine two `style=` values in one instruction, only in two consecutive tags),
  since `style=` only documents one value per instruction. The page frames `<FONT>`
  as a general note-text parsing feature (demonstrated there via
  `PropertyLinkedText`), not confirmed independently against plain `SetText`/
  `CreateText2` `TextString` content — `add_note`'s bold/italic support is therefore
  an inference by analogy, flagged here rather than asserted as directly confirmed.

## GD&T (geometric tolerancing)

`IModelDocExtension::CreateGTOL` does not exist — absent from the `IModelDocExtension`
member index, and a direct fetch of its exact URL returns the help site's file-not-found
JSON. The real method is `IModelDoc2::InsertGtol`.

### IModelDoc2::InsertGtol

- **Interface:** IModelDoc2
- **Method:** InsertGtol — requested as `IModelDocExtension::CreateGTOL`, which does
  not exist (confirmed by both the member-index absence on `IModelDocExtension` and a
  file-not-found JSON on direct fetch)
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS, Revision Number 10.0

**Signature:**

```vb
Function InsertGtol() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters — creates an **empty** GTol symbol | |

**Returns:** `System.Object` — the newly created (empty) `IGtol`. Failure return not
documented; treat `Nothing` as failure until confirmed live.

**Prior selection required:** Optional but behavior-changing, per the page's own
Remarks: "The leader attachment point for the newly created GTol object comes from
the selection made before calling this method. The initial location of the symbol is
near the selection location. If there is no selection, then the GTol does not have a
leader, is free standing, and is initially at the origin of the model or drawing."

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertGtol.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension_members.html (confirms no `CreateGTOL`/`GTol`-named member exists on `IModelDocExtension`)
- https://help.solidworks.com/2025/english/api/sldworksapi/Insert_GTol_Example_VB.htm (full official worked example, quoted in Gotchas of `SetFrameSymbols2`/`SetFrameValues2` below)

**status:** verified

**Gotchas — the critical section for this dossier's feature-control-frame syntax
requirement:**
- **`InsertGtol` only creates an empty symbol.** Per its own Remarks: "This method
  creates an empty symbol. To fill in the text and symbols of this GTol, use the
  pointer returned by this method to access the various get and set methods of the
  `IGTol` interface, such as `IGtol::SetFrameSymbols2` and `IGtol::SetFrameValues2`."
  **There is no single "content string" parameter on the creation call itself** —
  contrary to what the requested name (`CreateGTOL(..., contentString, ...)`)
  implies. The frame content is built with a *sequence* of calls after creation,
  documented in the next two records. (An older, `IDrawingDoc`-scoped alternative
  factory, `IDrawingDoc::NewGtol`, also exists — same zero-arg/object-return shape,
  not independently compared here.)
- **Two entirely different, format-dependent mechanisms exist for filling in frame
  content**, and this is a major, easy-to-miss trap for a 2025-targeting tool layer:
  1. **Legacy format** (GTols created before SOLIDWORKS 2022):
     `IGtol::SetFrameSymbols2` + `IGtol::SetFrameValues2`, using bracket-token strings
     like `<IGTOL-POSI>`/`<MOD-MMC>` referencing `gtol.sym`. This is what the only
     available official worked example uses.
  2. **Current/2022+ format**: `IGtol::GetFrame(FrameIndex)` → `IGtolFrame` →
     `IGtolFrame::SetSymbolXml(XmlString)`, using a full XML schema
     (`<GtolFrame>...`). Both `GetFrame` and `SetSymbolXml` carry Availability:
     SOLIDWORKS 2023 FCS, Revision 31, and each is explicitly scoped: `GetFrame`'s
     Remarks read "This method is valid only if this Gtol was created in SOLIDWORKS
     2022 or later"; `SetFrameSymbols2`/`SetFrameValues2` each read "This method is
     valid only if this Gtol was created in a version of SOLIDWORKS earlier than
     2022." These two mechanisms are **mutually exclusive per-GTol**, gated by the
     GTol object's internal format, not by which method you call `InsertGtol` from.
  - **Open question, not resolved by any accessible source: which format does
    `InsertGtol()` produce by default in a document created/edited under SOLIDWORKS
    2025?** Given 2022+ is now the long-standing native format, it is plausible new
    GTols default to the new format — in which case `SetFrameSymbols2`/
    `SetFrameValues2` (the only mechanism with a full official worked example) may
    silently fail or no-op on freshly-created GTols, and `GetFrame`→`SetSymbolXml`
    would be required instead. `IGtol::CanConvertFormat`/`ConvertFormat` exist to
    convert a legacy-format GTol to the current format, which only makes sense if
    legacy-format GTols can still be produced/encountered — but doesn't settle what a
    bare `InsertGtol()` call yields today. **This must be verified empirically
    against a live SOLIDWORKS 2025 session before a tool layer commits to either path
    exclusively; do not assume the legacy path works.**
- A tool layer wrapping this should probably attempt `SetFrameSymbols2`/
  `SetFrameValues2` and, on failure/no-op, fall back to `GetFrame`→`SetSymbolXml` (or
  vice versa) — or call `IGtol::CanConvertFormat`/`ConvertFormat` first to force a
  known format.

---

### IGtol::SetFrameSymbols2 + IGtol::SetFrameValues2 (legacy pre-2022-format frame content)

- **Interface:** IGtol
- **Method:** SetFrameSymbols2, then SetFrameValues2 (two-call sequence)
- **Minimum SW version:** SetFrameSymbols2 — not stated (no Availability section on
  its own page). SetFrameValues2 — SOLIDWORKS 2016 FCS, Revision Number 24.0.

**Signature:**

```vb
Sub SetFrameSymbols2( _
   ByVal FrameNumber As System.Short, _
   ByVal GCS As System.String, _
   ByVal TolDia1 As System.Boolean, _
   ByVal TolMC1 As System.String, _
   ByVal TolDia2 As System.Boolean, _
   ByVal TolMC2 As System.String, _
   ByVal DatumMC1 As System.String, _
   ByVal DatumMC2 As System.String, _
   ByVal DatumMC3 As System.String _
)

Function SetFrameValues2( _
   ByVal FrameNumber As System.Short, _
   ByVal Tol1 As System.String, _
   ByVal Tol2 As System.String, _
   ByVal Datum1 As System.String, _
   ByVal Datum2 As System.String, _
   ByVal Datum3 As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FrameNumber | Short | n/a | Yes | Feature control frame index; `1` for the first frame | |
| GCS | String | n/a | Yes | Geometric characteristic symbol, in `<LibraryName-SymbolName>` token format (see Gotchas) | |
| TolDia1 | Boolean | n/a | Yes | `True` if a diameter (⌀) symbol precedes tolerance 1 | |
| TolMC1 | String | n/a | Yes | Material-condition token for tolerance 1, e.g. `<MOD-MMC>`; `""` if none | |
| TolDia2 | Boolean | n/a | Yes | `True` if a diameter symbol precedes tolerance 2 | |
| TolMC2 | String | n/a | Yes | Material-condition token for tolerance 2; `""` if none | |
| DatumMC1 | String | n/a | Yes | Material-condition token(s) for the primary datum; `""` if none | |
| DatumMC2 | String | n/a | Yes | Material-condition token(s) for the secondary datum | |
| DatumMC3 | String | n/a | Yes | Material-condition token(s) for the tertiary datum | |
| Tol1 (SetFrameValues2) | String | n/a | Yes | Tolerance 1 numeric value as text, e.g. `"0.4"` | |
| Tol2 | String | n/a | Yes | Tolerance 2 value; `""` if unused | |
| Datum1 | String | n/a | Yes | Primary datum reference text — datum letter(s) optionally suffixed with material-condition tokens | |
| Datum2 | String | n/a | Yes | Secondary datum reference text | |
| Datum3 | String | n/a | Yes | Tertiary datum reference text | |

**Returns:** `SetFrameSymbols2` — none (`Sub`). `SetFrameValues2` — `Boolean`, `True`
if the values were set.

**Prior selection required:** None beyond having a valid `IGtol` object from
`InsertGtol()` — both methods operate directly on that object, no `ISelectionMgr`
state involved.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtol~SetFrameSymbols2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtol~SetFrameValues2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Insert_GTol_Example_VB.htm (official worked example, quoted below)

**status:** verified

**Gotchas — the feature-control-frame content string syntax, precisely, from the
fetched official pages:**
- **Symbol syntax is `<LibraryName-SymbolName>`**, referencing the text file
  `C:\ProgramData\SolidWorks\SolidWorks 20nn\lang\english\gtol.sym`. Confirmed
  examples straight from the official pages:
  - `GCS = "<IGTOL-POSI>"` — Position symbol, from the ISO Geometric Tolerancing
    Symbols library (`IGTOL`)
  - `TolMC1 = "<MOD-LMC>"` — Least Material Condition, from the Modifying Symbols
    library (`MOD`)
  - `TolMC1`/datum suffix `<MOD-MMC>` — Maximum Material Condition
  - `<MOD-RFS>` — Regardless of Feature Size, in the same `MOD` library (sw-1xx.4
    addendum: not in either official worked example, but confirmed to exist alongside
    `MOD-MMC`/`MOD-LMC` via a convergent search-engine summary of the `gtol.sym`
    `LibraryName-SymbolName` convention -- **unverified against a live session**,
    included here so `add_gtol`'s `material_condition="RFS"` has a real token to emit
    rather than silently emitting nothing)
  - The full library set is `GTOL`/`IGTOL`/`GGTOL`, each holding 14 tolerance symbols
    (`ANGULAR, CIRC, CONC, CYL, FLAT, LPROF, PARA, PERP, POSI, SPROF, SRUN, STRAIGHT,
    SYMMETRY, TRUN`), plus `LONG`/`AXIS` only in `GGTOL`.
- **Full official worked example** (`Insert_GTol_Example_VB.htm` — a position control
  with datums B, A, C and mixed MMC/LMC modifiers, transcribed verbatim, not
  reconstructed):
  ```vb
  Set swGtol = swModel.InsertGtol()
  swGtol.SetFrameSymbols2 1, "<IGTOL-POSI>", False, "", False, "", "", "", ""
  status = swGtol.SetFrameValues2(1, "0.4", "", "B-A-C<MOD-MMC>", "B<MOD-MMC>-C<MOD-LMC>", "C<MOD-MMC>-A")
  ```
  This sets frame 1 to: geometric characteristic = Position (`<IGTOL-POSI>`), no
  diameter symbol on tolerance 1 (`TolDia1=False`), tolerance value `0.4`, primary
  datum text `B-A-C<MOD-MMC>`, secondary datum text `B<MOD-MMC>-C<MOD-LMC>`, tertiary
  datum text `C<MOD-MMC>-A`.
- **A genuine, unresolved ambiguity worth flagging**: `SetFrameSymbols2` has
  dedicated `DatumMC1`/`DatumMC2`/`DatumMC3` string parameters explicitly documented
  as "Material condition symbols for primary/secondary/tertiary datum" — yet the
  official shipped example does **not** use them (passes `""` for all three) and
  instead embeds the `<MOD-MMC>`/`<MOD-LMC>` modifier tokens directly inline inside
  the `Datum1`/`Datum2`/`Datum3` strings passed to `SetFrameValues2`. Which is
  authoritative/preferred is not stated on either page — treat the
  inline-in-`SetFrameValues2` form as the safe, officially-demonstrated pattern, and
  treat driving it via `DatumMC1..3` as plausible but unconfirmed.
- **A diameter + MMC + plain A|B|C variant**, built strictly from the documented
  parameter meanings above (constructed, not transcribed — unverified against a live
  session):
  ```vb
  swGtol.SetFrameSymbols2 1, "<IGTOL-POSI>", True, "<MOD-MMC>", False, "", "", "", ""
  swGtol.SetFrameValues2 1, "0.4", "", "A", "B", "C"
  ```
  Intent: Position tolerance, diameter symbol on tolerance 1 (`TolDia1=True`), MMC
  modifier on tolerance 1 (`TolMC1="<MOD-MMC>"`), tolerance value `0.4`, unmodified
  datums A/B/C.
- Call order matters: `SetFrameSymbols2` must be called before `SetFrameValues2` for
  a given frame (stated in `SetFrameValues2`'s own Remarks).
- **Format-scoping**: both methods are documented, verbatim, as "valid only if this
  Gtol was created in a version of SOLIDWORKS earlier than 2022" — see the
  format-branching Gotcha on `InsertGtol` above; this is stated directly on both
  pages, not a hypothetical concern.

---

### IGtolFrame::SetSymbolXml (current/SW2022+-format frame content)

- **Interface:** IGtolFrame (obtained via `IGtol::GetFrame(FrameIndex)`)
- **Method:** SetSymbolXml
- **Minimum SW version:** SOLIDWORKS 2023 FCS, Revision Number 31

**Signature:**

```vb
Function SetSymbolXml( _
   ByVal Xmlstring As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Xmlstring | String | n/a | Yes | XML document describing the full content of one GTol feature-control frame (schema below) | |

**Returns:** `Boolean` — `True` if the XML string was successfully set (and,
implicitly, validated against the schema), `False` if not.

**Prior selection required:** None directly — operates on an `IGtolFrame` object
already obtained from `IGtol::GetFrame(FrameIndex)`, itself obtained from a GTol
created via `InsertGtol` (subject to the optional-selection behavior documented
there).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtolFrame~SetSymbolXml.html
- https://help.solidworks.com/2024/english/api/sldworksapiprogguide/Overview/Gtol_Frame_XML_Schema.htm (full XML schema, node-by-node UI mapping)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtol~GetFrame.html (Remarks: "This method is valid only if this Gtol was created in SOLIDWORKS 2022 or later")
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtol~ConvertFormat.html (converts a legacy-format GTol to current format; check `IGtol::CanConvertFormat` first)

**status:** verified

**Gotchas — the current-format frame content syntax, from the official "Gtol Frame
XML Schema" page:**
- Top-level node is `<GtolFrame>`. `<ToleranceSymbol>` is mandatory and takes a
  `<LibraryName-SymbolName>` string **with the angle brackets stripped** — e.g. the
  flatness symbol `<IGTOL-FLAT>` in `gtol.sym` becomes
  `<ToleranceSymbol>IGTOL-FLAT</ToleranceSymbol>` in the XML. (SOLIDWORKS re-adds the
  brackets internally.)
- Diameter/spherical-diameter/square modifiers on a tolerance value use
  `<PrimaryRangeSymbol>`/`<ToleranceZoneSymbol>`/`<RestrictedToleranceZoneLimitSymbol>`
  with legal values `phi` (diameter ⌀), `sPhi` (spherical diameter), `sqr` (square),
  or `deg` (degree, range-symbol nodes only).
- Material condition modifiers are a `<MaterialCondition>` block with boolean
  sub-nodes `<MaximumMaterialCondition>`/`<LeastMaterialCondition>`/
  `<ReciprocityRequirement>`/`<RegardlessToFeatureSize>`.
- Datum references are `<DatumCompartment>` blocks, each containing
  `<DatumDetail><DatumLetter>X</DatumLetter></DatumDetail>` (or, for grouped/sub-datums,
  nested `<Datums>`/`<SubDatums>`). Per-datum material condition uses
  `<DatumMaterialCondition>` with values `MaximumMaterialCondition`/
  `LeastMaterialCondition`/`RegardlessToFeatureSize`.
- **Worked example — position tolerance, diameter modifier, MMC, datums A|B|C**,
  assembled from the documented node names/legal-value sets above (constructed for
  this task, not copied verbatim from a single official example — high-confidence but
  unverified against a live session):
  ```xml
  <GtolFrame>
    <ToleranceSymbol>IGTOL-POSI</ToleranceSymbol>
    <ToleranceRangeInfo>
      <PrimaryToleranceValue>0.4</PrimaryToleranceValue>
      <PrimaryRangeSymbol>phi</PrimaryRangeSymbol>
    </ToleranceRangeInfo>
    <MaterialCondition>
      <MaximumMaterialCondition>true</MaximumMaterialCondition>
    </MaterialCondition>
    <DatumCompartment>
      <DatumDetail><DatumLetter>A</DatumLetter></DatumDetail>
    </DatumCompartment>
    <DatumCompartment>
      <DatumDetail><DatumLetter>B</DatumLetter></DatumDetail>
    </DatumCompartment>
    <DatumCompartment>
      <DatumDetail><DatumLetter>C</DatumLetter></DatumDetail>
    </DatumCompartment>
  </GtolFrame>
  ```
  Called as `frame.SetSymbolXml(xmlString)` where `frame = gtol.GetFrame(1)`.
- **This mechanism only applies to GTols in the "SOLIDWORKS 2022 format"** — mutually
  exclusive with the `SetFrameSymbols2`/`SetFrameValues2` mechanism above. See the
  unresolved format-default question flagged on `InsertGtol`.
- The XSD schema file itself is shipped locally at `install_dir\data\xmlschema` —
  worth validating against directly rather than trusting hand-built XML strings
  blind.
- Composite frames (a second frame stacked under the first with no repeated tolerance
  symbol) use an **empty** `<ToleranceSymbol></ToleranceSymbol>` on the second frame.

## Datum features

`IModelDocExtension::CreateDatumTag` does not exist — the real method is
`IModelDoc2::InsertDatumTag2`. `IModelDocExtension::CreateDatumTargetSym` does not
exist — the real method is `IModelDocExtension::InsertDatumTargetSymbol3` (interface
matches; verb/version don't).

### IModelDoc2::InsertDatumTag2

- **Interface:** IModelDoc2
- **Method:** InsertDatumTag2 — requested as `IModelDocExtension::CreateDatumTag`,
  which does not exist (confirmed: no such member on `IModelDocExtension`'s member
  index; the real member lives on `IModelDoc2`)
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS, Revision Number 10.0. No obsolete
  "InsertDatumTag" (no "2") predecessor exists — `InsertDatumTag2` is the only,
  original version.

**Signature:**

```vb
Function InsertDatumTag2() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters | |

**Returns:** `System.Object` — the newly created `IDatumTag`.

**Prior selection required:** Not explicitly stated — this method's own help page has
no Remarks section at all (just Return Value/Example/See Also/Availability), unlike
`InsertGtol`'s explicit selection-driven-leader Remarks. **Inferred, not confirmed**,
by strong analogy with `InsertGtol`/`InsertNote`'s explicitly-documented "leader
attachment from prior selection" pattern (the same parameterless, no-location-argument
shape): expect the entity to attach to (typically an edge/face) to need selecting via
`ISelectionMgr` beforehand for a meaningful leader/location, with a freestanding-at-origin
fallback if nothing is selected. Treat as unverified until confirmed against a live
session.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertDatumTag2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDatumTag~SetLabel.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDatumTag~SetDisplayStyle.html

**status:** verified (signature/lineage); prior-selection behavior unverified (see
above)

**Gotchas:**
- **`IModelDocExtension::CreateDatumTag` doesn't exist** — real method is
  `IModelDoc2::InsertDatumTag2`. Same parameterless-creation-then-fill-via-object
  pattern as `InsertGtol`/`InsertWeldSymbol3`.
- **To set content after creation**, two follow-up calls on the returned
  `IDatumTag`:
  - `IDatumTag::SetLabel(Label As String) As Boolean` — sets the datum letter, up to
    2 characters (e.g. `"A"`). Page states verbatim: "If the specified label is more
    than two characters long, SOLIDWORKS does not change the symbol and returns
    false." Available since SOLIDWORKS 2000 FCS, Revision 8.0.
  - `IDatumTag::SetDisplayStyle(UseDoc As Boolean, Style As Integer) As Boolean` —
    `Style` is "as defined in `swDatumDisplayType_e`" (the real name for the
    requested `swDatumTagStyle_e`, documented in the Enums section). Available since
    SOLIDWORKS 2006 SP4, Revision 14.4.
- No mandatory-selection confirmation could be found for this specific method (its
  help page is unusually thin — no Remarks at all) — flagged rather than assumed;
  verify against a live session.

---

### IModelDocExtension::InsertDatumTargetSymbol3

- **Interface:** IModelDocExtension
- **Method:** InsertDatumTargetSymbol3 — requested as
  `IModelDocExtension::CreateDatumTargetSym` (interface matches; verb/version don't —
  see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2018 FCS, Revision Number 26.0

**Signature:**

```vb
Function InsertDatumTargetSymbol3( _
   ByVal Datum1 As System.String, _
   ByVal Datum2 As System.String, _
   ByVal Datum3 As System.String, _
   ByVal AreaStyle As System.Integer, _
   ByVal AreaOutside As System.Boolean, _
   ByVal Value1 As System.Double, _
   ByVal Value2 As System.Double, _
   ByVal ValueStr1 As System.String, _
   ByVal ValueStr2 As System.String, _
   ByVal ArrowsSmart As System.Boolean, _
   ByVal ArrowStyle As System.Integer, _
   ByVal LeaderLineStyle As System.Integer, _
   ByVal LeaderBent As System.Boolean, _
   ByVal ShowArea As System.Boolean, _
   ByVal ShowSymbol As System.Boolean, _
   ByVal MoveableDatumStyle As System.Integer _
) As DatumTargetSym
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Datum1 | String | n/a | Yes | Datum reference string 1 (e.g. `"a"`) | |
| Datum2 | String | n/a | Yes | Datum reference string 2; `""` if unused | |
| Datum3 | String | n/a | Yes | Datum reference string 3; `""` if unused | |
| AreaStyle | Integer | n/a | Yes | `0` = point, `1` = circle, `2` = rectangle | |
| AreaOutside | Boolean | n/a | Yes | `True` to display the target area outside the part | |
| Value1 | Double | meters | Yes | Numeric area diameter or width | |
| Value2 | Double | meters | Yes | Numeric area height | |
| ValueStr1 | String | n/a | Yes | Displayed value for area diameter/width | |
| ValueStr2 | String | n/a | Yes | Displayed value for area height | |
| ArrowsSmart | Boolean | n/a | Yes | `True` to use smart arrows | |
| ArrowStyle | Integer | n/a | Yes | Arrowhead style | `swArrowStyle_e` |
| LeaderLineStyle | Integer | n/a | Yes | Leader line style | `swLeaderStyle_e` |
| LeaderBent | Boolean | n/a | Yes | `True` for a bent leader line | |
| ShowArea | Boolean | n/a | Yes | `True` to show the target area | |
| ShowSymbol | Boolean | n/a | Yes | `True` to display the target symbol | |
| MoveableDatumStyle | Integer | n/a | Yes | Moveable datum target symbol style | `swMoveableDatumStyle_e` |

**Returns:** `DatumTargetSym` — the created object, e.g. usable with
`GetDatumReferenceLabel`/`SetDatumReferenceLabel`. Failure return not documented.

**Prior selection required:** Yes, mandatory. The official worked example ("Insert
and Modify Datum Target Symbol Example (VBA)") explicitly selects a face immediately
before the call:
```vb
status = swModelDocExt.SelectByID2("", "FACE", -7.23565448987529E-03, -2.59480787517532E-02, 0, False, 0, Nothing, 0)
Set swDatumTargetSym = swModelDocExt.InsertDatumTargetSymbol3("a", "", "", 0, False, 0.003, 0.03, "3", "", True, 12, 0, True, False, True, swMoveableDatumStyle_Horizontal)
```

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertDatumTargetSymbol3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2_members.html (confirms lineage: `IModelDoc2::InsertDatumTargetSymbol` obsolete → `IModelDocExtension::InsertDatumTargetSymbol2` obsolete → `InsertDatumTargetSymbol3` current)
- https://help.solidworks.com/2025/english/api/sldworksapi/Insert_and_Modify_Datum_Target_Symbol_Example_VB.htm (official worked example, quoted above)

**status:** verified

**Gotchas:**
- `IModelDocExtension::CreateDatumTargetSym` doesn't exist — real current method
  matches on interface but not verb/version. Full lineage:
  `IModelDoc2::InsertDatumTargetSymbol` (obsolete) →
  `IModelDocExtension::InsertDatumTargetSymbol2` (obsolete) →
  `InsertDatumTargetSymbol3` (current, and the one with the full 16-param signature
  above).
- Unlike `InsertGtol`/`InsertDatumTag2`/`InsertWeldSymbol3`, this method **does** take
  its full content as explicit parameters at creation time rather than requiring
  post-creation setter calls — the odd one out in this family.
- Despite the rich parameter list, a face **must still be pre-selected** — the
  parameters position/configure the symbol, they don't specify *what geometry* it
  attaches to.

### GD&T/datum enumeration, GTol annotation access, and projected tolerance zone (sw-1xx.4)

Fetched for `add_gtol`/`add_datum_feature`/`list_datums`'s requirements — `IGtol`
positioning, datum-tag enumeration (for auto-lettering and datum-letter validation),
and the projected-tolerance-zone modifier the task spec's `projected_zone` parameter
implies but the GD&T section above (fetched for sw-1xx.4's own predecessor research
pass) never covered. Every direct `help.solidworks.com` fetch attempted for this
addendum 403'd, same as every other addendum in this file researched from this
environment (see the dossier intro and the "Note enumeration" addendum above) — all
records below are corroborated via convergent search-engine snippets of the official
pages only, not a direct page read, and are marked `status: unverified` accordingly.

#### IGtol::GetAnnotation (and the equivalent IDatumTag/DatumTargetSym pattern)

- **Interface:** IGtol
- **Method:** GetAnnotation
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetAnnotation() As System.Object   ' returns the IAnnotation wrapper
```

**Returns:** `System.Object` — an `IAnnotation`, the same wrapper type
`INote::GetAnnotation` returns (documented in the "Note enumeration" addendum above) —
confirmed by a search-snippet-quoted VBA fragment: `Set swAnno = swGtol.GetAnnotation()`
... `swAnno.SetPosition(...)`. `IAnnotation::SetPosition2`'s own per-type origin table
(see that record above) lists "Geometric Tolerances -- Upper-left corner of the
symbol" and "Datum Feature Symbols -- Point where leader hits symbol", confirming both
GTols and datum tags route position through this same `GetAnnotation()` ->
`IAnnotation::SetPosition2` two-step, exactly like `INote` — **not** a direct
`SetPosition2` call on the `IGtol`/`IDatumTag` object itself. `IDatumTargetSym`'s own
`GetAnnotation` was not independently found, but by strong analogy with every other
annotation-producing factory in this dossier (`InsertGtol`, `InsertDatumTag2`,
`CreateText2`) it's assumed to follow the identical pattern -- unverified.

**Source URL(s):**
- https://help.solidworks.com/2017/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IGtol~GetAnnotation.html (found via search hit; page content itself 403'd on direct fetch, same as every other URL in this addendum)

**status:** unverified (search-snippet corroboration only, as above)

**Update (sw-1xx.5):** `GetAnnotation` is directly confirmed to exist on two more
concrete types via the curl-workaround-fetched `ISFSymbol_members.html` and
`IWeldSymbol_members.html` member-index pages (see the sw-1xx.5 addendum below) --
each lists a `GetAnnotation` member. This doesn't upgrade `IDatumTargetSym`'s own
status above (still unverified, out of this issue's scope), but it does corroborate
the general pattern this record's analogy leans on: every annotation-producing
factory in this dossier's GD&T/surface-finish/weld family exposes `GetAnnotation`
back to the shared `IAnnotation` wrapper.

---

#### IView::GetFirstDatumTag + IDatumTag::GetNext + IDatumTag::GetLabel

- **Interface:** IView (`GetFirstDatumTag`) / IDatumTag (`GetNext`, `GetLabel`)
- **Method:** GetFirstDatumTag + GetNext + GetLabel — the exact `list_datums`
  enumeration analog of `IView::GetFirstNote` + `INote::GetNext` (documented in the
  "Note enumeration" addendum above), confirmed to exist by name via convergent search
  hits against official 2012/2015/2017/2020/2021/2023 "Set Text in Datum Tags and
  GTols Example (VBA)" pages (`swView.GetFirstDatumTag`) and the `IDatumTag::GetLabel`
  method page (present alongside `SetLabel` across the same version range).
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetFirstDatumTag() As System.Object   ' IView, returns first IDatumTag or Nothing
Function GetNext() As System.Object            ' IDatumTag, returns next sibling or Nothing
Function GetLabel() As System.String           ' IDatumTag, returns the current label text (e.g. "A")
```

**Returns:** `GetFirstDatumTag`/`GetNext` — an `IDatumTag`, or `Nothing`/`None` past the
last datum tag in the chain (same `Do While Not ... Is Nothing` idiom as
`GetFirstNote`/`GetNext`). `GetLabel` -- the label string previously set via
`IDatumTag::SetLabel`, up to 2 characters.

**Prior selection required:** None -- read directly off an already-held `IView`/
`IDatumTag` reference, walked the same way `list_notes`/`_iter_document_views` already
walks every view in the document (including each sheet's own pseudo-view via
`IDrawingDoc::GetFirstView` + `IView::GetNextView`).

**Source URL(s):**
- https://help.solidworks.com/2021/English/api/sldworksapi/Set_Text_in_Datum_Tags_and_GTols_Example_VB.htm (found via search hit; page content 403'd on direct fetch)
- https://help.solidworks.com/2023/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDatumTag~GetLabel.html (found via search hit; page content 403'd on direct fetch)

**status:** unverified (search-snippet corroboration only)

**Gotchas:**
- `list_datums` reuses this module's existing `_iter_document_views` walk
  (`GetFirstView`/`GetNextView`, sw-1xx.3) and applies the identical
  `GetFirstDatumTag`/`GetNext` chain-walk per view that `_iter_view_notes` already
  applies for `GetFirstNote`/`GetNext` -- same iterator shape, different accessor
  names.
- A separate, NOT-used-by-`list_datums` pair, `IView::GetFirstGtol` +
  `IGtol::GetNextGTOL`, also exists (confirmed via search hits against the
  `GetNextGTOL Method (IGtol)` page across 2019-2023) -- not needed here since
  `list_datums` only enumerates datum-*defining* tags (the letters `add_gtol`'s
  `datums` validates against), not the GTols that *reference* those letters.

---

#### IView::GetFirstDisplayDimension6 + IDisplayDimension::GetNext5 + IDisplayDimension::GetAnnotation (sw-jkb.1)

- **Interface:** IView (`GetFirstDisplayDimension6`) / IDisplayDimension (`GetNext5`,
  `GetAnnotation`)
- **Method:** GetFirstDisplayDimension6 + GetNext5 — the dimension analog of
  `IView::GetFirstNote`/`INote::GetNext` (documented in the "Note enumeration" addendum
  above) and `IView::GetFirstDatumTag`/`IDatumTag::GetNext` (documented immediately
  above this record). Directly fetched for `move_annotations_to_layer` (sw-jkb.1), which
  needed a per-view dimension walk this dossier did not otherwise cover — unlike most of
  this file's `unverified`/search-snippet-only enumeration records, every page below
  fetched with a plain `200` (no 403), so this one is `status: verified`.
- **Minimum SW version:** not stated on any fetched page.

**Signature:**

```vb
Function GetFirstDisplayDimension6() As System.Object   ' IView, returns first IDisplayDimension or Nothing
Function GetNext5() As DisplayDimension                 ' IDisplayDimension, returns next sibling or Nothing
Function GetAnnotation() As System.Object                ' IDisplayDimension, returns its IAnnotation wrapper
```

**Parameters:** none of the three takes any.

**Returns:** `GetFirstDisplayDimension6`/`GetNext5` — an `IDisplayDimension`, or
`Nothing`/`None` past the last display dimension in the chain (same
`GetFirstX`/`GetNext` linked-list convention as every other annotation family in this
dossier). `GetAnnotation` — the shared `IAnnotation` wrapper that carries `Layer`
(documented above), same role as `INote::GetAnnotation`/`IDatumTag::GetAnnotation`/
`ITableAnnotation::GetAnnotation`.

**Prior selection required:** None — read directly off an already-held `IView`/
`IDisplayDimension` reference, walked the same way `_iter_document_views` already walks
every view in the document (including each sheet's own pseudo-view).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetFirstDisplayDimension6.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension~GetNext5.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDisplayDimension_members.html (confirms `GetAnnotation`/`GetNext5` are both real, current — non-`Obsolete` — members)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms `GetFirstDisplayDimension6` is the current, non-`Obsolete` member)

**status:** verified

**Gotchas:**
- **Five prior generations are all `Obsolete`:** `IView::GetFirstDisplayDimension`
  (superseded by `...2`, itself superseded by `...3`, `...4`, `...5`, finally `...6`,
  which the fetched `IView_members.html` confirms carries no further `Obsolete` tag) and
  `IDisplayDimension::GetNext`/`GetNext2`/`GetNext3`/`GetNext4` (all superseded by
  `GetNext5`, itself un-tagged). `GetFirstDisplayDimension6`'s own page states it
  "obsoletes `IView::GetFirstDisplayDimension5` by supporting inactive sheets" — the
  same "current members only" convention this project already follows elsewhere (e.g.
  `SaveAs3` over `SaveAs`/`SaveAs2`).
- Fetched specifically because the issue's Context names "dimensions" as the first
  example of an annotation family a generated pack should be able to move to a layer --
  `move_annotations_to_layer`'s `_MOVE_ANNOTATION_TYPE_ITERATORS` includes a
  `"dimension"` entry backed by this pair (`_iter_view_dimensions`, same
  `_iter_com_chain` shape every other family in that mapping uses).
- A dimension can be *displayed* in more than one view even though it originates from a
  single model feature (the page's own Remarks: "a base-extrude dimension can be brought
  into three different views on a drawing") — each such occurrence is its own
  `IDisplayDimension` with its own `IAnnotation`/`Layer`, so moving "all dimensions" via
  this walk touches every displayed occurrence across every view, not one representative
  instance per underlying model dimension.

---

#### IGtol::SetPTZHeight2 (projected tolerance zone)

- **Interface:** IGtol
- **Method:** SetPTZHeight2 — the real mechanism behind the task spec's
  `add_gtol(..., projected_zone=...)` parameter, which the GD&T section above (this
  issue's own predecessor research pass) never covered; confirmed to exist, with this
  exact call shape, via a search-snippet-quoted example: `status =
  swGtol.SetPTZHeight2(1, 1, True, "50")`
- **Minimum SW version:** not stated in any accessible source

**Signature (reconstructed from the quoted call site plus this dossier's own
`SetFrameValues2`-family naming/typing conventions -- parameter names inferred, not
independently confirmed):**

```vb
Function SetPTZHeight2( _
   ByVal FrameNumber As System.Short, _
   ByVal ToleranceNumber As System.Short, _
   ByVal Show As System.Boolean, _
   ByVal Height As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FrameNumber | Short | n/a | Yes | Feature control frame index, same convention as `SetFrameSymbols2`/`SetFrameValues2` (`1` for the first frame) | |
| ToleranceNumber | Short | n/a | Yes | Which tolerance within the frame (`1` for tolerance 1 -- this project never populates tolerance 2, see `SetFrameValues2`'s own record) | |
| Show | Boolean | n/a | Yes | `True` to display the projected-tolerance-zone symbol (Ⓟ) and height | |
| Height | String | n/a (display-unit text, same convention as `SetFrameValues2`'s `Tol1`) | Yes | Projected height value as display text, e.g. `"50"` | |

**Returns:** `Boolean` — `True` if the height was successfully set.

**Prior selection required:** None beyond holding a valid `IGtol` from `InsertGtol()`
with frame 1 already populated via `SetFrameSymbols2`/`SetFrameValues2` -- same
call-ordering assumption as `SetFrameValues2` itself (documented as required to follow
`SetFrameSymbols2` for the same frame).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IGtol~SetPTZHeight2.html (constructed per this dossier's own URL-naming convention from the confirmed method name; not independently opened -- no direct search-hit link surfaced a page title for this exact method, and every other URL in this addendum 403'd on direct fetch regardless)

**status:** unverified (search-snippet corroboration only; signature reconstructed,
not independently confirmed against a live session)

**Gotchas:**
- Like `SetFrameValues2`'s `Tol1`, `Height` is a **String**, not a `Double` in meters
  -- this project's `add_gtol(..., projected_zone=<number, caller's default unit>)`
  formats it as plain display text (via the same `_format_gtol_number` helper used for
  `tolerance`) rather than routing it through `self._units.to_meters`, consistent with
  the GD&T section's own flagged ambiguity that these frame-content strings are
  document-display text, not COM `Double` length parameters.
- A companion `GetPTZHeight2` accessor was also confirmed via search hits (a "Retrieve
  the PTZ height using GetPTZHeight2" mention in a convergent snippet) but is out of
  scope here -- `add_gtol` is a one-shot creation tool with no read-back requirement
  for this specific value.

---

#### Composite (stacked) feature control frames via FrameNumber=2

An official, dedicated worked example exists -- "Create GTol Composite Frame Example
(VBA/VB.NET)", confirmed present across 2019-2024 doc versions via search hits -- but
its page content itself 403'd on every attempted fetch, so its exact code could not be
read directly. What's independently confirmed by the search results: `SetFrameSymbols2`/
`SetFrameValues2`'s own `FrameNumber` parameter is explicitly the mechanism for
targeting "frame 2" of a composite frame (a second, stacked row under the first, same
`IGtol` object) -- corroborated by the surrounding `SetFrameSymbols2` documentation
text itself, independent of the inaccessible dedicated example page.

**What is NOT independently confirmed**: whether frame 2's `GCS` (geometric
characteristic symbol) parameter should be passed as `""` (empty, visually inheriting
frame 1's characteristic symbol as one merged box) or must repeat the same
`<IGTOL-...>` token. The GD&T section's own `SetSymbolXml` (current/2022+ XML format)
record states explicitly, for that *different* mechanism, that "Composite frames ...
use an empty `<ToleranceSymbol></ToleranceSymbol>` on the second frame." This project's
`add_gtol` `composite` parameter applies that same empty-symbol convention by analogy
to the legacy `SetFrameSymbols2` mechanism (`GCS=""` for frame 2) -- **an inferred,
not dossier-confirmed, choice**, flagged here rather than silently assumed correct.

**Source URL(s):**
- https://help.solidworks.com/2019/english/api/sldworksapi/create_gtol_composite_frame_example_vbnet.htm (found via search hit; page content 403'd on direct fetch)
- https://help.solidworks.com/2022/English/api/sldworksapi/Create_Gtol_Composite_Frame_Example_VB.htm (found via search hit; page content 403'd on direct fetch)

**status:** unverified (mechanism -- `FrameNumber=2` -- confirmed by search hits;
frame-2 `GCS` value inferred by analogy to the unrelated XML mechanism's documented
behavior, not independently confirmed for `SetFrameSymbols2` itself)

## Surface finish and weld symbols

`IModelDocExtension::CreateSurfaceFinishSymbol2` does not exist — the real, current
method is `IModelDocExtension::InsertSurfaceFinishSymbol3`.
`IModelDocExtension::CreateWeldSymbol2` does not exist — the real method is
`IModelDoc2::InsertWeldSymbol3` plus `IWeldSymbol::SetText`. Both findings were
independently cross-checked by two separate research passes that converged on the
same real names and signatures.

### IModelDocExtension::InsertSurfaceFinishSymbol3

- **Interface:** IModelDocExtension
- **Method:** InsertSurfaceFinishSymbol3 — requested as
  `IModelDocExtension::CreateSurfaceFinishSymbol2` (interface matches; verb/version
  don't — the "2" in the requested name maps almost exactly to a real, but obsolete,
  predecessor — see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function InsertSurfaceFinishSymbol3( _
   ByVal SymType As System.Integer, _
   ByVal LeaderType As System.Integer, _
   ByVal LocX As System.Double, _
   ByVal LocY As System.Double, _
   ByVal LocZ As System.Double, _
   ByVal LaySymbol As System.Integer, _
   ByVal ArrowType As System.Integer, _
   ByVal MachAllowance As System.String, _
   ByVal OtherVals As System.String, _
   ByVal ProdMethod As System.String, _
   ByVal SampleLen As System.String, _
   ByVal MaxRoughness As System.String, _
   ByVal MinRoughness As System.String, _
   ByVal RoughnessSpacing As System.String _
) As SFSymbol
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| SymType | Integer | n/a | Yes | Type of surface-finish symbol | `swSFSymType_e` |
| LeaderType | Integer | n/a | Yes | Leader style | `swLeaderStyle_e` |
| LocX | Double | meters | Yes | X location for symbol; only used if `LeaderType != swNO_LEADER` (per Remarks) | |
| LocY | Double | meters | Yes | Y location for symbol; same conditional-use note as `LocX` | |
| LocZ | Double | meters | Yes | Z location for symbol; same conditional-use note as `LocX` | |
| LaySymbol | Integer | n/a | Yes | Lay-direction symbol | `swSFLaySym_e` |
| ArrowType | Integer | n/a | Yes | Arrowhead type | `swArrowStyle_e` |
| MachAllowance | String | n/a | Yes | Material removal allowance text; pass `""` if unused | |
| OtherVals | String | n/a | Yes | Other roughness values text; pass `""` if unused | |
| ProdMethod | String | n/a | Yes | Production method / treatment text; pass `""` if unused | |
| SampleLen | String | n/a | Yes | Sampling length text; pass `""` if unused | |
| MaxRoughness | String | n/a | Yes | Maximum roughness text; pass `""` if unused | |
| MinRoughness | String | n/a | Yes | Minimum roughness text; pass `""` if unused | |
| RoughnessSpacing | String | n/a | Yes | Roughness spacing text; pass `""` if unused | |

**Returns:** `SFSymbol` — the newly inserted surface-finish symbol object (via the
`ISFSymbol` interface). The help page does not document a failure return value; treat
any specific failure cause as unverified.

**Prior selection required:** Yes — an edge, face, or vertex must be selected before
the call ("Creates a surface-finish symbol based on the last selection"). The help
page does not enumerate the exact `SelectByID2` `Type` strings accepted; treat as
unverified pending live-session confirmation.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertSurfaceFinishSymbol3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertSurfaceFinishSymbol2.html (obsolete predecessor — same 14 params, `Boolean` return instead of `SFSymbol`)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSFSymType_e.html

**status:** verified

**Gotchas:**
- **The requested name (`CreateSurfaceFinishSymbol2`) maps almost exactly, by
  parameter shape, to the real but obsolete `IModelDoc2::InsertSurfaceFinishSymbol2`**
  — identical 14-parameter list and order, but it lives on `IModelDoc2` (not
  `IModelDocExtension`) and returns a bare `Boolean` instead of an `SFSymbol` object.
  It is superseded by `IModelDocExtension::InsertSurfaceFinishSymbol3` (documented
  here), which moved to `IModelDocExtension` and started returning the actual symbol
  object.
- `LocX`/`LocY`/`LocZ` are silently ignored unless `LeaderType != swNO_LEADER`, per
  Remarks — passing nonzero coordinates with a no-leader style has no effect.
- All the string parameters are positional and must be passed as `""` when not used —
  consistent with this API's general COM-interop convention (no optional/named args).

---

### IModelDoc2::InsertWeldSymbol3 + IWeldSymbol::SetText

- **Interface:** IModelDoc2 (creation) / IWeldSymbol (content)
- **Method:** InsertWeldSymbol3, then IWeldSymbol::SetText — requested as
  `IModelDocExtension::CreateWeldSymbol2` (interface and verb both wrong; the "2" maps
  to a real, obsolete, parameterized predecessor — see Gotchas)
- **Minimum SW version:** InsertWeldSymbol3 — SOLIDWORKS 2001Plus FCS, Revision
  Number 10.0. IWeldSymbol::SetText — SOLIDWORKS 99, datecode 1999207.

**Signature:**

```vb
Function InsertWeldSymbol3() As System.Object

Function SetText( _
   ByVal Top As System.Boolean, _
   ByVal Left As System.String, _
   ByVal Symbol As System.String, _
   ByVal Right As System.String, _
   ByVal Stagger As System.String, _
   ByVal Contour As System.Integer _
) As System.Boolean
```

**Parameters:**

`InsertWeldSymbol3` takes none. `SetText`:

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Top | Boolean | n/a | Yes | `True` to set text above the symbol's horizontal reference line, `False` for below | |
| Left | String | n/a | Yes | Text to the left of the weld symbol | |
| Symbol | String | n/a | Yes | The weld symbol name itself, from a fixed ISO list (see Gotchas) | |
| Right | String | n/a | Yes | Text to the right of the weld symbol | |
| Stagger | String | n/a | Yes | Text to the right of the stagger symbol; only visible if `IWeldSymbol::SetStagger` is enabled | |
| Contour | Integer | n/a | Yes | Contour setting | `swWeldSymbolContourTypes_e` |

**Returns:** `InsertWeldSymbol3` — `System.Object`, the newly created `IWeldSymbol`.
`SetText` — `Boolean`, `True` if set successfully.

**Prior selection required:** Yes. `InsertWeldSymbol3`'s own official worked example
states as an explicit Precondition: "Select a face, edge, or sketch segment for Weld
Symbol insertion" — done before the call, via UI selection carried into the macro.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertWeldSymbol3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertWeldSymbol2.html (obsolete predecessor — parameterized, single-call form, see Gotchas)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetText.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Insert_Weld_Symbol_Example_VB.htm (official worked example, quoted below)

**status:** verified

**Gotchas:**
- **The requested name (`CreateWeldSymbol2`) maps closely to a real, obsolete
  predecessor: `IModelDoc2::InsertWeldSymbol2`**, which (unlike the current
  `InsertWeldSymbol3`) took all content as parameters in a single call:
  ```vb
  Sub InsertWeldSymbol2( _
     ByVal Dim1 As String, ByVal Symbol As String, ByVal Dim2 As String, _
     ByVal Symmetric As Boolean, ByVal FieldWeld As Boolean, ByVal ShowOtherSide As Boolean, _
     ByVal DashOnTop As Boolean, ByVal Peripheral As Boolean, ByVal HasProcess As Boolean, _
     ByVal ProcessValue As String _
  )
  ```
  Its own page reads only "Obsolete. Superseded by `IModelDoc2::InsertWeldSymbol3`"
  with no further Remarks/parameter descriptions retrievable. Current code should use
  the parameterless-creation + `SetText`/`SetFieldWeld`/`SetPeripheral`/etc. pattern
  documented here instead.
- **Full official worked example** (`Insert_Weld_Symbol_Example_VB.htm`), showing the
  complete post-creation fill-in sequence:
  ```vb
  Set swWeldSymbol = swModel.InsertWeldSymbol3
  swWeldSymbol.SetFieldWeld swFieldWeldNone
  swWeldSymbol.SetPeripheral False
  swWeldSymbol.SetProcess True, "Process", True
  swWeldSymbol.SetStagger True
  swWeldSymbol.SetSymmetric swWeldSymmetric
  swWeldSymbol.SetText True, "Left", "BUTT", "Right", "Stagger", swWeldContourNone
  ```
- **`Symbol` is a fixed ISO weld-symbol-name list**, not a free string, per `SetText`'s
  own Remarks — the currently supported names are: `BUTT, BUSQ, BUSV, BUSB, BUSVBR,
  BUSBR, BUSU, BUSJ, BACK, FILL, PLUG, SPOT, SEAM, SEAMC, JSPT, JSM`. These are plain
  names (not `<Library-Symbol>` bracket tokens like GTol/note symbols use), sourced
  from the same underlying `gtol.sym` file.
- `IWeldSymbol` exposes many other setters used alongside `SetText` in the example
  above (`SetFieldWeld`, `SetPeripheral`, `SetProcess`, `SetStagger`, `SetSymmetric`)
  — driven by `swWeldSymbolField_e` (`swFieldWeldNone`/`swFieldWeldUp`/
  `swFieldWeldDown`) and `swWeldSymbolSymmetric_e`
  (`swWeldSymmetric`/`swWeldDashedLineOnTop`/`swWeldDashedLineOnBottom`) — neither
  independently fetched here, and not required by this dossier's requested enum list —
  plus the `Contour`/`swWeldSymbolContourTypes_e` documented in the Enums section.

### Surface finish/weld symbol "all-around" leader, and IWeldSymbol content setters (sw-1xx.5)

Fetched for `add_surface_finish`/`add_weld_symbol`'s `all_around`/`field_weld`/
`both_sides`/`tail_text` requirements. All four methods below were fetched directly
via the curl workaround documented under `swSFLaySym_e` in the Enums section
(`help.solidworks.com`'s Next.js page ships its real content as a JSON blob a bare
fetch tool never executes the script to retrieve; a browser-`User-Agent`'d `curl`
gets the same static HTML the site serves any first-time visitor, `__NEXT_DATA__`
JSON included).

**A genuine contradiction in the official docs, resolved here:**
`IAnnotation::SetLeader3`'s own Parameters table (documented earlier in this
dossier) describes its `AllAround` argument as "`True` to enable all-around (weld,
**surface finish**, or GTol) symbol display" — naming all three annotation types.
But that same page's Gotchas/Remarks-derived bullet list states "GTols and weld
symbols are **the only types** that support all-around leader symbols" — omitting
surface finish entirely. These two statements, both transcribed from the same
source page, disagree. This dossier resolves it as follows: `add_surface_finish`'s
`all_around` uses `SetLeader3` anyway (trusting the per-parameter description, the
more specific of the two claims) — **unverified beyond that textual conflict**, not
confirmed against a live session; `add_weld_symbol`'s `all_around` instead uses
`IWeldSymbol::SetPeripheral` (below), a dedicated, unambiguous, officially
worked-example-demonstrated setter for exactly this concept on a weld symbol
specifically (the UI calls it "Peripheral": "Creates a circle at the bend in the
weld line to indicate that the weld is applied all around the contour" per
`HIDD_WELD.htm`), sidestepping the `SetLeader3` ambiguity for the type it's certain
about.

#### ISFSymbol::GetAnnotation / IWeldSymbol::GetAnnotation

- **Interface:** ISFSymbol / IWeldSymbol
- **Method:** GetAnnotation
- **Minimum SW version:** not stated in any accessible source

**Signature:**

```vb
Function GetAnnotation() As System.Object   ' returns the IAnnotation wrapper
```

**Returns:** `System.Object` — an `IAnnotation`, the same wrapper type documented
throughout this dossier (`INote`/`IGtol`/`IDatumTag`).

**Prior selection required:** None — invoked directly on an already-held
`ISFSymbol`/`IWeldSymbol` reference (the object `InsertSurfaceFinishSymbol3`/
`InsertWeldSymbol3` returns).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISFSymbol_members.html (member index; lists `GetAnnotation`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol_members.html (member index; lists `GetAnnotation`)

**status:** verified — **this upgrades the sw-1xx.4 addendum's "assumed by strong
analogy, unverified" note for `IDatumTargetSym::GetAnnotation`** from a guess to a
corroborated pattern (still not independently confirmed for `IDatumTargetSym`
itself, which stays unverified, out of this issue's scope) -- every
annotation-producing factory this dossier documents (`InsertGtol`,
`InsertDatumTag2`, `InsertSurfaceFinishSymbol3`, `InsertWeldSymbol3`, `CreateText2`)
now has at least one directly-confirmed `GetAnnotation` sibling.

**Gotchas:**
- `add_surface_finish` does **not** call `SetPosition2` after creation --
  `InsertSurfaceFinishSymbol3` already takes `LocX`/`LocY`/`LocZ` at creation time
  (see that method's own record above), so `GetAnnotation` is only reached when
  `all_around` needs `SetLeader3`. `add_weld_symbol` always calls `GetAnnotation` ->
  `SetPosition2`, since `InsertWeldSymbol3` takes no position parameters at all.
  `IAnnotation::SetPosition2`'s own per-type origin table (see that record above)
  independently corroborates both types route position through `IAnnotation`:
  "Surface Finish Symbols -- Lower-left point of symbol", "Weld Symbols -- Left
  endpoint of the main horizontal line in the symbol".

#### IWeldSymbol::SetText's `Top` parameter and drafting-standard dependence

`SetText`'s own Parameters documentation (fetched directly via the curl workaround,
matching the description this dossier's original pass already recorded) states
`Top`'s meaning literally as "`True` to set the text in the portion of the symbol
above the horizontal line, `False` to set the text in the portion of the symbol
below the horizontal line" -- **not** "arrow side" or "this side" in those words.
`add_weld_symbol`'s docstring/tool description calling `Top=True` the "arrow side"
weld and `Top=False` the "other side" weld is this dossier's own interpretive
layer, sourced from `HIDD_WELD.htm`'s UI documentation: "The ISO standard uses the
weld symbols on (above) the line for a 'near side' or 'this side' weld and weld
symbols on the dashed line (below) for a 'far side' or 'other side' weld **by
default**. If you change the drafting standard to ISO, the software changes the
weld symbols" -- i.e. this above/below <-> near-side/far-side mapping is
ISO-drafting-standard-specific, not universal across every standard SolidWorks
supports (ANSI/GOST/JIS use different symbol conventions per `c_weld_symbols.htm`).
This project treats `Top=True` as arrow-side unconditionally, consistent with its
own established ISO convention elsewhere (`add_gtol`'s hardcoded `IGTOL`
library) and independently reinforced by `SetText`'s own Remarks (fetched
directly): "Specify `Symbol` with one of the currently supported **ISO** weld
symbols: `BUTT BUSQ BUSV BUSB BUSVBR BUSBR BUSU BUSJ BACK FILL PLUG SPOT SEAM
SEAMC JSPT JSM`" -- the `Symbol` parameter's own accepted-value list is ISO-only,
so a document set to a non-ISO drafting standard is out of scope for this
mechanism regardless of the `Top` question.

**Gotchas:**
- The task's own Requirements describe `add_weld_symbol` as "AWS-style" — worth
  flagging plainly: the underlying `IWeldSymbol::SetText` mechanism only accepts
  ISO-standard symbol codes (per its own Remarks, quoted above), not AWS/ANSI ones.
  `add_weld_symbol`'s docstring and tool description call it "ISO-style" rather
  than "AWS-style" to match what the COM layer actually enforces.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetText.html
- https://help.solidworks.com/2025/english/SolidWorks/sldworks/HIDD_WELD.htm

**status:** verified

#### IWeldSymbol::SetPeripheral

- **Interface:** IWeldSymbol
- **Method:** SetPeripheral
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function SetPeripheral(ByVal Peripheral As System.Boolean) As System.Boolean
```

**Parameters:** `Peripheral` — `True` for a peripheral (all-around) weld, `False` if
not.

**Returns:** `Boolean` — `True` if set successfully.

**Prior selection required:** None via `ISelectionMgr` — invoked directly on an
already-held `IWeldSymbol` reference (the object `InsertWeldSymbol3` returns).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetPeripheral.html

**status:** verified

#### IWeldSymbol::SetFieldWeld

- **Interface:** IWeldSymbol
- **Method:** SetFieldWeld
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function SetFieldWeld(ByVal FieldWeld As System.Integer) As System.Boolean
```

**Parameters:** `FieldWeld` — `swWeldSymbolField_e` (see Enums section): whether this
is a field/site weld, and if so, which way the flag points.

**Returns:** `Boolean` — `True` if set successfully.

**Prior selection required:** None — same pattern as `SetPeripheral` above.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetFieldWeld.html

**status:** verified

**Gotchas:**
- `add_weld_symbol`'s boolean `field_weld` parameter maps `True` ->
  `swFieldWeldUp` and `False` -> `swFieldWeldNone` — this project's own
  simplification of the 3-way enum (there is no documented "default" orientation to
  infer a boolean flag-direction choice from, so the tool layer doesn't expose
  `swFieldWeldDown` as a public option at all).

#### IWeldSymbol::SetProcess

- **Interface:** IWeldSymbol
- **Method:** SetProcess
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function SetProcess( _
   ByVal Process As System.Boolean, _
   ByVal Text As System.String, _
   ByVal Reference As System.Boolean _
) As System.Boolean
```

**Parameters:**

| Name | Type | Meaning |
| --- | --- | --- |
| Process | Boolean | `True` to set the welding-process indication flag |
| Text | String | Tail text -- per `HIDD_WELD.htm`'s "Specification process" field: "Type text ... in any number of lines, to appear in the tail of the symbol" |
| Reference | Boolean | `True` to draw a reference box around `Text` |

**Returns:** `Boolean` — `True` if set successfully.

**Prior selection required:** None — same pattern as `SetPeripheral` above.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetProcess.html
- https://help.solidworks.com/2025/english/SolidWorks/sldworks/HIDD_WELD.htm (conceptual "Weld Symbol Properties" page, confirms `Text`'s "tail of the symbol" placement and the `Reference` checkbox)

**status:** verified

**Gotchas:**
- `add_weld_symbol`'s `tail_text` maps to `Text` here with `Process=True`,
  `Reference=False` -- `Reference` (the box-around-text option) isn't exposed as a
  public parameter (cosmetic, not in this task's Requirements).

#### IWeldSymbol::SetSymmetric

- **Interface:** IWeldSymbol
- **Method:** SetSymmetric
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function SetSymmetric(ByVal Symmetric As System.Integer) As System.Boolean
```

**Parameters:** `Symmetric` — `swWeldSymbolSymmetric_e` (see Enums section).

**Returns:** `Boolean` — `True` if set successfully.

**Prior selection required:** None — same pattern as `SetPeripheral` above.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IWeldSymbol~SetSymmetric.html

**status:** verified

**Gotchas:**
- `add_weld_symbol`'s boolean `both_sides` maps `True` -> `swWeldSymmetric` per
  `HIDD_WELD.htm`'s "Symmetric" field description ("Properties on one side of the
  symbol line also appear on the other side"). `False` skips the call entirely
  (leaving `InsertWeldSymbol3`'s own creation-time default) rather than picking
  arbitrarily between the two non-symmetric variants (`swWeldDashedLineOnTop`/
  `swWeldDashedLineOnBottom`), neither of which this task's Requirements asks for.

#### Weld symbol name-code semantics (partial, honesty note)

The 16 ISO `Symbol` codes this dossier's original pass already listed (`BUTT, BUSQ,
BUSV, BUSB, BUSVBR, BUSBR, BUSU, BUSJ, BACK, FILL, PLUG, SPOT, SEAM, SEAMC, JSPT,
JSM`) have no `help.solidworks.com` page enumerating what each individual code
means (they are entries in the installed `gtol.sym` text file, not a fetchable API
page). This pass corroborates, with reasonable confidence from the `BU`-prefix
grouping pattern and cross-reference against `c_weld_symbols.htm`/`HIDD_WELD.htm`'s
conceptual descriptions and standard AWS/ISO groove-weld terminology, friendly
names for 10 of the 16: `FILL`=fillet, `PLUG`=plug/slot, `SPOT`=spot, `SEAM`=seam,
`BACK`=backing, `BUTT`=(generic) butt, `BUSQ`=square groove, `BUSV`=V-groove,
`BUSB`=bevel groove, `BUSU`=U-groove, `BUSJ`=J-groove. The remaining 5
(`BUSVBR`, `BUSBR`, `SEAMC`, `JSPT`, `JSM`) have no corroborated meaning found in
this pass — **do not guess names for these**; `add_weld_symbol`'s `symbol`/
`other_side_symbol` parameters accept the raw ISO code string directly (case
-insensitive) for any of the 16, so those 5 remain reachable without a friendly
alias.

## Center marks and centerlines

`IView::InsertCenterMark2` does not exist — `IView` has **no** `InsertCenterMark`
member at all (confirmed by fetching `IView_members.html` — it only exposes
`AutoInsertCenterMarks`/`AutoInsertCenterMarks2` plus read-only getters like
`GetCenterMarkCount2`/`GetFirstCenterMark2`). `InsertCenterMark2` does exist, but on
`IDrawingDoc`, and is Obsolete — the current member is `IDrawingDoc::InsertCenterMark3`.

### IDrawingDoc::InsertCenterMark3

- **Interface:** IDrawingDoc
- **Method:** InsertCenterMark3 — requested as `IView::InsertCenterMark2`, which does
  not exist (see the section intro above)
- **Minimum SW version:** SOLIDWORKS 2009 FCS, Revision Number 17.0

**Signature:**

```vb
Function InsertCenterMark3( _
   ByVal Style As System.Integer, _
   ByVal Propagate As System.Boolean, _
   ByVal Slot As System.Boolean _
) As CenterMark
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Style | Integer | n/a | Yes | Center mark style | `swCenterMarkStyle_e` |
| Propagate | Boolean | n/a | Yes | `True` to propagate the center mark throughout a pattern, `False` otherwise | |
| Slot | Boolean | n/a | Yes | `True` for a slot-style center mark, `False` otherwise | |

**Returns:** `CenterMark` (via `ICenterMark`) — pointer to the newly created center
mark. The help page does not document what is returned on failure; treat as
unverified.

**Prior selection required:** Yes — one or more circular edges, slot edges, or arcs
in a drawing view must be selected before the call; the center mark is added at the
selected geometry. To auto-insert center marks across an entire view instead of a
per-edge call, use `IView::AutoInsertCenterMarks`/`AutoInsertCenterMarks2` (a
separate, view-level method) rather than looping `InsertCenterMark3` — noted directly
in this method's own Remarks section.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertCenterMark3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertCenterMark2.html (confirms `InsertCenterMark2` is Obsolete, superseded by `InsertCenterMark3`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms `IView` has no `InsertCenterMark*` method of its own — only `AutoInsertCenterMarks[2]` and getters)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCenterMarkStyle_e.html

**status:** verified

**Gotchas:**
- Both the interface and version in the requested name are wrong: `IView` has **no**
  `InsertCenterMark` method at all. `InsertCenterMark2` does exist, but on
  `IDrawingDoc`, and is Obsolete — the current member is
  `IDrawingDoc::InsertCenterMark3`, which adds the `Slot` parameter over
  `InsertCenterMark2`'s `(Style, Propagate)`.
- Don't confuse this per-edge method with view-wide auto-insertion
  (`IView::AutoInsertCenterMarks2`) — they are separate calls with separate selection
  models (edge selection vs. whole-view/document preference-driven).

---

### IDrawingDoc::InsertCenterLine2

- **Interface:** IDrawingDoc
- **Method:** InsertCenterLine2
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function InsertCenterLine2() As Centerline
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters; the centerline's two entities come entirely from the current selection | |

**Returns:** `Centerline` (via `ICenterLine`) — pointer to the newly created
centerline object. The help page does not document a failure-case return value;
treat as unverified.

**Prior selection required:** Yes — "Inserts a centerline on the selected entities."
The help page's own description does not enumerate exactly which entity types/count
are valid; based on the SOLIDWORKS UI behavior this method backs (Insert > Annotations
> Centerline), two parallel linear edges or two circular/arc edges are the expected
selection, but that specific pairing rule is unverified against this help page alone —
confirm empirically if a caller needs to validate selection shape before calling.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertCenterLine2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms no `InsertCenterLine3` exists — `InsertCenterLine2` is current)

**status:** verified

**Gotchas:**
- Confirmed as given in the source research task (interface, method name, and
  version number all matched on first fetch) — no correction needed, unlike the
  other methods in this section.
- No `InsertCenterLine3` exists — `InsertCenterLine2` is the current, un-superseded
  method despite the "2" suffix suggesting an older generation.

---

**Addendum (sw-1xx.6, re-fetched independently via the same curl+UA
technique):** the batch center-mark/centerline tools this section backs need three
things the original research pass didn't cover: how to detect a *circular* edge
(for `target="all_holes"`), the per-mark display-setting members on `ICenterMark`
(for `size`/`extended_lines`/`connection_lines`), and how to enumerate and delete
existing center marks (for `remove_center_marks`). All fetched fresh for this issue.

### ICurve::IsCircle

- **Interface:** ICurve
- **Method:** IsCircle
- **Minimum SW version:** not stated on the page (pre-.NET-syntax-era method)

**Signature:**

```vb
Function IsCircle() As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters |

**Returns:** `Boolean` — `True` if the curve is a circle, `False` for any other
curve type.

**Prior selection required:** None — called directly on an `ICurve` reference
(obtained from `IEdge::GetCurve`, documented next), not selection-driven.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurve~IsCircle.html

**status:** verified

**Gotchas:**
- Per the page's own Remarks: use `IEdge::GetCurveParams2` to further tell a
  *complete* circle apart from an arc, if that distinction matters — `IsCircle`
  alone doesn't distinguish them.
- This is the mechanism `add_center_marks`' `target="all_holes"` uses to filter
  `IView::GetVisibleEntities2`'s edge results down to circular ones: for each edge,
  `edge.GetCurve().IsCircle()`. An edge whose curve can't be read, or that throws,
  is treated as non-circular (skipped) rather than failing the whole enumeration —
  same best-effort convention `list_view_entities`' `_entity_point` already uses.

---

### IEdge::GetCurve

- **Interface:** IEdge
- **Method:** GetCurve
- **Minimum SW version:** not stated on the page

**Signature:**

```vb
Function GetCurve() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters |

**Returns:** `System.Object` — pointer to the underlying curve for this edge (late-
bound; cast/use as `ICurve`).

**Prior selection required:** None — a read-only accessor on an already-held
`IEdge` reference (e.g. one element of `IView::GetVisibleEntities2`'s result array).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IEdge~GetCurve.html

**status:** verified

---

### ICenterMark::Size

- **Interface:** ICenterMark
- **Member:** Size (read/write property)
- **Minimum SW version:** SOLIDWORKS 2001Plus SP1, Revision Number 10.1

**Signature:**

```vb
Property Size As System.Double
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| value | Double | unstated | Yes (on set) | Length of the lines in this center mark |

**Returns:** `Double` — length of the lines in this center mark (get); no return
value (set).

**Prior selection required:** None to call — a property set directly on the
`ICenterMark` reference `IDrawingDoc::InsertCenterMark3` returns, immediately
after creation.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICenterMark~Size.html

**status:** verified

**Gotchas:**
- The page does not document a unit. Per this dossier's API-wide convention (see
  `README.md#units-convention`, and `SelectByID2`'s own X/Y/Z record above, which
  faced the same gap), this project treats it as **meters** at the COM boundary --
  `add_center_marks`' `size` parameter is in the caller's default unit and is
  converted via `self._units.to_meters()` before being assigned.

---

### ICenterMark::ShowLines

- **Interface:** ICenterMark
- **Member:** ShowLines (read/write property)
- **Minimum SW version:** SOLIDWORKS 2001Plus SP1, Revision Number 10.1

**Signature:**

```vb
Property ShowLines As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| value | Boolean | n/a | Yes (on set) | `True` shows the extension lines, `False` does not |

**Returns:** `Boolean` — whether the extension lines are shown (get); no return
value (set).

**Prior selection required:** None to call — a property set directly on the
`ICenterMark` reference `IDrawingDoc::InsertCenterMark3` returns, immediately
after creation.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICenterMark~ShowLines.html

**status:** verified

---

### ICenterMark::ConnectionLines

- **Interface:** ICenterMark
- **Member:** ConnectionLines (read/write property)
- **Minimum SW version:** SOLIDWORKS 2003 FCS, Revision Number 11.0

**Signature:**

```vb
Property ConnectionLines As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| value | Integer | n/a | Yes (on set) | Visibility of this center mark's connection line | `swCenterMarkConnectionLine_e` |

**Returns:** `Integer` — the current connection-line visibility bitmask (get); no
return value (set).

**Prior selection required:** None to call — a property set directly on the
`ICenterMark` reference `IDrawingDoc::InsertCenterMark3` returns, immediately
after creation.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICenterMark~ConnectionLines.html
- https://help.solidworks.com/2025/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.icentermark_members.html

**status:** verified

**Gotchas:**
- The bool -> bitmask mapping a tool-layer `connection_lines` boolean parameter
  needs is not documented anywhere — SolidWorks exposes four independent
  line-type bits (linear/circular/radial/base), not a single on/off switch. This
  project's own convention (not sourced from SolidWorks): `False` ->
  `swCenterMark_ShowNoConnectLines` (0), `True` ->
  `swCenterMark_ShowCircularConnectLines` (2), since batch center marks are
  placed on circular hole edges and a circular connection line is what visually
  groups them. A caller wanting a different combination should use
  `select_view_by_name` + direct `ICenterMark` access outside this tool.

---

### ICenterMark::Select

- **Interface:** ICenterMark
- **Method:** Select
- **Minimum SW version:** SOLIDWORKS 2016 FCS, Revision Number 24.0

**Signature:**

```vb
Function Select( _
   ByVal Append As System.Boolean, _
   ByVal Data As System.Object _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| Append | Boolean | n/a | Yes | `True` appends this center mark to the selection list, `False` replaces the selection list with just this center mark |
| Data | Object (`ISelectData`) | n/a | Yes | A `SelectData` object from `ISelectionMgr::CreateSelectData` |

**Returns:** `Boolean` — `True` if the center mark was selected, `False` if not.

**Prior selection required:** None as a precondition — this method *establishes*
selection on the center mark it's called on, the dedicated alternative to
`SelectByID2`/`AddSelectionListObject` for this annotation type (recall
`SelectByID2`'s own Type-string table above: `"CENTERMARKS"`/`"CENTERMARKSYMS"`
are not usable Type strings for this purpose — `swSelCENTERMARKS` has no
supported interface per that table, and `swSelCENTERMARKSYMS`'s mapping is
blank). `remove_center_marks` uses this + `IModelDocExtension::DeleteSelection2`
(the same select-then-delete idiom `delete_sheet`/`delete_view` already use) to
remove one center mark at a time while walking `IView::GetFirstCenterMark2`/
`ICenterMark::GetNext`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICenterMark~Select.html

**status:** verified

---

### IView::GetFirstCenterMark2

- **Interface:** IView
- **Method:** GetFirstCenterMark2
- **Minimum SW version:** SOLIDWORKS 2025 SP01, Revision Number 33.1

**Signature:**

```vb
Function GetFirstCenterMark2() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters |

**Returns:** `System.Object` — the first `ICenterMark` in the view, or
`Nothing`/`null` if the view has none.

**Prior selection required:** None — a walk-start primitive, same shape as
`IView::GetFirstNote` (already used by `_iter_view_notes`) and
`IView::GetFirstDatumTag` (already used by `_iter_view_datum_tags`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetFirstCenterMark2.html

**status:** verified

**Gotchas:**
- Availability is **SOLIDWORKS 2025 SP01, Revision 33.1** — very recent. It
  obsoletes `IView::GetFirstCenterMark` (no "2"), which the page's own Remarks
  describe as not supporting inactive sheets; `...2` is used here as the current
  member, consistent with this dossier's own prefer-the-current-overload
  convention elsewhere, but a caller targeting an older SOLIDWORKS build than
  2025 SP01 needs the obsolete predecessor instead.

---

### ICenterMark::GetNext

- **Interface:** ICenterMark
- **Method:** GetNext
- **Minimum SW version:** SOLIDWORKS 2003 FCS, Revision Number 11.0

**Signature:**

```vb
Function GetNext() As CenterMark
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters |

**Returns:** `CenterMark` (via `ICenterMark`) — the next center mark, or
`Nothing`/`null` at the end of the list.

**Prior selection required:** None — the walk-continuation primitive paired with
`IView::GetFirstCenterMark2` above, same shape as `INote::GetNext`/
`IDatumTag::GetNext`. `remove_center_marks`' own walk (`_iter_view_center_marks`)
follows the identical `nxt if nxt else None` idiom `_iter_view_notes`/
`_iter_view_datum_tags` already use, capturing `GetNext()` on the current mark
*before* deleting it (a deleted COM object's own `GetNext` is not guaranteed to
still answer).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICenterMark~GetNext.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetCenterMarkCount2.html (fetched to evaluate as a removal-count cross-check; see Gotchas below for why it's not used that way)

**status:** verified

**Gotchas:**
- **`IView::GetCenterMarkCount2` is NOT a reliable removed/remaining count and is
  deliberately not used by `remove_center_marks`.** Its own Remarks state:
  "Center marks are now annotations. Previously, center marks were features. This
  method is only valid for center marks that are features." Center marks created
  by this project's own `add_center_marks` (via `InsertCenterMark3`) are the
  current annotation-style kind, not the old feature-style kind — so this method
  can legitimately report `0` while marks exist. `remove_center_marks` instead
  counts its own successful `DeleteSelection2` calls made during the
  `GetFirstCenterMark2`/`GetNext` walk.
- Similarly, `ICenterMark::GetAnnotation` (documented on the `ICenterMark`
  members page) returns `Nothing`/`null` for the old feature-style marks — per
  its own Remarks, it only resolves for the `swSelCENTERMARKSYMS`-selected
  (annotation-style) kind. `remove_center_marks` therefore selects and deletes
  via `ICenterMark::Select` + `DeleteSelection2` directly, never via
  `GetAnnotation`, so it works uniformly across both kinds.

---

### ISelectionMgr::CreateSelectData

- **Interface:** ISelectionMgr
- **Method:** CreateSelectData
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Function CreateSelectData() As SelectData
```

**Parameters:**

| Name | Type | Units | Required | Meaning |
| --- | --- | --- | --- | --- |
| (none) | | n/a | | Takes no parameters |

**Returns:** `SelectData` (via `ISelectData`) — an opaque selection-metadata
object, required by `ICenterMark::Select`'s `Data` parameter (and other
interfaces' own `Select`-family methods across the API).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISelectionMgr~CreateSelectData.html

**status:** verified

## Annotation object manipulation

An initial fetch attempt for this section returned a client-rendered SPA shell with
no content for every `IAnnotation` page tried. A follow-up pass using the same
`curl` + browser `User-Agent` + `__NEXT_DATA__`-parsing technique that worked
elsewhere in this dossier succeeded on a retry — all four pages in this section
render correctly with that technique; the earlier failure was transient/session-specific,
not a real access block on these specific pages. All records below are `status:
verified` from directly fetched page content.

### IAnnotation::SetPosition2

- **Interface:** IAnnotation
- **Method:** SetPosition2 — requested as `IAnnotation::SetPosition`, which is
  Obsolete (superseded by `SetPosition2`; see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2014 SP3, Revision Number 22.3

**Signature:**

```vb
Function SetPosition2( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters | Yes | X coordinate of the origin of the annotation | |
| Y | Double | meters | Yes | Y coordinate of the origin of the annotation | |
| Z | Double | meters | Yes | Z coordinate of the origin of the annotation | |

**Returns:** `Boolean` — `True` if the position was successfully set, `False` if
not. `SetPosition2` only supports specific annotation types (see the table in
Gotchas); called on an unsupported type, "SOLIDWORKS takes no action and returns
false" (page's own wording).

**Prior selection required:** None via `ISelectionMgr` for the call itself —
`SetPosition2` is invoked directly on an `IAnnotation` object reference. That
reference is typically obtained either from a prior creation call's return value
(e.g. `CreateText2`, `InsertGtol`), from `ISelectionMgr::GetSelectedObject6` on an
already-selected annotation (cast/queried to `IAnnotation`), or by traversing
annotations. No additional selection action is needed once the reference is held.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetPosition2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetPosition.html (predecessor's own page states "Obsolete. Superseded by IAnnotation::SetPosition2")

**status:** verified

**Gotchas:**
- **The requested method, `IAnnotation::SetPosition` (unsuffixed), is itself real but
  Obsolete** — its page reads verbatim "Obsolete. Superseded by
  `IAnnotation::SetPosition2`." Both have an identical 3-parameter `(X, Y, Z) As
  Boolean` signature; prefer `SetPosition2` for new code.
- **Per-annotation-type XYZ-origin reference table**, quoted verbatim from the page's
  own Remarks (applies to both `SetPosition`/`SetPosition2`; in a drawing, all
  positions are relative to the drawing sheet's lower-left corner):

  | Annotation type | Position of X,Y,Z origin |
  | --- | --- |
  | Datum Feature Symbols | Point where leader hits symbol |
  | Datum Target Symbols | Center point of the circle attached to the leader |
  | Display dimensions | Point of leader attachment centered on a text box border / center point of bottom border of text box |
  | Geometric Tolerances | Upper-left corner of the symbol |
  | Notes | Upper-left corner of the text box |
  | Revision Clouds | Determined by `IRevisionCloud::Shape` |
  | Surface Finish Symbols | Lower-left point of symbol |
  | Table Annotations | Determined by `ITableAnnotation::AnchorType` |
  | Weld Symbols | Left endpoint of the main horizontal line in the symbol |

  Any other annotation type: no action, returns `False`.
- **Position can be clamped by geometric restrictions**, per the page: a
  surface-finish symbol inserted directly on a face (no leader) can only be moved
  within that face's borders; on an edge, only along that edge or its extensions.
  Datum feature symbols have similar restrictions. If the requested position
  violates a restriction, the annotation is placed "as near as possible" instead of
  failing outright.
- Table annotations: position cannot be set if the table is anchored — check
  `ITableAnnotation::Anchored` first.
- Dimensions with offset text: to move the dimension text, dimension line, *and*
  extension lines, turn offset text off, call `SetPosition2`, then turn it back on;
  to move only the dimension text, call `SetPosition2` directly (offset text stays
  on). Radial/diametric dimensions don't support this at all (already leader-attached).

---

### IAnnotation::SetLeader3

- **Interface:** IAnnotation
- **Method:** SetLeader3
- **Minimum SW version:** SOLIDWORKS 2006 FCS, Revision Number 14.0

**Signature:**

```vb
Function SetLeader3( _
   ByVal LeaderStyle As System.Integer, _
   ByVal LeaderSide As System.Integer, _
   ByVal SmartArrowHeadStyle As System.Boolean, _
   ByVal Perpendicular As System.Boolean, _
   ByVal AllAround As System.Boolean, _
   ByVal Dashed As System.Boolean _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| LeaderStyle | Integer | n/a | Yes | Leader style (see Gotchas for which styles are valid on which annotation types) | `swLeaderStyle_e` |
| LeaderSide | Integer | n/a | Yes | Leader attachment side | `swLeaderSide_e` |
| SmartArrowHeadStyle | Boolean | n/a | Yes | `True` to enable smart arrowhead style, `False` to disable | |
| Perpendicular | Boolean | n/a | Yes | `True` to enable perpendicular bent leader display, `False` to disable | |
| AllAround | Boolean | n/a | Yes | `True` to enable all-around (weld, surface finish, or GTol) symbol display, `False` to disable | |
| Dashed | Boolean | n/a | Yes | `True` for a dashed-line leader, `False` for solid | |

**Returns:** `Integer` status code, **not a Boolean** despite what a `SetLeader3`-style
name might suggest:

| Value | Meaning |
| --- | --- |
| 0 | Leader characteristics were successfully set |
| -1 | Not set, unknown error |
| -2 | `LeaderSide` setting is invalid |
| -3 | Leaders are not supported on this type of annotation |
| -4 | Leaders cannot be disabled on this type of annotation |
| -5 | Bent leaders cannot be disabled on this type of annotation |
| -6 | Underline-style leaders are not allowed on this type of annotation |

**Prior selection required:** None via `ISelectionMgr` for the call itself — invoked
directly on an `IAnnotation` object reference already held. Per the page's own
Remarks: "Only notes, GTols, surface finish symbols, weld symbols, datum target
symbols, and block instances support leaders of any kind" — calling `SetLeader3` on
any other annotation type returns status `-3`. This restriction should be enforced
by the tool layer before calling `SetLeader3`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~SetLeader3.html

**status:** verified

**Gotchas:**
- **Per-type leader-style restrictions**, quoted verbatim from the page's Remarks:
  - Weld symbol leaders can be hidden, but are always bent — straight leaders
    (`swSTRAIGHT`) are not supported.
  - Datum target symbols can have straight or bent leaders, but cannot be hidden
    (`swNO_LEADER` is not supported).
  - Only notes support underline leaders (`swUNDERLINED`).
  - GTols are the only annotation type that supports perpendicular bent leaders.
  - GTols and weld symbols are the only types that support all-around leader
    symbols.
  - Datum target symbols are the only type that supports dashed leaders.
- This method sets the annotation's leader *characteristics*, not the individual
  leader geometry — characteristics can be read/set (via `GetDashedLeader`,
  `GetLeaderAllARound`, `GetLeaderPerpendicular`, `GetLeaderSide`, `GetLeaderStyle`,
  `GetSmartArrowHeadStyle`) whether or not leaders are currently displayed. However,
  if leader display is disabled entirely, setting `LeaderSide`/
  `SmartArrowHeadStyle`/`Dashed` has no visible effect; similarly, if bent leaders
  are disabled, `Perpendicular`/`AllAround` have no visible effect.
- If leader display is enabled, this method changes the visible model — expect a
  graphics redraw.
- `IAnnotation::SetLeaderAttachmentPointAtIndex` is a separate, related method
  controlling per-point leader attachment geometry, not overall leader style — do
  not confuse with `SetLeader3`.

---

### IAnnotation::Layer

- **Interface:** IAnnotation
- **Method:** Layer (property, not a method)
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Property Layer As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | String | n/a | Yes | Name of the layer used for this annotation. Pass `""` to set the annotation to not be on any layer | |

**Returns:** `String` (getter) — the layer name the annotation currently belongs to.
Per the page's own NOTE: "The return value might be an empty string because an old
document might not contain layers. This also occurs if annotations have been
generated in a new document that does not have layers defined." — i.e. an empty
string is not unambiguously "no layer assigned" versus "document predates/lacks
layers."

**Prior selection required:** None via `ISelectionMgr` — read/write directly on an
already-held `IAnnotation` object reference. Layers are supported only in
SOLIDWORKS **drawing** documents (per the page's opening line) — this property is
meaningless (or at least untested) on annotations in part/assembly documents.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAnnotation~Layer.html

**status:** verified

**Gotchas:**
- Setting `Layer = ""` is the documented way to clear an annotation's layer
  assignment, not by passing `Nothing`/`null` — COM string properties don't
  distinguish empty-string from unset here.
- The getter's empty-string ambiguity (no layer vs. pre-layers/undefined-layers
  document) matters for any tool-layer code that reads `Layer` to decide whether to
  act — don't treat `""` as a reliable "not on any layer" signal without also
  checking whether the document defines layers at all.
- `IAnnotation` is the generic base representation for every annotation-like object
  in the API. Type-specific interfaces (`INote`, `IGTol`, `IDatumTag`,
  `IDatumTargetSym`, `IDisplayDimension`, etc.) are obtained from an `IAnnotation` via
  `GetSpecificAnnotation` (discriminated by `swAnnotationType_e`, see the Enums
  section), and conversely most of those type-specific interfaces expose a
  `GetAnnotation` method back to the shared `IAnnotation`. `SetPosition2`,
  `SetLeader3`, and `Layer` apply generically across annotation types by calling them
  on the shared `IAnnotation` reference, but some (e.g. leaders) are only
  meaningful/successful for a subset of concrete types, per each record's Gotchas
  above.

## Enums

#### swInsertAnnotation_e

Bitmask enum — annotation types to insert, consumed by
`IDrawingDoc::InsertModelAnnotations3`/`4`'s `Types` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swInsertCThreads | 1 (0x1) | Insert annotation cosmetic threads |
| swInsertDatums | 2 (0x2) | Insert datum feature symbols |
| swInsertDatumTargets | 4 (0x4) | Insert datum targets |
| swInsertDimensions | 8 (0x8) | Insert dimensions |
| swInsertInstanceCounts | 16 (0x10) | Insert dimension instance/revolution counts |
| swInsertGTols | 32 (0x20) | Insert annotation geometric tolerances |
| swInsertNotes | 64 (0x40) | Insert notes |
| swInsertSFSymbols | 128 (0x80) | Insert annotation surface finishes |
| swInsertWelds | 256 (0x100) | Insert annotation weld symbols |
| swInsertAxes | 512 (0x200) | Insert axes |
| swInsertCurves | 1024 (0x400) | Insert curves |
| swInsertPlanes | 2048 (0x800) | Insert planes |
| swInsertSurfaces | 4096 (0x1000) | Insert surfaces |
| swInsertPoints | 8192 (0x2000) | Insert routing points |
| swInsertOrigins | 16384 (0x4000) | Insert origins |
| swInsertDimensionsMarkedForDrawing | 32768 (0x8000) | Insert dimensions marked for drawing |
| swInsertHoleWizardProfileDimensions | 65536 (0x10000) | Insert Hole Wizard profile dimensions |
| swInsertHoleWizardLocationDimensions | 131072 (0x20000) | Insert Hole Wizard location dimensions |
| swInsertRefPoints | 262144 (0x40000) | Insert reference geometry points |
| swInsertDimensionsNotMarkedForDrawing | 524288 (0x80000) | Insert dimensions not marked for drawing |
| swInsertholeCallout | 1048576 (0x100000) | Insert hole callouts |
| swInsertWeldBeads | 2097152 (0x200000) | Insert annotation weld bead caterpillars |
| swInsertSketches | 4194304 (0x400000) | Insert sketches |
| swInsertCenterOfMass | 33554432 (0x2000000) | Insert center of mass |
| swInsertTolerancedDims | 16777216 (0x1000000) | Insert toleranced dimensions |
| swInsertWeldBeads_ET | 8388608 (0x800000) | Insert annotation weld bead end treatments |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swInsertAnnotation_e.html

**Addendum (sw-1xx.1, re-fetched independently via the same curl+UA
technique):** the 25 members above are the complete set — there is **no**
center-mark or centerline member on this enum, in any generation. Center
marks/centerlines are a wholly separate mechanism,
`IDrawingDoc::InsertCenterMark3` (`swCenterMarkStyle_e`, already documented
elsewhere in this file), not reachable through `InsertModelAnnotations3`/`4`'s
`Types` bitmask at all. A tool layer wanting a `types` option named
`"center_marks"`/`"centerlines"` cannot bind it to this bitmask — do not
invent a bit value for it.

#### swImportModelItemsSource_e

Consumed by `IDrawingDoc::InsertModelAnnotations3`/`4`'s `Option` parameter (source
of dimensions).

| Value | Number | Meaning |
| --- | --- | --- |
| swImportModelItemsFromEntireModel | 0 | All dimensions in the view |
| swImportModelItemsFromSelectedFeature | 1 | All dimensions of the currently selected feature |
| swImportModelItemsFromSelectedComponent | 2 | All dimensions of the currently selected component (assembly drawings) |
| swImportModelItemsFromAssemblyOnly | 3 | All dimensions of the assembly |

Note: these are the **corrected** meanings per `InsertModelAnnotations3`'s own
Remarks — SolidWorks API Help published before 2008 SP3 documented members `1` and
`2` swapped (feature vs. component). Treat any pre-2008-SP3 secondary source
describing this enum's values differently as wrong.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swImportModelItemsSource_e.html

**Addendum (sw-1xx.1, re-fetched independently via the same curl+UA
technique):** the 4 members above are the complete set — there is no
DimXpert member of any kind on this enum. DimXpert annotation import is a
real SOLIDWORKS capability, but the only mechanism this dossier found for it
is `IView::ImportAnnotations`'s `IncludeDimXpertAnnotations` boolean flag
(SOLIDWORKS 2025+, documented above) — a coarse per-category toggle on a
different method entirely, not a `swImportModelItemsSource_e` member. A tool
layer wanting a `sources="dimxpert"` option cannot bind it to this enum —
either route it to `IView::ImportAnnotations` as a genuinely separate code
path, or reject it outright rather than aliasing it to another source.

#### swAutodimScheme_e

Used by `ISketch::AutoDimension2` and `IDrawingDoc::AutoDimension` for
`HorizontalScheme`/`VerticalScheme`.

| Value | Number | Meaning |
| --- | --- | --- |
| swAutodimSchemeBaseline | 1 | Baseline dimensioning scheme |
| swAutodimSchemeOrdinate | 2 | Ordinate dimensioning scheme |
| swAutodimSchemeChain | 3 | Chain dimensioning scheme |
| swAutodimSchemeCenterline | 4 | Not supported in sketches or drawings; do not use |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimScheme_e.html

#### swAutodimEntities_e

Used by `IDrawingDoc::AutoDimension`'s `EntitiesToDimension` parameter (and
`ISketch::AutoDimension2`). Supported entities: lines, points, vertices, faces,
sketch entities, center lines, and center marks.

| Value | Number | Meaning |
| --- | --- | --- |
| swAutodimEntitiesBasedOnPreselect | 0 | Autodimension selected entities marked `swAutodimMarkEntities` if any exist; otherwise autodimension all supported entities |
| swAutodimEntitiesAll | 1 | Autodimension all supported entities in the view/sketch |
| swAutodimEntitiesSelected | 2 | Autodimension only entities marked `swAutodimMarkEntities`; falls back to all if none marked |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimEntities_e.html

#### swAutodimHorizontalPlacement_e (sw-1xx.2)

`IDrawingDoc::AutoDimension`'s `HorizontalPlacement` parameter — out of scope for
the original research pass (flagged unfetched in that record's own Gotchas);
fetched independently for sw-1xx.2 via the same curl+UA technique.

| Value | Number | Meaning |
| --- | --- | --- |
| swAutodimHorizontalPlacementBelow | -1 | Place the horizontal dimensions below the sketch/view |
| swAutodimHorizontalPlacementAbove | 1 | Place the horizontal dimensions above the sketch/view |

Note: no `0` member — this is a 2-way flat selector, not a bitmask, and its two
values are `-1`/`1`, not `0`/`1`.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimHorizontalPlacement_e.html

#### swAutodimVerticalPlacement_e (sw-1xx.2)

`IDrawingDoc::AutoDimension`'s `VerticalPlacement` parameter — same fetch note as
`swAutodimHorizontalPlacement_e` above.

| Value | Number | Meaning |
| --- | --- | --- |
| swAutodimVerticalPlacementLeft | -1 | Place the vertical dimensions left of the sketch/view |
| swAutodimVerticalPlacementRight | 1 | Place the vertical dimensions right of the sketch/view |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimVerticalPlacement_e.html

#### swAutodimStatus_e (sw-1xx.2)

`IDrawingDoc::AutoDimension`'s (and `ISketch::AutoDimension2`'s) return value — the
original research pass explicitly flagged this enum as "not itself fetched in this
pass" in the `AutoDimension` record's own Returns line; fetched independently for
sw-1xx.2.

| Value | Number | Meaning |
| --- | --- | --- |
| swAutodimStatusSuccess | 0 | Sketch/view successfully dimensioned |
| swAutodimStatusBadOptionValue | 1 | An option value for an argument is out of range |
| swAutodimStatusNoActiveDoc | 2 | No active document |
| swAutodimStatusDocTypeNotSupported | 3 | Only part and assembly documents are supported (per the page's own text — see Gotchas) |
| swAutodimStatusNoActiveSketch | 4 | Can only autodimension an active sketch |
| swAutodimStatus3DSketchNotSupported | 5 | Cannot autodimension a 3D sketch |
| swAutodimStatusSketchIsEmpty | 6 | Cannot autodimension an empty sketch |
| swAutodimStatusSketchIsOverDefined | 7 | Cannot autodimension an over-defined sketch |
| swAutodimStatusNoEntities | 8 | `EntitiesToDimension` is `swAutodimEntitiesSelected`, but nothing was selected+marked `swAutodimMarkEntities` |
| swAutodimStatusEntitiesNotValid | 9 | `EntitiesToDimension` is `swAutodimEntitiesSelected`, but the marked entities are not valid |
| swAutodimStatusCenterlineNotAllowed | 10 | The centerline scheme is not valid for sketches that cannot be revolved to create valid features |
| swAutodimStatusDatumNotSupplied | 11 | No datum was selected for either the horizontal or vertical dimensioning scheme |
| swAutodimStatusDatumNotUnique | 12 | More than one datum was selected for either dimensioning scheme |
| swAutodimStatusDatumNotValidType | 13 | A selected datum is not a sketch point or sketch line |
| swAutodimStatusDatumLineNotCenterline | 14 | The datum must be a centerline for the centerline scheme |
| swAutodimStatusDatumLineNotVertical | 15 | A sketch-line datum must be vertical for the vertical dimensioning scheme |
| swAutodimStatusDatumLineNotHorizontal | 16 | A sketch-line datum must be horizontal for the horizontal dimensioning scheme |
| swAutodimStatusAlgorithmFailed | 17 | Unspecified algorithm failure |
| swAutodimStatusSketchNoSolutionFound | 18 | Cannot autodimension a sketch for which there is no solution |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimStatus_e.html

**Gotcha:** several member descriptions on the page itself are sketch/`ISketch::
AutoDimension2`-flavored ("active sketch", "3D sketch", "over defined sketch") since
this enum is shared with that sibling method — a drawing-view call through
`IDrawingDoc::AutoDimension` realistically only returns a subset of these (success,
bad-option, no-active-doc, no-entities/entities-not-valid, datum-related, and
algorithm-failed/no-solution-found are the plausible ones; the sketch-specific codes
are not reachable from a drawing view). `swAutodimStatusDocTypeNotSupported`'s "only
part and assembly documents" description is itself `ISketch::AutoDimension2`-scoped
wording carried over from the shared enum page — it does not mean
`IDrawingDoc::AutoDimension` rejects drawings; that would contradict the whole
premise of the method.

#### swDimensionType_e

Identifies the concrete kind of a dimension; consumed/returned around
`IDimension`/`IDisplayDimension`.

| Value | Number | Meaning |
| --- | --- | --- |
| swDimensionTypeUnknown | 0 | Dimension type could not be determined |
| swOrdinateDimension | 1 | Base ordinate and its subordinates are of this type |
| swLinearDimension | 2 | Linear dimension type |
| swAngularDimension | 3 | Angular dimension type |
| swArcLengthDimension | 4 | Arc length dimension type |
| swRadialDimension | 5 | Radial dimension |
| swDiameterDimension | 6 | Diameter dimension |
| swHorOrdinateDimension | 7 | Horizontal ordinate dimension |
| swVertOrdinateDimension | 8 | Vertical ordinate dimension |
| swZAxisDimension | 9 | Z-axis dimension |
| swChamferDimension | 10 | Chamfer dimension |
| swHorLinearDimension | 11 | Horizontal linear dimension |
| swVertLinearDimension | 12 | Vertical linear dimension |
| swScalarDimension | 13 | Scalar dimension |
| swRadialLinearDimension | 14 | Doubled distance radial dimension |
| swDiametricLinearDimension | 15 | Doubled distance linear dimension |
| swAngularOrdinateDimension | 16 | Angular ordinate dimension |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDimensionType_e.html

#### swSetValueInConfiguration_e (sw-1xx.2)

`WhichConfigurations` for `IDimension::SetValue3`/`SetSystemValue3` — out of scope
for the original research pass; fetched independently for sw-1xx.2.

| Value | Number | Meaning |
| --- | --- | --- |
| swSetValue_NoConfiguration | -1 | Ignore configurations in drawing sketches |
| swSetValue_UseCurrentSetting | 0 | Use whatever setting this parameter currently has |
| swSetValue_InThisConfiguration | 1 | Set the value in the current configuration only |
| swSetValue_InAllConfigurations | 2 | Set the value in all configurations |
| swSetValue_InSpecificConfigurations | 3 | Set the value in the configuration(s) named by `Config_names` |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSetValueInConfiguration_e.html

#### swInConfigurationOpts_e (sw-1xx.2)

`WhichConfigurations` for `IDimension::GetSystemValue3`/`GetValue3` — a **different**
enum than `swSetValueInConfiguration_e` above despite the shared "this
configuration"/"all configurations" concepts on the getter vs. setter sides of the
same value. Fetched independently for sw-1xx.2 while resolving `GetSystemValue3`'s
own enum ref (its page names this enum, not `swSetValueInConfiguration_e`).

| Value | Number | Meaning |
| --- | --- | --- |
| swConfigPropertySuppressFeatures | 0 | (page gives no description beyond the name) |
| swThisConfiguration | 1 | Current configuration only |
| swAllConfiguration | 2 | All configurations |
| swSpecifyConfiguration | 3 | The configuration(s) named by `Config_names` |
| swLinkedToParent | 4 | Derived configurations only; non-derived configurations fall back to the active configuration |
| swSpeedpakConfiguration | 5 | (page gives no description beyond the name) |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swInConfigurationOpts_e.html

**Gotcha:** `swThisConfiguration` (`1`) and `swSetValue_InThisConfiguration` (`1`)
agree numerically — this dossier's tool layer relies on that agreement to use the
literal `1` for "current configuration only" on both the read and write side of a
dimension value round-trip — but the two enums are not the same declaration and the
rest of their members do not correspond position-for-position (e.g. `2` is
"all configurations" on both, but `swSetValue_InSpecificConfigurations` = `3` on the
setter side vs. `swSpecifyConfiguration` = `3` on the getter side happen to also
agree — verify numerically before assuming, do not assume by name alone).

#### swSetValueReturnStatus_e (sw-1xx.2)

Return status of `IDimension::SetValue3`/`SetSystemValue3` — the original research
pass explicitly flagged this enum as "not fetched in this pass" in both methods'
own Returns lines; fetched independently for sw-1xx.2.

| Value | Number | Meaning |
| --- | --- | --- |
| swSetValue_Successful | 0 | Successful |
| swSetValue_Failure | 1 | Failed for an unknown reason |
| swSetValue_InvalidValue | 2 | Not a valid value for the change parameter |
| swSetValue_DrivenDimension | 3 | Cannot be done on a dimension driven by geometry |
| swSetValue_ModelNotLoaded | 4 | Model must be loaded in order to set this value |
| swSetValue_FrozenFeatureOwner | 5 | Owner of the dimension is frozen |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSetValueReturnStatus_e.html

#### swAddOrdinateDims_e

The `DimType` enum ref for `IModelDocExtension::AddOrdinateDimension` (and the
obsolete `IDrawingDoc::AddOrdinateDimension2`).

| Value | Number | Meaning |
| --- | --- | --- |
| swOrdinate | 1 | Orientation (horizontal/vertical) is inferred from the selected points |
| swVerticalOrdinate | 2 | Vertical ordinate dimension |
| swHorizontalOrdinate | 3 | Horizontal ordinate dimension |
| swAngularOrdinate | 4 | Angular ordinate dimension |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAddOrdinateDims_e.html

#### swCreateOrdDimError_e (sw-1xx.2)

Return code of `IModelDocExtension::AddOrdinateDimension` — the original research
pass explicitly flagged this enum as "not fetched in this pass" in that method's own
Returns line; fetched independently for sw-1xx.2. The page gives no per-member
description text beyond the member name itself for any member.

| Value | Number |
| --- | --- |
| swCreateOrdDimErr_Undefined | -1 |
| swCreateOrdDimErr_Success | 0 |
| swCreateOrdDimErr_OrdFailure | 1 |
| swCreateOrdDimErr_GenNoInternalDims | 2 |
| swCreateOrdDimErr_GenBadSel | 3 |
| swCreateOrdDimErr_GenNeedModelLoaded | 4 |
| swCreateOrdDimErr_GenSamePartOnly | 5 |
| swCreateOrdDimErr_GenExtraSelection | 6 |
| swCreateOrdDimErr_GenFailure | 7 |
| swCreateOrdDimErr_OrdDupInGroup | 8 |
| swCreateOrdDimErr_OrdBadDir | 9 |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateOrdDimError_e.html

#### swTextJustification_e

Requested as `swTextAlign_e`, which does not exist (confirmed by the server's own
file-not-found JSON on direct fetch). The real enum is consumed by
`INote::SetTextJustification`/`GetTextJustification` (and per-line variants
`SetTextJustificationAtIndex`/`GetTextJustificationAtIndex`) — set *after* note
creation, not as a parameter to `CreateText2`/`CreateText`.

| Value | Number | Meaning |
| --- | --- | --- |
| swTextJustificationNone | 0 | No text justification |
| swTextJustificationLeft | 1 | Text is left-justified |
| swTextJustificationCenter | 2 | Text is center-justified |
| swTextJustificationRight | 3 | Text is right-justified |

Note: a separate enum, `swVerticalJustification_e`, exists for vertical justification
via `INote::SetTextVerticalJustification` — not independently fetched here, flagged
only so it isn't reached for by mistake.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swTextJustification_e.html

#### swDimensionTextParts_e (sw-1xx.2)

`WhichText` for `IDisplayDimension::SetText`/`GetText` — out of scope for the
original research pass; fetched independently for sw-1xx.2.

| Value | Number | Meaning |
| --- | --- | --- |
| swDimensionTextAll | 0 | Entire dimension text string (`SetText` only — invalid for `GetText`, per that record's own Gotchas) |
| swDimensionTextPrefix | 1 | Prefix portion of the text |
| swDimensionTextSuffix | 2 | Suffix portion of the text |
| swDimensionTextCalloutAbove | 3 | Callout-above portion of the text |
| swDimensionTextCalloutBelow | 4 | Callout-below portion of the text |
| swDimensionTextPrefixDefinition | 5 | Definition of the prefix portion of the text |
| swDimensionTextSuffixDefinition | 6 | Definition of the suffix portion of the text |
| swDimensionTextCalloutAboveDefinition | 7 | Definition of the callout portion of the text above the dimension |
| swDimensionTextCalloutBelowDefinition | 8 | Definition of the callout portion of the text below the dimension |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDimensionTextParts_e.html

#### swLeaderStyle_e

Bitmask enum. Consumed by `InsertSurfaceFinishSymbol3`'s `LeaderType`,
`InsertDatumTargetSymbol3`'s `LeaderLineStyle`, and `IAnnotation::SetLeader3`'s
`LeaderStyle`.

| Value | Number | Meaning |
| --- | --- | --- |
| swNO_LEADER | 0 | No leader |
| swSTRAIGHT | 1 | Straight leader |
| swBENT | 2 | Bent leader |
| swUNDERLINED | 3 | Underlined leader; parts only |
| swSPLINE | 4 | Spline leader from a note; drawings only |
| swVDA | 8 | Inspection leader |
| swAttachLeaderTop | 0x100 (256) | Bitmask, part multiline notes: attach leader to top of note; AND with `swBENT`/`swSTRAIGHT`/`swUNDERLINED` |
| swAttachLeaderCenter | 0x200 (512) | Bitmask: attach to center; same AND-combination rule |
| swAttachLeaderBottom | 0x400 (1024) | Bitmask: attach to bottom; same rule |
| swAttachLeaderNearest | 0x800 (2048) | Bitmask: left leader→top, right leader→bottom; same rule |
| swAlwaysAttachToBalloon | 0x1004 (4100) | Bitmask, balloons only: enables "Always Attach to Balloon" and disables "Break Around" leader options; AND with a base shape member |

Note: this is a genuine bitmask enum, not a flat list — the four `swAttachLeader*`
members and `swAlwaysAttachToBalloon` combine via bitwise AND/OR with one of the
low-value shape members (`swNO_LEADER`/`swSTRAIGHT`/`swBENT`/`swUNDERLINED`/
`swSPLINE`/`swVDA`).

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swLeaderStyle_e.html

#### swLeaderSide_e (sw-1xx.3)

Consumed by `IAnnotation::SetLeader3`'s `LeaderSide` parameter (documented above,
"Annotation object manipulation" section). **Numeric values not found** — every
`help.solidworks.com` fetch attempted for this enum's own swconst page returned the
same WAF 403 this dossier's intro and the "Note enumeration, formatting, and
editing" record above both document; no secondary mirror with the numeric
assignments was found either. Member *names* only, corroborated by two independent
search-engine hits quoting real usage (`swLeaderSide_e.swLS_SMART` cast to
`Integer` in a real code sample; a second hit naming all three members together):

| Value | Number | Meaning |
| --- | --- | --- |
| swLS_LEFT | unknown | Leader attaches on the left side |
| swLS_RIGHT | unknown | Leader attaches on the right side |
| swLS_SMART | unknown | SolidWorks picks the side automatically |

Source (attempted, returns error):
https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swLeaderSide_e.html

**status:** unverified — member names only, no numeric values from any accessible
source. `drawings.py`'s `_LEADER_SIDE_DEFAULT` picks a fixed internal value (not
tied to any of the three names above with confidence) rather than guess which name
maps to which number; do not add a public `LeaderSide`-selecting parameter from
this table without re-deriving the real values first.

#### swGtolShape_e

**Does not exist.** Direct fetch of
`https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swGtolShape_e.html`
returns the server's own file-not-found JSON, and a web search for `swGtolShape`
returns no matching SOLIDWORKS documentation page at any version. A GD&T frame's
geometric characteristic symbol ("shape") is not enum-driven at all — it's the
free-form `<LibraryName-SymbolName>` bracket-token string (legacy format,
`GCS`/`SetFrameSymbols2`) or the bare `LibraryName-SymbolName` `<ToleranceSymbol>`
element value (current format, `SetSymbolXml`), both referencing `gtol.sym` — see the
GD&T section above. Any tool-layer type modeling "GTol shape" should model it as a
constrained string/token, not a COM enum.

Source (attempted, returns error): https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swGtolShape_e.html

#### swDatumDisplayType_e

Requested as `swDatumTagStyle_e`, which does not exist (confirmed by file-not-found
JSON on direct fetch). Drives a datum tag's leader/shoulder **display style** (square
vs. round), set post-creation via `IDatumTag::SetDisplayStyle(UseDoc, Style)`, where
`UseDoc=True` ignores `Style` and uses the document's default instead.

| Value | Number | Meaning |
| --- | --- | --- |
| swDatumDisplayType_Default | 0 | Default datum feature display style |
| swDatumDisplayType_Square | 1 | Square datum tag |
| swDatumDisplayType_Round | 2 | Round datum tag |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDatumDisplayType_e.html

#### swSFSymType_e

Real under the exact requested name — no rename/discrepancy to flag. Consumed by
`InsertSurfaceFinishSymbol3`'s `SymType` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swSFBasic | 0 | Basic surface finish symbol |
| swSFJIS_Machining_Req | 1 | JIS machining required |
| swSFDont_Machine | 2 | Don't machine |
| swSFJIS_Surface_Texture_1 | 3 | JIS surface texture, variant 1 |
| swSFJIS_Surface_Texture_2 | 4 | JIS surface texture, variant 2 |
| swSFJIS_Surface_Texture_3 | 5 | JIS surface texture, variant 3 |
| swSFJIS_Surface_Texture_4 | 6 | JIS surface texture, variant 4 |
| swSFJIS_No_Machining | 7 | JIS, no machining |
| swSFJIS_Basic | 8 | JIS basic |
| swSFMachining_Req | 9 | Machining required |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSFSymType_e.html

#### swSFLaySym_e (sw-1xx.5)

Real under the exact requested name. Consumed by `InsertSurfaceFinishSymbol3`'s
`LaySymbol` parameter (direction-of-lay symbol, combined with `SymType` to form the
full surface finish symbol per the "Surface Finish Symbols" conceptual page: "Surface
finish symbols are formed by combining the Symbol and Lay Direction"). Direct fetch
of the `swconst` page 403'd with a bare `WebFetch` (same WAF block this dossier's
intro documents), but succeeded via this project's own documented workaround (`curl
-A "Mozilla/5.0 ..." <url>`, per `README.md`'s canonical-source-urls retry
convention) — the page is a client-rendered Next.js shell whose actual content ships
as a JSON blob (`__NEXT_DATA__` script tag, `props.pageProps.helpContentData.helpText`)
rather than as static HTML, which is why a bare fetch (no JS execution) sees only the
empty shell.

| Value | Number | Meaning |
| --- | --- | --- |
| swSFNone | 0 | No direction-of-lay symbol |
| swSFCircular | 1 | Circular |
| swSFCross | 2 | Crossed |
| swSFMultiDir | 3 | Multi-directional |
| swSFParallel | 4 | Parallel |
| swSFPerp | 5 | Perpendicular |
| swSFRadial | 6 | Radial |
| swSFParticulate | 7 | Particulate (non-directional) |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSFLaySym_e.html
(fetched directly via the curl workaround above; member names/order cross-checked
against a convergent search-engine snippet quoting the same 8 members before the
direct fetch was attempted)

**status:** verified

#### swArrowStyle_e (sw-1xx.5)

Real under the exact requested name. Consumed by `InsertSurfaceFinishSymbol3`'s
`ArrowType` parameter, `InsertDatumTargetSymbol3`'s `ArrowStyle` parameter (sw-1xx.4
left this one unfetched — its worked example passes `12`, confirmed below to be
`swSMART_ARROWHEAD`), and `IAnnotation::SetArrowHeadStyleAtIndex`. Fetched via the
same curl workaround as `swSFLaySym_e` above.

| Value | Number | Meaning |
| --- | --- | --- |
| swOPEN_ARROWHEAD | 0 | No fill |
| swCLOSED_ARROWHEAD | 1 | Filled |
| swSLASH_ARROWHEAD | 2 | Slash |
| swDOT_ARROWHEAD | 3 | Filled circle |
| swORIGIN_ARROWHEAD | 4 | No-fill circle |
| swWIDE_ARROWHEAD | 5 | Wide |
| swISOWIDE_ARROWHEAD | 6 | ISO wide |
| swRUS_ARROWHEAD | 7 | GOST standard |
| swCLOSETOP_ARROWHEAD | 8 | Filled top only |
| swCLOSEBOT_ARROWHEAD | 9 | Filled bottom only |
| swNO_ARROWHEAD | 10 | None |
| swSHOULDER_ARROWHEAD | 11 | No arrowhead; filled triangle at leader attachment point |
| swSMART_ARROWHEAD | 12 | Filled arrowhead with lightning bolt |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swArrowStyle_e.html

**status:** verified

#### swWeldSymbolContourTypes_e

Requested as `swWeldSymbolType_e`, which does not exist (confirmed by file-not-found
JSON on direct fetch — the weld symbol's *type/name*, e.g. `BUTT`/`FILL`/`PLUG`, is a
fixed ISO string set passed to `IWeldSymbol::SetText`'s `Symbol` parameter, not an
enum at all). The real weld-related enum in this dossier's scope governs **contour**,
consumed by `SetText`'s `Contour` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swWeldContourNone | 1 | No contour |
| swWeldContourFlat | 2 | Flat contour |
| swWeldContourConvex | 3 | Convex contour |
| swWeldContourConcave | 4 | Concave contour |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swWeldSymbolContourTypes_e.html

#### swWeldSymbolField_e (sw-1xx.5)

Consumed by `IWeldSymbol::SetFieldWeld`'s `FieldWeld` parameter (see the sw-1xx.5
addendum below). Fetched via the curl workaround (see `swSFLaySym_e` above).

| Value | Number | Meaning |
| --- | --- | --- |
| swFieldWeldNone | 1 | No field/site weld marking on this annotation |
| swFieldWeldUp | 2 | Field/site weld marking, flag pointing up |
| swFieldWeldDown | 3 | Field/site weld marking, flag pointing down |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swWeldSymbolField_e.html

**status:** verified

#### swWeldSymbolSymmetric_e (sw-1xx.5)

Consumed by `IWeldSymbol::SetSymmetric`'s `Symmetric` parameter (see the sw-1xx.5
addendum below). Fetched via the curl workaround (see `swSFLaySym_e` above).

| Value | Number | Meaning |
| --- | --- | --- |
| swWeldSymmetric | 1 | The weld symbol is symmetric -- content on one side of the reference line is mirrored to the other side |
| swWeldDashedLineOnTop | 2 | Not symmetric, dashed identification line above |
| swWeldDashedLineOnBottom | 3 | Not symmetric, dashed identification line below |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swWeldSymbolSymmetric_e.html

**status:** verified

#### swCenterMarkStyle_e

Consumed by `IDrawingDoc::InsertCenterMark3`'s `Style` parameter. Real under the
exact requested name.

| Value | Number | Meaning |
| --- | --- | --- |
| swCenterMark_NonAnnotation | 1 | Non-annotation center mark |
| swCenterMark_Single | 2 | Single center mark |
| swCenterMark_LinearGroup | 3 | Linear group center mark |
| swCenterMark_CircularGroup | 4 | Circular group center mark |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCenterMarkStyle_e.html

#### swCenterMarkConnectionLine_e (sw-1xx.6)

Consumed by `ICenterMark::ConnectionLines`'s property value (bitmask; fetched
independently for sw-1xx.6 via the same curl+UA technique, since neither this enum
nor `ICenterMark`'s own display-setting properties were in scope for the original
research pass).

| Value | Number | Meaning |
| --- | --- | --- |
| swCenterMark_ShowNoConnectLines | 0 | No connection lines shown |
| swCenterMark_ShowLinearConnectLines | 1 | Show linear connection lines |
| swCenterMark_ShowCircularConnectLines | 2 | Show circular connection lines |
| swCenterMark_ShowRadialConnectLines | 4 | Show radial connection lines |
| swCenterMark_ShowBaseCenterMarkLines | 8 | Show base center mark lines |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCenterMarkConnectionLine_e.html

**status:** verified

#### swAnnotationType_e

Identifies the concrete annotation subtype. Directly fetched and confirmed; a
20-item summary (member name + numeric value, no description text) with no
`GetSpecificAnnotation`-style overview on the page itself. Note: an initial
reconstruction attempt from third-party GitHub type-library mirrors, done when the
help page appeared to return only an empty SPA shell, found just 17 members and was
missing `swPMIOnly` (19) and `swRevisionCloud` (18) — those mirrors were stale or
incomplete. The table below is the directly-fetched, complete, current set.

| Value | Number | Meaning |
| --- | --- | --- |
| swCThread | 1 | Cosmetic thread callout |
| swDatumTag | 2 | Datum feature symbol |
| swDatumTargetSym | 3 | Datum target symbol |
| swDisplayDimension | 4 | Dimension (display dimension) |
| swGTol | 5 | Geometric tolerance (feature control frame) |
| swNote | 6 | Note |
| swSFSymbol | 7 | Surface finish symbol |
| swWeldSymbol | 8 | Weld symbol |
| swCustomSymbol | 9 | Custom symbol |
| swDowelSym | 10 | Dowel pin symbol |
| swLeader | 11 | Leader (standalone) |
| swBlock | 12 | Block instance |
| swCenterMarkSym | 13 | Center mark symbol |
| swTableAnnotation | 14 | Table (BOM/general table) annotation |
| swCenterLine | 15 | Centerline |
| swDatumOrigin | 16 | Datum origin symbol |
| swWeldBeadSymbol | 17 | Weld bead symbol |
| swRevisionCloud | 18 | Revision cloud |
| swPMIOnly | 19 | PMI-only annotation |

The page gives no per-member description text (just name + number) — the "Meaning"
column above is this dossier's own gloss based on the member name and each type's
corresponding interface documented elsewhere in this dossier, not transcribed page
text.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAnnotationType_e.html
Secondary sources: https://raw.githubusercontent.com/tdsmith/swharness/master/swconst.py ; https://raw.githubusercontent.com/pisfu/API/master/LabRabKompas/Sample2/SwConst_TLB.pas
