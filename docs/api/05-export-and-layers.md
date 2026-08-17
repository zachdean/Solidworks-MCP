---
interface: Multiple (IModelDocExtension, ISldWorks, IExportPdfData, IPartDoc, IDrawingDoc, ILayerMgr, ILayer)
min_methods: 12
status: complete
---

# Export, layers, and line format

Covers PDF export (`SaveAs3` + `IExportPdfData`), DXF/DWG export, eDrawings export, the
`ISldWorks` user-preference toggles/integers that silently change export output, layer
management (`ILayerMgr`/`ILayer`), and per-entity line format on drawings
(`IDrawingDoc::SetLineWidth`/`SetLineStyle`).

Several method/interface names given by the source research issue turned out not to
match the current (SOLIDWORKS 2025) API surface. Each is documented below under its
*real* name, with the discrepancy called out in that record's Gotchas — summarized here
for a quick scan, following the same honesty convention established in
[`03-annotations.md`](03-annotations.md) and [`04-tables.md`](04-tables.md):

- `IDrawingDoc::ExportToDWG2` does not exist. The only `ExportToDWG2` in the API lives on
  `IPartDoc` and exports sheet-metal flat-pattern geometry (plus faces/loops/annotation
  views) from a **part**, not a drawing sheet. Confirmed by a direct 404 fetch of the
  `IDrawingDoc` URL and by `IDrawingDoc_members.html` containing no `ExportToDWG*`
  member at all. The real mechanism for exporting **drawing sheets** to DXF/DWG is
  `IModelDocExtension::SaveAs3` (or the older `IModelDoc2::SaveAs4`) with a `.dxf`/`.dwg`
  filename extension, combined with `ISldWorks::SetUserPreferenceIntegerValue`/
  `SetUserPreferenceToggle` calls (documented below) — there is no drawing-specific
  "ExportToDXF" method. This is corroborated by two independent sources: the official
  "Save Drawing Sheets as DXF Example (VBA)" (2025), which loops `IDrawingDoc::
  ActivateSheet` + `IModelDoc2::SaveAs4` per sheet, and the "File > Save As > Save as
  type > Dxf or Dwg > Options" reference page, whose entire settings table is expressed
  in terms of `SetUserPreferenceToggle`/`SetUserPreferenceIntegerValue` calls, not a
  drawing export method's parameters.
- `IModelDocExtension::SetLineWeight`/`SetLineStyle` do not exist, and there is no
  `ILineFontMgr` interface anywhere in the API (confirmed by 404 fetches of all three
  URLs). The real methods are `IDrawingDoc::SetLineWidth` and `IDrawingDoc::SetLineStyle`
  (plus a sibling `IDrawingDoc::SetLineColor`, not separately documented below since it
  wasn't in the task's method list) — both act on the current drawing-view selection,
  not a document-wide default.
- `swDxfOutputFonts_e` does not exist as its own enum type — a direct fetch 404s.
  `swDxfOutputFonts` is a **member** of `swUserPreferenceIntegerValue_e`, and (unusually
  for that enum) its two valid values are explicitly documented on the DXF/DWG Save As
  Options reference page rather than on the enum's own page — see the
  `swUserPreferenceIntegerValue_e` entry in Enums below.
- `swEdrawingsSaveAsSelectionOption` (a `swUserPreferenceIntegerValue_e` member) is
  listed as **Obsolete** on the current (2025) "System Options > Export > EDRW/EPRT/EASM"
  reference page, yet it is still the constant used by `IModelDocExtension::SaveAs3`'s
  own **2025-dated** Remarks worked example (`swApp.SetUserPreferenceIntegerValue
  swEdrawingsSaveAsSelectionOption, swEdrawingSaveAll`). This is a direct contradiction
  between two current, official pages — flagged explicitly in that record's Gotchas
  rather than silently picked one way. Treat `swEdrawingsSaveAsSelectionOption` as
  functionally present (the SaveAs3 page still tells callers to use it) but
  API-documentation-obsolete; do not be surprised if it is removed in a future version.

