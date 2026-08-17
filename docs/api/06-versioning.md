---
interface: ISldWorks
min_methods: 1
status: complete
---

# Versioning

Covers `ISldWorks::RevisionNumber`, the only API member `solidworks_mcp/version_gate.py`
depends on to enforce this project's minimum-SOLIDWORKS-release policy (see
[`README.md`](README.md#target-release) -- all research targets SOLIDWORKS 2025, and
`version_gate.py` refuses to run a tool against anything older by default).

---

### ISldWorks::RevisionNumber

- **Interface:** ISldWorks
- **Method:** RevisionNumber
- **Minimum SW version:** Present since SOLIDWORKS 1.0 (pre-2000); documented behavior below
  covers every release back to the initial public release of SOLIDWORKS 2000.

**Signature:**

```vb
Function RevisionNumber() As System.String
```

**Parameters:**

| Name | Type | Units | Required | Meaning | Enum ref |
| --- | --- | --- | --- | --- | --- |
| *(none)* | | | | `RevisionNumber` takes no parameters | |

**Returns:** `String`, always in the form `"major.sp.hotfix"` -- three dot-separated
integers, e.g. `"33.0.0"` (SOLIDWORKS 2025 FCS), `"33.2.1"` (SOLIDWORKS 2025 SP2 HF1).
Per the official Remarks:

- `major` is an integer that increments by one with each successive major public
  release.
- The middle (`sp`) and last (`hotfix`) components together are what the help page
  calls "minor", a decimal number: `sp` is its integer part (incremented by 1.0 per
  service pack) and `hotfix` is its first decimal digit (incremented by 0.1 per
  service-pack hot fix) -- e.g. SP1 -> `"...1.0"`, SP1 HF1 -> `"...1.1"`, SP2 ->
  `"...2.0"`.
- For the initial public release of SOLIDWORKS 2000: `"8.0.0"`. For SOLIDWORKS 2000
  SP1: `"8.1.0"`. For the initial public release of SOLIDWORKS 2005: `"13.0.0"`; SP0.1:
  `"13.0.1"`; SP1: `"13.1.0"`.
- Alpha/beta/pre-release builds return **negative** `sp` values instead (a1: `-1.0`,
  b1: `-2.0`, b2: `-3.0`, b3: `-4.0`, PR1: `-5.0`, "though this value might be lower or
  higher depending on the number of beta releases"). Worked example: SOLIDWORKS 2015
  beta 2 returns `"23.-3.0"`. `version_gate.parse_revision_number` accepts a negative
  `sp` (its regex is `-?\d+` for every component) so these still parse into a
  `SwRelease`, they just carry a negative `service_pack`.
- No exception is documented for any input state; the method always returns a string.

**`major` -> release year:** the help page's own worked examples give two fixed
points: SOLIDWORKS 2000 -> major `8`, SOLIDWORKS 2005 -> major `13`. Both satisfy
`release_year = major + 1992`, which is the formula `version_gate.SwRelease.year` uses.
SOLIDWORKS 2025 is therefore major `33` (`2025 - 1992`), and SOLIDWORKS 2015 (major
`23`, corroborated by the `"23.-3.0"` beta example) matches the same formula --
three independent data points on the one primary source, not extrapolated from a
single sample.

**Prior selection required:** None. Called directly on the `ISldWorks` application
object (e.g. from `ISldWorks::ActiveDoc`'s owner) -- no `ISelectionMgr` state needed.

**Source URL(s):**
- https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~RevisionNumber.html

**status:** verified

**Gotchas:**
- **Property-vs-method ambiguity.** The `.NET Syntax` block above declares
  `RevisionNumber` as a method (`Function RevisionNumber() As String`, called with
  `()`), but `solidworks_mcp/automation/base.py` already has to work around SOLIDWORKS
  COM type libraries being inconsistent, across versions and builds, about whether a
  given member surfaces to Python as a bare property or a callable method (see its
  `is_connected`/`connect`/`_try_connect_com`, which try `self._sw_app.RevisionNumber`
  bare first and fall back to `self._sw_app.RevisionNumber()` on exception).
  `version_gate.read_revision_number` goes one step further: even when the bare access
  does *not* raise, the result may still be a bound method rather than a string (since
  the documented member is a method), so it calls the result if `callable()` is `True`.
- The format is described in prose as `"major.minor"` but every worked example on the
  page (and every real value this project has observed) is three dot-separated
  integers, not two. Treat the return value as strictly `major.sp.hotfix` -- a
  two-component parse would silently drop the hotfix digit.
- Nothing on this page states whether the string is ever prefixed/suffixed with
  non-numeric text (a build tag, a language code, etc.) on any real installation --
  only well-formed `major.sp.hotfix` values are documented. `version_gate` treats
  anything else as unparseable (`VersionGateError`) rather than guessing at a looser
  format.
