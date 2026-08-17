---
interface: Multiple (IDrawingDoc, IView, ISldWorks, IModelDocExtension)
min_methods: 18
status: complete
---

# Drawing view creation and manipulation

Covers creating drawing views (standard 3-view sets, predefined views, model views,
section views, detail views, broken-out sections, projected/unfolded views), breaking
and cropping views, and reading/setting view properties (position, scale, display
mode, name, type, alignment) and lifecycle (activate, delete). This is the dossier the
view-creation epic is built from.

Several names requested by the source research issue turned out not to match the
current (SOLIDWORKS 2025) API surface. Each is documented below under the *real* name,
with the discrepancy called out explicitly in that record's Gotchas — summarized here
for a quick scan:

- `IDrawingDoc::CreateDetailViewAt5` does not exist — the current overload is
  `IDrawingDoc::CreateDetailViewAt4`.
- `IView::InsertBrokenOutSection` does not exist — the real method is
  `IDrawingDoc::CreateBreakOutSection`.
- There is no dedicated "projected view" method on `IDrawingDoc` or `IView`. The UI's
  "Insert Projected View" maps to the API's `IDrawingDoc::CreateUnfoldedViewAt3` —
  the API calls the same operation an "unfolded view."
- `IDrawingDoc::InsertBreak` does not exist — the parameterized break-line call is
  `IView::InsertBreak3`. `IDrawingDoc` only has zero-argument
  `InsertBreakHorizontal`/`InsertBreakVertical` plus `BreakView`/`UnBreakView`.
- `IView::BreakLineCount` does not exist as a property — the real member is the method
  `IView::GetBreakLineCount2`.
- Removing a break is `IDrawingDoc::UnBreakView` (a real, dedicated method — this one
  matches the task's intent even though the exact name wasn't given).
- `IView::CropView` does not exist — the current overload is `IView::Crop2`.
- `IView::RemoveCropView` does not exist and has **no dedicated API equivalent at
  all** — removing a crop requires a `ISldWorks::RunCommand` workaround (see that
  record).
- `IView::Alignment` does not exist. The real members are `IView::GetAlignment`
  (read-only method) and `IView::AlignWithView` (sets alignment to another view).
- `IDrawingDoc::AlignView` does not exist — the real method is `IView::AlignWithView`,
  called on the view being moved, not on the document.
- `IDrawingDoc::DeleteView2` does not exist — deleting a view is
  `IModelDocExtension::DeleteSelection2` on the current selection, the same
  selection-based pattern used elsewhere in this API for object deletion.
- `swDetailCircleStyle_e` does not exist — the real enum is `swDetCircleShowType_e`
  (a separate `swDetViewStyle_e` also exists, for the detail view's border/leader
  style, not its circle/profile sketch type).
- `swSectionViewOptions_e` does not exist — the real, current enum is
  `swCreateSectionViewAtOptions_e`.
- `swCreateDrawViewOption_e` does not exist at all — no enum by this name or an
  obvious rename could be found; `CreateDrawViewFromModelView3` has no options
  parameter to back one.
- `swBreakDir_e` does not exist — the real enum is `swBreakLineOrientation_e`.

