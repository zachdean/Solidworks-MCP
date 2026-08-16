---
interface: IDrawingDoc
min_methods: 1
status: template
---

# Dossier format template

This file is excluded from `scripts/check_api_docs.py` validation by its `_` prefix
(along with `README.md`) — it exists to demonstrate the required record format with
one fully worked, fetched example. Copy the front matter and record shape below into
new dossiers under `docs/api/`.

## Front matter

Every real dossier file starts with:

```yaml
---
interface: <primary interface this file documents, e.g. IDrawingDoc>
min_methods: <int — the validator fails the build if this file documents fewer
  H3 method records than this count>
status: <in-progress | complete>
---
```

## Method record format

Each documented method gets its own H3 heading (`### Interface::Method`) and the
fields below, in order. `scripts/check_api_docs.py` machine-checks six of these per
record — **Signature** (must be a fenced code block), **Parameters** (must be a
markdown table with a header-separator row), **Returns**, **Prior selection
required**, **Source URL(s)** (must contain at least one `http(s)://` URL), and the
**status:** line (must be `verified` or `unverified`). The rest (Interface, Method,
Minimum SW version, Gotchas) are required by this format as a matter of research
discipline but are not machine-checked — a reviewer, not the validator, catches a
missing one. Gotchas is deliberately left unchecked: a record with genuinely nothing
to warn about is legitimate.

- **Interface**, **Method**, **Minimum SW version**
- **Signature** — full ordered parameter list with COM types, in a fenced code block
- **Parameters** — table of name | type | units (meters/radians!) | required | meaning | enum ref
- **Returns** — type and what a failure looks like (`None` / `False` / `0` / negative code)
- **Prior selection required** — what must be selected via `ISelectionMgr` before the
  call, or "None"
- **Source URL(s)**
- **status:** `verified` or `unverified`
- **Gotchas** — deprecated predecessors, parameter-order traps, dialog-popping risk

---

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