`help.solidworks.com` blocks plain fetches (HTTP 403) without a browser-like
`User-Agent` header — see [`README.md`](README.md#canonical-source-urls) for the retry
convention used throughout. 404s in this dossier were confirmed by the same two-part
test established in `04-tables.md`: no `Function`/`Sub`/`Property <Name>(` syntax block
**and** no `"helpContentData":{"title":...}` matching the requested member name on the
fetched page (the generic "Welcome to the SOLIDWORKS Web Help" landing page has neither).

## PDF export

### IModelDocExtension::SaveAs3

- **Interface:** IModelDocExtension
- **Method:** SaveAs3
- **Minimum SW version:** SOLIDWORKS 2020 SP02, Revision Number 28.2 (supersedes the
  now-obsolete `SaveAs2`)

**Signature:**

```vb
Function SaveAs3( _
   ByVal Name As System.String, _
   ByVal Version As System.Integer, _
   ByVal Options As System.Integer, _
   ByVal ExportData As System.Object, _
   ByVal AdvancedSaveAsOptions As System.Object, _
   ByRef Errors As System.Integer, _
   ByRef Warnings As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Full pathname to save to; the file extension indicates the conversion to perform (e.g. `.pdf`, `.dxf`, `.dwg`, `.edrw`/`.eprt`/`.easm`) | |
| Version | Integer | n/a | Yes | Format/version to save as; only needed when the extension doesn't uniquely determine it (e.g. detached vs. standard drawing) | `swSaveAsVersion_e` |
| Options | Integer | n/a | Yes | Save options bitmask | `swSaveAsOptions_e` |
| ExportData | Object | n/a | No | An `IExportPdfData` object controlling which drawing sheets to export **to PDF**. Pass `Nothing`/`null` for all other formats, or to export all sheets to PDF | |
| AdvancedSaveAsOptions | Object | n/a | No | An `IAdvancedSaveAsOptions` object (from `IModelDocExtension::GetAdvancedSaveAsOptions`) for subset-of-configurations / component-rename save behavior. Pass `Nothing`/`null` if unused | |
| Errors | Integer (ByRef) | n/a | Yes (pass `Nothing`/`null` to suppress) | Bitmask of failure causes on return | `swFileSaveError_e` |
| Warnings | Integer (ByRef) | n/a | Yes (pass `Nothing`/`null` to suppress) | Bitmask of warnings/info on return | `swFileSaveWarning_e` |

**Returns:** `Boolean`. True and `Errors = 0` if the save succeeded; false and `Errors`
containing a bitwise-OR of `swFileSaveError_e` values if not. `Warnings` is populated
(as a bitwise-OR of `swFileSaveWarning_e` values) even on a successful save.

**Prior selection required:** None, **except** for IGES/STL/STEP export, which requires
the document to convert to be the active document (`ISldWorks::ActivateDoc3` then
`ISldWorks::ActiveDoc`) — not a selection-list requirement. Separately: "Exports the
entire model, unless faces or bodies are selected, in which case it exports only
those" — call `IModelDoc2::ClearSelection2` first if a full-model export is wanted and
a selection might be present.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SaveAs3.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension_members.html (confirms `SaveAs`→Obsolete/superseded-by-`SaveAs2`, `SaveAs2`→Obsolete/superseded-by-`SaveAs3`, and `SaveAs3` itself carries no Obsolete tag — i.e. `SaveAs3` is the current member)
- https://help.solidworks.com/2025/english/api/sldworksapi/Save_File_as_PDF_Example_VB.htm (concrete PDF worked example, cross-referenced from `GetExportFileData`)
- https://help.solidworks.com/2025/english/api/sldworksapi/Save_Drawing_Sheets_as_DXF_Example_VB.htm (concrete DXF worked example)

**status:** verified

**Gotchas:**
- **The official, currently-published (2025) "Save File as PDF Example (VBA)" calls the
  `Obsolete`-tagged `SaveAs`, not `SaveAs3`.** Confirmed directly on
  `IModelDocExtension_members.html`: `SaveAs` is marked "Obsolete. Superseded by
  `SaveAs2`," which is itself marked "Obsolete. Superseded by `SaveAs3`" — yet
  SOLIDWORKS' own current example code for the exact PDF-export scenario this dossier
  documents uses the two-generations-obsolete method. This is worth flagging loudly
  for any implementer tempted to copy that example verbatim: use `SaveAs3` in new code
  (it is the non-obsolete member per this Source URL), but understand its `ExportData`
  parameter's behavior was only actually demonstrated via `SaveAs` in official sources —
  see the next Gotcha.
- **eDrawings export mechanism, concretely (2025-dated official example):**
  ```vb
  swApp.SetUserPreferenceIntegerValue swEdrawingsSaveAsSelectionOption, swEdrawingSaveAll
  swModelDocExt.SaveAs "H:\Grid.edrw", swSaveAsCurrentVersion, swSaveAsOptions_Silent, Nothing, nErrors, nWarnings
  ```
  This is on the `SaveAs3` help page's own Remarks — i.e. eDrawings export uses the same
  `SaveAs`/`SaveAs3` entry point as everything else, driven purely by the `.edrw`/
  `.eprt`/`.easm` file extension, with sheet-selection and content options controlled
  entirely through `ISldWorks::SetUserPreferenceToggle`/`SetUserPreferenceIntegerValue`
  (see the `swUserPreferenceToggle_e`/`swUserPreferenceIntegerValue_e` entries in Enums
  below for the specific eDrawings-relevant members), **not** through `ExportData`
  (`ExportData`/`IExportPdfData` is PDF-only — see `Name` and `ExportData` rows above).
  No add-in requirement is documented on any fetched page for this call to succeed — but
  exporting to `.edrw`/`.eprt`/`.easm`
  **is explicitly unsupported when running "SOLIDWORKS Connected"** (the 3DEXPERIENCE
  cloud-hosted variant), per the "System Options > Export > EDRW/EPRT/EASM" reference
  page. `swEdrawingsSaveAsSelectionOption` is flagged Obsolete on that same page as of
  2025 despite being used in this still-current example — see this dossier's intro
  discrepancy list.
- The `SaveAs` example call is `IModelDocExtension::SaveAs(Name, Version, Options,
  ExportData, Errors, Warnings)` — 6 parameters, no `AdvancedSaveAsOptions`, with
  `ExportData` in the same relative role `SaveAs3` gives it. `SaveAs3` simply inserts
  `AdvancedSaveAsOptions` before `Errors`; nothing in the fetched pages suggests
  `ExportData`'s behavior differs between the two, but this was not independently
  confirmed against a live session — test empirically before assuming parity.
- **DXF/DWG per-sheet export, concretely (2025-dated official example):** activate each
  sheet, then save once per sheet:
  ```vb
  vSheetName = swDraw.GetSheetNames
  For i = 0 To UBound(vSheetName)
      bRet = swDraw.ActivateSheet(vSheetName(i))
      bRet = swModel.SaveAs4("C:\temp\" & vSheetName(i) & ".dxf", swSaveAsCurrentVersion, swSaveAsOptions_Silent, nErrors, nWarnings)
  Next i
  ```
  This uses `IModelDoc2::SaveAs4` (not `SaveAs3`, not `ExportData`) once per activated
  sheet — the DXF filename itself, not an `ExportData`/`Which`-sheets parameter, is what
  determines which sheet's geometry lands in which file. Compare against
  `swDxfMultiSheetOption`/`swDxfMultisheet_e` in Enums below for the alternative
  single-call "all sheets to one file" / "all sheets to paper space" behaviors.
- `Options` only reliably governs **native SOLIDWORKS format** saves per `swSaveAsOptions_e`'s
  own Remarks — for PDF/DXF/DWG/eDrawings/IGES/STEP/etc., use
  `SetUserPreferenceToggle`/`SetUserPreferenceIntegerValue` instead (see below).
  `swSaveAsOptions_Silent` is the one flag consistently used across all format examples
  in this dossier to suppress interactive dialogs, regardless of target format.
- Overwrites existing files unless read-only; fires `FileSaveNotify`; strips
  configuration-specific bitmap previews except the current configuration's.

### ISldWorks::GetExportFileData

- **Interface:** ISldWorks
- **Method:** GetExportFileData
- **Minimum SW version:** SOLIDWORKS 2007 SP1, Revision Number 15.1

**Signature:**

```vb
Function GetExportFileData( _
   ByVal FileType As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FileType | Integer | n/a | Yes | File type to get an export-data interface for | `swExportDataFileType_e` |

**Returns:** `Object` — an `IExportPdfData` instance for the requested file type. As of
2025, `swExportDataFileType_e` has exactly one member (`swExportPdfData = 1`), so in
practice this always returns `IExportPdfData` — there is currently no other
`IExportXxxData` interface reachable through this method.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~GetExportFileData.html
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swExportDataFileType_e.html (confirms the single-member claim)

**status:** verified

**Gotchas:**
- Call this once per export to obtain a fresh `IExportPdfData`, then configure it with
  `SetSheets`/`ViewPdfAfterSaving`/`ExportAs3D` before passing it as `SaveAs3`'s
  `ExportData` parameter.
- The official worked example calls this as `swApp.GetExportFileData(1)` — i.e. the
  literal `1` (== `swExportPdfData`), not a named constant — confirming the enum truly
  has no other member to select between in current SOLIDWORKS versions.

### IExportPdfData::SetSheets

- **Interface:** IExportPdfData
- **Method:** SetSheets
- **Minimum SW version:** SOLIDWORKS 2007 SP1, Revision Number 15

**Signature:**

```vb
Function SetSheets( _
   ByVal Which As System.Integer, _
   ByVal Sheets As System.Object _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Which | Integer | n/a | Yes | Which drawing sheets to export to PDF | `swExportDataSheetsToExport_e` |
| Sheets | Object | n/a | Yes | Array of drawing-sheet name strings to export | |

**Returns:** `Boolean`. True if the sheets were set successfully, false if not (the page
does not enumerate specific failure causes — e.g. an unknown sheet name — treat as
unverified until confirmed against a live session).

**Prior selection required:** None via `ISelectionMgr` — called directly on the
`IExportPdfData` object returned by `GetExportFileData`.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExportPdfData~SetSheets.html
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swExportDataSheetsToExport_e.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Save_File_as_PDF_Example_VB.htm (concrete worked call, quoted below)

**status:** verified

**Gotchas — sheet-selection mechanism, concretely (for `batch_export_pack`):**
- `swExportDataSheetsToExport_e` has exactly three members:
  `swExportData_ExportAllSheets = 1`, `swExportData_ExportCurrentSheet = 2`,
  `swExportData_ExportSpecifiedSheets = 3` (see Enums below).
- The official worked example uses the `ExportSpecifiedSheets` path concretely:
  ```vb
  Dim strSheetName(4) As String
  Dim varSheetName As Variant
  strSheetName(0) = "Sheet1"
  strSheetName(1) = "Sheet2"
  strSheetName(2) = "Sheet3"
  varSheetName = strSheetName
  boolstatus = swExportPDFData.SetSheets(swExportData_ExportSpecifiedSheets, varSheetName)
  swExportPDFData.ViewPdfAfterSaving = True
  boolstatus = swModelDocExt.SaveAs(filename, 0, 0, swExportPDFData, lErrors, lWarnings)
  ```
  i.e. `Sheets` is a plain array (VBA `Variant`/COM `SAFEARRAY` of `BSTR`) of sheet
  **name** strings (matching `ISheet::GetName`/the names returned by
  `IDrawingDoc::GetSheetNames`), not sheet objects or indices.
- Whether the `Sheets` array argument is required/ignored when `Which` is
  `ExportAllSheets` (1) or `ExportCurrentSheet` (2) is **not stated** on the fetched page
  and the only worked example uses `ExportSpecifiedSheets` (3) — treat passing an empty
  array or `Nothing` for `Sheets` under those two modes as unverified; confirm
  empirically, or always populate `Sheets` defensively even when `Which` doesn't
  logically need it.
- Sheet order in the `Sheets` array is presumed to control PDF page order for a
  multi-sheet export, matching how the SOLIDWORKS UI's "Save As PDF" sheet-picker
  behaves — not independently confirmed by the fetched pages; verify empirically for
  `batch_export_pack` if page order matters.

### IExportPdfData::ViewPdfAfterSaving

- **Interface:** IExportPdfData
- **Method:** ViewPdfAfterSaving (property, not a method)
- **Minimum SW version:** SOLIDWORKS 2013 SP03, Revision Number 21.3

**Signature:**

```vb
Property ViewPdfAfterSaving As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Boolean | n/a | Yes | True to open the saved PDF after saving, false to not | |

**Returns:** `Boolean` (getter) — current setting.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExportPdfData~ViewPdfAfterSaving.html

**status:** verified

**Gotchas:**
- **Set this to `False` for any unattended/batch export** (e.g. `batch_export_pack`) —
  the default state is not documented on this page; do not assume it defaults to
  `False`. Leaving it `True` in an automation context will pop the OS PDF viewer for
  every exported file.
- Overlaps in name/purpose with the document-preference-level `swPDFViewOnSave`
  (`swUserPreferenceToggle_e`, see Enums below) — `ViewPdfAfterSaving` is scoped to this
  one `IExportPdfData` call; `swPDFViewOnSave` is the interactive-UI system option. Which
  one wins if they disagree is not stated on either page — unverified; setting both
  consistently (both `False` for batch export) sidesteps the question.

### IExportPdfData::ExportAs3D

- **Interface:** IExportPdfData
- **Method:** ExportAs3D (property, not a method)
- **Minimum SW version:** SOLIDWORKS 2008 SP1, Revision Number 16.1

**Signature:**

```vb
Property ExportAs3D As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Boolean | n/a | Yes | True to export this document to 3D PDF, false to not | |

**Returns:** `Boolean` (getter) — current setting.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExportPdfData~ExportAs3D.html

**status:** verified

**Gotchas:**
- The page's own Remarks: "Call `IModelDocExtension::SaveAs` after setting this
  property" — i.e. `ExportAs3D` must be set on the `IExportPdfData` object *before* the
  `SaveAs`/`SaveAs3` call that consumes it, same ordering requirement as `SetSheets` and
  `ViewPdfAfterSaving`.
  Interaction with multi-sheet drawing PDF export (via `SetSheets`) — e.g. whether a 3D
  PDF export can also carry multiple flat drawing sheets, or is exclusive to a single
  3D-model view — is **not stated** on the fetched page; unverified.
- `sw3DPDFAccuracy` (`swUserPreferenceIntegerValue_e`, see Enums below) is the sibling
  document-preference controlling 3D PDF tessellation accuracy once `ExportAs3D = True`.

## DXF/DWG export

### IPartDoc::ExportToDWG2

- **Interface:** IPartDoc
- **Method:** ExportToDWG2
- **Minimum SW version:** SOLIDWORKS 2014 FCS, Revision Number 22.0 (supersedes the
  obsolete `IPartDoc::IExportToDWG`/`IExportToDWG2`)

**Signature:**

```vb
Function ExportToDWG2( _
   ByVal FilePath As System.String, _
   ByVal ModelName As System.String, _
   ByVal Action As System.Integer, _
   ByVal ExportToSingleFile As System.Boolean, _
   ByVal Alignment As System.Object, _
   ByVal IsXDirFlipped As System.Boolean, _
   ByVal IsYDirFlipped As System.Boolean, _
   ByVal SheetMetalOptions As System.Integer, _
   ByVal Views As System.Object _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FilePath | String | n/a | Yes | Path and file name of the exported DXF/DWG file | |
| ModelName | String | n/a | Yes | Path and file name of the active part document | |
| Action | Integer | n/a | Yes | Export action | `swExportToDWG_e` (not separately fetched in this dossier — see Gotchas) |
| ExportToSingleFile | Boolean | n/a | Yes | True to save as one file, false to save as multiple files | |
| Alignment | Object | meters (translation) / unitless direction components | Yes | 12-double array: `[0..2]` new-origin x,y,z; `[3..5]` new-x-direction vector; `[6..8]` new-y-direction vector; `[9..11]` face/loop-selection normal vector (valid only for `swExportToDWG_ExportSelectedFacesOrLoops`) | |
| IsXDirFlipped | Boolean | n/a | Yes | True to flip the output x direction | |
| IsYDirFlipped | Boolean | n/a | Yes | True to flip the output y direction | |
| SheetMetalOptions | Integer | n/a | Yes, if `Action = swExportToDWG_ExportSheetMetal` | Bitmask of sheet-metal export options (bit table below) | |
| Views | Object | n/a | Yes, if `Action = swExportToDWG_ExportAnnotationViews` | Array of annotation-view names to export | |

`SheetMetalOptions` bitmask (bit 1 = LSB):

| Bit | Meaning when set to 1 |
| --- | --- |
| 1 | Export flat-pattern geometry |
| 2 | Include hidden edges |
| 3 | Export bend lines |
| 4 | Include sketches |
| 5 | Merge coplanar faces |
| 6 | Export library features |
| 7 | Export forming tools |
| 8–11 | Reserved (0) |
| 12 | Export bounding box |
| 13 | Export cosmetic thread |
| 14 | Export hidden sketches |

**Returns:** `Boolean`. True if the export succeeded, false if not (no further
per-cause breakdown documented on this page — cross-check against `Errors`-style output
is not available for this method, unlike `SaveAs3`).

**Prior selection required:** "You must select multi-body sheet-metal features (i.e.,
multiple flat-pattern features) before calling this method" per the page's own Remarks
— this is a genuine `ISelectionMgr` prerequisite, unlike most other records in this
dossier.

**Source URL(s):**
- https://help.solidworks.com/2025/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IPartDoc~ExportToDWG2.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (confirms no `ExportToDWG*` member exists on `IDrawingDoc`, corroborating the discrepancy noted in this dossier's intro)

**status:** verified

**Gotchas:**
- **This method exports sheet-metal flat-pattern/face/loop/annotation-view geometry
  from a part document — it is not the mechanism for exporting a drawing's sheets to
  DXF/DWG.** See this dossier's intro discrepancy list and the DXF/DWG `Gotchas` under
  `SaveAs3` above for the real drawing-sheet export mechanism
  (`SaveAs3`/`SaveAs4` + a `.dxf`/`.dwg` extension + `swDxfMultiSheetOption`).
- `Alignment = {0,0,0,0,0,0,0,0,0,0,0,0}` (12 zeros) produces the default orientation —
  equivalent to not selecting any alignment edges in the UI.
- Sheet-metal exports are automatically constrained to align the flat-pattern normal to
  the 2D sheet normal, limiting the effective degrees of freedom `Alignment` provides.
- This method supersedes `IPartDoc::IExportToDWG`/`IExportToDWG2` by (a) adding the
  bounding-box `SheetMetalOptions` bit and (b) no longer prepending the flat-pattern
  name to `FilePath` when `ExportToSingleFile = False`. `swExportToDWG_e` (the `Action`
  enum) was not independently fetched/verified in this research pass — its member names
  are referenced by this page (`swExportToDWG_ExportSheetMetal`,
  `swExportToDWG_ExportAnnotationViews`, `swExportToDW_ExportSelectedFacesOrLoops` — note
  the last one's inconsistent `ExportToDW` vs `ExportToDWG` spelling **as it literally
  appears on the fetched page**, itself worth flagging as a possible documentation typo)
  but its full enum table (including numeric values) is unverified; fetch
  `swExportToDWG_e`'s own page before writing code against `Action` values.

**Resolution (sw-jcq.2 -- `export_dxf_dwg` tool):** confirms and acts on the
discrepancy flagged above. `export_dxf_dwg` does **not** call
`IPartDoc::ExportToDWG2` -- it is the wrong interface (`IPartDoc`, not
`IDrawingDoc`), requires a pre-selected multi-body sheet-metal feature (not
generally true of an arbitrary drawing's model), and exports flat-pattern
geometry rather than a drawing sheet. Instead it uses
`IModelDocExtension::SaveAs3` (already this project's standard save/export
entry point, per `save_drawing`/`export_pdf`) with a `.dxf`/`.dwg`
`output_path`, driven by the `swDxfOutputFonts`/`swDxfMultiSheetOption`/
`swDxfVersion` members of `swUserPreferenceIntegerValue_e` documented below --
exactly the mechanism this dossier's intro and this record's Gotchas already
identify as the real one. There is no `ExportToDWG2`-shaped positional tuple
for a drawing-sheet export to match, because no such method exists on
`IDrawingDoc`.

## Export settings via user preferences

### ISldWorks::SetUserPreferenceToggle

- **Interface:** ISldWorks
- **Method:** SetUserPreferenceToggle
- **Minimum SW version:** Not stated on the fetched page — this is a long-standing core
  `ISldWorks` member (its sibling `GetUserPreferenceToggle`/`SetUserPreferenceIntegerValue`
  pages are likewise undated); treat as available across all SOLIDWORKS API versions in
  scope for this project.

**Signature:**

```vb
Sub SetUserPreferenceToggle( _
   ByVal UserPreferenceValue As System.Integer, _
   ByVal OnFlag As System.Boolean _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UserPreferenceValue | Integer | n/a | Yes | Which boolean system option to set | `swUserPreferenceToggle_e` |
| OnFlag | Boolean | n/a | Yes | True to turn the option on, false to turn it off | |

**Returns:** `Sub` — no return value.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~SetUserPreferenceToggle.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Save_Drawing_Sheets_as_DXF_Example_VB.htm (concrete DXF-mapping-dialog-suppression usage, quoted below)
- https://help.solidworks.com/2025/English/api/swconst/FileSaveAsDXFOptions.htm (maps every DXF/DWG dialog checkbox to its exact toggle constant)

**status:** verified

**Gotchas:**
- **This is an application-wide (system option) setter, not a document-level setting.**
  It persists across the SOLIDWORKS session (and for some preferences, across sessions)
  — it is equivalent to interactively changing Tools > Options > System Options. Reset
  any preference you change for one export back to its prior value afterward, or you
  will silently change the behavior of every subsequent export in the same session. The
  official DXF example demonstrates exactly this save/restore pattern:
  ```vb
  Dim bShowMap As Boolean  ' never actually read from the real setting first — see below
  swApp.SetUserPreferenceToggle swDXFDontShowMap, True
  ' ...export loop...
  swApp.SetUserPreferenceToggle swDXFDontShowMap, bShowMap   ' restores to a fresh Boolean's default (False)!
  ```
  Note the example itself never calls `GetUserPreferenceToggle(swDXFDontShowMap)` to
  capture the *real* prior value into `bShowMap` before overwriting it — `bShowMap` is
  an uninitialized `Boolean` (`False`) the whole time. This looks like a bug in
  SOLIDWORKS' own official example; don't copy this part verbatim — call
  `ISldWorks::GetUserPreferenceToggle` first if you actually need to restore the
  pre-existing value.
- **This is the mechanism to suppress the DXF/DWG layer-mapping dialog for unattended
  batch export.** `swDxfMapping` (enable layer mapping) and `swDXFDontShowMap`
  (suppress the mapping dialog popup when `swDxfMapping = True`) together control
  whether an export call will block on a modal dialog — critical for any
  `batch_export_pack`-style automation. If layer mapping is enabled and the "don't show"
  toggle is off, an unattended export can hang waiting for UI input.
- Also has a document-scoped sibling: `IModelDocExtension::SetUserPreferenceToggle` (see
  that method's own page, not separately documented in this dossier) — for
  document-property-level toggles as opposed to system-option-level ones. Which specific
  members belong to which scope is determined per-member by SOLIDWORKS' "System Options
  and Document Properties" reference, not by a rule statable here.

### ISldWorks::SetUserPreferenceIntegerValue

- **Interface:** ISldWorks
- **Method:** SetUserPreferenceIntegerValue
- **Minimum SW version:** Not stated on the fetched page (see `SetUserPreferenceToggle`
  above for the same caveat).

**Signature:**

```vb
Function SetUserPreferenceIntegerValue( _
   ByVal UserPreferenceValue As System.Integer, _
   ByVal Value As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| UserPreferenceValue | Integer | n/a | Yes | Which integer system option to set | `swUserPreferenceIntegerValue_e` |
| Value | Integer | n/a | Yes | New value for that option (often itself another enum's member, e.g. `swDxfFormat_e` for `swDxfVersion`) | Varies per `UserPreferenceValue` — see Enums below |

**Returns:** `Boolean`. True if the value was set, false if not (no further breakdown of
failure causes documented).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~SetUserPreferenceIntegerValue.html
- https://help.solidworks.com/2025/English/api/swconst/FileSaveAsDXFOptions.htm (DXF/DWG-specific value tables)
- https://help.solidworks.com/2025/english/api/sldworksapi/Save_Drawing_Sheets_as_DXF_Example_VB.htm (concrete usage)

**status:** verified

**Gotchas:**
- Same application-wide/session-persistent scope caveat as `SetUserPreferenceToggle`
  above — save and restore the prior value with `GetUserPreferenceIntegerValue` around
  any export call that changes one of these.
- **`swDxfMultiSheetOption` is the real answer to "per-sheet vs. whole-document" DXF/DWG
  export** (the behavior the source research issue expected to find on a drawing
  `ExportToDWG2` method): set it to a `swDxfMultisheet_e` member
  (`swDxfActiveSheetOnly = 0`, `swDxfSeparateSheets = 1`, `swDxfMultiSheet = 2`) before
  calling `SaveAs`/`SaveAs3`/`SaveAs4` on a multi-sheet drawing. Separately,
  `swDxfExportAllSheetsToPaperSpace` (a **toggle**, not part of this integer enum) governs
  whether multi-sheet output lands in DXF/DWG paper space. See the
  `swUserPreferenceToggle_e`/`swUserPreferenceIntegerValue_e` Enums entries below for the
  full export-relevant member lists.
- Unlike most `swconst` enums, **`swUserPreferenceIntegerValue_e`'s own enumeration page
  publishes no numeric values at all** — every member links out to "System Options and
  Document Properties" instead of showing a `Member Value` pair. A few members' valid
  values are documented elsewhere (e.g. `swDxfOutputFonts`'s `0`/`1` on the DXF Options
  page, captured in Enums below) but most are not published anywhere fetched in this
  research pass. Always pass the **named constant**, never a raw literal, when calling
  this method — the numeric values are not a stable, documented contract.

## Layers

`ILayerMgr` is obtained from a drawing document's `IModelDoc2::GetLayerManager` (or the
document-specific `IDrawingDoc` equivalent) — confirmed by the official "Determine if
Layer is Visible" worked example (`Set swLayerMgr = swModel.GetLayerManager`). Layers
are a **drawing-document-only** concept (consistent with the `IAnnotation::Layer`
Remarks already documented in [`03-annotations.md`](03-annotations.md)).

### ILayerMgr::AddLayer

- **Interface:** ILayerMgr
- **Method:** AddLayer
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function AddLayer( _
   ByVal NameIn As System.String, _
   ByVal DescIn As System.String, _
   ByVal ColorIn As System.Integer, _
   ByVal StyleIn As System.Integer, _
   ByVal WidthIn As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| NameIn | String | n/a | Yes | Layer name | |
| DescIn | String | n/a | Yes | Description for the new layer | |
| ColorIn | Integer | n/a | Yes | COLORREF value for items on this layer | |
| StyleIn | Integer | n/a | Yes | Line style for this layer | `swLineStyles_e` |
| WidthIn | Integer | n/a | Yes | Line width for this layer | `swLineWeights_e` |

**Returns:** `Integer`. `1` if the layer was created successfully. The page does not
state the failure return value (e.g. for a duplicate name) — treat as unverified; likely
`0` by analogy with `ILayerMgr::SetCurrentLayer`'s documented `0`-on-failure, but not
independently confirmed for `AddLayer`.

**Prior selection required:** None via `ISelectionMgr` — called directly on an
`ILayerMgr` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayerMgr~AddLayer.html

**status:** verified

**Gotchas:**
- `IDrawingDoc::CreateLayer2` is a parallel, older, document-level way to create a layer
  in one call — the official "Determine if Layer is Visible" example uses it instead of
  `ILayerMgr::AddLayer`:
  `swDraw.CreateLayer2(sLayerName, "Layer for part in " & sLayerName, 0, swLineCONTINUOUS, swLW_NORMAL, True, True)`
  — 7 parameters (name, description, color, style, width, plus two trailing `Boolean`s
  not present on `AddLayer`, presumably initial Visible/Frozen state — not independently
  fetched/confirmed in this research pass). Which of the two (`ILayerMgr::AddLayer` vs.
  `IDrawingDoc::CreateLayer2`) is preferred/current is not stated by either page;
  `AddLayer` is what the task's source research issue asked for and is documented as the
  primary record here.
- `ColorIn` is a raw Win32 `COLORREF` (`0x00BBGGRR`), the same convention as
  `ILayer::Color` below — not an `swColor_e`-style named constant.

### ILayerMgr::GetLayer

- **Interface:** ILayerMgr
- **Method:** GetLayer
- **Minimum SW version:** SOLIDWORKS 99, Revision Number 1999207

**Signature:**

```vb
Function GetLayer( _
   ByVal NameIn As System.String _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| NameIn | String | n/a | Yes | Layer name | |

**Returns:** `Object` — an `ILayer` for the named layer. Behavior when `NameIn` does not
match an existing layer is not stated on the fetched page (presumably `Nothing`/`null`)
— unverified.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayerMgr~GetLayer.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Determine_if_Layer_is_Visible_Example_VB.htm (concrete usage: `Set swLayer = swLayerMgr.GetLayer("Layer1")`)

**status:** verified

**Gotchas:**
- Companion accessors mentioned on this page but not separately documented here:
  `ILayerMgr::GetCurrentLayer` (returns the active layer's name) and
  `ILayerMgr::IGetLayer` (an interface-typed sibling — likely the raw-interface variant
  used internally by strongly-typed language bindings, per the `I`-prefix convention
  seen elsewhere in this API, e.g. `IExportPdfData` vs. a hypothetical `IIExportPdfData`
  — not independently confirmed).

### ILayerMgr::GetLayerList

- **Interface:** ILayerMgr
- **Method:** GetLayerList
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function GetLayerList() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | — | — | — | This method takes no parameters | |

**Returns:** `Object` — a 0-based array of strings, one per `ILayer` name in this
`ILayerMgr`.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayerMgr~GetLayerList.html

**status:** verified

**Gotchas:**
- Explicitly documented as 0-based (the page calls this out directly) — unlike some
  other SOLIDWORKS API array returns in this codebase's other dossiers where indexing
  convention had to be inferred from an example.
- Returns names only, not `ILayer` objects — call `GetLayer(name)` per element to get a
  usable `ILayer` reference for reading/writing its properties.

### ILayerMgr::SetCurrentLayer

- **Interface:** ILayerMgr
- **Method:** SetCurrentLayer
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Function SetCurrentLayer( _
   ByVal NameIn As System.String _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| NameIn | String | n/a | Yes | Name of the layer to make active | |

**Returns:** `Integer`. `1` if the active layer was changed, `0` if not (e.g. `NameIn`
does not match an existing layer — inferred from the binary success/fail phrasing, not
independently enumerated on the page).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayerMgr~SetCurrentLayer.html

**status:** verified

**Gotchas:**
- The "current"/"active" layer is where newly sketched drawing entities land by default
  — this does not itself change which layer any *existing* entity or annotation belongs
  to (that's `IAnnotation::Layer`, already documented in
  [`03-annotations.md`](03-annotations.md), or `IDrawingDoc::ChangeComponentLayer` for
  view components — see the layer-visibility worked example referenced under
  `ILayer::Visible` below).

### ILayer::Visible

- **Interface:** ILayer
- **Method:** Visible (property, not a method)
- **Minimum SW version:** SOLIDWORKS 99 SP6, datecode 1999355

**Signature:**

```vb
Property Visible As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Boolean | n/a | Yes | True to make the layer visible, false to hide it | |

**Returns:** `Boolean` (getter) — current visibility.

**Prior selection required:** None via `ISelectionMgr` — read/write directly on an
`ILayer` reference.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayer~Visible.html
- https://help.solidworks.com/2025/english/api/sldworksapi/Determine_if_Layer_is_Visible_Example_VB.htm

**status:** verified

**Gotchas:**
- **Ordering requirement, stated explicitly on the page:** setting `Visible` can change
  `ILayer::Printable`'s state as a side effect. To land both properties in the desired
  final state: (1) set `Visible`, (2) *read* `Printable` to see its resulting state, (3)
  set `Printable` again only if it isn't already what you want. Setting them in the
  wrong order, or setting `Printable` without re-checking it after a `Visible` change,
  can silently leave a layer non-printable (or printable-but-hidden, if that combination
  is even reachable — see `Printable`'s own Gotchas).
- The worked example creates a layer, reassigns a selected drawing-view component to it
  via `IDrawingDoc::ChangeComponentLayer(layerName, allViews As Boolean)` (not separately
  documented in this dossier), then reads `ILayer::Visible` back — i.e. layer visibility
  is commonly inspected right after a bulk re-layering operation to confirm the new
  layer's default visibility state.

### ILayer::Printable

- **Interface:** ILayer
- **Method:** Printable (property, not a method)
- **Minimum SW version:** SOLIDWORKS 2015 FCS, Revision Number 23.0

**Signature:**

```vb
Property Printable As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Boolean | n/a | Yes | True to print this layer when the document is printed, false to not | |

**Returns:** `Boolean` (getter) — current printable state.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayer~Printable.html

**status:** verified

**Gotchas:**
- **"It is not possible to make a layer printable if it is not visible"** — stated
  directly on the page. Setting `Printable = True` on a currently-hidden layer is
  expected to have no effect (or be reverted) until `Visible = True` is also set;
  exact runtime behavior (silently ignored vs. throws vs. no-ops) is not stated —
  unverified, confirm empirically before relying on error/no-error to detect this case.
- Same set-`Visible`-then-recheck-`Printable` ordering requirement documented redundantly
  on both this page and `ILayer::Visible`'s page — see that record's Gotchas for the
  exact 3-step sequence.
- This property is notably newer (SOLIDWORKS 2015) than the rest of `ILayer`'s surface
  (SOLIDWORKS 99) — code targeting older SOLIDWORKS versions cannot rely on it existing.

### ILayer::Color

- **Interface:** ILayer
- **Method:** Color (property, not a method)
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Property Color As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Integer | n/a | Yes | COLORREF value for this layer's line color | |

**Returns:** `Integer` (getter) — current COLORREF value.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayer~Color.html

**status:** verified

**Gotchas:**
- COLORREF is the Win32 `0x00BBGGRR` packed-integer convention (blue in the high byte,
  red in the low byte) — the reverse byte order from typical `0xRRGGBB` web/CSS colors.
  Getting this backwards silently produces a wrong-but-valid color rather than an error.

### ILayer::Style

- **Interface:** ILayer
- **Method:** Style (property, not a method)
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Property Style As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Integer | n/a | Yes | Line style for this layer | `swLineStyles_e` |

**Returns:** `Integer` (getter) — current `swLineStyles_e` value.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayer~Style.html

**status:** verified

**Gotchas:**
- Unlike `IDrawingDoc::SetLineStyle` below (which takes a `String`-typed parameter
  despite documenting an enum ref — see that record's Gotchas), `ILayer::Style` is
  correctly `Integer`-typed and consistent with `swLineStyles_e`. Don't conflate the two
  — a layer's default line style (this property) is independent from a specific
  selected edge/entity's line style override (`IDrawingDoc::SetLineStyle`); an entity's
  own override, if any, takes precedence over its layer's `Style` when actually drawn
  (consistent with how "By Layer" formatting works in most CAD tools, though this
  specific precedence claim was not independently confirmed against a fetched
  SOLIDWORKS page in this research pass — treat as a reasonable inference, not verified
  fact).

### ILayer::Width

- **Interface:** ILayer
- **Method:** Width (property, not a method)
- **Minimum SW version:** SOLIDWORKS 99, datecode 1999207

**Signature:**

```vb
Property Width As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Value (setter) | Integer | n/a | Yes | Line width for this layer | `swLineWeights_e` |

**Returns:** `Integer` (getter) — current `swLineWeights_e` value.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ILayer~Width.html

**status:** verified

**Gotchas:**
- Same by-layer-vs-per-entity precedence caveat as `ILayer::Style` above, and same
  unverified-precedence status.

## Line format (per-entity, on a drawing)

### IDrawingDoc::SetLineWidth

- **Interface:** IDrawingDoc
- **Method:** SetLineWidth
- **Minimum SW version:** Not stated on the fetched page.

**Signature:**

```vb
Sub SetLineWidth( _
   ByVal Width As System.Integer _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Width | Integer | n/a | Yes | Weight for the line | `swLineWeights_e` |

**Returns:** `Sub` — no return value.

**Prior selection required:** Yes — "Sets the line thickness for a **selected** edge or
sketch entity" per the page's own one-line summary. An edge or sketch entity must be
selected (via `ISelectionMgr`, e.g. `IModelDoc2::Extension.SelectByID2` or an interactive
pick) in the drawing before calling this method. Behavior when nothing is selected is
not stated — unverified.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~SetLineWidth.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~SetLineWidthCustom.html (sibling method, name only, confirms this family exists beyond the two requested)

**status:** verified

**Gotchas:**
- This is a **per-selected-entity override**, not a document-wide or layer-wide default
  — see this dossier's intro discrepancy note: there is no `IModelDocExtension`-level
  "set default line weight for the document" method under this name; `ILayer::Width`
  (above) is the closest document-scoped analog, applying only to entities on that
  layer that haven't been given their own override via this method.
  `IDrawingDoc::SetLineWidthCustom` (see Source URLs) exists as a sibling for
  non-standard widths but was not independently fetched/documented in this pass.
  `IDrawingDoc::GetLineFontCount2`/`GetLineFontId`/`GetLineFontInfo2`/`GetLineFontName2`
  are the corresponding read-side accessors, likewise not separately documented here.
- No `Sub`/`Function` return means no direct success/failure signal — call
  `ISelectionMgr::GetSelectedObjectCount2` before and after, or re-read the entity's
  line width, to confirm the call took effect if the calling code needs to detect
  failure.

### IDrawingDoc::SetLineStyle

- **Interface:** IDrawingDoc
- **Method:** SetLineStyle
- **Minimum SW version:** Not stated on the fetched page.

**Signature:**

```vb
Sub SetLineStyle( _
   ByVal StyleName As System.String _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| StyleName | String | n/a | Yes | Style/font for the selected edge or sketch entity | `swLineStyles_e` (see Gotchas — type mismatch) |

**Returns:** `Sub` — no return value.

**Prior selection required:** Yes — same requirement as `SetLineWidth` above: an edge or
sketch entity must be selected before calling.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~SetLineStyle.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~GetLineFontName2.html (second source, fetched specifically to resolve the type-mismatch ambiguity below)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~GetLineFontInfo2.html

**status:** unverified

**Gotchas:**
- **Type mismatch in the official documentation, called out explicitly rather than
  silently resolved:** the VB/C#/C++ syntax blocks all agree `StyleName` is a
  `System.String`, yet the Parameters section describes it as "Style or font... as
  defined in `swLineStyles_e`" — an *integer* enum (`swLineCONTINUOUS = 0`,
  `swLineHIDDEN = 1`, etc., see Enums below). A `String` parameter cannot directly carry
  an enum's integer value.
- **Second-source cross-check (per this dossier's research rule for ambiguous pages):**
  fetched the sibling read accessor `IDrawingDoc::GetLineFontName2` to try to settle
  this. Its own Remarks state plainly: **"This method can return a font name Hidden,
  Visible, etc."** — i.e. `IDrawingDoc`'s line-font surface genuinely is addressed by
  human-readable name strings (confirmed example: `"Hidden"`), not by `swLineStyles_e`'s
  numeric members or their C#/VB identifier text (`"swLineHIDDEN"`) — reading (b) from
  the original two candidate readings, not (a). This resolves *which kind* of string
  `SetLineStyle`'s `StyleName` almost certainly wants, but not the exhaustive, exact set
  of valid strings: `GetLineFontName2` returns a name per index across
  `0..IDrawingDoc::GetLineFontCount2()-1`, so the authoritative way to discover every
  valid `StyleName` value is to enumerate that count/name pair at runtime rather than
  rely on a static list — no fetched page publishes the full name set directly. Left as
  `status: unverified` because of that remaining gap, not because the string-vs-enum
  question is still open.
- `IDrawingDoc::GetLineFontInfo2` (fetched alongside `GetLineFontName2`) confirms line
  fonts are stored as repeating solid/space segment-length patterns (e.g. solid =
  `segCount=1, segLengths[]={0.5}`; dashed = `segCount=2, segLengths[]={0.25,-0.25}`,
  negative meaning "space") — supporting context for the name-based model above, not
  itself part of this record's call surface.
- Companion method `IDrawingDoc::SetLineColor` exists (seen in this method's own "See
  Also" list) but was not independently fetched/documented in this pass.

## Enums

#### swExportDataFileType_e

Consumed by `ISldWorks::GetExportFileData`'s `FileType` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swExportPdfData | 1 | The only member as of SOLIDWORKS 2025 — `GetExportFileData` currently always returns an `IExportPdfData` |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swExportDataFileType_e.html

#### swExportDataSheetsToExport_e

Consumed by `IExportPdfData::SetSheets`'s `Which` parameter.

| Value | Number | Meaning |
| --- | --- | --- |
| swExportData_ExportAllSheets | 1 | Export all drawing sheets |
| swExportData_ExportCurrentSheet | 2 | Export only the currently active sheet |
| swExportData_ExportSpecifiedSheets | 3 | Export only the sheets named in `SetSheets`'s `Sheets` array (the only mode demonstrated in the official worked example) |

No further per-member description text beyond the number is given on the page itself.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swExportDataSheetsToExport_e.html

#### swSaveAsOptions_e

Bitmask enum, consumed by `IModelDocExtension::SaveAs3`'s (and `SaveAs`/`SaveAs4`'s)
`Options` parameter. Per its own Remarks, these options apply only to **native
SOLIDWORKS file formats** — non-native exports (PDF, DXF/DWG, eDrawings, VRML, etc.) are
controlled through `SetUserPreferenceToggle`/`SetUserPreferenceIntegerValue` instead
(see below), though `swSaveAsOptions_Silent` is used across every worked example in this
dossier regardless of target format.

| Value | Number | Meaning |
| --- | --- | --- |
| swSaveAsOptions_Silent | 1 (0x1) | Suppress interactive save dialogs |
| swSaveAsOptions_Copy | 2 (0x2) | Save as a copy and continue editing the original |
| swSaveAsOptions_SaveReferenced | 4 (0x4) | Also save referenced components/external references (assemblies/drawings) |
| swSaveAsOptions_AvoidRebuildOnSave | 8 (0x8) | Avoid a rebuild on save | 
| swSaveAsOptions_UpdateInactiveViews | 16 (0x10) | Update views on inactive drawing sheets (drawings with 1+ sheets only) |
| swSaveAsOptions_OverrideSaveEmodel | 32 (0x20) | Override the "Save eDrawings data in SOLIDWORKS document" system option for this save; not valid for `IPartDoc::SaveToFile2` |
| swSaveAsOptions_IgnoreBiography | 256 (0x100) | Prune the file's revision history to just the current file name |
| swSaveAsOptions_CopyAndOpen | 512 (0x200) | Save as a copy and open the copy |
| swSaveAsOptions_IncludeVirtualSubAsmComps | 1024 (0x400) | Save regular components inside virtual subassemblies |
| swSaveAsOptions_ExportTo2DPdfFromInspection | 2048 (0x800) | Export drawing sheets from SOLIDWORKS Inspection to 2D PDF |
| swSaveAsOptions_DetachedDrawing | Obsolete | — |
| swSaveAsOptions_SaveEmodelData | Obsolete | — |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSaveAsOptions_e.html

#### swFileSaveError_e

Bitmask enum, returned via `SaveAs3`'s (and `SaveAs`/`SaveAs4`'s) `Errors` ByRef
parameter on failure. Complete member table — this is the error-decoder source of
truth for this project:

| Value | Number | Meaning |
| --- | --- | --- |
| swGenericSaveError | 1 (0x1) | Unspecified save failure |
| swReadOnlySaveError | 2 (0x2) | Target file is read-only |
| swFileNameEmpty | 4 (0x4) | File name cannot be empty |
| swFileNameContainsAtSign | 8 (0x8) | File name cannot contain `@` |
| swFileLockError | 16 (0x10) | File is locked (no further description on page) |
| swFileSaveFormatNotAvailable | 32 (0x20) | Save-as file type is not valid |
| swFileSaveAsDoNotOverwrite | 128 (0x80) | Refused to overwrite an existing file |
| swFileSaveAsInvalidFileExtension | 256 (0x100) | File extension does not match the SOLIDWORKS document type |
| swFileSaveAsNoSelection | 512 (0x200) | No bodies selected for `IPartDoc::SaveToFile2`'s selected-bodies save mode; **not** a valid failure for `IModelDocExtension::SaveAs`/`SaveAs3` |
| swFileSaveAsBadEDrawingsVersion | 1024 (0x400) | eDrawings version mismatch/incompatibility |
| swFileSaveAsNameExceedsMaxPathLength | 2048 (0x800) | File name exceeds 255 characters |
| swFileSaveAsNotSupported | 4096 (0x1000) | Save-as operation is not supported, **or** completed in a way where the output may be incomplete (e.g. SOLIDWORKS was hidden — see Gotchas) |
| swFileSaveRequiresSavingReferences | 8192 (0x2000) | Saving an assembly with renamed components requires also saving references (pair with `swSaveAsOptions_SaveReferenced`) |
| swFileSaveAsDetachedDrawingsNotSupported | 16384 (0x4000) | Detached-drawing save-as is not supported for this document |
| swFileSaveWithRebuildError | Obsolete | Superseded by `swFileSaveWarning_e` |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swFileSaveError_e.html

**Gotchas for building an error decoder from this table:**
- **The bit sequence has a gap: no member is documented at value 16 (0x40, i.e. bit 7).**
  Walking the documented values in order — 1, 2, 4, 8, 16 (0x10), 32 (0x20), *[0x40 is
  skipped]*, 128 (0x80), 256, 512, 1024, 2048, 4096, 8192, 16384 — confirms 0x40 is
  absent from the fetched page, not an extraction error on this dossier's part. A
  decoder built strictly from named bits must not silently drop unrecognized bits (this
  one or any future addition) — surface "unknown error bit 0x40 set" explicitly rather
  than ignoring it, or the decoder will quietly swallow a real failure if SOLIDWORKS
  ever sets it (undocumented today, but bitmask enums in this API do grow across
  versions — see `swSaveAsOptions_e`'s two Obsolete members above as evidence values get
  reused/retired over time).
- Per the enum page's own Remarks: **"Not all of these return codes are fatal errors. The
  return code is a bitmask of different conditions... some of which are fatal and some
  are informational or warnings."** A decoder should not treat every set bit as
  necessarily fatal — cross-reference against the `SaveAs3` return value (`False`) as the
  actual fail/succeed signal, and treat individual `Errors` bits as diagnostic detail.
- `swFileSaveAsNotSupported`'s second bullet is explicit troubleshooting guidance from
  SOLIDWORKS itself: if this bit is set and persists after setting
  `ISldWorks::Visible = True` and retrying, SOLIDWORKS' own docs say to contact
  `apisupport@3ds.com` — i.e. this specific bit can indicate a
  hidden-application/automation-specific failure mode worth special-casing in a batch
  export tool's error messages.
- `swFileSaveAsNoSelection` is explicitly scoped to `IPartDoc::SaveToFile2`, not
  `SaveAs`/`SaveAs3` — a decoder shared across both call sites should annotate this bit
  as context-dependent rather than always meaning the same thing.

#### swDxfMultisheet_e

Consumed via `swUserPreferenceIntegerValue_e.swDxfMultiSheetOption` (see below) — this
is the real "per-sheet vs. whole-document" DXF/DWG export switch, set before calling
`SaveAs`/`SaveAs3`/`SaveAs4` on a multi-sheet drawing.

| Value | Number | Meaning |
| --- | --- | --- |
| swDxfActiveSheetOnly | 0 | Export only the currently active sheet |
| swDxfSeparateSheets | 1 | Export each sheet to its own file |
| swDxfMultiSheet | 2 | Export all sheets combined into one file |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDxfMultisheet_e.html

Note: this is distinct from `swDxfExportAllSheetsToPaperSpace`, a separate **toggle**
(`swUserPreferenceToggle_e`, below) controlling paper-space vs. model-space placement of
multi-sheet output — the two settings compose (sheet-splitting behavior × paper-space
placement), not alternatives to each other.

#### swLineWeights_e

"Line weights used in layers." Consumed by `ILayerMgr::AddLayer`'s `WidthIn`,
`ILayer::Width`, and `IDrawingDoc::SetLineWidth`'s `Width` parameter/property.

| Value | Number | Meaning |
| --- | --- | --- |
| swLW_NONE | -1 | No line weight |
| swLW_THIN | 0 | Thinnest |
| swLW_NORMAL | 1 | Normal/default |
| swLW_THICK | 2 | Thick |
| swLW_THICK2 | 3 | Thicker |
| swLW_THICK3 | 4 | Thicker still |
| swLW_THICK4 | 5 | Thicker still |
| swLW_THICK5 | 6 | Thicker still |
| swLW_THICK6 | 7 | Thickest of the named `THICK` steps |
| swLW_NUMBER | 8 | Numbered/indexed weight (no further page description) |
| swLW_LAYER | 9 | Use the entity's layer's weight (no further page description) |
| swLW_CUSTOM | 10 | Custom weight (no further page description) |

No further per-member description text beyond the number is given on the page itself
for most members (noted individually above where the page truly says nothing more).

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swLineWeights_e.html

#### swLineStyles_e

"Line styles used in drawings." Consumed by `ILayerMgr::AddLayer`'s `StyleIn`,
`ILayer::Style`, and (per its own Parameters text, despite the `String`-typed signature
— see that record's Gotchas) `IDrawingDoc::SetLineStyle`'s `StyleName`.

| Value | Number | Meaning |
| --- | --- | --- |
| swLineCONTINUOUS | 0 | Solid |
| swLineHIDDEN | 1 | Dashed |
| swLinePHANTOM | 2 | Phantom (no further page description) |
| swLineCHAIN | 3 | Chain (no further page description) |
| swLineCENTER | 4 | Center (no further page description) |
| swLineSTITCH | 5 | Stitch (no further page description) |
| swLineCHAINTHICK | 6 | Thin/Thick chain |
| swLineDEFAULT | 7 | Document default style (no further page description) |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swLineStyles_e.html

#### swUserPreferenceToggle_e (export-relevant members)

This enum has hundreds of members covering every SOLIDWORKS system option; **its own
enumeration page publishes no numeric values** — every member links out to "System
Options and Document Properties" instead. The export-relevant subset below, curated for
this dossier's scope (PDF/DXF/DWG/eDrawings), is cross-referenced against the "File >
Save As > Save as type > Dxf or Dwg > Options" and "System Options > Export >
EDRW/EPRT/EASM" reference pages, which name these exact members even though they don't
give numeric values either. **Always pass these as named constants — no numeric value
for any member in this table was found published anywhere in this research pass.**

| Member | Meaning |
| --- | --- |
| swDxfMapping | Enable custom SOLIDWORKS-to-DXF/DWG layer mapping |
| swDXFDontShowMap | Suppress the layer-mapping dialog popup on each save when `swDxfMapping = True` — critical for unattended batch export (see `SetUserPreferenceToggle`'s Gotchas) |
| swDxfUseSolidworksLayers | Use SOLIDWORKS' own layer names directly instead of a custom map |
| swDxfExportAllSheetsToPaperSpace | Export all sheets of a multi-sheet drawing to DXF/DWG paper space |
| swDxfAllSheetsToPaperSpace | A second, similarly-named member appears in the raw enum listing distinct from `swDxfExportAllSheetsToPaperSpace` above; only the latter is confirmed bound to the "Export all drawing sheets to paper space" dialog checkbox by the DXF Options reference page. This one's exact purpose/scope is unverified — possibly a legacy duplicate, possibly import-side rather than export-side. Do not assume it's interchangeable with `swDxfExportAllSheetsToPaperSpace` without confirming empirically |
| swDXFExportHiddenLayersOn | Export entities on hidden layers |
| swDXFExportHiddenLayersWarnIsOn | Show/dismiss the "hidden layers" warning dialog on export |
| swDxfEndPointMerge | Merge line endpoints on export (avoids gaps between model edges; increases export time; off by default per the DXF Options page) |
| swDXFHighQualityExport | Higher-quality DWG export (valid only when `swDxfEndPointMerge = True`; increases export time) |
| swDxfExportSplinesAsSplines | True = export splines as splines; False = export as polylines |
| swDxfExportViewAsBlock | Export view geometry as DXF/DWG blocks |
| sw3DPDFCompressLossyTessellation | Compress 3D PDF tessellation data lossily |
| swPDFExportHighQuality | Higher-quality PDF export |
| swPDFExportEmbedFonts | Embed fonts in the exported PDF |
| swPDFExportInColor | Export PDF in color (vs. black & white) |
| swPDFExportPrintHeaderFooter | Include print header/footer in the exported PDF |
| swPDFExportIncludeDrawingsPaperColor | Include the drawing sheet's paper color in the PDF |
| swPDFExportIncludeLayersNotToPrint | Include layers marked "not to print" in the PDF |
| swPDFExportShadedEdgesHighQuality | Higher-quality shaded-edge rendering in the PDF |
| swPDFExportUseCurrentPrintLineWeights | Use the current print line weights (rather than the layer/entity's own) for the PDF's line rendering |
| swPdfIncludeBookmarks | Include PDF bookmarks (e.g. per-sheet) |
| swPDFViewOnSave | Open the PDF after saving — the system-option-level counterpart to `IExportPdfData::ViewPdfAfterSaving`'s call-level setting (see that record's Gotchas for the unresolved precedence question) |
| swEDrawingsOkayToMeasure | Allow measurement in the exported eDrawings file |
| swEDrawingsExportSTLOkay | Allow the eDrawings Viewer recipient to save an STL from the file |
| swEDrawingsSaveBOM | Save table features (e.g. BOM) into the eDrawings file |
| swEDrawingsSaveShadedDataInDrawings | Save shaded data from a SOLIDWORKS drawing into the published eDrawings file (drawings only) |
| swEDrawingsIncludeLayersNotToPrint | Include layers marked "not to print" in the eDrawings file |
| swEDrawingsSaveAnimationOkay | Save motion studies into the eDrawings file |
| swEDrawingsSaveAnimationToAllConfigs | True = save each motion study across every configuration; False = save only in the configuration it was last calculated in |
| swEDrawingsSaveAnimationRecalculate | Recalculate an out-of-date motion study before saving (valid only when `swEDrawingsSaveAnimationToAllConfigs = False`) |
| swSaveFileProperties | Save custom file properties into the exported eDrawings file |
| swSaveFilePropertiesForEachComp | Save file properties per-component (assemblies only; valid only when `swSaveFileProperties = True`) |

Sources:
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swUserPreferenceToggle_e.html (member name list; confirms no numeric values published)
- https://help.solidworks.com/2025/English/api/swconst/FileSaveAsDXFOptions.htm (DXF/DWG members, dialog bindings)
- https://help.solidworks.com/2025/english/api/swconst/FileSaveAseDrawingsOptions.htm (eDrawings members, dialog bindings; also the source of the `swEdrawingsSaveAsSelectionOption`-is-Obsolete finding noted in this dossier's intro)

**Numeric values for `export_pdf`'s `high_quality`/`keep_invisible_layers` params (sw-jcq.1):**
- `swPDFExportHighQuality = 325 (0x145)`, sourced from a third-party compiled
  `SwConst_TLB.pas` transcription
  (https://github.com/pisfu/API/blob/master/LabRabKompas/Sample2/SwConst_TLB.pas,
  same class of source `constants_drawing.py::SwUserPreferenceToggle`'s existing
  `swAutomaticScaling3ViewDrawings = 86` already relies on) — that same file
  independently transcribes `swAutomaticScaling3ViewDrawings` as `$00000056` = 86,
  matching this project's already-trusted value exactly, which is the corroboration
  used to accept `swPDFExportHighQuality`'s value from the same file. Neighboring
  members in that file (`swPDFExportInColor = $143`, `swPDFExportEmbedFonts = $144`,
  `swPDFExportHighQuality = $145`, `swPDFExportPrintHeaderFooter = $146`,
  `swPDFExportUseCurrentPrintLineWeights = $147`) form a contiguous run, consistent
  with a real, ordered enum block rather than a transcription error.
- `swPDFExportIncludeLayersNotToPrint` has **no numeric value published or found
  anywhere** in this research pass (absent from the same third-party TLB file, which
  predates this member — likely added in a newer SOLIDWORKS version than that file's
  source). It is also semantically distinct from "invisible" — it governs layers
  marked **not to print** (`ILayer::Printable = False`), not layers marked **hidden**
  (`ILayer::Visible = False`); `export_pdf`'s `keep_invisible_layers` parameter is
  about the latter. For both reasons (no numeric value, wrong semantics),
  `export_pdf` does not use this preference at all — it implements
  `keep_invisible_layers` by temporarily flipping each hidden layer's `ILayer::Visible`
  to `True` for the duration of the export via `ILayerMgr::GetLayerList`/`GetLayer`
  (both fully documented above), then restoring each layer's prior value afterward.
  This uses only numerically-unambiguous, already-verified API surface.

**Numeric values for `export_dxf_dwg`'s layer-mapping toggles (sw-jcq.2):**
`swDxfMapping = 8 (0x8)`, `swDXFDontShowMap = 21 (0x15)`, and
`swDxfUseSolidworksLayers = 305 (0x131)` (name referenced but not currently
consumed by any tool), sourced from the same third-party `SwConst_TLB.pas`
transcription used above for `swPDFExportHighQuality`
(https://github.com/pisfu/API/blob/master/LabRabKompas/Sample2/SwConst_TLB.pas).
This pass's corroboration is stronger than that one's: the file reproduces
*both* of this project's already-trusted values from the same enum block
family -- `swAutomaticScaling3ViewDrawings = 86` and
`swPDFExportHighQuality = 0x145` -- exactly, inside a contiguous, sequentially
-numbered `swUserPreferenceToggle_e` block (`swDxfMapping` at `$00000008`
sits between `swDisplayTemporaryAxes = $00000007` and
`swSketchAutomaticRelations = $00000009`, consistent with a real ordered
enum rather than a transcription error). Searched for in the same file but
**not found** (absent, not guessed): `swDxfExportAllSheetsToPaperSpace` and
`swDXFExportHiddenLayersOn` -- both likely added in a newer SOLIDWORKS
version than this file's source. Neither is used by `export_dxf_dwg` for
that reason.

#### swUserPreferenceIntegerValue_e (export-relevant members)

Same "no published numeric values on the enum's own page" situation as
`swUserPreferenceToggle_e` above — this curated subset is cross-referenced against the
same two dialog-options reference pages.

| Member | Meaning | Enum ref (for `Value`) |
| --- | --- | --- |
| swDxfVersion | DXF/DWG output format version | `swDxfFormat_e` — fully fetched and verified: `swDxfFormat_R12`=0, `R13`=1, `R14`=2, `R2000`=3, `R2004`=4, `R2007`=5, `R2010`=6, `R2013`=7, `R2018`=8 |
| swDxfOutputFonts | Font handling on DXF/DWG export | Not its own enum (see this dossier's intro) — documented values: `0` = AutoCAD STANDARD font only, `1` = TrueType |
| swDxfOutputLineStyles | Line-style handling on DXF/DWG export | Documented values: `0` = AutoCAD standard styles, `1` = SOLIDWORKS custom styles |
| swDxfOutputNoScale | Force 1:1 scale output (drawings only; no separate sheet-scale-vs-view-scale distinction or scale-factor option available via API per the DXF Options page) | Documented values: `0` = not enabled, `1` = 1:1 scale |
| swDxfMappingFileIndex | Index into the `swDxfMappingFiles` string-list preference selecting which saved custom map file to use for `swDxfMapping` | Integer index, `-1` observed as a "no file yet" sentinel in the official code snippet (see Gotchas) |
| swDxfMultiSheetOption | Per-sheet vs. whole-document DXF/DWG export mode — see this dossier's intro and `SetUserPreferenceIntegerValue`'s Gotchas | `swDxfMultisheet_e` (fully documented above) |
| swEdrawingsSaveAsSelectionOption | Which sheets/content to include in an eDrawings export | **Marked Obsolete** on the current EDRW/EPRT/EASM options page as of 2025, yet still used in `SaveAs3`'s own current Remarks example (`swEdrawingSaveAll`) — see this dossier's intro discrepancy note |
| sw3DPDFAccuracy | Tessellation accuracy for 3D PDF export (pairs with `IExportPdfData::ExportAs3D = True`) | Not independently fetched in this pass |

**Gotchas:**
- Official code snippet for using `swDxfMappingFileIndex` alongside the string-list
  `swDxfMappingFiles` preference (not itself in this dossier's method-record scope, but
  needed to actually drive a custom layer-mapping file end-to-end):
  ```vb
  swApp.SetUserPreferenceStringListValue swUserPreferenceStringListValue_e.swDxfMappingFiles, mapFilePath
  index = swApp.GetUserPreferenceIntegerValue(swUserPreferenceIntegerValue_e.swDxfMappingFileIndex)
  If (index = -1) Then
      swApp.SetUserPreferenceIntegerValue swUserPreferenceIntegerValue_e.swDxfMappingFileIndex, 0
  End If
  ```
  I.e. the map-file **index** must be explicitly initialized to `0` the first time a map
  file is added (a fresh/empty list apparently reports index `-1`) — this is not
  something `SetUserPreferenceStringListValue` handles automatically.

**Numeric values for `export_dxf_dwg`'s font/multisheet/version/mapping preferences
(sw-jcq.2):** same `SwConst_TLB.pas` source and corroboration argument as this
dossier's `swUserPreferenceToggle_e` numeric-values note above (same file,
same contiguous-ordered-block evidence, same already-trusted cross-check
values). The `swUserPreferenceIntegerValue_e` block in that file is
internally consistent with the two numeric sub-values this dossier already
had independent, official confirmation for --
`swDxfVersion = 0`/`swDxfOutputFonts = 1` sit at the very start of the block
(`$00000000`/`$00000001`), and `swDxfOutputLineStyles = 0x87`/
`swDxfOutputNoScale = 0x88` appear later in the same block -- both pairs
adjacent, matching the DXF Options reference page's member ordering used
elsewhere in this dossier.

| Member | Value | Hex |
| --- | --- | --- |
| `swDxfVersion` | 0 | `0x0` |
| `swDxfOutputFonts` | 1 | `0x1` |
| `swDxfMappingFileIndex` | 2 | `0x2` |
| `swDxfOutputLineStyles` | 135 | `0x87` |
| `swDxfOutputNoScale` | 136 | `0x88` |
| `swEdrawingsSaveAsSelectionOption` | 237 | `0xED` |
| `swDxfMultiSheetOption` | 253 | `0xFD` |

Sources:
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swUserPreferenceIntegerValue_e.html (member name list; confirms no numeric values published)
- https://help.solidworks.com/2025/English/api/swconst/FileSaveAsDXFOptions.htm (DXF/DWG members, dialog bindings, and the `swDxfOutputFonts`/`swDxfOutputLineStyles`/`swDxfOutputNoScale` numeric values)
- https://help.solidworks.com/2025/english/api/swconst/FileSaveAseDrawingsOptions.htm (eDrawings members)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDxfFormat_e.html (full `swDxfVersion` value table)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDxfMultisheet_e.html
- https://github.com/pisfu/API/blob/master/LabRabKompas/Sample2/SwConst_TLB.pas (third-party numeric-value transcription; see corroboration note above)

#### swUserPreferenceStringListValue_e (export-relevant members)

Not independently fetched from `help.solidworks.com` in this research pass
(no dedicated enumeration page URL was located); the one member this dossier
needs is referenced by name in the official `swDxfMappingFileIndex` worked
example above (`SetUserPreferenceStringListValue
swUserPreferenceStringListValue_e.swDxfMappingFiles, mapFilePath`). Its
numeric value comes from the same `SwConst_TLB.pas` source as the tables
above.

| Member | Value | Meaning |
| --- | --- | --- |
| `swDxfMappingFiles` | 0 | List of known DXF/DWG layer-mapping file paths, selected by index via `swDxfMappingFileIndex` |

**Gotcha:** the official worked example's call
(`SetUserPreferenceStringListValue swDxfMappingFiles, mapFilePath`) passes
what reads as a single `String` in VBA, but the method name and this
dossier's own `swSaveFileProperties`-style naming convention both imply a
`String()` array (`SAFEARRAY` of `BSTR`) is the real parameter shape --
VBA's loose typing can make a scalar argument look interchangeable with a
one-element array at a call site without actually being one. Not
independently confirmed against a live session; `export_dxf_dwg` passes a
one-element list (`[map_file]`), consistent with how every other
array-shaped COM parameter in this codebase (e.g. `IExportPdfData::SetSheets`)
is called, rather than a bare string.

**status:** unverified (member name/value corroborated as above; the setter's
exact parameter shape is not)

#### swEdrawingSaveAsOption_e

Consumed via `swUserPreferenceIntegerValue_e.swEdrawingsSaveAsSelectionOption`
(above) -- which sheets/content an eDrawings export includes. Not
independently fetched from `help.solidworks.com` in this research pass (no
dedicated enumeration page URL was located); referenced by name in
`SaveAs3`'s own Remarks worked example (`swEdrawingSaveAll`, quoted in this
dossier's intro). Numeric values from the same `SwConst_TLB.pas` source as
the tables above, in their own contiguous block (`swEdrawingSaveActive = 1`,
`swEdrawingSaveAll = 2`, `swEdrawingSaveSelected = 3` -- sequential, again
consistent with a real ordered enum).

| Member | Value | Meaning |
| --- | --- | --- |
| `swEdrawingSaveActive` | 1 | Save only the active sheet/configuration |
| `swEdrawingSaveAll` | 2 | Save all sheets/configurations (used by `SaveAs3`'s own official example) |
| `swEdrawingSaveSelected` | 3 | Save only the currently selected entities (`ISelectionMgr`) -- **not** a "named sheet list" mode; `export_edrawings` therefore only exposes `"all"`/`"current"`, not an explicit sheet-name list |

**status:** unverified (same caveat as `swUserPreferenceStringListValue_e` above)
