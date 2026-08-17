---
interface: Multiple (ISldWorks, IModelDoc2, IModelDocExtension, IDrawingDoc, ISheet, ICustomPropertyManager)
min_methods: 17
status: complete
---

# Documents, sheets, and custom properties

Covers the document/session lifecycle (`ISldWorks`), model save/rebuild (`IModelDoc2`,
`IModelDocExtension`), drawing sheet management (`IDrawingDoc`), and custom properties
(`ICustomPropertyManager`, `IModelDocExtension::CustomPropertyManager`). This is the
dossier the document/session and sheet-management tools are built from.

Two requested names from the source research issue turned out not to exist in the
`swconst`/`sldworksapi` namespaces as spelled:

- `ISldWorks::ActiveDoc2` does not resolve — the real member is `IActiveDoc2` (see its
  record below).
- `swDwgProjectionType_e` does not exist — the real enum is `swDrawingProjectionType_e`
  (see the Enums section below).

`IDrawingDoc::DeleteSheet` also does not exist as a direct API method — confirmed
against the `IDrawingDoc` member index, not just a missing page. Its record below
documents the real selection-based workaround instead of inventing a signature.

## Session & document lifecycle

### ISldWorks::NewDocument

- **Interface:** ISldWorks
- **Method:** NewDocument
- **Minimum SW version:** SOLIDWORKS 2000 FCS (Revision Number 8.0)

**Signature:**

```vb
Function NewDocument( _
   ByVal TemplateName As System.String, _
   ByVal PaperSize As System.Integer, _
   ByVal Width As System.Double, _
   ByVal Height As System.Double _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| TemplateName | String | n/a | Yes | Fully qualified path and name of the template file to use for creating the new document | |
| PaperSize | Integer | n/a | Yes | Size of paper/sheet for the new document | `swDwgPaperSizes_e` |
| Width | Double | meters | Only when PaperSize = swDwgPapersUserDefined | Custom sheet width; ignored for non-drawing templates and for standard (non-user-defined) paper sizes | |
| Height | Double | meters | Only when PaperSize = swDwgPapersUserDefined | Custom sheet height; ignored for non-drawing templates and for standard (non-user-defined) paper sizes | |

**Returns:** `Object`. The newly created document (cast to `PartDoc`, `AssemblyDoc`, or `DrawingDoc`/`ModelDoc2` as appropriate), or `NULL` if the operation fails (e.g., invalid or missing template path).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~NewDocument.html

**status:** verified

**Gotchas:**
- `Width`/`Height` are meaningful only when `PaperSize` is `swDwgPapersUserDefined` (drawing templates); for part/assembly templates and standard drawing paper sizes these two arguments are ignored, but must still be supplied (pass 0).
- The return type is a generic `Object`/`IDispatch`, not a typed `ModelDoc2` — callers must QueryInterface/cast to the correct doc-type interface.
- To discover the default template path (rather than hardcoding one), use `ISldWorks::GetUserPreferenceStringValue` per the official Remarks section.
- A related, newer overload `ISldWorks::INewDocument2` exists (listed under See Also) — check its signature separately if targeting it instead.

### ISldWorks::OpenDoc6

- **Interface:** ISldWorks
- **Method:** OpenDoc6
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function OpenDoc6( _
   ByVal FileName As System.String, _
   ByVal Type As System.Integer, _
   ByVal Options As System.Integer, _
   ByVal Configuration As System.String, _
   ByRef Errors As System.Integer, _
   ByRef Warnings As System.Integer _
) As ModelDoc2
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FileName | String | n/a | Yes | Document name, or full path if the file is not in the current working directory, including file extension | |
| Type | Integer | n/a | Yes | Document type to open | `swDocumentTypes_e` |
| Options | Integer | n/a | Yes | Bitmask controlling how the document is opened (e.g., silent, read-only, large-design-review) | `swOpenDocOptions_e` |
| Configuration | String | n/a | No | Configuration to open the model in (parts/assemblies only, not drawings); if empty or not found, the last-used configuration is used | |
| Errors | Integer (ByRef/out) | n/a | Yes (output) | Load errors/status from the open operation | `swFileLoadError_e` |
| Warnings | Integer (ByRef/out) | n/a | Yes (output) | Load warnings/extra info from the open operation | `swFileLoadWarning_e` |

**Returns:** `ModelDoc2`. The newly loaded model document, or `NULL` if the document failed to open. Note: even on a successful assembly load, `Errors` can still contain `swFileLoadError_e.swFileNotFoundError` if a referenced component could not be located.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~OpenDoc6.html
- https://www.codestack.net/solidworks-api/application/documents/bring-document-foreground/ (cross-check of parameter order via worked VBA example)

**status:** verified

**Gotchas:**
- `Errors` and `Warnings` are `ByRef`/`out` integer parameters — in VB/VBA you must pass declared variables (not literals); in C# they are `out` params.
- `OpenDoc6` does **not** activate/display the document if it's already loaded in memory as part of an assembly or drawing — `ISldWorks::ActiveDoc`/`IActiveDoc2` will not return it in that case. Call `ActivateDoc2` or `IActivateDoc3` afterward to bring it to the foreground.
- Superseded by `ISldWorks::OpenDoc7` (SOLIDWORKS 2008+), which adds display-state control, uses `IDocumentSpecification` for input, and (as of SOLIDWORKS 2020 SP03.1 / SOLIDWORKS Connected on the 3DEXPERIENCE platform) is required instead of `OpenDoc6`.
- As of SOLIDWORKS 2012 SP5, `OpenDoc6` no longer throws a `swFileLoadError_e.swFutureVersion` error for future-version files — use `IModelDocExtension::IsFutureVersion` to detect that case instead.
- Calling `OpenDoc6` does **not** change the process's current working directory the way an interactive File Open does; this can change which referenced files get resolved. Use `ISldWorks::SetCurrentWorkingDirectory` to mimic interactive behavior if references matter.
- To open foreign formats (IGES, STEP, etc.) use `ISldWorks::LoadFile4` instead — `OpenDoc6` is for native SOLIDWORKS documents.

### ISldWorks::ActivateDoc3

- **Interface:** ISldWorks
- **Method:** ActivateDoc3
- **Minimum SW version:** SOLIDWORKS 2012 FCS (Revision Number 20.0)

**Signature:**

```vb
Function ActivateDoc3( _
   ByVal Name As System.String, _
   ByVal UseUserPreferences As System.Boolean, _
   ByVal Option As System.Integer, _
   ByRef Errors As System.Integer _
) As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name of the already-loaded document to activate; include the file extension to disambiguate same-named files of different document types | |
| UseUserPreferences | Boolean | n/a | Yes | `True` to rebuild per the `swRebuildOnActivation` system option; `False` to rebuild per `Option` instead | |
| Option | Integer | n/a | Yes | Rebuild-on-activation behavior (ignored if `UseUserPreferences` is `True`) | `swRebuildOnActivation_e` |
| Errors | Integer (ByRef/out) | n/a | Yes (output) | Status of the activate operation; `0` if no errors or warnings | `swActivateDocError_e` |

**Returns:** `Object`. The activated model document (brought to the foreground of SOLIDWORKS).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~ActivateDoc3.html
- https://www.codestack.net/solidworks-api/application/documents/bring-document-foreground/ (cross-check of parameter order via worked VBA example: `swApp.ActivateDoc3 swModel.GetTitle(), False, swRebuildOnActivation_e.swDontRebuildActiveDoc, 0`)

**status:** verified

**Gotchas:**
- If `Name` omits the file extension, SOLIDWORKS resolves the document by filename alone, which is ambiguous when two open documents share a base name but differ in type (e.g., `12345.sldprt` vs `12345.sldasm`). Always pass the extension, or verify the type afterward with `IModelDoc2::GetType`.
- If `Option` is `swRebuildOnActivation_e.swUserDecision`, SOLIDWORKS pops a modal dialog asking whether to rebuild — this is a dialog-popping risk for unattended/automated macros and should be avoided in favor of `swDontRebuildActiveDoc` or `swRebuildActiveDoc`.
- `UseUserPreferences = True` silently overrides whatever is passed in `Option`.
- A same-named `IActivateDoc3` variant and a legacy `ActiveDoc`/`IActiveDoc2` read-only property also appear in "See Also" — don't confuse the activation *method* with the active-document *property*.
- `Errors` returns `swActivateDocError_e.swDocNeedsRebuildWarning` (not a hard failure) when a rebuild was skipped due to `swDontRebuildActiveDoc`; the document can then be rebuilt manually via `IModelDoc2::EditRebuild3`.

### ISldWorks::IActiveDoc2 (requested as ActiveDoc2)

- **Interface:** ISldWorks
- **Method:** IActiveDoc2 (property)
- **Minimum SW version:** Not stated on the fetched 2025 help page — no "Availability" section is present for this member (see Gotchas).

**Signature:**