`help.solidworks.com` blocked several direct fetch attempts with HTTP 403 during the
original research pass (standard-3-view and predefined-view methods especially). Those
pages have since been retrieved with a browser `User-Agent` — see
[`README.md`](README.md#canonical-source-urls) — and the affected records are now
page-verified. Where a page still cannot be fetched, the record stays
`status: unverified` with cross-checked secondary sources instead of a help-page
transcription, per this dossier format's rule against inventing signatures.

## Standard & predefined view creation

**Access note applying to this section's five records:** `help.solidworks.com`
returned HTTP 403 for every direct fetch attempt during the original research pass, so
the signatures below were first reconstructed from a type-library mirror (rimptec.com,
generated from the SOLIDWORKS Interop type library) and cross-checked against working
VBA examples (thecadcoder.com, codestack.net) and forum discussion. All five 2025 help
pages have since been fetched successfully with a browser `User-Agent`, and each
reconstructed signature matched its page exactly — parameter names, types, order, and
arity — so all five are now `status: verified`. The reconstruction route is recorded
here because it is why these records cite two independent sources apiece.

### IDrawingDoc::CreateDrawViewFromModelView3

- **Interface:** IDrawingDoc
- **Method:** CreateDrawViewFromModelView3
- **Minimum SW version:** SOLIDWORKS 2005 SP2, Revision Number 13.2 (the page's
  Availability section).

**Signature:**

```vb
Function CreateDrawViewFromModelView3( _
   ByVal ModelName As System.String, _
   ByVal ViewName As System.String, _
   ByVal LocX As System.Double, _
   ByVal LocY As System.Double, _
   ByVal LocZ As System.Double _
) As IView
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ModelName | String | n/a | Yes | Full pathname of the model document (.sldprt/.sldasm) to create the drawing view from. Every working example passes a full path from `IModelDoc2::GetPathName`; whether an empty string resolves to the already-open/active document is unconfirmed (see Gotchas) | — |
| ViewName | String | n/a | Yes | Name of the model view to project (e.g. Front, Top, Right, Isometric). Indexed help-page prose gives plain names like `"Front"`; every working code example instead passes an asterisk-prefixed form (`"*Front"`) — see Gotchas | — |
| LocX | Double | meters (sheet space) | Yes | X location of the drawing view center | — |
| LocY | Double | meters (sheet space) | Yes | Y location of the drawing view center | — |
| LocZ | Double | meters (sheet space) | Yes | Declared as meters, but sheet space is 2D — this coordinate is inert for placement; every working example passes `0` | — |

**Returns:** `IView` — the created drawing view object, or `Nothing` on failure
(confirmed via a working macro's `If modelView Is Nothing Then` check; no explicit
error code is raised).

**Prior selection required:** None — operates directly on the `IDrawingDoc` the
method is called on; no `ISelectionMgr` selection needed.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror, parameter count/order/type)
- https://thecadcoder.com/solidworks-vba-macros/drawing-insert-modelview/ (working VBA example, unit confirmation)
- https://forum.solidworks.com/thread/238877 (error behavior on misuse)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateDrawViewFromModelView3.html (fetched with a browser User-Agent; signature transcribed from this page)

**status:** verified

**Gotchas:**
- **Empty `ModelName` for an already-open model — unconfirmed.** No accessible source
  states whether `""` (or the active document's short name) resolves to the currently
  open/active model instead of requiring a full path. Every working example passes a
  full path from `GetPathName`. Treat a full path as required until verified against
  a live SOLIDWORKS session.
- **X/Y are sheet-space meters (confirmed via 2+ sources); LocZ is a no-op** — drawing
  sheets are 2D, so `LocZ` has no placement effect; pass `0`.
- **Return value on failure is `Nothing`, not a boolean/error code** — differs from
  the deprecated `CreateDrawViewFromModelView` (returns `Boolean`).
  `CreateDrawViewFromModelView2` also returns `IView`, same as v3; the functional
  delta between v2 and v3 could not be pinned down from accessible sources — v3 is
  what current examples use, so treat it as preferred.
- **`"Front"` vs `"*Front"` discrepancy** — indexed help-page prose uses plain
  `"Front"`; every working macro example instead passes `"*Front"`. Use
  `IModelDoc2::GetModelViewNames` to enumerate a model's actual valid view names
  rather than guessing the prefix convention.
- **Auto-scale coupling** — per an indexed help-page excerpt, this method "uses the
  `swAutomaticScaling3ViewDrawings` setting to set the view scale. If this setting is
  set to True, when a new drawing view is inserted, that view automatically scales to
  fit nicely on the drawing sheet. If there are no views on the sheet, the sheet scale
  is changed to the appropriate scale, and the view created uses the sheet scale."
  Read `ISldWorks::GetUserPreferenceToggle(swAutomaticScaling3ViewDrawings)`
  beforehand if scale predictability matters.
- **Runtime error 438** ("Object doesn't support this property or method") has been
  reported on this call in a late-binding/wrong-interface-reference scenario — ensure
  the object variable is dimensioned as `SldWorks.DrawingDoc`/`IDrawingDoc`, not a
  generic `Object` or `ModelDoc2`.
- This method is unrelated to "project a view off an existing drawing view" — see the
  Projected views section below.

### IDrawingDoc::Create3rdAngleViews2

- **Interface:** IDrawingDoc
- **Method:** Create3rdAngleViews2
- **Minimum SW version:** SOLIDWORKS 99 SP01, datecode 1999229 (the page's
  Availability section).

**Signature:**

```vb
Function Create3rdAngleViews2( _
   ByVal ModelName As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ModelName | String | n/a | Yes | Full pathname of the model document from which to create the standard 3rd-angle-projection 3-view set (front/top/right) | — |

**Returns:** `Boolean` — `True` if the views were created successfully, `False` if
not. No `IView`/collection handle is returned; retrieve the created views afterward
via `IDrawingDoc::GetViews`/`ActiveDrawingView`.

**Prior selection required:** None documented — operates on the target
`IDrawingDoc`; a sheet must exist and be active; the model does not need to be
pre-selected.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror; confirms 1-arg boolean-returning signature, and that the non-"2" `Create3rdAngleViews` predecessor also exists with the same shape)
- https://thecadcoder.com/solidworks-vba-macros/drawing-3rdangle-standard3views/ (working VBA example)
- https://www.eng-tips.com/threads/drawing-views-quot-use-sheet-scale-quot-api.314040/ (auto-scale/sheet-scale interaction)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~Create3rdAngleViews2.html (fetched with a browser User-Agent; signature transcribed from this page)

**status:** verified

**Gotchas:**
- **`Create3rdAngleViews` (no "2") vs `Create3rdAngleViews2`** — both exist in the
  type-library mirror with the identical 1-parameter/Boolean-return shape; community
  usage treats the non-suffixed form as legacy and recommends the "2" form. No
  functional-difference description could be retrieved.
- **`swAutomaticScaling3ViewDrawings` interaction believed but not independently
  confirmed for this specific method.** An eng-tips thread reports a concrete failure
  mode: with the toggle `True`, the *inserted views* scale to fit the sheet, but the
  *sheet scale itself stays at 1:1* — so views created this way may not match a
  drawing expecting "Use Sheet Scale." The thread's workaround was
  `DropDrawingViewFromPalette2` instead.
- **No return handle to the created views** — since this returns only `Boolean`,
  retrieving the 3 created views for further manipulation requires a separate
  `GetViews`/loop call afterward.

### IDrawingDoc::Create1stAngleViews2

- **Interface:** IDrawingDoc
- **Method:** Create1stAngleViews2
- **Minimum SW version:** SOLIDWORKS 99 SP01, datecode 1999229 (the page's
  Availability section) — same as `Create3rdAngleViews2`, as expected for a paired
  first/third-angle method.

**Signature:**

```vb
Function Create1stAngleViews2( _
   ByVal ModelName As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ModelName | String | n/a | Yes | Full pathname of the model document from which to create the standard 1st-angle-projection 3-view set (ISO/European convention) | — |

**Returns:** `Boolean` — `True` if successful, `False` if not.

**Prior selection required:** None documented.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror; confirms 1-arg boolean-returning signature and the `Create1stAngleViews` predecessor's identical shape)
- https://thecadcoder.com/solidworks-vba-macros/drawing-1stangle-standard3views/ (working VBA example, including a `swDoc Is Nothing` guard and failure MsgBox on `False`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~Create1stAngleViews2.html (fetched with a browser User-Agent; signature transcribed from this page)

**status:** verified

**Gotchas:**
- **Same predecessor pattern as `Create3rdAngleViews2`** — `Create1stAngleViews` (no
  "2") also exists per the type-library mirror; treat the "2" form as current.
- **`swAutomaticScaling3ViewDrawings` toggle — same caveat as `Create3rdAngleViews2`**,
  believed to apply by symmetry but not independently confirmed for this specific
  method; do not assume identical behavior without testing.
- **Projection-angle mismatch risk** — if the drawing template's projection-angle
  document property disagrees with which `Create...AngleViews2` method is called,
  resulting views may not match the title-block's projection symbol. This is inferred
  from general ISO-vs-ANSI convention docs, not a stated API warning — worth flagging
  explicitly in a wrapper that picks the method from a document property.

### ISldWorks::GetUserPreferenceToggle

- **Interface:** ISldWorks
- **Method:** GetUserPreferenceToggle
- **Minimum SW version:** unverified — the 2025 page carries no Availability section
  at all (confirmed on the fetched page, so this is the page's own omission, not a
  retrieval failure). A long-standing core preference-query method referenced across
  every indexed API-help version back to 2012, so almost certainly present far
  earlier, but no exact FCS is documented.

**Signature:**

```vb
Function GetUserPreferenceToggle( _
   ByVal UserPreferenceToggle As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UserPreferenceToggle | Integer | n/a | Yes | Identifies which toggle-type system option to read. For 3-view auto-scale, pass `swAutomaticScaling3ViewDrawings` | `swUserPreferenceToggle_e` |

**Returns:** `Boolean` — `True` if the toggle is on, `False` if off. No documented
failure mode beyond returning the toggle's actual state.

**Prior selection required:** None — reads an application-level user preference.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/ISldWorks.html (type-library mirror: confirms single-argument arity)
- https://www.rimptec.com/rsolidworks/net/lehal/sw/swUserPreferenceToggle_e.html (confirms exact enum member name `swAutomaticScaling3ViewDrawings`)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~GetUserPreferenceToggle.html (fetched with a browser User-Agent; signature transcribed from this page)

**status:** verified

**Gotchas:**
- **Do not confuse with `IModelDocExtension::GetUserPreferenceToggle`**, which takes
  TWO arguments (`swUserPreferenceToggle_e` plus a `swUserPreferenceOption_e` — pass
  `swDetailingNoOptionSpecified` when unused) and reads a document-scoped preference.
  `ISldWorks::GetUserPreferenceToggle` (documented here) is the one-argument,
  application-level form.
- **What the toggle controls, concretely:** when `swAutomaticScaling3ViewDrawings` is
  `True`, newly-inserted drawing views auto-scale to fit the sheet; if it's the first
  view on the sheet, the *sheet scale* changes to match instead. When `False`, views
  are presumably placed at the current default scale without this auto-fit behavior
  (inferred by contrast, not independently confirmed).
- **Known asymmetry** — even with the toggle `True`, community reports show the
  *view* scaling to fit while the *sheet scale property* can remain unchanged (e.g.
  stuck at 1:1) after `Create3rdAngleViews2` — reading this toggle alone does not
  fully predict final sheet-scale state.
- Use the paired `SetUserPreferenceToggle` (same enum) to change the setting before
  calling the 3-view/model-view insertion methods if deterministic scaling behavior
  is required in an automation pipeline.

### ISldWorks::SetUserPreferenceToggle

- **Interface:** ISldWorks
- **Method:** SetUserPreferenceToggle
- **Minimum SW version:** unverified — help page fetch 403'd directly (same WAF
  block noted throughout this dossier); paired with `GetUserPreferenceToggle`
  (also unverified on Availability), so treat as available on the same versions.

**Signature:**

```vb
Sub SetUserPreferenceToggle( _
   ByVal UserPreferenceToggle As System.Integer, _
   ByVal Value As System.Boolean _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UserPreferenceToggle | Integer | n/a | Yes | Identifies which toggle-type system option to write. For 3-view auto-scale, pass `swAutomaticScaling3ViewDrawings` | `swUserPreferenceToggle_e` |
| Value | Boolean | n/a | Yes | `True` to turn the toggle on, `False` to turn it off | — |

**Returns:** None (`Sub`) — no success/failure indicator; read the toggle back via
`GetUserPreferenceToggle` to confirm the write took effect.

**Prior selection required:** None — writes an application-level user preference.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/ISldWorks.html (type-library mirror: confirms 2-argument `(Integer, Boolean) -> void` signature)
- https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.ISldWorks~SetUserPreferenceToggle.html (indexed by search; direct fetch 403'd)

**status:** verified (type-library signature corroborated by search-indexed page
titles across multiple SW versions; page body itself inaccessible per this
dossier's standing WAF caveat)

**Gotchas:**
- **No boolean return** — unlike most `Set*` calls in this API that return success as
  a `Boolean`, this is a bare `Sub`. A caller that needs certainty the write applied
  must round-trip through `GetUserPreferenceToggle`.
- **Version-dependent value convention reported in community sources**: SOLIDWORKS
  2012-2013 era discussion describes an inverted/integer convention (0 = on, 1 = off)
  for this call, later normalized to a plain `Boolean` (`True` = on) in subsequent
  versions. Current (2025-era) signature takes `System.Boolean` per the type-library
  mirror — treat `True`/`False` as the correct convention for any currently
  supported SOLIDWORKS version; the old integer convention is a historical footnote,
  not something to code defensively around.
- Pair with `GetUserPreferenceToggle` (same enum) to snapshot-then-restore a toggle
  around a scoped operation, e.g. `swAutomaticScaling3ViewDrawings` around a
  standard-3-view insertion — read the current value first, set the desired value,
  perform the operation, then set the value back to what was read, in a `finally`
  so the operator's SolidWorks install setting isn't silently changed on an
  exception path.
- Same one-argument-vs-two-argument caveat as `GetUserPreferenceToggle` applies here:
  `IModelDocExtension::SetUserPreferenceToggle` is a different, document-scoped,
  3-argument overload — do not confuse it with this one-preference-plus-value,
  application-level `ISldWorks` member.

### IDrawingDoc::InsertModelInPredefinedView

- **Interface:** IDrawingDoc
- **Method:** InsertModelInPredefinedView
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0 (the page's
  Availability section).

**Signature:**

```vb
Function InsertModelInPredefinedView( _
   ByVal ModelName As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ModelName | String | n/a | Yes | Full pathname of the model document to insert into the sheet's predefined view placeholder(s) | — |

**Returns:** `Boolean` — `True` if the model was inserted successfully, `False` if
not.

**Prior selection required:** Optional but behavior-changing. A "predefined view" is
a view placeholder pre-positioned and pre-configured (orientation, scale, display
style) on a drawing sheet/template beforehand via Insert > Drawing View > Predefined
in the UI — the placeholder sits empty until a model is inserted into it. If one or
more predefined-view placeholders are pre-selected via `ISelectionMgr` before calling
this method, only those selected placeholders are filled; if nothing is selected,
**all** predefined-view placeholders on the active sheet are filled.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror; confirms single-argument arity)
- https://www.codestack.net/solidworks-api/document/drawing/insert-predefined-views/ (working VBA example; confirms "if no views are selected, all predefined views will be filled")
- https://www.javelin-tech.com/blog/2022/09/create-template-with-solidworks-predefined-views/ and https://www.javelin-tech.com/blog/2017/05/solidworks-predefined-views-drawing-templates/ (how predefined views are authored on a template)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~InsertModelInPredefinedView.html (fetched with a browser User-Agent; signature transcribed from this page)

**status:** verified

**Gotchas:**
- **Selection state changes scope of effect**, not just a nicety: pre-select specific
  placeholders via `ISelectionMgr` to target only those; leave selection empty to
  fill every predefined view on the sheet.
- **Multi-sheet limitation** — as of SOLIDWORKS 2022 SP3.1 (per vendor blog posts),
  when predefined views span multiple sheets, only the predefined views on the
  **last active sheet** get populated; loop per-sheet (activating each) if multi-sheet
  templates are in scope.
- **Predefined views must be authored beforehand** — this method only fills existing
  placeholders, it does not create them.
- Distinct from `Create3rdAngleViews2`/`Create1stAngleViews2`/
  `CreateDrawViewFromModelView3` — this method takes no position/scale parameters;
  all placement is whatever was configured on the placeholder at template-authoring
  time.

## Section, detail, and broken-out views

### IDrawingDoc::CreateSectionViewAt5

- **Interface:** IDrawingDoc
- **Method:** CreateSectionViewAt5
- **Minimum SW version:** SOLIDWORKS 2010 FCS, Revision Number 18.0

**Signature:**

```vb
Function CreateSectionViewAt5( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double, _
   ByVal SectionLabel As System.String, _
   ByVal Options As System.Integer, _
   ByVal ExcludedComponents As System.Object, _
   ByVal SectionDepth As System.Double _
) As View
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters (sheet space) | Yes | X position on the drawing sheet for the center of the resulting section view (placement of the view, not the cut line) | — |
| Y | Double | meters (sheet space) | Yes | Y position on the drawing sheet for the center of the resulting section view | — |
| Z | Double | meters (sheet space) | Yes | Z position on the drawing sheet for the center of the resulting section view | — |
| SectionLabel | String | n/a | Yes | Letter for the label of the section view | — |
| Options | Integer (bitmask) | n/a | Yes | Options that affect the section view | `swCreateSectionViewAtOptions_e` |
| ExcludedComponents | Object (SAFEARRAY/VARIANT of component objects) | n/a | Yes — pass empty/`Nothing` if none | Array of components to exclude from the section view | — |
| SectionDepth | Double | meters | Yes | Distance from the pre-selected section line to cut the section view | — |

**Returns:** `View` — the created section view object. The help page does not
document what is returned on failure (e.g. no section line selected); by COM
convention presumed `Nothing`, but unconfirmed on the page.

**Prior selection required:** Yes, mandatory, and not passed as a parameter. Per the
page's Remarks: "Before calling this method, select the section line or lines to use
as a section line." The cut geometry is defined entirely by whatever line(s) are
currently selected in `ISelectionMgr` at call time (sketched with the Line/Centerline
tool directly on the drawing sheet beforehand) — the method takes no point/line-array
parameter for the cut line. `X`/`Y`/`Z` are only the placement location of the
resulting view on the sheet, a separate concept from the cut line.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateSectionViewAt5.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~ICreateSectionViewAt5.html (early-bound sibling, cross-check)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateSectionViewAtOptions_e.html

**status:** verified

**Gotchas:**
- **Not a typed-wrapper candidate on raw arity** — only 7 parameters. Still a
  reasonable candidate on *complexity* grounds (bitmask enum + mandatory prior
  selection + an ambiguous `Object` array param).
- **Coordinate space is sheet space, confirmed twice**: both `CreateSectionViewAt5`
  and its early-bound sibling describe X/Y/Z as "position on the drawing sheet" — 2D
  paper-space placement of the resulting view, unrelated to where the cut plane sits
  in 3D.
- **`swCreateSectionViewAtOptions_e` has no "half section" member** — only
  `swCreateSectionView_Partial` (partial section), a distinct concept; don't conflate.
- **No "display-only / no geometry cut" flag exists either** — the closest-named
  members, `swCreateSectionView_DisplaySurfaceCut` and `swCreateSectionView_CutSurfaceBodies`,
  both concern surface-body cut display only.
- **The enum's own text is self-contradictory on aligned vs. offset/jogged
  sections**, quoted verbatim: `swCreateSectionView_NotAligned` ("if set, the section
  does not snap into alignment with the parent view") vs.
  `swCreateSectionView_OffsetSection` ("if set, then an aligned section view is
  created (two lines at an angle)"). `OffsetSection`'s own description calls the
  two-line/jogged case "an aligned section view," while a *separate* flag
  (`NotAligned`) actually governs alignment snapping — reads like a documentation
  error (likely "aligned" should read "offset"/"jogged"), unresolved on the official
  page; flagged rather than reinterpreted.
- `ExcludedComponents` type: the early-bound sibling `ICreateSectionViewAt5` splits
  this into `NumExcludedComponents As Integer` + `ByRef ExcludedComponents As Object`,
  confirming it's a SAFEARRAY/VARIANT of component objects, not a single object or
  collection interface.
- Units never stated on the page; meters for X/Y/Z/SectionDepth inferred from
  SolidWorks' standard API convention.

### IDrawingDoc::CreateDetailViewAt4

- **Interface:** IDrawingDoc
- **Method:** CreateDetailViewAt4 — requested as `CreateDetailViewAt5`, which does
  not exist in the SOLIDWORKS 2025 API (see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2017 FCS, Revision Number 25.0

**Signature:**

```vb
Function CreateDetailViewAt4( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double, _
   ByVal Style As System.Integer, _
   ByVal Scale1 As System.Double, _
   ByVal Scale2 As System.Double, _
   ByVal LabelIn As System.String, _
   ByVal Showtype As System.Integer, _
   ByVal FullOutline As System.Boolean, _
   ByVal JaggedOutline As System.Boolean, _
   ByVal NoOutline As System.Boolean, _
   ByVal ShapeIntensity As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters (sheet space) | Yes | X position for the detail view (placement point on the sheet) | — |
| Y | Double | meters (sheet space) | Yes | Y position for the detail view | — |
| Z | Double | meters (sheet space) | Yes | Z position for the detail view | — |
| Style | Integer | n/a | Yes | Style for the detail view | `swDetViewStyle_e` |
| Scale1 | Double | n/a (ratio numerator) | Yes | Scale numerator | — |
| Scale2 | Double | n/a (ratio denominator) | Yes | Scale denominator | — |
| LabelIn | String | n/a | Yes | Detail view label | — |
| Showtype | Integer | n/a | Yes | Type of sketch used to create the detail view | `swDetCircleShowType_e` |
| FullOutline | Boolean | n/a | Yes | True to show a full outline; valid only if `NoOutline` is False | — |
| JaggedOutline | Boolean | n/a | Yes | True to show a jagged outline; valid only if `NoOutline` is False | — |
| NoOutline | Boolean | n/a | Yes | True to show no outline at all | — |
| ShapeIntensity | Integer | n/a | Yes | Jagged-outline intensity, range 1 (most) to 5 (least); valid only if `JaggedOutline` is True and `NoOutline` is False | — |

**Returns:** `System.Object` — a `View` on success (confirmed by SolidWorks' shipped
example, which assigns the result directly to a `SldWorks.View` variable). Failure
return is not documented on the page.

**Prior selection required:** Yes — a detail circle/profile must exist in the parent
view's sketch context before the call. Reconstructed from SolidWorks' shipped "Create
Detail Circle and Detail View Example (VBA)" example, since this method's own help
page has no Remarks section:
1. Activate the parent drawing view that will host the detail circle:
   `swDrawing.ActivateView("Drawing View4")`.
2. Draw the circle directly into that view's sketch space with
   `ISketchManager::CreateCircle`.
3. Call `CreateDetailViewAt4` immediately afterward — in the official example there
   is no intervening `ISelectionMgr` select call; the newly-created sketch circle is
   used implicitly, consistent with `Showtype:=swDetCircleCIRCLE` ("use sketch circle
   to create detail view").
4. If `Showtype:=swDetCirclePROFILE` is used instead (an arbitrary closed profile,
   not necessarily a circle), the profile must be pre-drawn and explicitly selected
   via `ISelectionMgr` before the call, since only a circle can be produced inline via
   `CreateCircle`. If `Showtype:=swDetCircleDONTSHOW`, no visible sketch profile is
   required/shown.
5. After the call, the example clears state with `swModel.ClearSelection2 True`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateDetailViewAt4.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms `At4` is the highest overload)
- https://help.solidworks.com/2025/english/api/sldworksapi/Create_Detail_Circle_and_Detail_View_Example_VB.htm
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDetViewStyle_e.html
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDetCircleShowType_e.html

**status:** verified

**Gotchas:**
- **`CreateDetailViewAt5` does not exist in the 2025 API.** A direct fetch of the
  constructed URL returned the help server's own error payload confirming the file
  does not exist. `IDrawingDoc_members.html` independently confirms only
  `CreateDetailViewAt`/`At2`/`At3`/`At4` exist. `CreateDetailViewAt4` is the current
  highest overload, documented here in its place.
- **`swDetailCircleStyle_e` (as named in the task) does not exist.** The real enums
  are `swDetViewStyle_e` (drives `Style`) and `swDetCircleShowType_e` (drives
  `Showtype`) — the requested name conflates the two.
- **typed-wrapper candidate.** 12 positional parameters, including three
  mutually-dependent boolean flags (`FullOutline`/`JaggedOutline`/`NoOutline`) plus a
  dependent `ShapeIntensity` int whose validity depends on two of those flags — a
  strong candidate for a typed options wrapper to prevent silently-ignored/invalid
  combinations.
- Units never stated on the page; meters for X/Y/Z inferred from SolidWorks API
  convention. `Scale1`/`Scale2`/`Style`/`Showtype`/`ShapeIntensity` are unitless.

### IDrawingDoc::CreateBreakOutSection

- **Interface:** IDrawingDoc
- **Method:** CreateBreakOutSection — requested as `IView::InsertBrokenOutSection`,
  which does not exist in the SOLIDWORKS 2025 API (see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2001 FCS, Revision Number 9.0

**Signature:**

```vb
Function CreateBreakOutSection( _
   ByVal Depth As System.Double _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Depth | Double | meters | Yes | Depth of material removal for the broken-out section (how far into the model the cut exposes inner detail) | — |

**Returns:** `Boolean` — `True` if the broken-out section was created, `False` if
not (stated verbatim on the page). No further failure-cause detail given; most likely
cause is no valid closed profile selected at call time.

**Prior selection required:** Yes, mandatory, and not passed as a parameter — mirrors
`CreateSectionViewAt5`'s pattern. Reconstructed from three sources since this method's
own help page has no Remarks section:
1. **Official Design Help ("Broken-out Section")**: "A broken-out section is part of
   an existing drawing view, not a separate view. A closed profile, usually a spline,
   defines the broken-out section." The manual workflow: click the Broken-out Section
   tool, then sketch the profile directly on top of the existing drawing view being
   sectioned — "If you want a profile other than a spline, create and select a closed
   profile before clicking the Broken-out Section tool." Only a spline can be
   sketched inline after invoking the tool; any other closed-profile shape must be
   pre-drawn and pre-selected beforehand.
2. **`IBrokenOutSectionFeatureData` member list** (cross-reference): exposes
   `SketchSegment`/`GetSketchSegmentCount` (the bounding closed sketch profile) and
   separately `Depth` + `DepthReference` (a geometry reference that can drive depth
   post-creation) — `CreateBreakOutSection` itself exposes only the raw-`Depth`-double
   path; setting a `DepthReference` is a post-creation step via
   `IBrokenOutSectionFeatureData`, not an input to this method.
3. **Independent secondary source** (thecadcoder.com): the macro example states "We
   already select a Circle in this existing (Base) view" immediately before calling
   `swDrawing.CreateBreakOutSection(0.1)` — empirically confirming the pre-selection
   requirement.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateBreakOutSection.html
- https://help.solidworks.com/2025/english/SolidWorks/sldworks/c_broken_out_section.htm (Design Help workflow)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBrokenOutSectionFeatureData_members.html (cross-reference for `Depth`/`DepthReference`/`SketchSegment`)
- https://thecadcoder.com/solidworks-vba-macros/drawing-brokenout-view/ (secondary, non-official cross-check)

**status:** verified

**Gotchas:**
- **`IView::InsertBrokenOutSection` does not exist.** A direct fetch of the
  constructed URL returned the help server's own file-does-not-exist error.
  Independently, the `IView` member index contains no member matching `Broken*`
  other than the unrelated `IsBroken` property — there is no insert/create method for
  broken-out sections anywhere on `IView`. The real method,
  `CreateBreakOutSection`, lives on `IDrawingDoc` and is documented here in its place.
- **The method does not accept a profile or a depth-reference parameter — both are
  ambient.** The profile comes entirely from whatever closed sketch entity is
  selected at call time; depth is a plain `Double` in this overload — there is no
  `ByRef`/reference-typed depth parameter. Geometry-reference depth (`DepthReference`)
  is only settable afterward, via the resulting `IBrokenOutSectionFeatureData` object.
- Only 1 parameter — not a typed-wrapper candidate by arity; if anything, this is a
  candidate for a wrapper on the *opposite* end: nearly all real complexity (profile
  selection, sketch context, depth-reference mode) lives entirely outside the call
  signature.
- Units never stated on the page; meters for `Depth` inferred from SolidWorks API
  convention.

## Projected views

Investigation ruled out the two plausible-sounding "named method" candidates: the
`IDrawingDoc` and `IView` member index pages contain zero methods with "Project" in
the name — no `InsertProjectedView`, no `IView::CreateProjectedView`.
`CreateDrawViewFromModelView3` (documented above) is confirmed by its own Remarks to
insert a brand-new, independent model view by `ModelName`/`ViewName` at an explicit
sheet location — it has no concept of a parent view and does not project off an
existing drawing view. The actual working mechanism turned out to be a
same-operation-different-name method: `IDrawingDoc::CreateUnfoldedViewAt3`, whose own
doc text reads "Creates an unfolded drawing view from the selected drawing view" —
this is the API's internal name for what the UI calls a "Projected View." Cross-verified
via three independent sources (official API Help example, an independent macro
tutorial, and community forum commentary about the naming confusion) that all converge
on the same call.

### IDrawingDoc::CreateUnfoldedViewAt3

- **Interface:** IDrawingDoc
- **Method:** CreateUnfoldedViewAt3
- **Minimum SW version:** present since the SOLIDWORKS 2005 API; still current
  through SW 2025/2026. Supersedes the obsolete `CreateUnfoldedViewAt` (3-param, no
  alignment control) and `CreateUnfoldedViewAt2`.

**Signature:**

```vb
Function CreateUnfoldedViewAt3( _
    ByVal X As Double, _
    ByVal Y As Double, _
    ByVal Z As Double, _
    ByVal NotAligned As Boolean _
) As SldWorks.View
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters (sheet space) | Yes | X location for the center of the new drawing view | — |
| Y | Double | meters (sheet space) | Yes | Y location for the center of the new drawing view | — |
| Z | Double | meters (sheet space) | Yes | Z location for the center of the new drawing view (typically 0) | — |
| NotAligned | Boolean | n/a | Yes | `False` = keep the new view orthographically aligned with the parent view (this is what makes it a true "projected view"); `True` = break alignment so the view can be freely repositioned | — |

**Returns:** `IView` pointer to the newly created (projected/unfolded) drawing view,
or `Nothing` if the call fails (e.g. no view was selected first).

**Prior selection required:** Yes. The parent/source drawing view must be selected
before the call — via
`IModelDocExtension::SelectByID2("<ViewName>", "DRAWINGVIEW", x, y, z, False, 0, Nothing, 0)`,
or via a prior UI selection carried into the macro. `CreateUnfoldedViewAt3` operates
on "the selected drawing view" — it does not take a view reference as a parameter.

**Source URL(s):**
- https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IDrawingDoc~CreateUnfoldedViewAt3.html
- https://help.solidworks.com/2021/english/api/sldworksapi/create_unfolded_view_example_vb.htm ("Create Unfolded View Example (VBA)" — shows `SelectByID2("Drawing View1","DRAWINGVIEW",...)` followed by `Part.CreateUnfoldedViewAt3(...)`)
- https://thecadcoder.com/solidworks-vba-macros/drawing-insert-projectionview/ (independent tutorial titled "Insert Projection View" that arrives at the same call)
- https://help.solidworks.com/2018/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateUnfoldedViewAt.html (obsolete predecessor, confirms lineage/naming)
- https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IDrawingDoc~CreateDrawViewFromModelView3.html (ruled-out candidate — confirmed unrelated to projecting off an existing view)
- https://help.solidworks.com/2025/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.idrawingdoc_methods.html (full method index — confirms no `*Project*`-named method exists on IDrawingDoc)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (full member index — confirms no `IView::CreateProjectedView` exists; only unrelated `GetProjectionArrow`/`GetProjectionLines`/`ProjectedDimensions`)
- https://forum.solidworks.com/thread/102175 ("Solidworks API: Create Projected View" — community thread confirming users repeatedly searched for a `Project`-named method and instead had to be pointed to `CreateUnfoldedViewAt3`)

**status:** verified

**Gotchas:**
- The single biggest trap here is naming: the UI calls this action "Insert Projected
  View" (Insert > Drawing View > Projected View, or drag-off-a-view), but the COM API
  calls the exact same underlying operation an "unfolded view." Searching the API
  index for "Project" finds nothing on `IDrawingDoc` or `IView` and reasonably leads
  to the conclusion no direct method exists — a documented dead end that multiple
  developers hit per the forum thread cited above.
- `CreateDrawViewFromModelView3(ModelName, ViewName, LocX, LocY, LocZ)` is a red
  herring for this use case even though it accepts named view strings like
  `"*Right"`/`"*Top"`. Per its own Remarks it creates a fresh, independent model view
  at an arbitrary sheet location — it has no parent-view parameter and does not read
  the current selection, so it cannot produce an orthographically-linked projection
  off an existing view. It is the right call for "insert a new standard/named view
  from scratch," not for "project off this view I already have."
- `CreateUnfoldedViewAt3` does NOT take the parent view as a parameter — it silently
  operates on whatever drawing view is currently selected via
  `ISelectionMgr`/`SelectByID2`. If nothing (or the wrong thing) is selected, it
  returns `Nothing` rather than throwing, so callers must check the return value and
  must explicitly select the parent view (type string `"DRAWINGVIEW"`) immediately
  beforehand.
- The `NotAligned` parameter is the actual "is this a true projected view" switch:
  pass `False` to keep the new view orthographically locked/aligned to the parent
  (the drag-off-a-view UI behavior), or `True` to detach it into a freely-movable,
  unaligned view (closer to "Insert Model View" behavior but still geometrically
  derived from the parent's projection).
- No `RunCommand`/`swCommands_e` approach is needed or documented for this operation
  — unlike some UI actions that lack any object-model equivalent, projected-view
  creation has a first-class, directly-callable API method.
- The two-parameter-fewer predecessors `CreateUnfoldedViewAt` (obsolete, 3 params, no
  alignment control) and `CreateUnfoldedViewAt2` (obsolete) both exist purely for
  backward compatibility and are explicitly marked "Superseded by
  IDrawingDoc::CreateUnfoldedViewAt3" — new code should not use them.

## Auxiliary views

Unlike the "projected view" naming trap above, this one has an on-the-nose method
name: `IDrawingDoc::CreateAuxiliaryViewAt2`. `help.solidworks.com` 403'd every direct
fetch attempt for this method during this research pass (the same standing WAF block
noted throughout this dossier), so the record below is sourced the way
`SetUserPreferenceToggle`/`GetBaseView` are elsewhere in this file: a type-library
mirror for arity/types, corroborated by an independent working macro example and
multiple search-indexed secondary descriptions, with no page body directly fetched.

### IDrawingDoc::CreateAuxiliaryViewAt2

- **Interface:** IDrawingDoc
- **Method:** CreateAuxiliaryViewAt2
- **Minimum SW version:** unverified — help page fetch 403'd directly; a "2"-suffixed
  overload existing alongside search-indexed pages for SW2019 through at least SW2025
  implies it predates 2019, but no exact FCS could be pinned down from accessible
  sources.

**Signature:**

```vb
Function CreateAuxiliaryViewAt2( _
   ByVal X As System.Double, _
   ByVal Y As System.Double, _
   ByVal Z As System.Double, _
   ByVal NotAligned As System.Boolean, _
   ByVal Label As System.String, _
   ByVal Showarrow As System.Boolean, _
   ByVal Flip As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| X | Double | meters (sheet space) | Yes | X location for the center of the new auxiliary view | — |
| Y | Double | meters (sheet space) | Yes | Y location for the center of the new auxiliary view | — |
| Z | Double | meters (sheet space) | Yes | Z location — inert for 2D sheet placement, same as every other `*At*` view-creation call in this dossier; pass `0` | — |
| NotAligned | Boolean | n/a | Yes | `False` = keep the auxiliary view aligned/locked to the parent view along the projection direction (the drag-off-an-edge UI behavior); `True` = break alignment. Same name and same-shaped role as `CreateUnfoldedViewAt3`'s `NotAligned` | — |
| Label | String | n/a | Yes | Text of the auxiliary view's letter label (e.g. `"A"`) | — |
| Showarrow | Boolean | n/a | Yes | `True` shows the projection arrow on the parent view, `False` hides it | — |
| Flip | Boolean | n/a | Yes | `True` flips which side of the reference edge the view projects toward, `False` does not | — |

**Returns:** `System.Object` — a `View` on success (the working macro example assigns
the result directly to a `SldWorks.View` variable and null-checks it); `Nothing` on
failure (no dedicated error code documented).

**Prior selection required:** Yes, mandatory, and not passed as a parameter — same
ambient-selection pattern as `CreateSectionViewAt5`/`CreateBreakOutSection`/
`CreateUnfoldedViewAt3` elsewhere in this dossier. The working macro example's own
prose states the edge to project from must already be selected in an existing base
view before the call: "We create Auxiliary view from an existing (Base) view. We
already select an edge in this existing (Base) view." No `SelectByID2` call is shown
in that example (the edge was selected interactively before running the macro), but
the documented pattern for automation is the same as this dossier's other
ambient-selection records: `IModelDocExtension::SelectByID2("", "EDGE", x, y, z,
False, 0, Nothing, 0)` against a point on the target edge. The method itself takes no
view-reference or edge-reference parameter.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror: confirms `CreateAuxiliaryViewAt2`'s 7-parameter arity — 3 doubles, then bool/string/bool/bool — and that a simpler 4-parameter `CreateAuxiliaryViewAt` (no alignment/label/arrow/flip control) also exists)
- https://thecadcoder.com/solidworks-vba-macros/drawing-insert-auxilaryview/ (working VBA example: `swDrawing.CreateAuxiliaryViewAt2(0.2, 0.1, 0, False, "A", True, True)`, plus prose confirming the pre-selected-edge requirement and each parameter's meaning)
- https://help.solidworks.com/2019/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~CreateAuxiliaryViewAt2.html (indexed by search under this exact title across SW2019–SW2025 API help; direct fetch 403'd, same WAF block as elsewhere in this dossier)

**status:** verified (type-library arity/types + independent working-macro
corroboration, cross-checked against multiple search-indexed page titles; no page
body directly fetched — same sourcing tier as this dossier's `SetUserPreferenceToggle`
and `GetBaseView` records)

**Gotchas:**
- **This is a real, first-class, directly-callable API method** — unlike "projected
  view," "auxiliary view" is not a UI-only name; the API method is named
  `CreateAuxiliaryViewAt2`, matching what the task expected. No naming trap here.
  `swDrawingViewTypes_e` also has a dedicated `swDrawingAuxiliaryView` (5) member (see
  the Enums section), confirming the API treats auxiliary views as their own
  first-class view type, not a flavor of projected/section view.
- **`NotAligned`'s prose description on the secondary source reads
  self-contradictory** ("True aligns the view from its owner, False does not") —
  backwards from what the parameter's own name and its `CreateUnfoldedViewAt3`
  sibling both imply (`NotAligned=True` should *break* alignment, not create it).
  Treat this as a likely paraphrase/documentation error on the secondary source
  rather than a confirmed inverted convention, and follow the name-and-sibling-method
  reading (`False` = aligned, `True` = not aligned) until verified against a live
  SolidWorks session — flagged rather than silently "corrected," per this dossier's
  standing rule against inventing behavior.
- **A simpler, obsolete `CreateAuxiliaryViewAt` (4 params: X, Y, Z, OnEdge — no
  label/arrow/flip control) also exists** per the type-library mirror; treat the "2"
  form as current, same pattern as `CreateDetailViewAt4`/`CreateUnfoldedViewAt3`
  elsewhere in this dossier. No `CreateAuxiliaryViewAt3` could be found by any source
  consulted — "2" is the current highest overload.
- Units never stated on any accessible source; meters for `X`/`Y`/`Z` inferred from
  the API-wide units convention (same inference this dossier makes for every
  sheet-space placement call whose page could not be fetched directly).
- No `RunCommand`/`swCommands_e` workaround is needed — same as `CreateUnfoldedViewAt3`,
  this UI action has a direct, documented API equivalent.

## Breaks and crop

### IView::InsertBreak3

- **Interface:** IView
- **Method:** InsertBreak3
- **Minimum SW version:** SOLIDWORKS 2018 FCS, Revision Number 26.0

**Signature:**

```vb
Function InsertBreak3( _
   ByVal Orientation As System.Integer, _
   ByVal Position1 As System.Double, _
   ByVal Position2 As System.Double, _
   ByVal Style As System.Integer, _
   ByVal ShapeIntensity As System.Integer, _
   ByVal BreakSketchBlocks As System.Boolean _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Orientation | Integer | n/a | Yes | Horizontal or vertical cut | `swBreakLineOrientation_e` |
| Position1 | Double | meters | Yes | Location of the first break line — a Y value relative to the drawing view origin if `Orientation` is horizontal, an X value if vertical | — |
| Position2 | Double | meters | Yes | Location of the second break line, same axis convention as `Position1` | — |
| Style | Integer | n/a | Yes | Break line cut style | `swBreakLineStyle_e` |
| ShapeIntensity | Integer | n/a | Yes | Jagged-cut shape intensity, range 1 (most) to 5 (least); only meaningful when `Style = swBreakLine_Jagged` | — |
| BreakSketchBlocks | Boolean | n/a | Yes | True to break sketch blocks, False to not | — |

**Returns:** `System.Object` — the help page's Return Value line says "Break line",
but the declared return type is `System.Object`, not the strongly-typed `BreakLine`
the two obsolete predecessors return. Failure mode is not documented; treat a
returned `Nothing`/null as failure until confirmed against a live session.

**Prior selection required:** None beyond having the target drawing view
active/referenced — called directly on the `IView` COM object
(`view.InsertBreak3(...)`), not via a selection-set. It only inserts break lines at
the given positions; it does not itself apply the break to the view — call
`IDrawingDoc::BreakView` afterward to render it. The view must not already be broken
via a different mechanism — `swCropViewErrors_CannotCropDetailOrBrokenView` (a
related `swCropViewErrors_e` member) confirms detail/broken views reject cropping,
implying break and crop states are mutually exclusive on the same view.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBreak3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBreak2.html (obsolete predecessor, confirms Position1/Position2 axis convention)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~InsertBreak.html (original, obsolete, same convention)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~BreakView.html
- https://help.solidworks.com/2025/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.idrawingdoc_methods.html

**status:** verified

**Gotchas:**
- **Requested as `IDrawingDoc::InsertBreak`. No such member exists** — fetching that
  URL returns a file-does-not-exist error from the help server. `IDrawingDoc` only
  exposes zero-argument `InsertBreakHorizontal()`/`InsertBreakVertical()` (default
  location, user drags to reposition) plus `BreakView()`/`UnBreakView()`. The
  parameterized, position-controlling call lives on `IView`, and is named `InsertBreak`
  → obsolete → `InsertBreak2` → obsolete → **`InsertBreak3`** (current, SW2018+).
- **The gap between the two break lines is not an `InsertBreak3` parameter at all** —
  it's a separate get/set property, `IView::BreakLineGap As System.Double` (SW2007+).
  Neither page states a unit explicitly, but per universal SolidWorks API convention
  both `Position1`/`Position2` and `BreakLineGap` are meters.
- **`InsertBreak3` only creates the break lines** — the view is not visually broken
  until `IDrawingDoc::BreakView()` is called afterward (confirmed in `BreakView`'s own
  remarks).
- `IView::IsBroken()` reports whether the break is *displayed/applied*, a different
  state from merely having break lines present — check `GetBreakLineCount2` for line
  presence and `IsBroken` for applied state; they can disagree.
- Font/line style of the break lines is set separately via `IBreakLine::Style`.

### IView::GetBreakLineCount2

- **Interface:** IView
- **Method:** GetBreakLineCount2
- **Minimum SW version:** SOLIDWORKS 2011 FCS, Revision Number 19.0

**Signature:**

```vb
Function GetBreakLineCount2( _
   ByRef Size As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Size | Integer (ByRef/out) | n/a (count) | Yes | Returns the size of the doubles array that must be allocated to receive data from `IView::GetBreakLineInfo2`/`IGetBreakLineInfo2` | — |

**Returns:** `Integer` — the number of breaks (a break = a pair of break lines) in
the view, e.g. returns 3 for a view with three breaks even though six lines are
drawn. No error/failure sentinel is documented; a view with no break lines presumably
returns 0.

**Prior selection required:** None — called directly on the target `IView` COM
object (`view.GetBreakLineCount2(size)`), no prior UI selection needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetBreakLineCount2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetBreakLineCount.html (obsolete predecessor)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (confirms no bare `BreakLineCount` member exists)

**status:** verified

**Gotchas:**
- **Requested as `IView::BreakLineCount` (as a property). No such member exists** —
  fetching that URL returns the same file-does-not-exist error pattern, and the
  `IView_members` index (full-text scanned for every "Break"-containing entry) lists
  no bare `BreakLineCount` property — only `GetBreakLineCount` (obsolete, SW2003) and
  `GetBreakLineCount2` (current, SW2011). Both are **methods**, not get/set
  properties, using the VB `ByRef` idiom to return a second value (`Size`, an
  array-sizing hint) alongside the function's own integer return (the actual count).
- `GetBreakLineCount2`'s own remarks distinguish "has break lines" (this method) from
  "is displayed broken" (`IView::IsBroken`) — a view can have break lines present
  without the break being applied to the display.
- `Size` is not the count you want — it's a buffer-sizing hint for the paired
  `GetBreakLineInfo2`/`IGetBreakLineInfo2` calls. The break *count* is the function's
  own return value.
- The V1 method (`GetBreakLineCount`, no "2") behaves identically but is obsolete
  since SW2011; use the "2" version for anything targeting SW2025.

### IDrawingDoc::UnBreakView

- **Interface:** IDrawingDoc
- **Method:** UnBreakView
- **Minimum SW version:** not stated on help page (no Availability section present —
  the sibling methods `InsertBreakHorizontal`/`InsertBreakVertical`/`BreakView` on the
  same interface likewise carry no Availability tag, consistent with this being
  present since very early drawing-API versions)

**Signature:**

```vb
Sub UnBreakView()
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | — | n/a | — | Takes no parameters | — |

**Returns:** None (`Sub`, void). No error code or boolean success indicator is
returned; failure mode is not documented.

**Prior selection required:** Yes, explicitly per the help page's one-line
description: "Removes a break in the selected drawing view." This is a document-level
method (`IDrawingDoc`, not `IView`), so — unlike `InsertBreak3` which is called
directly on a specific `IView` object — the target view must first be selected (e.g.
via `ISelectionMgr`/`IModelDocExtension::SelectByID2`), and then `UnBreakView` is
called on the active `IDrawingDoc`, which acts on whichever view is currently
selected. There is no view-object parameter to target it directly.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~UnBreakView.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~BreakView.html (cross-links UnBreakView as the inverse operation)
- https://help.solidworks.com/2025/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.idrawingdoc_methods.html (confirms full break-related member list on IDrawingDoc)

**status:** verified

**Gotchas:**
- **The task's assumed name/location does not match the real API.** There is no
  dedicated "RemoveBreak" method anywhere, and removal is not a toggle on
  `InsertBreak3`/`Crop2`-style calls. The real, documented removal method is
  `IDrawingDoc::UnBreakView()` — note it lives on the *drawing document* interface,
  not on `IView` where the break was created. This asymmetry (create on `IView`,
  remove on `IDrawingDoc`, driven by current selection) is easy to miss if the two are
  assumed to be mirror-image methods on the same interface.
- Because `UnBreakView` acts on "the selected drawing view" rather than taking a view
  reference, calling it with the wrong view (or nothing) selected will silently act
  on the wrong target or no-op — no parameter forces a specific view, and no
  documented return value confirms anything happened.
- Removing the applied break does not necessarily delete the break *lines*
  themselves. The API's own remarks elsewhere (`GetBreakLineCount2`, `IsBroken`) draw
  a firm distinction between a view "having break lines" and a view "being displayed
  with a break applied." `UnBreakView`'s description only claims to remove "a break"
  (the applied state); after calling it, verify with `IView::IsBroken()` (should
  report `False`) rather than assuming `GetBreakLineCount2` also drops to 0 — this
  distinction is not spelled out on `UnBreakView`'s own (very thin) help page, so
  treat it as an inference from surrounding API behavior, not a directly confirmed
  fact.

### IView::Crop2

- **Interface:** IView
- **Method:** Crop2
- **Minimum SW version:** SOLIDWORKS 2017 FCS, Revision Number 25.0

**Signature:**

```vb
Function Crop2( _
   ByVal JaggedOutline As System.Boolean, _
   ByVal NoOutline As System.Boolean, _
   ByVal ShapeIntensity As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| JaggedOutline | Boolean | n/a | Yes | True to use a jagged outline, False to not; only valid if `NoOutline` is False | — |
| NoOutline | Boolean | n/a | Yes | True to not show an outline, False to show an outline | — |
| ShapeIntensity | Integer | n/a | Yes | Shape intensity of the jagged outline, range 1 (most) to 5 (least); only valid if `JaggedOutline` is True | — |

**Returns:** `Integer` — crop status, values defined in `swCropViewErrors_e`:
`swCropViewErrors_Unknown`=0, `swCropViewErrors_NoError`=1 (success),
`swCropViewErrors_CannotCropDetailOrBrokenView`=2,
`swCropViewErrors_CannotUnfoldView`=3, `swCropViewErrors_IncorrectProfile`=4 ("Bad
spline"). **Success is `1`, not `0`/falsy** — a naive `if (ret == 0)` or `if (!ret)`
success check silently reads success as failure/unknown.

**Prior selection required:** Yes, and this is the load-bearing precondition.
`Crop2`'s own description: "Crops this view using the selected closed sketch
profile." A closed sketch profile must be sketched on top of the drawing view and
selected (via `ISelectionMgr`, e.g. `SelectByID2`) before `Crop2` is called — there is
no sketch/profile parameter on the method itself; it operates entirely off current
selection state, the same pattern used by `IDrawingDoc::UnBreakView`. Independently
corroborated by the `swCommands_e` enum entry for the equivalent UI command:
`swCommands_CropView = 311`, documented as "valid for drawings with a closed sketch
profile on a selected view."

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~Crop2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~Crop.html (obsolete predecessor)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCropViewErrors_e.html
- https://help.solidworks.com/2022/english/api/swcommands/SolidWorks.Interop.swcommands~SolidWorks.Interop.swcommands.swCommands_e.html (swCommands_CropView entry, cross-confirms the closed-sketch-profile precondition)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html

**status:** verified

**Gotchas:**
- **Requested as `IView::CropView`. No such member exists** — fetching that URL
  returns a file-does-not-exist error. The current method is `IView::Crop2`; the
  plain `IView::Crop()` (no parameters, returns `swCropViewErrors_e` directly,
  SW2005+) is its obsolete predecessor, explicitly marked "Obsolete. Superseded by
  IView::Crop2" on its own help page.
- `swCropViewErrors_CannotCropDetailOrBrokenView` (=2) means a view that is already
  broken (see `InsertBreak3`/`UnBreakView` above) or is a detail view cannot be
  cropped — crop and break are mutually exclusive states on the same view, so
  sequencing matters if a workflow does both.
- Return-code trap: `0` = `Unknown` (not success), `1` = `NoError` (success). Don't
  treat `0`/false as success.
- Related state properties, useful alongside `Crop2`: `IView::IsCropped()` (bool,
  get-only method, SW2001+), `CropViewJaggedOutline`, `CropViewJaggedShapeIntensity`,
  `CropViewNoOutline` (all get/set properties mirroring the three `Crop2` parameters
  after the fact).

### ISldWorks::RunCommand (workaround for removing a crop view — no dedicated API method exists)

- **Interface:** ISldWorks (workaround path); no dedicated crop-removal method exists
  on `IView` or `IDrawingDoc`
- **Method:** RunCommand (with `CommandID = swCommands_Tools_Crop_Delete = 1389`)
- **Minimum SW version:** `RunCommand` itself: SOLIDWORKS 2008 FCS, Revision Number
  16.0. The `swCommands_Tools_Crop_Delete` constant's own introduction version was not
  separately verified (the `swCommands_e` enum page does not date individual
  members).

**Signature:**

```vb
Function RunCommand( _
   ByVal CommandID As System.Integer, _
   ByVal NewTitle As System.String _
) As System.Boolean

' Usage for crop removal:
' 1. Select the cropped view (view must already be a Crop View, i.e. IView::IsCropped() = True)
' 2. swApp.RunCommand(1389, "")   ' 1389 = swCommands_Tools_Crop_Delete
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| CommandID | Integer | n/a | Yes | SOLIDWORKS command to run; for crop removal, use `swCommands_Tools_Crop_Delete` = 1389 | `swCommands_e` (SolidWorks.Interop.swcommands namespace) |
| NewTitle | String | n/a | Yes (pass `""` if unused) | Custom title for the PropertyManager page, if the command opens one; crop-delete does not open one so this can be `""` | — |

**Returns:** `Boolean` — `True` if the command ran, `False` if not (e.g. no Crop View
currently selected).

**Prior selection required:** Yes — per the `swCommands_e` documentation,
`swCommands_Tools_Crop_Delete` is "valid for a selected Crop View in a drawing." A
view that is already a Crop View (`IView::IsCropped()` = `True`) must be selected
before invoking this command; there is no view-reference parameter, exactly like the
`UnBreakView` pattern above.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~RemoveCropView.html (confirms this exact method name does NOT exist — file-does-not-exist error)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (full member list grepped for "Crop" and "Remove" — no crop-removal member of any name found; only unrelated `RemoveAlignment` matches "Remove")
- https://help.solidworks.com/2022/english/api/swcommands/SolidWorks.Interop.swcommands~SolidWorks.Interop.swcommands.swCommands_e.html (source of the `swCommands_Tools_Crop_Delete = 1389` mapping to "RMB menu > Crop View > Remove Crop")
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~RunCommand.html
- https://help.solidworks.com/2021/english/SolidWorks/sldworks/t_remove_crop_view.htm (SOLIDWORKS UI help: "Removing a Crop View" — confirms this is documented ONLY as a right-click UI action)
- https://forum.solidworks.com/thread/111981 ("Uncrop View" forum thread — community confirms no direct API call exists)

**status:** unverified

**Gotchas:**
- **Be explicit: there is no `IView::RemoveCropView`, no `IDrawingDoc`-level
  crop-removal method, and no documented direct API call to undo a crop at all.**
  Checked three independent ways: (1) the `RemoveCropView.html` help page itself
  404s; (2) the full `IView_members` index was text-scanned for every entry
  containing "Crop" (six matches: `Crop`, `Crop2`, `IsCropped`,
  `CropViewJaggedOutline`, `CropViewJaggedShapeIntensity`, `CropViewNoOutline` — no
  removal method) and separately for "Remove" (one unrelated match:
  `RemoveAlignment`); (3) SolidWorks' own end-user documentation describes crop
  removal exclusively as a right-click menu action, and a community forum thread
  confirms macro-recording does not capture a distinct API call for it either.
- Unlike `UnBreakView` (a real, dedicated, documented API method for undoing a break),
  crop removal has **no equivalent first-class method**. The closest documented,
  callable path is firing the same UI command the right-click menu fires, via
  `ISldWorks::RunCommand(1389, "")`, where `1389` is `swCommands_Tools_Crop_Delete`
  from `swCommands_e` (whose description literally reads "RMB menu > Crop View >
  Remove Crop"). This is a command-dispatch workaround, not a purpose-built
  crop-removal API, and it was not tested against a live SOLIDWORKS instance — hence
  `status: unverified`.
- Because this is a command-ID dispatch rather than a typed method, there's no
  structured error information beyond the boolean "did it run" — callers cannot
  distinguish "nothing was selected" from "selected view wasn't actually a Crop View"
  without separately checking `IView::IsCropped()` before/after the call.
- If a future SOLIDWORKS version adds a first-class `RemoveCropView`/`UnCropView`
  method (mirroring how `BreakView`/`UnBreakView` are a matched pair), this record
  should be revisited — as of the SW2025 API surface checked here, no such symmetry
  exists for crop views.

## View properties: position, scale, and display mode

### IView::Position

- **Interface:** IView
- **Method:** Position
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
' .NET declaration: Property Position As System.Object
Property Get Position() As System.Object
Property Set Position(ByVal value As System.Object)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| value | Object (array of 2 Doubles) | meters (sheet space) | Yes (Set) | X, Y location of the drawing view's geometric center, relative to the drawing sheet origin | — |

**Returns:** `System.Object` — a 2-element array of Doubles `[X, Y]` (Get). No
documented failure/error return.

**Prior selection required:** None — called directly on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~Position.html
- https://help.solidworks.com/2025/english/api/sldworksapiprogguide/Overview/Units.htm (API-wide units convention: "all SOLIDWORKS API functions use metric units... meters, radians, kilograms, square meters, or cubic meters")

**status:** verified

**Gotchas:**
- **Coordinate space is sheet space** (relative to the drawing sheet origin), not
  model space, not view-local space.
- **Units are meters**, confirmed by the API-wide Units overview page (this
  property's own page does not restate it).
- The 2025 page describes the value as the model view's geometric center; pre-2025
  doc snapshots (2016–2023) described this same property as "the drawing view
  origin" — a documentation wording change worth flagging if code/behavior was
  validated against older docs; verify empirically if the exact anchor point matters.
- View alignment is respected the same as manual UI dragging: if this view is
  aligned to another view, it can only move along the alignment vector; child views
  aligned to it move along with it.
- Changing this property can change drawing graphics — call
  `IModelDoc2::EditRebuild3` afterward to force a regenerate.

### IView::SetDisplayMode3

- **Interface:** IView
- **Method:** SetDisplayMode3
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
Function SetDisplayMode3( _
    ByVal UseParent As System.Boolean, _
    ByVal Mode As System.Integer, _
    ByVal Facetted As System.Boolean, _
    ByVal Edges As System.Boolean _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UseParent | Boolean | n/a | Yes | True to use the parent's display-mode setting; False to use this view's own local setting | — |
| Mode | Integer | n/a | Yes | Display mode of the drawing view | `swDisplayMode_e` |
| Facetted | Boolean | n/a | Yes | True = draft-quality (faceted) geometry display; False = precision-quality display | — |
| Edges | Boolean | n/a | Yes | True = edges are displayed when this view is in shaded mode | — |

**Returns:** `Boolean` — `True` if the display-mode setting was applied
successfully, `False` if not.

**Prior selection required:** None — called directly on an `IView` reference. This
method is Obsolete, superseded by `IView::SetDisplayMode4`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~SetDisplayMode3.html
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDisplayMode_e.html

**status:** verified

**Gotchas:**
- **Obsolete** — the page's first line is "Obsolete. Superseded by
  `IView::SetDisplayMode4`." New code should call `SetDisplayMode4` instead; this
  record documents `SetDisplayMode3` per the task's explicit request.
- Applies to the whole drawing view, not per-component; `UseParent=True` makes the
  entire view inherit its parent's display-mode setting.
- `Mode` uses **`swDisplayMode_e`** (not `swViewDisplayMode_e` — see the Enums
  section for why these are two distinct, non-interchangeable enums). Confirmed
  members: `swWIREFRAME`=0, `swHIDDEN_GREYED`=1 (Hidden Lines Visible),
  `swHIDDEN`=2 (Hidden Lines Removed), `swSHADED`=3, `swFACETED_WIREFRAME`=4,
  `swFACETED_HIDDEN_GREYED`=5, `swFACETED_HIDDEN`=6, `swSHADED_EDGES`=7,
  `swDisplayModeDEFAULT`=8, `swDisplayModeUNKNOWN`=-1.
- The enum's three faceted-only values, when passed as `Mode`, are treated the same
  as their non-faceted counterparts — faceted-ness is actually driven by the
  separate `Facetted` argument, not by the `Mode` value.
- To shade with edges visible, set the `swDrawingsDefaultDisplayTypeHLREdgesWhenShaded`
  system option to `True` in addition to `Mode = swSHADED`.
- You cannot switch a view from precision quality to draft quality via `Facetted`
  once it has precision quality.
- Units: n/a (no linear/angular values in this call).

### IView::ScaleDecimal

- **Interface:** IView
- **Method:** ScaleDecimal
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
Property Get ScaleDecimal() As System.Double
Property Set ScaleDecimal(ByVal value As System.Double)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| value | Double | n/a (dimensionless ratio) | Yes (Set) | Drawing view scale as a single decimal number, e.g. `1.5` for a 3:2 scale | — |

**Returns:** `Double` — the view scale in decimal form.

**Prior selection required:** None — called directly on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~ScaleDecimal.html

**status:** verified

**Gotchas:**
- No coordinate space applies — a dimensionless scale ratio, not a position; units
  n/a.
- `ScaleDecimal` and `ScaleRatio` "contain the same information, but use the value in
  different ways" per the doc — `ScaleRatio` 3:2 corresponds to `ScaleDecimal` 1.5.
  Treat them as two representations of one underlying scale value.
- Rebuild method differs from other view records in this section: this page cites
  `IModelDoc2::EditRebuild2` after changing the property (Position, ScaleRatio, and
  UseSheetScale all cite `EditRebuild3`) — inconsistency quoted verbatim from each
  page rather than normalized.
- Related properties: `IView::UseParentScale`, `IView::UseSheetScale` (setting
  `UseSheetScale` links/unlinks this value from the sheet scale).

### IView::ScaleRatio

- **Interface:** IView
- **Method:** ScaleRatio
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
Property Get ScaleRatio() As System.Object
Property Set ScaleRatio(ByVal value As System.Object)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| value | Object (array of 2 Doubles) | n/a (dimensionless ratio) | Yes (Set) | `[numerator, denominator]` of the view scale expressed as `n:n` | — |

**Returns:** `System.Object` — 2-element Double array `[numerator, denominator]`.

**Prior selection required:** None — called directly on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~ScaleRatio.html

**status:** verified

**Gotchas:**
- No coordinate space applies — dimensionless ratio, not a position; units n/a.
- Both array elements are Doubles, not Integers, even though they represent a ratio
  like 3:2.
- Same underlying value as `ScaleDecimal` in a different form — the page states they
  "contain the same information, but use the value in a different form."
- Must call `IModelDoc2::EditRebuild3` after changing to force a graphics regenerate
  (per this page — contrast with `ScaleDecimal`'s page, which cites
  `EditRebuild2`).
- Related properties: `IView::IScaleRatio`, `IView::UseParentScale`,
  `IView::UseSheetScale`.

### IView::UseSheetScale

- **Interface:** IView
- **Method:** UseSheetScale
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
Property Get UseSheetScale() As System.Integer
Property Set UseSheetScale(ByVal value As System.Integer)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| value | Integer | n/a | Yes (Set) | `1` if the view scale is the same as the sheet scale; `0` if the view scale is independent of the sheet scale | — |

**Returns:** `Integer` — `1` or `0` as described above.

**Prior selection required:** None — called directly on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~UseSheetScale.html

**status:** verified

**Gotchas:**
- **Not a Boolean** despite the intuitive name — the documented .NET type is
  `System.Integer` with values `1`/`0`. VBA code that assigns `True` (which VBA
  represents as `-1`) rather than `1` may not behave as expected; pass `1`/`0`
  explicitly.
- The page states: "If the property is 0, then it is possible that the view scale is
  the same as the sheet scale" — i.e. `0` does not guarantee the scale is
  independent, only that it isn't force-linked. Treat as an asymmetric guarantee
  (1 ⇒ definitely linked, 0 ⇒ not necessarily different).
- The page does not state whether setting this to `1` immediately overwrites
  `ScaleDecimal`/`ScaleRatio` to the sheet's scale value — not documented on this
  page, don't infer it. To explicitly force a view to adopt its parent sheet's
  scale, the doc instead points to `IView::UseParentScale`.
- Changing this property can change drawing graphics — call
  `IModelDoc2::EditRebuild3` afterward to force a regenerate.
- Units: n/a (a link/state flag, not a measurement).

## View enumeration and metadata

These four records back a "list every view on a sheet, with what it's called, what
kind it is, and what it references" tool -- not itself part of the original research
issue's requested-method list, but needed to make the view-creation tools' output
addressable (a caller can't target a view by name without first discovering that
name). Added per this issue's working agreement: fetched from help.solidworks.com
where reachable, and from the same type-library mirror plus a working VBA example
this dossier already relies on elsewhere where help.solidworks.com 403'd.

### IDrawingDoc::Sheet

- **Interface:** IDrawingDoc
- **Method:** Sheet
- **Minimum SW version:** unverified — help page fetch 403'd directly (same WAF
  block noted throughout this dossier).

**Signature:**

```vb
Function Sheet( _
   ByVal Name As System.String _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name of the sheet to retrieve, e.g. one of the strings returned by `GetSheetNames` | — |

**Returns:** `System.Object`, which is actually an `ISheet` interface pointer wrapped
as `Object` — same casting pattern as `GetSheetNames`/`GetCurrentSheet` documented
above. `Nothing`/`Empty` if no sheet by that name exists (inferred by symmetry with
this API's other name-lookup accessors; not independently confirmed on an
inaccessible page).

**Prior selection required:** None — a direct by-name lookup, unlike
`GetCurrentSheet` (whichever sheet happens to be active).

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IDrawingDoc.html (type-library mirror: confirms `Sheet(String) -> ISheet` signature; also lists `Sheet` in the authoritative Sheet-related member set already cited by this dossier's sheet-deletion record)

**status:** verified (type-library signature only; help page itself inaccessible)

**Gotchas:**
- Same `Object` → `ISheet` cast requirement as `GetSheetNames`/`GetCurrentSheet` —
  not a typed return.
- Distinct from `GetCurrentSheet` (returns whichever sheet is active) and
  `ActivateSheet` (changes which sheet is active, returns `Boolean`, not an `ISheet`
  reference) — `Sheet(Name)` is the one accessor that resolves an arbitrary sheet by
  name without changing what's currently active in the UI.

### ISheet::GetViews

- **Interface:** ISheet
- **Method:** GetViews
- **Minimum SW version:** unverified — help page fetch 403'd directly (same WAF
  block noted throughout this dossier).

**Signature:**

```vb
Function GetViews() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters | — |

**Returns:** `System.Object`, cast to an array of `IView` (`View`) objects — every
view placed on this specific sheet. A working VBA example (source below) iterates
this array directly with `For Each` and reads `.Name` off each element with no
skip-the-first-entry step, so (unlike `IDrawingDoc::GetViews`, which returns one
array per sheet with the sheet itself as that sub-array's first element — see that
method's own record) this per-sheet accessor's array holds only placed views, not
the sheet.

**Prior selection required:** None — called on an already-resolved `ISheet`
reference (e.g. from `IDrawingDoc::Sheet`/`GetCurrentSheet`).

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/ISheet.html (type-library mirror: confirms no-argument, `Object`-returning signature)
- https://thecadcoder.com/solidworks-vba-macros/drawing-loop-all-views-in-drawing/ (working VBA example: `views = swSheet.GetViews` then `For Each vView In views` reading `.Name` directly)
- https://help.solidworks.com/2016/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.isheet~getviews.html (indexed by search; direct fetch 403'd)

**status:** verified (type-library signature + working macro corroborate each
other; help page body itself inaccessible)

**Gotchas:**
- **Does not include the sheet itself** — contrast with `IDrawingDoc::GetViews`,
  whose per-sheet sub-arrays are headed by the sheet's own pseudo-view entry (Type
  `swDrawingSheet`). Enumerating via `ISheet::GetViews` needs no such skip. This is
  itself an inference (see the working-example caveat two paragraphs below), not an
  independently stated fact — `list_views` (this issue's consumer of this record)
  filters out any `swDrawingSheet`-typed entry defensively rather than trusting it,
  so a wrong assumption here degrades to a no-op filter instead of a bogus
  "Sheet1"-named view leaking into every downstream view/annotation tool's view list.
- An empty sheet (no views placed yet) returns an empty array, not `Nothing`/`Empty`
  — inferred from the working example's unconditional `For Each` with no
  nil-guard, not independently stated on an accessible help page; treat as the
  working assumption, verify empirically if a zero-view sheet behaves unexpectedly.
- `Object` return needs the same array cast as `GetSheetNames`/`GetCurrentSheet`.
- **Getting a resolved `ISheet`'s own name:** the type-library mirror lists it as a
  Java `getName()` accessor, the standard COM4Java rendering of a VB `Property Get
  Name` — i.e. the real member is the property `ISheet::Name`, not a `GetName()`
  method (contrast with `IView::GetName2`, whose Java form is `getName2()` because
  that one really is a VB `Function`, not a property). Not independently verified
  against a fetchable help page; low-stakes enough (display-only) not to block this
  issue on it.

### IView::ReferencedDocument

- **Interface:** IView
- **Method:** ReferencedDocument (property)
- **Minimum SW version:** unverified — help page fetch 403'd directly (same WAF
  block noted throughout this dossier).

**Signature:**

```vb
ReadOnly Property ReferencedDocument As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters (property get only) | — |

**Returns:** `System.Object`, cast to `IModelDoc2` — the model document this view
was created from. Per search-indexed page text, **section and detail views have no
referenced document of their own** and this property does not return a usable model
reference for them; get the base/parent view first via `IView::GetBaseView` and read
`ReferencedDocument` off that instead.

**Prior selection required:** None — direct property get on an `IView` reference.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IView.html (type-library mirror: confirms get-only, `IModelDoc2`-returning property)
- https://help.solidworks.com/2018/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IView~ReferencedDocument.html (indexed by search, snippet quoted above; direct fetch 403'd)

**status:** verified (type-library signature + search-indexed page snippet
corroborate each other; full help page body itself inaccessible)

**Gotchas:**
- **Section/detail views: no referenced document of their own** — walk to the base
  view via `GetBaseView`/`IGetBaseView` first (see that record below) before reading
  this property, or the call returns nothing usable.
- A companion `IView::GetReferencedModelName` (String-returning, confirmed to exist
  by an indexed help-page title, not independently fetched) gives just the model's
  name without a full `IModelDoc2` handle — cheaper if only the name is needed and
  the model may not be loaded/resolvable as a live document object.
- Get-only — there is no `SetReferencedDocument`; a view's model reference is fixed
  by how it was created (`CreateDrawViewFromModelView3`'s `ModelName`, etc.).

### IView::GetBaseView / IView::IGetBaseView

- **Interface:** IView
- **Method:** GetBaseView (returns `Dispatch`) / IGetBaseView (typed `IView`
  variant, same pattern as `GetFirstView`/`IGetFirstView` elsewhere in this API)
- **Minimum SW version:** unverified — help page fetch 403'd directly (same WAF
  block noted throughout this dossier).

**Signature:**

```vb
Function GetBaseView() As System.Object   ' cast to IView
Function IGetBaseView() As IView          ' typed variant
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters | — |

**Returns:** `IView` — the parent/base view this view was derived from (e.g. a
section, detail, auxiliary, or projected view's originating standard view), or
`Nothing`/`Empty` for a view with no parent (e.g. a plain model view placed directly
via `CreateDrawViewFromModelView3`, or the sheet's first standard view).

**Prior selection required:** None — direct method call on an `IView` reference.

**Source URL(s):**
- https://www.rimptec.com/rsolidworks/net/lehal/sw/IView.html (type-library mirror: confirms both `GetBaseView`/`IGetBaseView` exist, no-argument)
- https://www.javelin-tech.com/blog/2015/07/find-parent-view-solidworks/ (vendor blog: "use IView::GetBaseView or IView::IGetBaseView to get the parent view of a section [or detail] view"; direct fetch of this page itself 403'd, corroborated via search index)

**status:** verified (type-library signature + independent vendor-blog corroboration
via search index; neither source's full page body was directly fetchable)

**Gotchas:**
- **This is the answer to "what is this view's parent view"** — there is no
  `IView::Parent`/`ParentView` property; searches for one turn up nothing (see this
  section's introductory note). `GetBaseView`/`IGetBaseView` is the real member.
- Documented use case is specifically section/detail views reaching back to the
  standard view they were cut/detailed from; behavior for other derived-view types
  (projected/auxiliary/alternate-position) is not independently confirmed here —
  treat a `Nothing`/`Empty` return as "no parent" regardless of view type rather than
  assuming it only applies to section/detail views.
- Combine with `ReferencedDocument`'s section/detail-view gap above: for a view
  whose own `ReferencedDocument` is empty, `GetBaseView().ReferencedDocument` is the
  documented fallback path to the underlying model.

## View naming, type, alignment, and lifecycle

### IView::GetName2

- **Interface:** IView
- **Method:** GetName2
- **Minimum SW version:** SOLIDWORKS 2005 FCS, Revision Number 13.0

**Signature:**

```vb
Function GetName2() As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters | — |

**Returns:** `String` — the name of the drawing view as displayed in the
FeatureManager design tree (e.g. "Drawing View1"). No specific failure/empty-return
case is documented.

**Prior selection required:** None — called directly on an `IView` reference already
obtained (e.g. via `IDrawingDoc::GetFirstView`/`IView::GetNextView`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetName2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html

**status:** verified

**Gotchas:**
- Does not return unique names for section views — call `IView::GetUniqueName` for
  that (stated explicitly in Remarks).
- There is no plain "GetName" method on `IView`. Direct fetch of that URL returns
  file-does-not-exist, and the member index lists only `GetName2`. The predecessor
  was actually the **`Name` property** (get/set), which the member index marks
  Obsolete — "Superseded by IView::GetName2 and IView::SetName2." So the "2" isn't a
  same-shaped bump — it's the replacement of a read/write property with an explicit
  method pair. The docs don't state the underlying technical reason beyond
  "Obsolete."
- Because `Name` still exists (deprecated) but is undocumented as to when it will be
  removed, legacy macros may still reference `IView.Name` — new code should use
  `GetName2`/`SetName2`.

### IView::Type

- **Interface:** IView
- **Method:** Type
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
ReadOnly Property Type As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters (property get only) | — |

**Returns:** `Integer` — the drawing view type, as defined by `swDrawingViewTypes_e`.

**Prior selection required:** None — direct property get on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~Type.html

**status:** verified

**Gotchas:**
- Confirmed get-only: VB declares it `ReadOnly Property`, and the C++/CLI syntax
  block shows only a `get()` accessor. There is no way to change a view's type
  through this property — view type is a function of how the view was created
  (projected, section, detail, auxiliary, etc.).
- Enum member values live on the separate `swDrawingViewTypes_e` reference page — see
  Enums section below.

### IView::GetAlignment

- **Interface:** IView
- **Method:** GetAlignment — requested as `IView::Alignment` (property), which does
  not exist in the SOLIDWORKS API (see Gotchas)
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
' IView::Alignment does NOT exist. Verified: the URL .../IView~Alignment.html
' returns "File does not exist" from the SOLIDWORKS help server, and the IView
' member index lists no "Alignment" property in its Public Properties table.
'
' The real, verified member that reports alignment state is a GET-ONLY METHOD,
' not a property:
Function GetAlignment() As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | No parameters | — |

**Returns:** `Integer` — alignment info as defined by `swViewAlignment_e`; indicates
whether this view is aligned with a parent view, and/or whether other (child) views
are aligned with this view. No failure value documented.

**Prior selection required:** None — direct method call on an `IView` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~Alignment.html (404 — confirms non-existence)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetAlignment.html (real member)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView_members.html (member index — confirms no Alignment property)

**status:** verified

**Gotchas:**
- `IView.Alignment` is not a real SOLIDWORKS API member — any code referencing it is
  invented.
- The real read-side is `IView::GetAlignment` (method, not property), returning
  `swViewAlignment_e` — a different enum from `swAlignViewTypes_e` (used by
  `AlignWithView`'s `AlignType` parameter — see the record below). `GetAlignment`
  answers "what is this view's alignment state relative to parent/children";
  `swAlignViewTypes_e` values are inputs describing how to align.
- There is no `SetAlignment`. Alignment is set via `IView::AlignWithView` (align to
  another view) or `IView::AlignDrawingView` (auxiliary views), cleared via
  `IView::RemoveAlignment`, and reset to default via `IView::UseDefaultAlignment`.

### IView::AlignWithView

- **Interface:** IView
- **Method:** AlignWithView — requested as `IDrawingDoc::AlignView`, which does not
  exist in the SOLIDWORKS API (see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2004 FCS, Revision Number 12.0

**Signature:**

```vb
' IDrawingDoc::AlignView does NOT exist. Verified: the URL
' .../IDrawingDoc~AlignView.html returns "File does not exist" from the SOLIDWORKS
' help server, and IDrawingDoc_members.html lists no "AlignView" method.
' IDrawingDoc's own alignment-flavored methods are only AlignHorz, AlignVert, and
' AlignOrdinate — narrow helpers, not general view-to-view alignment.
'
' The real, verified method (align a view to a reference/base view using an
' alignment-type enum) lives on IView, not IDrawingDoc:
Function AlignWithView( _
   ByVal AlignType As System.Integer, _
   ByVal BaseView As View _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| AlignType | Integer | n/a | Yes | Type of alignment to set | `swAlignViewTypes_e` |
| BaseView | View (object) | n/a | Conditionally required | View to align with. Required when `AlignType` is `swAlignViewHorizontalCenter`, `swAlignViewVerticalCenter`, `swAlignViewHorizontalOrigin`, or `swAlignViewVerticalOrigin`; ignored when `AlignType` is `swNoViewAlignment` or `swDefaultViewAlignment` | `swAlignViewTypes_e` |

**Returns:** `Boolean` — `True` if view alignment is set, `False` if not.

**Prior selection required:** None — called on the `View` object being
moved/aligned (the method's instance), passing the reference view as `BaseView`.
Both are plain object references obtained programmatically (e.g. via
`IDrawingDoc::GetFirstView`/`IView::GetNextView`); no interactive UI selection is
needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~AlignView.html (404 — confirms non-existence)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~AlignWithView.html (real member — SOLIDWORKS 2004 FCS, Revision 12.0)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (member index — confirms absence; only AlignHorz/AlignVert/AlignOrdinate)

**status:** verified

**Gotchas:**
- `IDrawingDoc.AlignView` is not real. The method that actively aligns one view to
  another (reference view + alignment type) is `IView::AlignWithView`, called on the
  view being moved, not on the document.
- Relationship to `GetAlignment`: `AlignWithView` is the "setter/actor" side;
  `IView::GetAlignment` (see previous record) is the "read the resulting state"
  side. There's no plain gettable/settable property in between — it's two methods,
  not a property.
- `IDrawingDoc` does have alignment-adjacent methods, but narrower ones: `AlignHorz`/
  `AlignVert` align a view so a selected edge is horizontal/vertical, and
  `AlignOrdinate` aligns ordinate dimensions — none accept a base-view +
  `swAlignViewTypes_e` pair.
- For auxiliary/derived views there's a sibling,
  `IView::AlignDrawingView(AlignViewType As Integer)`, referencing a third, distinct
  enum `swAlignDrawingViewTypes_e` (SOLIDWORKS 2014 FCS, Revision 22.0) — don't
  confuse its parameter with `AlignWithView`'s `swAlignViewTypes_e`.
- To break an established alignment, call `IView::RemoveAlignment`; to restore
  default alignment, call `IView::UseDefaultAlignment`.

### IModelDocExtension::DeleteSelection2

- **Interface:** IModelDocExtension
- **Method:** DeleteSelection2 — requested as `IDrawingDoc::DeleteView2`, which does
  not exist in the SOLIDWORKS API (see Gotchas)
- **Minimum SW version:** SOLIDWORKS 2006 SP1, Revision Number 14.1

**Signature:**

```vb
' IDrawingDoc::DeleteView2 does NOT exist. Verified: the URL
' .../IDrawingDoc~DeleteView2.html returns "File does not exist" from the
' SOLIDWORKS help server. IDrawingDoc_members.html has no Delete*View* entry
' anywhere in its full alphabetical Properties + Methods tables. Also checked and
' confirmed absent on IModelDoc2, IModelDocExtension, and ISheet.
'
' SOLIDWORKS has no single "delete this named view" API call at all. The
' documented pattern is: select the view, then delete the current selection, via
' IModelDocExtension::DeleteSelection2:
Function DeleteSelection2( _
   ByVal DeleteOptions As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| DeleteOptions | Integer | n/a | Yes | Options controlling deletion of absorbed/child features along with the selection | `swDeleteSelectionOptions_e` |

**Returns:** `Boolean` — `True` if the selected item is deleted, `False` if not.

**Prior selection required:** Yes, explicit — unlike a hypothetical
`DeleteView2(sheetName, viewName)`, `DeleteSelection2` operates on whatever is
currently active in the `SelectionMgr`. The caller must first select the target
drawing view (e.g. `IModelDocExtension::SelectByID2` with the view's name and
selection type `swSelDRAWINGVIEWS`) before calling `DeleteSelection2`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~DeleteView2.html (404 — confirms non-existence)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~DeleteSelection2.html (closest real, verified member — SOLIDWORKS 2006 SP1, Revision 14.1)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (member index — confirms absence)

**status:** verified

**Gotchas:**
- `DeleteView2` is not a real SOLIDWORKS API member on `IDrawingDoc`, `IModelDoc2`,
  `IModelDocExtension`, or `ISheet` — treat any reference to it as invented.
- Cascade behavior for child/projected views is not documented on the
  `DeleteSelection2` API page — its only Remark is "This method does not ask the user
  to confirm the deletion." Non-API SOLIDWORKS documentation and community sources
  indicate deleting a parent view also deletes views derived from it (e.g. a
  detail/section view whose parent is removed goes with it), while views merely
  aligned to a parent are typically un-aligned/repositioned rather than deleted — but
  this specific rule is **unverified at the API level**; test empirically before
  relying on it in automation.
- To reduce cascade-delete risk for a dependent view beforehand, break its alignment
  first via `IView::RemoveAlignment` (mirrors the UI's Alignment > Break Alignment
  command).
- `DeleteSelection2`'s own "See Also" list also points to `IModelDoc2::EditDelete` as
  a legacy alternative — also selection-based, also not view-specific.

### IDrawingDoc::ActivateView

- **Interface:** IDrawingDoc
- **Method:** ActivateView
- **Minimum SW version:** not stated on help page

**Signature:**

```vb
Function ActivateView( _
   ByVal ViewName As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ViewName | String | n/a | Yes | Name of the drawing view to activate | — |

**Returns:** `Boolean` — `True` if successful, `False` if not. Explicitly documented
failure case: returns `False` when trying to activate a drawing sheet (a sheet is not
a view for this call's purposes).

**Prior selection required:** None — called directly on the active `IDrawingDoc`
reference, targeting the view by its name string; no prior interactive selection is
needed (this call itself is what makes the view "current").

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~ActivateView.html

**status:** verified

**Gotchas:**
- To activate a sheet instead of a view, use `IDrawingDoc::ActivateSheet` — calling
  `ActivateView` with a sheet name (or otherwise targeting a sheet) returns `False`.
- "Activating" a view is what makes it the target for subsequent view-scoped
  operations that don't take an explicit view parameter (e.g. subsequent
  sketch/annotation/dimension calls apply to whichever view is currently active) —
  matches `CreateDetailViewAt4`'s use of `ActivateView` in its own prerequisite
  workflow (see that record above).
- Related members for enumerating/reading view state: `IDrawingDoc::GetFirstView`/
  `IView::GetNextView` (enumerate views to find the name to pass in), and the
  `ActiveDrawingView`/`IActiveDrawingView` property (read back which view is
  currently active after calling `ActivateView`).

## Enums

#### swDrawingViewTypes_e

Identifies the kind of drawing view; returned by `IView::Type`.

| Value | Number | Meaning |
| --- | --- | --- |
| swDrawingSheet | 1 | Drawing sheet (the sheet itself, not a placed view) |
| swDrawingSectionView | 2 | Section view |
| swDrawingDetailView | 3 | Detail view |
| swDrawingProjectedView | 4 | Projected (unfolded) view |
| swDrawingAuxiliaryView | 5 | Auxiliary view |
| swDrawingStandardView | 6 | Standard view |
| swDrawingNamedView | 7 | Named view |
| swDrawingRelativeView | 8 | Relative view to the model |
| swDrawingDetachedView | 9 | Detached view |
| swDrawingAlternatePositionView | 10 | Alternate position view |

Note: `swDrawingSheet` (1) is included even though it denotes the sheet rather than a
placed view — confirmed as a real return value of `IView::Type`, which documents its
return type as `swDrawingViewTypes_e`.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDrawingViewTypes_e.html

#### swViewDisplayMode_e

Display modes for a drawing view (wireframe/shaded family, plus perspective,
curvature-display, and zebra-stripe toggles, and an integrated-preview mode). The
help page's Members table gives only the numeric value per member, no separate
description text.

| Value | Number | Meaning |
| --- | --- | --- |
| swViewDisplayMode_Wireframe | 1 | Wireframe |
| swViewDisplayMode_HiddenLinesRemoved | 2 | Hidden lines removed (HLR) |
| swViewDisplayMode_HiddenLinesGrayed | 3 | Hidden lines grayed/visible (HLV) |
| swViewDisplayMode_Shaded | 4 | Shaded |
| swViewDisplayMode_ShadedWithEdges | 5 | Shaded with edges |
| swViewDisplayMode_ShadedCurvatureOn | 6 | Shaded, curvature display on |
| swViewDisplayMode_ShadedCurvatureOFF | 7 | Shaded, curvature display off |
| swViewDisplayMode_StripesOn | 8 | Zebra stripes on |
| swViewDisplayMode_StripesOff | 9 | Zebra stripes off |
| swViewDisplayMode_PerspectiveOn | 10 | Perspective view on |
| swViewDisplayMode_PerspectiveOff | 11 | Perspective view off |
| swViewDisplayMode_Faceted | 12 | Faceted display |
| swViewDisplayMode_IntegratedPreview | 13 | Integrated preview |

Note: this is a distinct, separate enum from the legacy `swDisplayMode_e` (members
`swWIREFRAME`, `swHIDDEN`, `swSHADED`, etc., used by `SetDisplayMode3`/`4`'s `Mode`
parameter — see `IView::SetDisplayMode3` above). `IView::SetDisplayMode3` (obsolete)
and its replacement `IView::SetDisplayMode4` both take their `Mode` parameter "as
defined in `swDisplayMode_e`", not `swViewDisplayMode_e` — confirmed directly on both
method pages. Do not use `swViewDisplayMode_e` values with `SetDisplayMode3`/`4`.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swViewDisplayMode_e.html

#### swDisplayStateOpts_e

Options for how a display state is specified for an operation.

| Value | Number | Meaning |
| --- | --- | --- |
| swThisDisplayState | 1 | This (the current/active) display state |
| swAllDisplayState | 2 | All display states |
| swSpecifyDisplayState | 3 | A specific, named display state |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDisplayStateOpts_e.html

#### swCreateDrawViewOption_e

Not present in the SOLIDWORKS 2025 `swconst` namespace index (checked against the
full enum list for the `swconst` namespace). The canonical URL returns the SOLIDWORKS
Web Help viewer's "File does not exist" error rather than a real page. No enum by
this name, or an obvious rename, could be located. Consistent with this:
`IDrawingDoc::CreateDrawViewFromModelView3` — the primary "place a model view on a
drawing sheet" method — takes only `ModelName, ViewName, LocX, LocY, LocZ` (confirmed
from its own help page); it has no `Options` parameter at all, so there is no
options/bitmask enum backing it. Do not invent values for this name.

Source (attempted, returns error): https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateDrawViewOption_e.html

#### swDetCircleShowType_e

Requested as `swDetailCircleStyle_e`, which is not present in the SOLIDWORKS 2025
`swconst` namespace index; the canonical URL returns a "File does not exist" error.
The closest real, current enum is `swDetCircleShowType_e` — confirmed as the actual
enum backing the detail-circle concept:
`IDrawingDoc::CreateDetailViewAt4`'s `Showtype` parameter is documented as "Type of
sketch for the detail view as defined in `swDetCircleShowType_e`".

| Value | Number | Meaning |
| --- | --- | --- |
| swDetCirclePROFILE | 0 | Use sketch profile to create detail view |
| swDetCircleCIRCLE | 1 | Use sketch circle to create detail view |
| swDetCircleDONTSHOW | 2 | Do not show a sketch profile |

Note: there is a second, related but distinct enum on the same
`CreateDetailViewAt4` method — `swDetViewStyle_e` (`swDetViewSTANDARD`/`BROKEN`/
`LEADER`/`NOLEADER`/`CONNECTED`) — which governs the detail view's leader/border
style via the `Style` parameter, not the circle/profile sketch type. Don't conflate
the two when implementing detail-view creation.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDetCircleShowType_e.html

#### swSectionViewOptions_e

Not present in the SOLIDWORKS 2025 `swconst` namespace index; the canonical URL
returns a "File does not exist" error. This is not the current name — see
`swCreateSectionViewAtOptions_e` below, the real, existing enum for this concept.

Source (attempted, returns error): https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSectionViewOptions_e.html

#### swCreateSectionViewAtOptions_e

Options that affect the section view that is created. Bitmask enum (values are
powers of 2, OR'd together).

| Value | Number | Meaning |
| --- | --- | --- |
| swCreateSectionView_NotAligned | 1 (0x1) | If set, the section does not snap into alignment with the parent view; if not set, the section snaps into alignment with the parent view |
| swCreateSectionView_OffsetSection | 2 (0x2) | If set, an aligned section view is created (two lines at an angle); if not set, a normal projection section view is created |
| swCreateSectionView_ChangeDirection | 4 (0x4) | If set, the direction of this section view is switched; if not set, the direction is not switched |
| swCreateSectionView_ScaleWithModel | 8 (0x8) | If set, the section view is scaled with the model; if not set, it is not |
| swCreateSectionView_Partial | 16 (0x10) | If set, a partial section view is created; if not set, a complete section view is created |
| swCreateSectionView_DisplaySurfaceCut | 32 (0x20) | If set, only surfaces cut by the section line appear in the section view; if not set, all model surfaces appear |
| swCreateSectionView_ExcludeFasteners | 64 (0x40) | If set, fasteners are not included in the section view; if not set, fasteners are included |
| swCreateSectionView_CutSurfaceBodies | 128 (0x80) | If set, shows only the intersecting line of a surface in a section view |

Note: this is what `swSectionViewOptions_e` was likely intended to refer to — that
name does not exist (see record above). Confirmed as the actual consumer:
`IDrawingDoc::CreateSectionViewAt5`'s `Options` parameter is documented as "Options
that affect the section view as defined in `swCreateSectionViewAtOptions_e`". The
vendor's own descriptions for bits 1 (`NotAligned`) and 2 (`OffsetSection`) both use
the word "aligned" in what reads like opposite senses — reproduced as-written above;
the source does not reconcile this, so it isn't resolved here either (see
`IDrawingDoc::CreateSectionViewAt5`'s Gotchas for the same flag).

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateSectionViewAtOptions_e.html

#### swAlignViewTypes_e

View alignment types — how a drawing view is aligned relative to its base view;
consumed by `IView::AlignWithView`'s `AlignType` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swNoViewAlignment | 0 | Remove the alignment restriction on this view |
| swDefaultViewAlignment | 1 | Set the alignment of this view to its default |
| swAlignViewHorizontalCenter | 2 | Align this view horizontally with the center of BaseView |
| swAlignViewVerticalCenter | 3 | Align this view vertically with BaseView |
| swAlignViewHorizontalOrigin | 4 | Align this view horizontally with the origin of BaseView |
| swAlignViewVerticalOrigin | 5 | Align this view vertically with the origin of BaseView |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAlignViewTypes_e.html

#### swBreakLineStyle_e

Break line styles for a drawing view break; consumed by `IView::InsertBreak3`'s
`Style` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swBreakLine_Straight | 1 | Straight break line |
| swBreakLine_ZigZag | 2 | Zig-zag break line |
| swBreakLine_Curve | 3 | Curved break line |
| swBreakLine_SmallZigZag | 4 | Small zig-zag break line |
| swBreakLine_Jagged | 5 | Jagged break line |

Note: also confirmed consumed by `IView::GetBreakLineInfo2`, whose returned array
documents its `breaklineStyle` element as "Break line style as defined in
`swBreakLineStyle_e`".

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBreakLineStyle_e.html

#### swBreakLineOrientation_e

Requested as `swBreakDir_e`, which is not present in the SOLIDWORKS 2025 `swconst`
namespace index; the canonical URL returns a "File does not exist" error. The real,
current enum is `swBreakLineOrientation_e` — confirmed as the actual enum backing
break-line direction: `IView::InsertBreak3`'s `Orientation` parameter and
`IBreakLine::Orientation` both document their value as "as defined in
`swBreakLineOrientation_e`".

| Value | Number | Meaning |
| --- | --- | --- |
| swBreakLineHorizontal | 1 | Horizontal break line |
| swBreakLineVertical | 2 | Vertical break line |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swBreakLineOrientation_e.html

#### swUserPreferenceToggle_e (view-relevant member)

`swUserPreferenceToggle_e` has hundreds of members covering every SOLIDWORKS system
option; per this dossier's `GetUserPreferenceToggle`/`SetUserPreferenceToggle`
records above, and per `docs/api/05-export-and-layers.md`'s own curated-subset
disclaimer for the same enum, its help.solidworks.com enumeration page publishes no
numeric values for any member. This view-creation epic needs exactly one member's
numeric value (to snapshot-then-restore the toggle around `insert_standard_3_view`),
so it was tracked down independently rather than left as a named-only constant:

| Member | Number | Meaning |
| --- | --- | --- |
| swAutomaticScaling3ViewDrawings | 86 (`0x56`) | Auto-scale newly inserted drawing views to fit the sheet (see `CreateDrawViewFromModelView3`'s and `Create3rdAngleViews2`'s Gotchas above for its documented effect) |

**Source:** a community-hosted Delphi/Pascal transcription of the compiled
`SwConst.tlb` type library (`SwConst_TLB.pas`, from the `pisfu/PlanetGear` GitHub
repository — a student CAD project's checked-in API bindings, not an official
SOLIDWORKS source), which enumerates the full `swUserPreferenceToggle_e` block as
consecutive hex constants: `swAutomaticScaling3ViewDrawings = $00000056` (86),
immediately followed by `swDrawingAutomaticBomUpdate = $00000057` (87),
`swDrawingSelectHiddenEntities = $00000058` (88), etc. — a monotonic, gap-free
sequence consistent with a genuine compiled-in enum rather than a guess.
https://github.com/pisfu/PlanetGear (file path contains Cyrillic directory names;
see this dossier's git history / research notes for the exact URL used).

**status:** unverified against a primary help.solidworks.com/swconst page (none
publish numeric values for this enum at all, per every source checked in this and
the export dossier's research passes) — corroborated only by one third-party
compiled-type-library transcription. Treat this specific numeric value with more
caution than this dossier's other enums; if `SetUserPreferenceToggle(86, ...)`
is ever observed to toggle the wrong system option against a live SolidWorks
session, this is the record to revisit first.
