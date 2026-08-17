# SolidWorks API Dossiers

This directory holds hand-researched reference sheets ("dossiers") for the SolidWorks
COM API. Each dossier documents a slice of the API (drawing views, annotations, tables,
export, etc.) so that implementation work can read a verified signature instead of
guessing parameter order against undocumented COM interop.

## Target release

All research targets **SolidWorks 2025**. Where a method's behavior or signature
differs from earlier versions, note the version delta explicitly in that method's
Gotchas section — do not silently document a newer or older signature.

## Units convention

**The SolidWorks API is meters and radians everywhere**, regardless of the document's
display units (which are typically inches/mm/degrees in the UI). Every length parameter,
return value, and property in a dossier's Parameter table must state its unit explicitly
as `meters` or `radians` (or `n/a` for non-geometric values). Never assume a parameter is
in "current document units" without a source confirming it.

The convention is a default, not a guarantee. Where a source actively contradicts it, mark
the units cell `unverified` and explain the contradiction in that record's Gotchas rather
than asserting `meters` — see the `Zone*Margin` parameters in
[`01-documents-and-sheets.md`](01-documents-and-sheets.md) for the worked example. An
implementer writing a unit conversion against a wrong "meters" claim gets silently broken
geometry, so a documented unknown beats a confident guess.

## Canonical source URLs

- API method/property pages:
  `https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.<Interface>~<Method>.html`
- `swconst` enum pages:
  `https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.<enum>_e.html`
- Also useful: [CodeStack API reference](https://www.codestack.net/) for worked examples,
  and the SolidWorks API forum for known parameter-order gotchas that the official docs
  don't call out.

`help.solidworks.com` blocks requests without a browser-like `User-Agent` header (returns
HTTP 403). If a fetch tool can't retrieve a page, retry with a plain `curl -A "Mozilla/5.0
..." <url>` before giving up on that source.

Cross-check every signature against at least two sources when the help page is ambiguous,
incomplete, or contradicts another version's page, and say so in the doc's Gotchas. If a
page cannot be fetched from any source, record the method with `status: unverified` and an
explicit note in Gotchas — never invent a signature.

## Dossier file format

Every dossier file (anything under `docs/api/` other than this README and files whose
name starts with `_`, which are scaffolding such as `_TEMPLATE.md`) must:

1. Start with YAML front matter. `min_methods` (the number of H3 method records the
   file must contain) is required and machine-checked; `interface` (the primary
   interface the file documents) is convention and not machine-checked, but should
   still be included — see [`_TEMPLATE.md`](_TEMPLATE.md#front-matter).
2. Document each method as an H3 (`### `) record following the format in
   [`_TEMPLATE.md`](_TEMPLATE.md).

`scripts/check_api_docs.py` (wired into `scripts/check.sh`, and covered by the pytest
suite) enforces this shape — it fails the build if a dossier is missing required
sections, a method record is missing its Signature / Parameter table / Returns / Prior
selection required / Source URL(s) / status line, or a file has fewer method records
than its declared `min_methods`.

## Index

| File | Interfaces covered | Status |
| --- | --- | --- |
| [`_TEMPLATE.md`](_TEMPLATE.md) | — (format example only, excluded from validation) | n/a |
| [`01-documents-and-sheets.md`](01-documents-and-sheets.md) | ISldWorks, IModelDoc2, IModelDocExtension, IDrawingDoc, ISheet, ICustomPropertyManager | complete |
| [`02-views.md`](02-views.md) | IDrawingDoc, IView, ISldWorks, IModelDocExtension | complete |
| [`03-annotations.md`](03-annotations.md) | IModelDocExtension, ISelectionMgr, IModelDoc2, IDrawingDoc, IView, IDisplayDimension, IDimension, IGtol, IGtolFrame, IDatumTag, IWeldSymbol, IAnnotation | complete |
| [`04-tables.md`](04-tables.md) | IModelDocExtension, IView, IBomTableAnnotation, IDrawingDoc, ISheet, IRevisionTableAnnotation, IWeldmentCutListAnnotation, IHoleTableAnnotation, ITableAnnotation, IAnnotation | complete |
| [`05-export-and-layers.md`](05-export-and-layers.md) | IModelDocExtension, ISldWorks, IExportPdfData, IPartDoc, IDrawingDoc, ILayerMgr, ILayer | complete |
| [`06-versioning.md`](06-versioning.md) | ISldWorks | complete |

Rows are added here by each research issue as it lands its dossier under `docs/api/`.