```vb
ReadOnly Property IActiveDoc2 As ModelDoc2
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none — read-only property, no input parameters) | | | | | |

**Returns:** `ModelDoc2`. The currently active document, or `null`/`Nothing` if no document is active.

**Prior selection required:** None. Note the returned document is not necessarily the document currently being *edited*: e.g., during in-context editing of an assembly component, this property returns the assembly (the active document), not the component being edited (the edit target). Use `IAssemblyDoc::GetEditTarget`/`IGetEditTarget2` to get the edit target.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~IActiveDoc2.html

**status:** verified

**Gotchas:**
- The requested name `ISldWorks::ActiveDoc2` does **not** resolve at the expected URL pattern (`...ISldWorks~ActiveDoc2.html` 404s). The actual COM/.NET member name — and the correct help-page slug — is **`IActiveDoc2`** (the "I"-prefixed variant is the API's naming convention for a newer/typed revision of an existing member; the untyped legacy sibling is `ISldWorks::ActiveDoc`, which returns an `Object` rather than a `ModelDoc2`). Confirmed by cross-search: multiple `help.solidworks.com/<year>/.../ISldWorks~IActiveDoc2.html` results across versions (2016–2023), none for a bare `ActiveDoc2`.
- No "Availability"/Revision-Number section is present on the help page for this member (also true for `ISldWorks::CloseDoc`, below) — this appears to predate the Availability-tagging convention SolidWorks began applying to newer API pages (documented members from SW2000/2001-era onward reliably carry it; this one and `CloseDoc` do not). Do not infer a version; treat as unspecified rather than guessing.
- A document opened via `OpenDoc6`/`OpenDoc7` but not yet activated will **not** be returned by this property — it only reflects the document currently activated/foregrounded (see `ActivateDoc3`).

### ISldWorks::CloseDoc

- **Interface:** ISldWorks
- **Method:** CloseDoc
- **Minimum SW version:** Not stated on the fetched 2025 help page — no "Availability" section is present for this member (see Gotchas).

**Signature:**

```vb
Sub CloseDoc( _
   ByVal Name As System.String _
)
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name of the document to close (see Gotchas for special values) | |

**Returns:** None (`Sub` — no return value). Failure is silent: if `Name` refers to a document that is not currently open, the call is a no-op.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~CloseDoc.html

**status:** verified

**Gotchas:**
- `Name = ""` (empty string) closes the **active** document, without saving.
- If the named document is in a dirty (modified/unsaved) state, `CloseDoc` closes it **without saving** — there is no confirmation prompt and no save-first option; callers must explicitly save beforehand (e.g., `IModelDoc2::Save3`) if changes should be preserved.
- If `Name` refers to a document that is not open, this method silently does nothing (no error is raised).
- This method also closes any non-active *hidden* documents.
- If the document being closed is the only document open in a background SOLIDWORKS session (`ISldWorks::UserControl = False`), closing it (via `CloseDoc` or `QuitDoc`) terminates the entire SOLIDWORKS session/process. Set `UserControl = True` to keep the session alive/visible instead.
- No "Availability"/Revision-Number metadata is present on the help page (also true of `IActiveDoc2`, above); this is consistent with `CloseDoc` being one of the oldest, foundational `ISldWorks` members, predating the Availability-tagging convention used on newer pages. Treat the minimum version as unspecified rather than guessed.

## Document save & rebuild

### IModelDoc2::GetType

- **Interface:** IModelDoc2
- **Method:** GetType
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function GetType() As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | This method takes no parameters | |

**Returns:** `Integer`. Type of this document, as defined in `swDocumentTypes_e` (n/a — not a length or angle; it is a document-type code).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~GetType.html

**status:** verified

**Gotchas:**
- Not stated on the help page, but a real .NET interop trap: `GetType` is also the name of the method every `System.Object` inherits for CLR reflection (`obj.GetType()` returns a `System.Type`). In statically-typed .NET languages the compiler resolves `IModelDoc2.GetType()` correctly via the interop interface, but late-bound/reflection-heavy code (or IntelliSense) can be confused by the name collision — worth flagging to consumers of a typed wrapper around this call.
- The return value is a raw `Integer` that must be interpreted against `swDocumentTypes_e` (e.g. `swDocPART`, `swDocASSEMBLY`, `swDocDRAWING`) — see the Enums section below.

### IModelDoc2::Save3

- **Interface:** IModelDoc2
- **Method:** Save3
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function Save3( _
   ByVal Options As System.Integer, _
   ByRef Errors As System.Integer, _
   ByRef Warnings As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Options | Integer (ByVal) | n/a | Yes | Mode in which to save the document | `swSaveAsOptions_e` |
| Errors | Integer (ByRef, out) | n/a | Yes (pass a variable; pass `Nothing`/`null` to suppress) | Errors that caused the save to fail, returned as a bitwise OR of error codes | `swFileSaveError_e` |
| Warnings | Integer (ByRef, out) | n/a | Yes (pass a variable; pass `Nothing`/`null` to suppress) | Warnings or extra information generated during the save, returned as a bitwise OR of warning codes | `swFileSaveWarning_e` |

**Returns:** `Boolean`. True if the save was successful (in which case `Errors` is 0); false if not (in which case `Errors` contains a bitwise OR of the `swFileSaveError_e` codes that caused the failure). `Warnings` may be non-zero even on a successful save.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~Save3.html

**status:** verified

**Gotchas:**
- `Save3` is the "quick save to the existing filename" path: it saves the current document using its current name, location, and format, and cannot rename/relocate the file or change its format/version. The help page's own Remarks say: *"See IModelDocExtension::SaveAs if this is new document, this document is to be saved to a file with a new name, or this document is to be saved to a version of a particular format."* The same division of labor applies to `SaveAs3` (below), the modern replacement for that "save as" path — its own Remarks explicitly state *"Use IModelDoc2::Save3 to save a file using its current name."*
- `Errors` and `Warnings` are `ByRef` (COM out-param) integer bitmasks, decoded against `swFileSaveError_e` / `swFileSaveWarning_e` respectively (see Enums section). Pass `Nothing`/`null` for either if you don't need that information back.
- Fires the `FileSaveNotify` event to any listening add-in.
- Same minimum version as `GetType`, `ForceRebuild3`, and `EditRebuild3` (SOLIDWORKS 2001Plus FCS, Revision 10.0) — one of the oldest stable methods in the interface, unlike the much newer `SaveAs3` (2020 SP02).

### IModelDocExtension::SaveAs3

- **Interface:** IModelDocExtension
- **Method:** SaveAs3
- **Minimum SW version:** SOLIDWORKS 2020 SP02 (Revision Number 28.2)

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
| Name | String (ByVal) | n/a | Yes | Full pathname of the document to save; the file extension indicates any format conversion to perform (e.g. `Part1.igs` to save as IGES). If only a file name is given, the file is saved in the active document's directory | |
| Version | Integer (ByVal) | n/a | Yes | Format/version in which to save, used when the filename extension does not uniquely indicate the target format (e.g. detached vs. standard drawing) | `swSaveAsVersion_e` |
| Options | Integer (ByVal) | n/a | Yes | Save options (e.g. silent save); additional options can be set via `ISldWorks::SetUserPreferenceIntegerValue` | `swSaveAsOptions_e` |
| ExportData | Object (ByVal) | n/a | No — pass `Nothing`/`null` to save all sheets to PDF | An `IExportPdfData` object specifying which drawing sheets to export to PDF | |
| AdvancedSaveAsOptions | Object (ByVal) | n/a | No — pass `Nothing`/`null` for none | An `IAdvancedSaveAsOptions` object (obtained via `IModelDocExtension::GetAdvancedSaveAsOptions`) specifying advanced options such as saving a subset of configurations or renaming/relocating component references | |
| Errors | Integer (ByRef, out) | n/a | Yes (pass a variable; pass `Nothing`/`null` to suppress) | Errors that caused the save to fail, as a bitwise OR of error codes | `swFileSaveError_e` |
| Warnings | Integer (ByRef, out) | n/a | Yes (pass a variable; pass `Nothing`/`null` to suppress) | Warnings/extra information generated during the save, as a bitwise OR of warning codes | `swFileSaveWarning_e` |

**Returns:** `Boolean`. True if the save was successful (`Errors` is 0); false if not (`Errors` contains a bitwise OR of the `swFileSaveError_e` codes generated).

**Prior selection required:** None required in general. This method exports the entire model *unless* faces or bodies are currently selected, in which case it exports only the selected entities — call `IModelDoc2::ClearSelection2` first if a whole-model export is intended despite an existing selection. Additionally, to save as IGES, STL, or STEP, the document being converted must be the *active* document: call `ISldWorks::ActivateDoc3` to make it active first (and `ISldWorks::ActiveDoc`/`IActiveDoc2` to retrieve it).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SaveAs3.html

**status:** verified

**Gotchas:**
- **Relationship to `Save3`:** the help page's own Remarks state, verbatim: *"Use IModelDoc2::Save3 to save a file using its current name."* `SaveAs3` is the method to use for a new name, a new format/version, or the first save of a new document — i.e. `Save3` is the "quick save," and `SaveAs3` is the modern, fully general "save as" path.
- `SaveAs3` obsoletes `IModelDocExtension::SaveAs2`; the documented difference is the addition of the `AdvancedSaveAsOptions` parameter (an `IAdvancedSaveAsOptions` object), which enables saving a subset of configurations and renaming/relocating individual component references — capabilities `SaveAs2` did not have.
- Overwrites existing files unless they are read-only.
- Removes any configuration-specific bitmap previews except the current configuration's.
- Fires the `FileSaveNotify` event to any listening add-in.
- Saving a document as PDF while it is open view-only is not supported.
- Minimum version (SOLIDWORKS 2020 SP02, Revision 28.2) is dramatically newer than the other four methods in this section (all SOLIDWORKS 2001Plus FCS, Revision 10.0) — code targeting older SOLIDWORKS releases cannot call `SaveAs3` and must fall back to `SaveAs`/`SaveAs2`.

### IModelDoc2::ForceRebuild3

- **Interface:** IModelDoc2
- **Method:** ForceRebuild3
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function ForceRebuild3( _
   ByVal TopOnly As System.Boolean _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| TopOnly | Boolean (ByVal) | n/a | Yes | True rebuilds the top-level assembly only; false rebuilds the top-level assembly and all subassemblies | |

**Returns:** `Boolean`. True if all features in the active configuration at the specified assembly level in the model were rebuilt; false if not.

**Prior selection required:** None. Operates on the active configuration of the model on which it is called.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~ForceRebuild3.html

**status:** verified

**Gotchas:**
- "Force" rebuild recomputes all features unconditionally, regardless of whether SOLIDWORKS considers them dirty/out-of-date — this makes it much slower than `EditRebuild3`, which only rebuilds features actually flagged as needing a rebuild.
- The `TopOnly` boolean is easy to misread: `True` rebuilds *only* the top-level assembly (subassemblies are left alone); `False` rebuilds the top-level assembly *and* all subassemblies. It is not a "rebuild everything" switch in the direction the name might suggest.
- See also `IModelDocExtension::ForceRebuildAll` for forcing a rebuild across all configurations/documents rather than just the active configuration of one document (referenced in the page's "See Also" list; not independently verified in this dossier).
- This method does not consume `swRebuildOptions_e` (see Enums section) — it uses the plain `TopOnly` boolean instead. `swRebuildOptions_e` is consumed elsewhere in the API, by rebuild-related methods on `IModelDocExtension` that were not fetched or verified as part of this dossier.

### IModelDoc2::EditRebuild3

- **Interface:** IModelDoc2
- **Method:** EditRebuild3
- **Minimum SW version:** SOLIDWORKS 2001Plus FCS (Revision Number 10.0)

**Signature:**

```vb
Function EditRebuild3() As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | — | — | — | This method takes no parameters | |

**Returns:** `Boolean`. True if only those features that need to be rebuilt were rebuilt in the active configuration in the model; false if not.

**Prior selection required:** None, but per the help page's Remarks: *"This method only works in-context of the active document."* It must be called against the active document — it cannot target a background/inactive document.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~EditRebuild3.html

**status:** verified

**Gotchas:**
- This is the incremental/"smart" rebuild counterpart to `ForceRebuild3`: it rebuilds only features flagged as needing a rebuild, rather than unconditionally recomputing every feature, so it is normally much cheaper to call.
- Restricted to the active document only (stated explicitly in Remarks) — unlike some other model-document methods, it cannot be invoked against a document that is open but not currently active.
- See also `IModelDocExtension::EditRebuildAll` (rebuilds across more than the active configuration) and `IModelDoc2::Rebuild`, both listed in the page's "See Also" but not independently verified in this dossier.

## Sheet management

### IDrawingDoc::NewSheet4

- **Interface:** IDrawingDoc
- **Method:** NewSheet4
- **Minimum SW version:** SOLIDWORKS 2015 FCS (Revision Number 23.0)

**Signature:**

```vb
Function NewSheet4( _
   ByVal Name As System.String, _
   ByVal PaperSize As System.Integer, _
   ByVal TemplateIn As System.Integer, _
   ByVal Scale1 As System.Double, _
   ByVal Scale2 As System.Double, _
   ByVal FirstAngle As System.Boolean, _
   ByVal TemplateName As System.String, _
   ByVal Width As System.Double, _
   ByVal Height As System.Double, _
   ByVal PropertyViewName As System.String, _
   ByVal ZoneLeftMargin As System.Double, _
   ByVal ZoneRightMargin As System.Double, _
   ByVal ZoneTopMargin As System.Double, _
   ByVal ZoneBottomMargin As System.Double, _
   ByVal ZoneRow As System.Integer, _
   ByVal ZoneCol As System.Integer _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name to give the new drawing sheet | |
| PaperSize | Integer | n/a | Yes | Paper size; only used if `TemplateIn` is `swDwgTemplates_e.swDwgTemplateNone` | `swDwgPaperSizes_e` |
| TemplateIn | Integer | n/a | Yes | Which drawing template to use | `swDwgTemplates_e` |
| Scale1 | Double | n/a | Yes | Scale numerator (e.g. `1` for a 1:2 scale) | |
| Scale2 | Double | n/a | Yes | Scale denominator (e.g. `2` for a 1:2 scale) | |
| FirstAngle | Boolean | n/a | Yes | `True` for first-angle projection, `False` for third-angle | |
| TemplateName | String | n/a | Yes | Full path of a custom template; only used if `TemplateIn` is `swDwgTemplates_e.swDwgTemplateCustom`. Pass `""` otherwise | |
| Width | Double | meters | Yes | Paper width; only used if `TemplateIn` is `swDwgTemplateNone` or `PaperSize` is `swDwgPapersUserDefined` | `swDwgPaperSizes_e` |
| Height | Double | meters | Yes | Paper height; same validity condition as `Width` | `swDwgPaperSizes_e` |
| PropertyViewName | String | n/a | Yes | Name of the view whose model supplies custom property values. Pass `""` for none | |
| ZoneLeftMargin | Double | **unverified — not meters**, see Gotchas | Yes | Zone area left margin, distance from the sheet's left edge | |
| ZoneRightMargin | Double | **unverified — not meters**, see Gotchas | Yes | Zone area right margin, distance from the sheet's right edge | |
| ZoneTopMargin | Double | **unverified — not meters**, see Gotchas | Yes | Zone area top margin, distance from the sheet's top edge | |
| ZoneBottomMargin | Double | **unverified — not meters**, see Gotchas | Yes | Zone area bottom margin, distance from the sheet's bottom edge | |
| ZoneRow | Integer | n/a | Yes | Number of zone rows in the sheet's zone area; `ZoneRow x ZoneCol` is the total zone count | |
| ZoneCol | Integer | n/a | Yes | Number of zone columns in the sheet's zone area | |

The help page states no explicit units for `Width`/`Height`/the `Zone*Margin` params.
`meters` for `Width`/`Height` follows the API-wide convention in
[`README.md`](README.md#units-convention) and is corroborated by the worked example below.
The `Zone*Margin` params are the documented exception to that convention: the same example
contradicts it outright (see Gotchas), so do **not** write a mm-to-meters conversion for
them without confirming empirically.

**Returns:** `Boolean`. The help page states only "True if drawing sheet creation was
successful, false if not" — it does not enumerate failure causes (e.g. a duplicate
`Name`), so treat any specific failure cause as unverified until confirmed against a
live SolidWorks session. No exception is thrown on failure.

**Prior selection required:** None. Called directly on an `IDrawingDoc` obtained from
`ISldWorks::ActiveDoc` (or equivalent) — no `ISelectionMgr` state needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~NewSheet4.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_methods.html (confirms `NewSheet`/`NewSheet2`/`NewSheet3`/`NewSheet4` are all still-current, distinct members)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~NewSheet2.html and `~NewSheet3.html` (signatures, for the supersession claim below)
- https://help.solidworks.com/2025/english/api/sldworksapi/Create_Drawing_Sheet_Zones_Example_VB.htm (worked VBA call, for the zone-parameter example below)

**status:** verified

**Gotchas:**
- `NewSheet4` supersedes `NewSheet`, `NewSheet2`, and `NewSheet3`, each strictly a
  prefix of the next: `NewSheet(Name, PaperSize, TemplateIn, Scale1, Scale2)` (a `Sub`,
  no return value) → `NewSheet2` adds `FirstAngle, TemplateName, Width, Height` → `NewSheet3`
  adds `PropertyViewName` → `NewSheet4` adds the six `Zone*`/`ZoneRow`/`ZoneCol`
  parameters. Verified directly by fetching all three predecessor pages, not inferred —
  always use `NewSheet4`.
- `TemplateName` and `PropertyViewName` must be passed as `""` when unused, not
  omitted — COM interop here is positional, not named/optional.
- The zone parameters are not optional even when zones aren't wanted. The official
  "Create Drawing Sheet Zones" VBA example calls
  `NewSheet4("Test", swDwgPaperAsize, swDwgTemplateAsize, 1, 1, True, "", 0, 0, "", 0.5, 0.5, 0.5, 0.5, 2, 2)`
  to create a sheet with a 2x2 (4-zone) grid and margins of `0.5` on all sides — the
  example does not demonstrate a zero-zone call, so how to fully suppress the zone
  grid (e.g. `ZoneRow`/`ZoneCol` of `0` or `1`) is unverified; confirm empirically if a
  caller needs zones disabled.
- **The `Zone*Margin` units are not meters, despite the API-wide convention.** The same
  official example's `SetupSheet6` call passes an explicitly metric
  `Width=0.2794, Height=0.2159` (an 11 x 8.5 in A-size landscape sheet) alongside the
  same `0.5, 0.5, 0.5, 0.5` margins. A 0.5 m margin on a 0.2794 m sheet is geometrically
  impossible, so the margins are in some other unit — `0.5` in inches (12.7 mm) is the
  plausible reading, but nothing on either page states it. Treat the unit as unverified
  and confirm against a live session before converting: a wrapper that helpfully
  converts mm to meters here will produce a rejected or nonsensical zone grid.
- Cross-checked: the syntax block on the fetched page is internally consistent across
  its VB, C#, and C++/CLI declarations, and the fetched 2025 page content is
  byte-identical to the archived 2024 revision of the same page — the two-source
  corroboration this dossier format calls for.

### IDrawingDoc::ActivateSheet

- **Interface:** IDrawingDoc
- **Method:** ActivateSheet
- **Minimum SW version:** Not stated on the SOLIDWORKS 2025 help page (no Availability section present for this method; it is a long-standing core sheet-navigation method).

**Signature:**

```vb
Function ActivateSheet( _
   ByVal Name As System.String _
) As System.Boolean
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name of the sheet to activate | |

**Returns:** `Boolean`. True if the sheet was activated; false if SOLIDWORKS generated an error (e.g. no sheet with that name).

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~ActivateSheet.html

**status:** verified

**Gotchas:**
- Makes the named sheet the current/active sheet, similar in effect to `IDrawingDoc::SheetNext`/`SheetPrevious`. After activating, use `IDrawingDoc::GetCurrentSheet` (or `IGetCurrentSheet`) to obtain the `ISheet` interface for the now-active sheet.
- To activate a specific drawing view (not just a sheet), use `IDrawingView::ActivateView` instead.
- The help page for this method has no "Availability" section at all in the 2025 doc set — this appears to be an omission on very old, stable API surface rather than evidence the method is new; do not infer a version from its absence.

### IDrawingDoc::SetupSheet5

- **Interface:** IDrawingDoc
- **Method:** SetupSheet5
- **Minimum SW version:** SOLIDWORKS 2009 FCS (Revision Number 17.0)

**Signature:**

```vb
Function SetupSheet5( _
   ByVal Name As System.String, _
   ByVal PaperSize As System.Integer, _
   ByVal TemplateIn As System.Integer, _
   ByVal Scale1 As System.Double, _
   ByVal Scale2 As System.Double, _
   ByVal FirstAngle As System.Boolean, _
   ByVal TemplateName As System.String, _
   ByVal Width As System.Double, _
   ByVal Height As System.Double, _
   ByVal PropertyViewName As System.String, _
   ByVal RemoveModifiedNotes As System.Boolean _
) As System.Boolean
```

**Parameters:**

Full positional list, in order, exactly as documented on the help page:

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name | String | n/a | Yes | Name for the sheet | |
| PaperSize | Integer | n/a | Yes | Size of paper, used only if `TemplateIn` is `swDwgTemplateNone` | `swDwgPaperSizes_e` |
| TemplateIn | Integer | n/a | Yes | Template to use for the sheet | `swDwgTemplates_e` |
| Scale1 | Double | n/a (dimensionless ratio) | Yes | Scale numerator | |
| Scale2 | Double | n/a (dimensionless ratio) | Yes | Scale denominator | |
| FirstAngle | Boolean | n/a | Yes | True for first angle projection, false for third angle projection | see `swDrawingProjectionType_e` in Enums for the equivalent named constants used elsewhere in the API; this parameter itself is a raw Boolean, not that enum |
| TemplateName | String | n/a | Yes | Full path + filename of the custom sheet-format template; only meaningful if `TemplateIn` is `swDwgTemplateCustom` | |
| Width | Double | meters | Yes | Paper width; valid only if `TemplateIn` is `swDwgTemplateNone` or `PaperSize` is `swDwgPapersUserDefined` | |
| Height | Double | meters | Yes | Paper height; valid only if `TemplateIn` is `swDwgTemplateNone` or `PaperSize` is `swDwgPapersUserDefined` | |
| PropertyViewName | String | n/a | Yes | Name of the view containing the model from which to pull custom property values | |
| RemoveModifiedNotes | Boolean | n/a | Yes | True to delete modified notes, false to leave them | |

**Returns:** `Boolean`, per the syntax block (`) As System.Boolean`). The SetupSheet5 help page has no prose "Return Value" section describing what `True`/`False` mean (unlike SetupSheet4's page, which states "True if set successfully, false if not") — the signature's return type is verified directly from the page; the specific failure semantics of that Boolean are not documented on this page and are marked unverified below rather than assumed from the SetupSheet4 precedent.

**Prior selection required:** None. The sheet is identified by the `Name` string parameter, not by prior FeatureManager selection.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~SetupSheet5.html
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~SetupSheet4.html (used for the SetupSheet4→SetupSheet5 delta)
- SOLIDWORKS API forum thread "SetupSheet5 VBA editor change parameters" (https://forum.solidworks.com/thread/228510) — used as an independent cross-check for parameter order/count/units (found via search; direct fetch of the forum was blocked by an Akamai edge WAF returning "Access Denied", so this is corroborated via search-result quotation, not a full page fetch)

**status:** verified

**Gotchas:**
- **Scope of `verified`:** the signature (parameter names, types, order, count) is two-source verified — against the fetched help page and an independent forum macro snippet (below). What is *not* verified from this page is the precise meaning of a `False` return (e.g. whether it's raised for a duplicate `Name`, an invalid `TemplateIn`/`PaperSize` combination, or something else) — the help page simply omits that prose, and it is not inferred here from the SetupSheet4 precedent. Confirm empirically if a caller needs to branch on the specific failure cause.
- **typed-wrapper candidate.** SetupSheet5 takes 11 positional parameters — a mix of String, Integer (two different enum domains), Double, and Boolean, several of which are conditionally meaningful only depending on the value of an earlier parameter (`PaperSize` only matters if `TemplateIn = swDwgTemplateNone`; `Width`/`Height` only matter if `TemplateIn = swDwgTemplateNone` or `PaperSize = swDwgPapersUserDefined`; `TemplateName` only matters if `TemplateIn = swDwgTemplateCustom`). Calling this positionally is extremely error-prone — a transposed `Scale1`/`Scale2` or a stray `True`/`False` in the wrong slot compiles fine and fails silently or picks the wrong projection/template. This is a strong candidate for a typed wrapper function (named-parameter struct/DTO) in this project's codebase rather than calling the raw COM signature positionally.
- **Lineage vs. SetupSheet4:** `SetupSheet` → `SetupSheet2` → `SetupSheet3` → `SetupSheet4` → `SetupSheet5` → `SetupSheet6` (current, non-obsolete method). `SetupSheet4`'s positional parameter list is `Name, PaperSize, TemplateIn, Scale1, Scale2, FirstAngle, TemplateName, Width, Height, PropertyViewName` — the same 10 names/types/order as SetupSheet5's first 10 parameters. SetupSheet5 adds exactly one new trailing parameter versus SetupSheet4: `ByVal RemoveModifiedNotes As System.Boolean` (11th positional parameter, "True to delete modified notes, false to not"). All other parameters are unchanged in name, type, and order. Both SetupSheet4 and SetupSheet5 are themselves marked **Obsolete** on their help pages: SetupSheet4's page says "Obsolete. Superseded by IDrawingDoc::SetupSheet5"; SetupSheet5's page says "Obsolete. Superseded by IDrawingDoc::SetupSheet6." SetupSheet6 was not in scope for this dossier but exists and is the current recommended call as of SOLIDWORKS 2025.
- **Second-source cross-check:** a working macro snippet located via web search (SOLIDWORKS API forum thread "SetupSheet5 VBA editor change parameters", https://forum.solidworks.com/thread/228510) calls SetupSheet5 as:
  ```vb
  boolstatus = Part.SetupSheet5("MW Sheet", 12, 12, 1, 20, False, _
     "C:\SWDVault\Engineering\Z00 - Solidworks\sheetformat\TAG_MW_Single_View.slddrt", _
     0.42, 0.297, "Default", False)
  ```
  This is 11 positional arguments in exactly the order extracted from the help page (`Name, PaperSize, TemplateIn, Scale1, Scale2, FirstAngle, TemplateName, Width, Height, PropertyViewName, RemoveModifiedNotes`), corroborating both the parameter count/order and the units claim: `Width=0.42, Height=0.297` corresponds to A3 paper (420 mm × 297 mm) expressed in **meters**, confirming the SolidWorks API's meters-everywhere convention applies to these two parameters regardless of document display units. (Direct fetch of the forum thread itself was blocked by an Akamai edge WAF returning "Access Denied"; this snippet is corroborated via search-result quotation, not a full page fetch.)
- Both SetupSheet4 and SetupSheet5 are marked Obsolete in favor of the next revision (SetupSheet6); new code should prefer SetupSheet6, but SetupSheet5 remains fully functional and is what's likely already in use in legacy macros/integrations this project may need to interoperate with.
- Per Remarks on both the SetupSheet4 and SetupSheet5 pages: call `IModelDoc2::ForceRebuild3` after calling this method to make first-angle/third-angle projection changes actually take effect in the drawing views — omitting the rebuild call is a documented gotcha, not an inference.
- If `TemplateName` differs from the sheet format file currently in use, SOLIDWORKS silently updates/replaces the sheet format — a side effect worth flagging to callers who only intended to change paper size or scale.
- `FirstAngle` is a raw positional Boolean here, not the `swDrawingProjectionType_e` enum (see Enums section) — do not confuse the two when building a typed wrapper; a wrapper should probably accept the enum and translate to this Boolean internally for readability, but the underlying COM parameter is strictly Boolean.

### IDrawingDoc::GetSheetNames

- **Interface:** IDrawingDoc
- **Method:** GetSheetNames
- **Minimum SW version:** Not stated on the SOLIDWORKS 2025 help page (no Availability section present).

**Signature:**

```vb
Function GetSheetNames() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | n/a | n/a | n/a | Method takes no arguments | |

**Returns:** `Object` (a `Variant` array of Strings at the COM layer). Array containing the names of the drawing sheets in this drawing.

**Prior selection required:** None.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~GetSheetNames.html

**status:** verified

**Gotchas:**
- Returns `System.Object`, which in .NET interop must be cast to a `String()` array (e.g. `CType(swDraw.GetSheetNames(), String())` in VB.NET) — a common source of runtime cast exceptions if the caller assumes a typed array directly.
- An `IGetSheetNames` sibling method also exists on `IDrawingDoc` (per the member index) — likely the "safe array" / interop-friendlier variant used from C++ contexts; not documented here since it was out of scope, but worth knowing it exists if `GetSheetNames`'s `Object` return is inconvenient.
- Sheet order in the returned array is not guaranteed by this page to match on-screen tab order; use in conjunction with `GetCurrentSheet`/`ActivateSheet` rather than assuming index-based correspondence to displayed sheet order.

### IDrawingDoc::GetCurrentSheet

- **Interface:** IDrawingDoc
- **Method:** GetCurrentSheet
- **Minimum SW version:** Not stated on the SOLIDWORKS 2025 help page (no Availability section present).

**Signature:**

```vb
Function GetCurrentSheet() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | n/a | n/a | n/a | Method takes no arguments | |

**Returns:** `Object`, which is actually an `ISheet` interface pointer wrapped as `Object` (documented Return Value text is simply "Sheet"). The returned `ISheet` object includes methods used to access the `IBomTable` object.

**Prior selection required:** None — operates on whichever sheet is currently active (see `ActivateSheet`).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~GetCurrentSheet.html

**status:** verified

**Gotchas:**
- Return type is `System.Object` and must be cast to `ISheet` by the caller (e.g. `CType(swDraw.GetCurrentSheet(), SldWorks.Sheet)`/`ISheet` depending on interop assembly) — same casting gotcha pattern as `GetSheetNames`.
- An `IGetCurrentSheet` sibling method also exists on `IDrawingDoc` per the member index, presumably the interop-friendlier typed variant; not documented here since out of scope.
- Returns whatever sheet is currently active in the UI/session — if the caller just created or activated a different sheet via `ActivateSheet`/`NewSheet4`, that call must complete (and, per SetupSheet's Remarks pattern elsewhere in this interface, sometimes a rebuild) before `GetCurrentSheet` reliably reflects the change.

### ISheet::GetProperties2

- **Interface:** ISheet
- **Method:** GetProperties2
- **Minimum SW version:** SOLIDWORKS 2016 FCS (Revision Number 24.0)

Not part of the original sw-kzy epic's source research issue; added while building `list_sheets`/`get_active_sheet` (sw-kzy.1), which need a per-sheet scale/paper-size/projection-type/dimensions read and no other documented `IDrawingDoc`/`ISheet` member provides one in a single call.

**Signature:**

```vb
Function GetProperties2() As System.Object
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | n/a | n/a | n/a | Method takes no arguments | |

**Returns:** `Object` (a `Variant` array of eight `Double`s at the COM layer). Per the help page's Remarks, verbatim structure:

```
[ paperSize, templateIn, scale1, scale2, firstAngle, width, height, sameCustomProp ]
```

| Index | Name | Meaning |
| --- | --- | --- |
| 0 | paperSize | Paper size; a `Long`/Integer packed into a `Double`, per `swDwgPaperSizes_e` |
| 1 | templateIn | Template index; a `Long`/Integer packed into a `Double`, per `swDwgTemplates_e` |
| 2 | scale1 | Scale numerator |
| 3 | scale2 | Scale denominator |
| 4 | firstAngle | Boolean packed into a `Double`: `true` (`1.0`)/`1` if the sheet uses first-angle projection, `false` (`0.0`)/`0` if third-angle |
| 5 | width | Paper width |
| 6 | height | Paper height |
| 7 | sameCustomProp | Boolean packed into a `Double`: `true` if the sheet's Sheet Properties dialog has "Same as sheet specified in Document Properties" selected, `false` if not |

**Prior selection required:** None — called directly on an already-resolved `ISheet` reference (e.g. from `IDrawingDoc::GetCurrentSheet`/`Sheet`), same as `ISheet::GetViews` (docs/api/02-views.md).

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISheet~GetProperties2.html — fetched directly (the bare `WebFetch` tool 403s on every `help.solidworks.com` URL tried in this session, the same WAF behavior noted throughout this dossier's other records; a plain `curl` with a browser `User-Agent` header succeeded where the tool's own request signature didn't — worth remembering for future dossier work hitting the same wall). Page content confirmed authentic via its own embedded `helpContentData` JSON payload (title `"GetProperties2 Method (ISheet)"`), not a scraped mirror.
- https://help.solidworks.com/2021/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISheet~GetProperties2.html — independently fetched via the same method; byte-identical `helpText` payload to the 2025 page (same eight-element array order, same "SOLIDWORKS 2016 FCS, Revision Number 24.0" Availability line), corroborating that this record hasn't changed across at least five SOLIDWORKS releases.

**status:** verified

**Gotchas:**
- **Units of `width`/`height` are not stated on this page.** Unlike `NewSheet4`'s Width/Height (whose meters units this dossier corroborates via a worked VBA example), this page's Remarks give no unit for the two dimensions it returns. Treating them as meters here follows the API-wide convention documented in [`README.md`](README.md#units-convention) and the fact that they are the read-side counterpart of `NewSheet4`'s/`SetupSheet5`'s same-named, meters-denominated `Width`/`Height` parameters — but this specific page does not state it, so flag it as convention-inferred, not independently confirmed, if a caller's values look off by a unit-conversion factor.
- **`sameCustomProp` (index 7) is unused by this issue's tools.** `list_sheets`/`get_active_sheet` (sw-kzy.1) read indices 0–6 only; index 7 reflects a Sheet Properties dialog checkbox state with no requested tool surface here.
- The page's own "NOTES" section additionally states: to ensure a correct return value, the document must be open read-write or read-only — opening it view-only leaves "insufficient information available". Not independently verified against the fake-COM harness (no such distinction exists there); flagged here for a caller hitting unexpectedly-empty values against a real session.
- `ISheet::GetSize` is called out on the same page ("See Also") as an alternative/companion for just the sheet's size and standard-size classification; not fetched independently for this dossier since `GetProperties2` alone covers every field `list_sheets`/`get_active_sheet` need.
- Same `Object` → typed-array casting requirement as `GetSheetNames`/`GetCurrentSheet` elsewhere in this dossier — a real interop layer requires an explicit cast to `double[]`, not a direct index into the raw `Object`.

### ISheet::GetTemplateName

- **Interface:** ISheet
- **Method:** GetTemplateName
- **Minimum SW version:** Not stated on the SOLIDWORKS 2025 help page (no Availability section present) — same omission pattern as `GetSheetNames`/`SetupSheet5`'s page elsewhere in this dossier; not evidence of a new method.

Not part of the original sw-kzy epic's source research issue; added while building `set_sheet_properties`/`get_sheet_properties` (sw-kzy.2), which need to read a sheet's *current* custom-template path back — `ISheet::GetProperties2` (above) only exposes `templateIn` (whether the sheet uses a template at all), not the path string itself, and `IDrawingDoc`'s own member list (see the sheet-deletion record below) has no template-path getter either. `ISheet::GetTemplateName` is not itself on `IDrawingDoc`'s member list — it is exclusively an `ISheet` member, found via `IDrawingDoc`'s own "ISheet Interface Members" page, fetched specifically to answer this: does *any* documented COM member expose a sheet's current template path back to a caller?

**Signature:**

```vb
Function GetTemplateName() As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| (none) | n/a | n/a | n/a | Method takes no arguments | |

**Returns:** `String`. Per the help page's own "Return Value" line: "Template path name."

**Prior selection required:** None — called directly on an already-resolved `ISheet` reference, same as `ISheet::GetProperties2` above.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISheet~GetTemplateName.html — fetched directly via the same `curl` + browser `User-Agent` workaround `GetProperties2`'s record above documents (the bare `WebFetch` tool 403s on `help.solidworks.com`). Page content confirmed authentic via its own embedded `helpContentData` JSON payload (title `"GetTemplateName Method (ISheet)"`).
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISheet_members.html — fetched directly (same method) to confirm `GetTemplateName` is a real, current `ISheet` member (alongside `GetTemplateSketch`, `ReloadTemplate`, `SetTemplateName`) and to search for any *other* undocumented-here template-path getter — none found besides this one.

**status:** verified (single primary source; no independent second-source cross-check was located for this specific method, unlike `GetProperties2`'s 2021/2025 byte-identical-page corroboration above)

**Gotchas:**
- **Answers `set_sheet_properties`'s open question directly: a template-path getter does exist.** A caller can read a sheet's current custom template path back via this method — `set_sheet_properties` (sw-kzy.2) uses it to preserve `TemplateName` across a partial update instead of refusing to touch a sheet that already uses a custom template.
- **The `"*.drt"` sentinel.** Per this page's own Remarks: "If the sheet does not use a template, i.e., uses a custom layout, this method returns `"*.drt"`." (SolidWorks' own terminology collision: this "custom layout" wording refers to `SetupSheet5`'s `TemplateIn = swDwgTemplateNone` case — sized directly from `PaperSize`/`Width`/`Height` — not to `swDwgTemplateCustom`, which is the *opposite* case, a real custom `.slddrt` file.) `get_sheet_properties`/`set_sheet_properties` treat this literal string as "no real path" (reported as `None`/preserved as `""`) rather than surfacing `"*.drt"` itself as if it were a usable `TemplateName` value — passing that literal back into `SetupSheet5`'s `TemplateName` parameter is untested and not assumed safe.
- Per Remarks: "To ensure a correct return value, open the document in edit mode." Not independently verified against the fake-COM harness (no such distinction exists there); flagged here for a caller hitting an unexpectedly-empty/stale value against a real session, same caveat `GetProperties2`'s record above documents for its own read-mode Remark.
- `ISheet::SetTemplateName`/`ReloadTemplate`/`GetTemplateSketch` are sibling members on the same page's "See Also" — not fetched independently for this dossier since `set_sheet_properties` writes a new template via `SetupSheet5`'s own `TemplateName` parameter (already documented above), not `SetTemplateName`.

### IDrawingDoc sheet deletion (via selection — no direct DeleteSheet API)

- **Interface:** IDrawingDoc (no direct method; workaround uses IModelDocExtension)
- **Method:** DeleteSheet — does not exist (see verification below); workaround built from `IModelDocExtension::SelectByID2` + `IModelDocExtension::DeleteSelection2`
- **Minimum SW version (of the workaround, i.e. the later of its two real calls):** SOLIDWORKS 2006 SP1 (Revision Number 14.1) — `SelectByID2` alone is available from SOLIDWORKS 2005 FCS (Revision Number 13.0), but `DeleteSelection2` is not available until SOLIDWORKS 2006 SP1 (Revision Number 14.1), which is therefore the effective minimum version for this whole pattern.

**`IDrawingDoc::DeleteSheet` does not exist.** Direct verification:
1. Fetching the canonical URL `https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~DeleteSheet.html` returns SOLIDWORKS's own "page not found" payload, with the underlying error detail: `"errorDetails":"on Help Viewer Location - main : HTML=sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~DeleteSheet.html : V=2025 : L=english : P=api Error - Error checking file existence: File does not exist: /data/HelpDoc/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDraw..."` — i.e. the file backing that page literally does not exist on SOLIDWORKS's own help server.
2. The `IDrawingDoc` member index page (`SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html`, fetched and parsed directly) lists every real member of `IDrawingDoc`. The full set of Sheet-related members is: `ActivateSheet, EditSheet, EditSheet2, GetCurrentSheet, GetEditSheet, GetSheetCount, GetSheetNames, IGetCurrentSheet, IGetSheetNames, IReorderSheets, NewSheet, NewSheet2, NewSheet3, NewSheet4, PasteSheet, ReorderSheets, SetSheetsSelected, SetupSheet, SetupSheet2, SetupSheet3, SetupSheet4, SetupSheet5, SetupSheet6, Sheet, SheetNext, SheetPrevious`. `DeleteSheet` is not among them, in either direction (not merely missing its own page — it is absent from the authoritative member listing too). No equivalent `IModelDoc2::DeleteSheet` exists either.

**Real-world workaround pattern** (select the sheet in the FeatureManager tree, then delete the selection), documented across multiple SOLIDWORKS forum threads (e.g. "select and delete drawing sheet", "Code to Delete a sheet"):

**Signature:**

```vb
Dim swModel As SldWorks.ModelDoc2
Dim swExt   As SldWorks.ModelDocExtension
Dim bRet    As Boolean

Set swModel = swApp.ActiveDoc
Set swExt   = swModel.Extension

' Select the sheet by name (Type string "SHEET" corresponds to the
' swSelSHEETS member of swSelectType_e, per the swconst page's own
' Type-string column - confirmed, not a guess)
bRet = swExt.SelectByID2("Sheet1", "SHEET", 0, 0, 0, False, 0, Nothing, 0)

If bRet Then
    ' DeleteOptions:=0 -> default deletion behavior per swDeleteSelectionOptions_e
    ' Does not prompt the user for confirmation.
    bRet = swExt.DeleteSelection2(0)
End If
```

**Parameters:**

The ones actually used above, from the real `SelectByID2` and `DeleteSelection2` signatures:

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| Name (SelectByID2 arg 1) | String | n/a | Yes | Name of the sheet to select (e.g. `"Sheet1"`), or empty string | |
| Type (SelectByID2 arg 2) | String | n/a | Yes | Selection type, uppercase; `"SHEET"` selects a drawing sheet | `swSelectType_e` (member `swSelSHEETS`, whose documented Type-string is `"SHEET"`) |
| X, Y, Z (SelectByID2 args 3-5) | Double (each) | meters | Yes | Selection location in model space; `0, 0, 0` when selecting by name rather than by picking a 3D point | |
| Append (SelectByID2 arg 6) | Boolean | n/a | Yes | True to append to current selection instead of replacing it | |
| Mark (SelectByID2 arg 7) | Integer | n/a | Yes | Selection "mark" bit used to distinguish selection groups; `0` for a plain single selection | |
| Callout (SelectByID2 arg 8) | Callout (object) | n/a | No | Callout object association; `Nothing`/`null` when not selecting via a callout | |
| SelectOption (SelectByID2 arg 9) | Integer | n/a | Yes | Extra selection options, `0` for default | `swSelectOption_e` |
| DeleteOptions (DeleteSelection2 arg 1) | Integer | n/a | Yes | Deletion behavior flags; `0` for default deletion of the current selection | `swDeleteSelectionOptions_e` |

**Returns:** Both calls return `Boolean`. `SelectByID2` returns true if the sheet was found and selected. `DeleteSelection2` returns true if the selected item(s) were deleted, false if not; per its help page, "This method does not ask the user to confirm the deletion."

**Prior selection required:** None before this sequence — the sequence itself performs the selection via `SelectByID2` immediately before deleting.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc~DeleteSheet.html (confirms non-existence — "File does not exist" error payload)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDrawingDoc_members.html (authoritative member list — DeleteSheet absent)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~SelectByID2.html (real signature for the selection call)
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~DeleteSelection2.html (real signature for the delete call)
- https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSelectType_e.html (confirms `swSelSHEETS` member maps to Type string `"SHEET"`, not `"SHEETS"`)
- SOLIDWORKS API forum, "select and delete drawing sheet" and "Code to Delete a sheet" threads (found via search; corroborate the `SelectByID2("...", "SHEET", ...)` + delete pattern as the community's standard workaround) — https://forum.solidworks.com/thread/219373 and https://forum.solidworks.com/thread/15709

**status:** verified

**Gotchas:**
- `DeleteSheet` is confirmed absent both as a direct help page (404 payload with an explicit "File does not exist" backend error) and as a listed member of `IDrawingDoc` on the authoritative members index — this is not a case of an obscure/undocumented-but-real method, it genuinely is not part of the interface.
- Direct fetch of the SOLIDWORKS API forum threads that describe this workaround was blocked by an Akamai edge WAF ("Access Denied" / errors.edgesuite.net) for both a plain WebFetch and a browser-UA curl; the workaround pattern above is corroborated via search-result snippets that quote/paraphrase those threads, not by fully reading the thread pages directly. Treat the exact forum wording as unverified even though the underlying `SelectByID2`/`DeleteSelection2` signatures themselves are primary-sourced and solid.
- Multiple forum threads report that the older `IModelDoc2::EditDelete` variant of this pattern (`SelectByID2` then `EditDelete` instead of `DeleteSelection2`) is flaky for sheets specifically, sometimes failing with "None of the selected entities could be deleted" — prefer `IModelDocExtension::DeleteSelection2` (shown above) over `EditDelete` for this case, and if `DeleteSelection2` also returns false, that's a known pain point, not necessarily a caller bug.
- `SelectByID2`'s `Type` argument is case-sensitive uppercase; confirmed directly against the `swSelectType_e` enum's own documented Type-string column, where `swSelSHEETS = 19` maps to the string `"SHEET"` (singular) — easy to mistype as `"SHEETS"` by analogy with the enum member's own name.
- `DeleteSelection2` does not prompt for confirmation (explicitly stated on its help page) — unlike deleting via the UI, this is a silent, irreversible-in-that-macro-run operation; callers should implement their own confirmation/undo strategy.
- Because there is no dedicated `DeleteSheet` call, there's also no dedicated way to delete a sheet *by object reference* (e.g. from an `ISheet` obtained via `GetCurrentSheet`) without first re-selecting it by name through `SelectByID2` — a caller holding an `ISheet` reference must still know/retrieve its name string to delete it via this pattern.

## Custom properties

### ICustomPropertyManager::Get6

- **Interface:** ICustomPropertyManager
- **Method:** Get6
- **Minimum SW version:** SOLIDWORKS 2018 FCS (Revision Number 26.0)

**Signature:**

```vb
Function Get6( _
   ByVal FieldName As System.String, _
   ByVal UseCached As System.Boolean, _
   ByRef ValOut As System.String, _
   ByRef ResolvedValOut As System.String, _
   ByRef WasResolved As System.Boolean, _
   ByRef LinkToProperty As System.Boolean _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FieldName | String | n/a | Yes | Name of the custom property to read | |
| UseCached | Boolean | n/a | Yes | True to use cached data (fast path if the configuration was previously activated); False to force fresh evaluation | |
| ValOut | String (ByRef, out) | n/a | Yes (out) | Raw stored value of the custom property | |
| ResolvedValOut | String (ByRef, out) | n/a | Yes (out) | Evaluated value of the custom property | |
| WasResolved | Boolean (ByRef, out) | n/a | Yes (out) | True if the value returned was actually evaluated, False if not (see Gotchas cache table) | |
| LinkToProperty | Boolean (ByRef, out per declared syntax) | n/a | Yes | Declared `ByRef`/`out` in the signature; the parameter description text reads it as an input ("True to link FieldName to its parent part, false to not") — see Gotchas | |

**Returns:** `Integer`. Result code as defined in `swCustomInfoGetResult_e` (not one of the enums in scope for this dossier; only referenced here).

**Prior selection required:** None. Called directly on an `ICustomPropertyManager` object obtained from `IModelDocExtension::CustomPropertyManager` (or `IConfiguration`/`IFeature` equivalents); no `ISelectionMgr` selection needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICustomPropertyManager~Get6.html
- https://blog.codestack.net/custom-properties-automation (cross-check of parameter order via VBA usage: `res = swCustPrpMgr.Get6(prpName, cached, prpVal, prpResVal, wasResolved, isLinked)`)

**status:** verified

**Gotchas:**
- **Direction ambiguity on `LinkToProperty`:** the help page's VB declaration marks it `ByRef` (and the C#/C++ syntax blocks mark it `out`), which makes it look like an output the method fills in. But the parameter's own description reads like an input instruction: "True to link FieldName to its parent part, false to not." CodeStack's usage sample names it `isLinked` and treats it consistently with the other `ByRef` outs (`wasResolved`, `prpResVal`), i.e., as something the call returns rather than something the caller sets. The two sources do not agree on intent vs. mechanics — treat `LinkToProperty` as an out parameter per the declared signature, but be aware the prose reads as if it were a request flag.
- **Cache/activation interaction** (from the Remarks table): if `UseCached=True` and the configuration was already activated, up-to-date data is returned and `WasResolved=True`. If `UseCached=True` and the configuration was *not* previously activated, cached (possibly stale) data is returned and `WasResolved=False`. If `UseCached=False`, up-to-date data is always returned regardless of prior activation. Set `UseCached=False` whenever current data is required.
- **Side effect on document state:** if the configuration was not previously activated, `Get6` loops through all of the model's configurations to find the property, which can be slow, and the model may be left in a configuration other than the one it started in. Call `IModelDoc2::ForceRebuild3` after `Get6` to restore the original configuration.
- Unlike the now-obsolete `ICustomPropertyManager::Get3`, `Get6` does **not** preface resolved values of external referenced documents with `fromparent+`.
- `Get6` supersedes `Get2`/`Get3` (both cited as obsolete on this page) for configuration-specific, linked, evaluated custom-property reads, and is faster than them when the configuration is already active. CodeStack additionally notes `Get5` (SOLIDWORKS 2014) and `Get4` (SOLIDWORKS 2011 SP4) as older, version-gated fallbacks — those predecessor pages were not independently fetched for this dossier, so take the version numbers as CodeStack-sourced only.

### ICustomPropertyManager::Add3

- **Interface:** ICustomPropertyManager
- **Method:** Add3
- **Minimum SW version:** SOLIDWORKS 2014 FCS (Revision Number 22.0)

**Signature:**

```vb
Function Add3( _
   ByVal FieldName As System.String, _
   ByVal FieldType As System.Integer, _
   ByVal FieldValue As System.String, _
   ByVal OverwriteExisting As System.Integer _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FieldName | String | n/a | Yes | Name of the custom property to add | |
| FieldType | Integer | n/a | Yes | Type of the custom property | `swCustomInfoType_e` |
| FieldValue | String | n/a | Yes | Value of the custom property | |
| OverwriteExisting | Integer | n/a | Yes | Behavior when a property of the same name already exists | `swCustomPropertyAddOption_e` |

**Returns:** `Integer`. Result code as defined in `swCustomInfoAddResult_e` (not one of the enums in scope for this dossier; only referenced here).

**Prior selection required:** None. Called directly on an `ICustomPropertyManager` object; no `ISelectionMgr` selection needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICustomPropertyManager~Add3.html
- https://blog.codestack.net/custom-properties-automation (cross-check of parameter order via VBA usage: `res = swCustPrpMgr.Add3(prpName, prpType, prpVal, swCustomPropertyAddOption_e.swCustomPropertyReplaceValue)`)

**status:** verified

**Gotchas:**
- `FieldType` and `OverwriteExisting` are declared as plain `System.Integer` in the signature, not as the named enum types — pass the numeric enum values from `swCustomInfoType_e` / `swCustomPropertyAddOption_e` (this is the standard SOLIDWORKS API pattern of typing enum parameters as Integer/Long in the public interface).
- Whether an existing property is overwritten, replaced, or the call is a no-op depends entirely on `OverwriteExisting` (`swCustomPropertyAddOption_e`) — passing `swCustomPropertyOnlyIfNew` (0) on a name collision leaves the existing property untouched rather than erroring.
- The help page's See Also links this method to `ICustomPropertyManager::Delete2` and to `Set2`, reflecting the typical add-vs-set split: `Add3` creates or overwrites-per-option; `Set2` only updates an already-existing property (see `Set2` Gotchas below).

### ICustomPropertyManager::Set2

- **Interface:** ICustomPropertyManager
- **Method:** Set2
- **Minimum SW version:** SOLIDWORKS 2014 FCS (Revision Number 22.0)

**Signature:**

```vb
Function Set2( _
   ByVal FieldName As System.String, _
   ByVal FieldValue As System.String _
) As System.Integer
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| FieldName | String | n/a | Yes | Name of the existing custom property to update | |
| FieldValue | String | n/a | Yes | New value for the existing custom property | |

**Returns:** `Integer`. Result code as defined in `swCustomInfoSetResult_e` (not one of the enums in scope for this dossier; only referenced here).

**Prior selection required:** None. Called directly on an `ICustomPropertyManager` object; no `ISelectionMgr` selection needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICustomPropertyManager~Set2.html

**status:** verified

**Gotchas:**
- **`Set2` does not create properties.** The parameter description explicitly says `FieldName` is the name of the "existing" custom property — calling `Set2` on a name that does not already exist is expected to fail (via its `swCustomInfoSetResult_e` result code) rather than add it. Use `Add3` (with an appropriate `swCustomPropertyAddOption_e`) to create a property first.
- `Set2` has no `FieldType` parameter — it changes only the value string of an already-typed property, it does not change the property's declared `swCustomInfoType_e` type.
- Only one source (the help page itself) was available for this record; no independent cross-check source was found for `Set2` specifically, though its parameter order is uncontested and simple (two String parameters).

### IModelDocExtension::CustomPropertyManager

- **Interface:** IModelDocExtension
- **Method:** CustomPropertyManager (property, not a method)
- **Minimum SW version:** SOLIDWORKS 2007 FCS (Revision Number 15.0)

**Signature:**

```vb
Property Get CustomPropertyManager( _
   ByVal ConfigName As System.String _
) As ICustomPropertyManager
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| ConfigName | String | n/a | Yes | Name of the configuration whose custom properties are wanted, or `""` (empty string) for the document-level (general-to-the-file) property set | |

**Returns:** `ICustomPropertyManager` object for the requested property set (document-level or configuration-specific).

**Prior selection required:** None. Called directly on an `IModelDocExtension` object (e.g., `ModelDoc2.Extension`); no `ISelectionMgr` selection needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~CustomPropertyManager.html

**status:** verified

**Gotchas:**
- **Dual behavior, sourced from the help page's Remarks:** "File custom information is stored in the document file. It can be: General to the file, in which case there is a single value whatever the model's configuration — or — Configuration-specific, in which case a different value may be set for each configuration in the model." The page then states directly: "To access a general custom information value, set the configuration argument to an empty string. To get a document-level property, pass an empty string ("") to the configuration argument." This is the entry point for both cases — passing `""` reaches the document-level (general) property set, and passing an actual configuration name reaches that configuration's own property set — the same property (`IModelDocExtension::CustomPropertyManager`) is used for both, distinguished only by the argument.
- **Declared-type discrepancy:** the help page's own VB syntax block declares `ReadOnly Property CustomPropertyManager(ByVal ConfigName As System.String) As CustomPropertyManager` — i.e., the return type shown in the signature box is the coclass name `CustomPropertyManager`, not the interface. The separate "Property Value" section on the same page clarifies the actual returned object is an "ICustomPropertyManager object." This dossier's Signature line above uses `ICustomPropertyManager`, per the Property Value clarification — be aware the raw declaration text differs cosmetically.
- The actual declared parameter name on the help page is `ConfigName`, not `ConfigurationName`.
- Equivalent per-scope properties exist on other objects — `IConfiguration::CustomPropertyManager` and `IFeature::CustomPropertyManager` — linked from this page's See Also but not independently fetched/documented here.

## Enums

#### swDocumentTypes_e

| Value | Number | Meaning |
| --- | --- | --- |
| swDocNONE | 0 | No document type / uninitialized |
| swDocPART | 1 | Part document |
| swDocASSEMBLY | 2 | Assembly document |
| swDocDRAWING | 3 | Drawing document |
| swDocSDM | 4 | SDM (Structure Design/other internal) document |
| swDocLAYOUT | 5 | Layout document |
| swDocIMPORTED_PART | 6 | Imported part (Multi-CAD) |
| swDocIMPORTED_ASSEMBLY | 7 | Imported assembly (Multi-CAD) |

Remarks: When opening library feature parts, use `swDocPART`.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDocumentTypes_e.html

#### swDwgTemplates_e

| Value | Number | Meaning |
| --- | --- | --- |
| swDwgTemplateAsize | 0 | US "A" size drawing template |
| swDwgTemplateAsizeVertical | 1 | US "A" size drawing template, vertical (portrait) orientation |
| swDwgTemplateBsize | 2 | US "B" size drawing template |
| swDwgTemplateCsize | 3 | US "C" size drawing template |
| swDwgTemplateDsize | 4 | US "D" size drawing template |
| swDwgTemplateEsize | 5 | US "E" size drawing template |
| swDwgTemplateA4size | 6 | ISO A4 size drawing template |
| swDwgTemplateA4sizeVertical | 7 | ISO A4 size drawing template, vertical (portrait) orientation |
| swDwgTemplateA3size | 8 | ISO A3 size drawing template |
| swDwgTemplateA2size | 9 | ISO A2 size drawing template |
| swDwgTemplateA1size | 10 | ISO A1 size drawing template |
| swDwgTemplateA0size | 11 | ISO A0 size drawing template |
| swDwgTemplateCustom | 12 | Custom template; use with `TemplateName` in `SetupSheet4`/`SetupSheet5` to point at a specific `.slddrt` file |
| swDwgTemplateNone | 13 | No template; sheet size instead comes from `PaperSize` (`swDwgPaperSizes_e`) and/or explicit `Width`/`Height` |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDwgTemplates_e.html

#### swDwgPaperSizes_e

| Value | Number | Meaning |
| --- | --- | --- |
| swDwgPaperAsize | 0 | US "A" size paper |
| swDwgPaperAsizeVertical | 1 | US "A" size paper, vertical (portrait) orientation |
| swDwgPaperBsize | 2 | US "B" size paper |
| swDwgPaperCsize | 3 | US "C" size paper |
| swDwgPaperDsize | 4 | US "D" size paper |
| swDwgPaperEsize | 5 | US "E" size paper |
| swDwgPaperA4size | 6 | ISO A4 size paper |
| swDwgPaperA4sizeVertical | 7 | ISO A4 size paper, vertical (portrait) orientation |
| swDwgPaperA3size | 8 | ISO A3 size paper |
| swDwgPaperA2size | 9 | ISO A2 size paper |
| swDwgPaperA1size | 10 | ISO A1 size paper |
| swDwgPaperA0size | 11 | ISO A0 size paper |
| swDwgPapersUserDefined | 12 | User-defined/custom paper size; used together with explicit `Width`/`Height` (in meters) in `SetupSheet4`/`SetupSheet5` |

Note: `swDwgPaperSizes_e` and `swDwgTemplates_e` are numerically parallel only for values 0–11 (the lettered and ISO sizes) — same numbers, same relative ordering. They **diverge at value 12**: `swDwgTemplates_e`'s member 12 is `swDwgTemplateCustom` ("use `TemplateName` for a custom `.slddrt` file path"), while `swDwgPaperSizes_e`'s member 12 is `swDwgPapersUserDefined` ("use explicit `Width`/`Height`") — different names and different meanings, not a coincidental match. `swDwgTemplates_e` additionally has member 13 (`swDwgTemplateNone`), which `swDwgPaperSizes_e` has no counterpart for at all. Do not treat the two enums as interchangeable: they are consumed by different parameters (`TemplateIn` vs. `PaperSize`) with different conditional applicability in `SetupSheet4`/`SetupSheet5`, and the one place their numbering actually matters (value 12) is exactly where they mean different things.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDwgPaperSizes_e.html

#### swDrawingProjectionType_e (requested in the source issue as `swDwgProjectionType_e` — no such enum)

The task's requested enum name, `swDwgProjectionType_e`, does not exist. Fetching `https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDwgProjectionType_e.html` returns SOLIDWORKS's own "page not found" payload with backend error detail confirming the file itself does not exist, the same signature seen for the confirmed-nonexistent `IDrawingDoc::DeleteSheet`. Searching the `SolidWorks.Interop.swconst` namespace index page for projection-related enum names surfaced the real one: **`swDrawingProjectionType_e`** ("Drawing projection types"). Its values:

| Value | Number | Meaning |
| --- | --- | --- |
| swDrawing1stAngleProjection | 1 | **First-angle projection** |
| swDrawing3rdAngleProjection | 2 | **Third-angle projection** |

Note: this enum is a separate, independent representation of the projection-angle concept from the raw `FirstAngle As Boolean` parameter on `IDrawingDoc::SetupSheet4`/`SetupSheet5`/`NewSheet4` documented above (`True` = first angle, `False` = third angle on that Boolean parameter, matching `swDrawing1stAngleProjection`/`swDrawing3rdAngleProjection` semantically but not passed as this enum type in those specific method calls).

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDrawingProjectionType_e.html

#### swSaveAsOptions_e

Bitmask enum.

| Value | Number | Meaning |
| --- | --- | --- |
| swSaveAsOptions_Silent | 1 (0x1) | Suppress dialogs during save |
| swSaveAsOptions_Copy | 2 (0x2) | Save the document as a copy and continue editing the original |
| swSaveAsOptions_SaveReferenced | 4 (0x4) | Also save referenced components (sub-assemblies/parts) in assemblies and drawings; for a part with an external reference, saves the external reference too |
| swSaveAsOptions_AvoidRebuildOnSave | 8 (0x8) | Avoid rebuilding the document on save |
| swSaveAsOptions_UpdateInactiveViews | 16 (0x10) | Update views on inactive drawing sheets; not valid for `IPartDoc::SaveToFile2` |
| swSaveAsOptions_OverrideSaveEmodel | 32 (0x20) | Save eDrawings-related data into the file, overriding the Tools/Options system setting; not valid for `IPartDoc::SaveToFile2` |
| swSaveAsOptions_IgnoreBiography | 256 (0x100) | Prune the file's SOLIDWORKS revision history down to just the current file name |
| swSaveAsOptions_CopyAndOpen | 512 (0x200) | Save the document as a copy and open the copy |
| swSaveAsOptions_IncludeVirtualSubAsmComps | 1024 (0x400) | Save regular components contained in virtual subassemblies |
| swSaveAsOptions_ExportTo2DPdfFromInspection | 2048 (0x800) | Export drawing sheets from Inspection to 2D PDF |
| swSaveAsOptions_DetachedDrawing | n/a | Obsolete |
| swSaveAsOptions_SaveEmodelData | n/a | Obsolete |

Remarks: These options only apply when saving to native SOLIDWORKS file formats.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSaveAsOptions_e.html

#### swSaveAsVersion_e

| Value | Number | Meaning |
| --- | --- | --- |
| swSaveAsCurrentVersion | 0 | Typical/default save behavior (save in the current SOLIDWORKS version's native format) |
| swSaveAsFormatProE | 2 | Save in Pro/ENGINEER format |
| swSaveAsStandardDrawing | 3 | Save as a standard (non-detached) drawing |
| swSaveAsDetachedDrawing | 4 | Save as a detached drawing |
| swSaveAsSW98plus | n/a | Obsolete and no longer supported |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSaveAsVersion_e.html

#### swFileSaveError_e

Bitmask enum. Not all values indicate fatal failures — some are informational/warning conditions folded into the same bitmask.

| Value | Number | Meaning |
| --- | --- | --- |
| swGenericSaveError | 1 (0x1) | Generic/unspecified save error |
| swReadOnlySaveError | 2 (0x2) | File is read-only |
| swFileNameEmpty | 4 (0x4) | File name cannot be empty |
| swFileNameContainsAtSign | 8 (0x8) | File name cannot contain the "@" symbol |
| swFileLockError | 16 (0x10) | File is locked |
| swFileSaveFormatNotAvailable | 32 (0x20) | Save-As file type is not valid |
| swFileSaveAsDoNotOverwrite | 128 (0x80) | Do not overwrite an existing file |
| swFileSaveAsInvalidFileExtension | 256 (0x100) | File name extension does not match the SOLIDWORKS document type |
| swFileSaveAsNoSelection | 512 (0x200) | No bodies selected to save (valid for `IPartDoc::SaveToFile2`; not valid for `IModelDocExtension::SaveAs`) |
| swFileSaveAsBadEDrawingsVersion | 1024 (0x400) | Invalid eDrawings version for save |
| swFileSaveAsNameExceedsMaxPathLength | 2048 (0x800) | File name exceeds 255 characters |
| swFileSaveAsNotSupported | 4096 (0x1000) | Save As is not supported, or completed in a way where the result may be incomplete (e.g., SOLIDWORKS is hidden) |
| swFileSaveRequiresSavingReferences | 8192 (0x2000) | Saving an assembly with renamed components requires also saving its references |
| swFileSaveAsDetachedDrawingsNotSupported | 16384 (0x4000) | Detached-drawing Save As is not supported |
| swFileSaveWithRebuildError | n/a | Obsolete — see `swFileSaveWarning_e` |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swFileSaveError_e.html

#### swFileSaveWarning_e

Bitmask enum. These warnings are returned from `IModelDoc2` Save methods and do not cause the save to fail.

| Value | Number | Meaning |
| --- | --- | --- |
| swFileSaveWarning_RebuildError | 1 (0x1) | Rebuild error occurred during save |
| swFileSaveWarning_NeedsRebuild | 2 (0x2) | Document needs a rebuild |
| swFileSaveWarning_ViewsNeedUpdate | 4 (0x4) | Drawing views need to be updated |
| swFileSaveWarning_AnimatorNeedToSolve | 8 (0x8) | SOLIDWORKS Animator data needs to be solved |
| swFileSaveWarning_AnimatorFeatureEdits | 16 (0x10) | Animator feature edits pending |
| swFileSaveWarning_EdrwingsBadSelection | 32 (0x20) | Bad eDrawings selection |
| swFileSaveWarning_AnimatorLightEdits | 64 (0x40) | Animator light edits pending |
| swFileSaveWarning_AnimatorCameraViews | 128 (0x80) | Animator camera view edits pending |
| swFileSaveWarning_AnimatorSectionViews | 256 (0x100) | Animator section view edits pending |
| swFileSaveWarning_MissingOLEObjects | 512 (0x200) | OLE objects referenced by the document are missing |
| swFileSaveWarning_OpenedViewOnly | 1024 (0x400) | Only the opened view was saved |
| swFileSaveWarning_XmlInvalid | 2048 (0x800) | Associated XML data is invalid |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swFileSaveWarning_e.html

#### swCustomInfoType_e

| Value | Number | Meaning |
| --- | --- | --- |
| swCustomInfoUnknown | 0 | (no description given on page) |
| swCustomInfoNumber | 3 | Integer value |
| swCustomInfoDouble | 5 | Double value |
| swCustomInfoYesOrNo | 11 | Yes or No value |
| swCustomInfoText | 30 | Text value |
| swCustomInfoDate | 64 | Datetime value |
| swCustomInfoEquation | 105 | Equation value |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCustomInfoType_e.html

#### swCustomPropertyAddOption_e

| Value | Number | Meaning |
| --- | --- | --- |
| swCustomPropertyOnlyIfNew | 0 | Add the custom property only if it is new |
| swCustomPropertyDeleteAndAdd | 1 | Delete an existing custom property having the same name and add the new custom property |
| swCustomPropertyReplaceValue | 2 | Replace the value of an existing custom property having the same name |

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCustomPropertyAddOption_e.html

#### swRebuildOptions_e

Rebuild options. This is documented as a **bitmask** enum — values are combined with bitwise OR, not used as mutually exclusive alternatives.

| Value | Number | Meaning |
| --- | --- | --- |
| swRebuildAll | 1 (0x1) | Assembly or drawing; rebuilds geometry that has not been regenerated |
| swForceRebuildAll | 2 (0x2) | Assembly or drawing; forces a rebuild of all geometry |
| swUpdateMates | 4 (0x4) | Assembly only; only rebuilds mates, which is much faster than rebuilding geometry — especially useful with `IComponent2::Transform2` |
| swCurrentSheetDisp | 8 (0x8) | Drawing only; only rebuilds the display of the views on the current drawing sheet |
| swUpdateDirtyOnly | 16 (0x10) | Drawing only; only rebuilds drawing views that are dirty, when OR'd with the `swCurrentSheetDisp` option |

Note: none of the methods documented in this dossier (`GetType`, `Save3`, `SaveAs3`, `ForceRebuild3`, `EditRebuild3`) actually take a `swRebuildOptions_e` parameter — `ForceRebuild3` uses a plain `TopOnly` boolean instead. This enum is consumed elsewhere in the API (e.g. by rebuild-related methods on `IModelDocExtension` referenced in various See Also lists above); those methods were not fetched or verified as part of this dossier.

Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swRebuildOptions_e.html
