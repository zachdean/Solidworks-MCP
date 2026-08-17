"""
SolidWorks Version Gating
--------------------------
SolidWorks method signatures drift across releases (`CreateDrawViewFromModelView`
-> `...3`, `InsertBomTable` -> `...3`/`...4`). Silently calling a deprecated
overload against a newer/older install produces confusing runtime behavior
instead of a clear error, so every registered tool is checked against a
minimum SOLIDWORKS release before its handler ever runs -- see
`tools/registry.py::dispatch`.

Reading the connected version
==============================
`ISldWorks::RevisionNumber` returns the SOLIDWORKS version, per the official
API reference (`help.solidworks.com/2025/.../ISldWorks~RevisionNumber.html`,
Remarks section, fetched 2026-08-17):

    This method returns a string in the form "major.minor", where major is
    an integer and minor is a decimal number. For the initial public release
    of SOLIDWORKS 2000, this method returns 8.0.0. For SOLIDWORKS 2000 SP1,
    this method returns 8.1.0 ... For the initial public release of
    SOLIDWORKS 2005, this method returns 13.0.0 ... In general, each
    successive major public release increments the major number by one,
    each service pack increments the minor decimal number by 1.0, and each
    service pack hot fix increments the minor decimal number by 0.1.

So the wire format is always three dot-separated integers, `major.sp.hotfix`
(e.g. `"33.2.1"` for SOLIDWORKS 2025 SP2 HF1) -- "minor" in the prose above is
that decimal number's *integer* part (SP) and *first decimal digit* (hotfix)
concatenated back into two components. Pre-release builds use negative `sp`
values (e.g. `"23.-3.0"` for a SOLIDWORKS 2015 beta 2); `parse_revision_number`
accepts those too since they still round-trip through `SwRelease` correctly
(only `year` is used for gating).

`major` and the release year are related by a constant offset confirmed by
both worked examples on that page: SOLIDWORKS 2000 -> major 8 (2000 - 1992),
SOLIDWORKS 2005 -> major 13 (2005 - 1992). SOLIDWORKS 2025 is therefore
major 33.

The property-vs-method ambiguity
==================================
`automation/base.py` already works around SOLIDWORKS COM type libraries being
inconsistent about whether a member is generated as a bare property or a
method across versions/builds (see its `is_connected` / `connect` /
`_try_connect_com`). `RevisionNumber`'s own `.NET Syntax` block documents it
as a method (`Function RevisionNumber() As System.String`), so
`read_revision_number` below goes one step further than `base.py`'s plain
try/except: even when the bare attribute access itself does not raise, it
may still hand back a bound method rather than a string, so the result is
called if it is callable.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import re

from .config import get_config
from .constants import SwErrors

__all__ = [
    "SwRelease",
    "VersionGateError",
    "read_revision_number",
    "parse_revision_number",
    "get_connected_release",
    "effective_min_release",
    "require_version",
]


# SOLIDWORKS RevisionNumber's major component + this offset == the release
# year, confirmed against the 2000 (major 8) and 2005 (major 13) worked
# examples in the official Remarks -- see module docstring.
_MAJOR_TO_YEAR_OFFSET = 1992

_REVISION_RE = re.compile(r"^(?P<major>-?\d+)\.(?P<sp>-?\d+)\.(?P<hotfix>-?\d+)$")


class VersionGateError(Exception):
    """The connected RevisionNumber could not be read or parsed."""


@dataclass(frozen=True, order=True)
class SwRelease:
    """A parsed `ISldWorks::RevisionNumber` value, ordered by
    `(major, service_pack, hotfix)` -- oldest to newest."""

    major: int
    service_pack: int
    hotfix: int
    raw: str = field(compare=False)

    @property
    def year(self) -> int:
        """The SOLIDWORKS release year, e.g. 2025 for major 33."""
        return self.major + _MAJOR_TO_YEAR_OFFSET

    def __str__(self) -> str:
        return f"SOLIDWORKS {self.year} (RevisionNumber {self.raw!r})"


def read_revision_number(sw_app: Any) -> str:
    """Read the raw `ISldWorks::RevisionNumber` string off a live COM app
    object, handling the property-vs-method ambiguity -- see module
    docstring. Raises `VersionGateError` if the member cannot be read at
    all (e.g. `sw_app` is `None` or genuinely has no such member)."""
    if sw_app is None:
        raise VersionGateError("Not connected to SOLIDWORKS -- no RevisionNumber to read")
    try:
        value = sw_app.RevisionNumber
    except Exception:
        try:
            value = sw_app.RevisionNumber()
        except Exception as exc:
            raise VersionGateError(f"Could not read ISldWorks::RevisionNumber: {exc}") from exc
    else:
        if callable(value):
            value = value()
    return str(value)


def parse_revision_number(raw: str) -> SwRelease:
    """Parse a raw `RevisionNumber` string (`"major.sp.hotfix"`, e.g.
    `"33.0.0"`) into a `SwRelease`. Raises `VersionGateError` if `raw` does
    not match that shape."""
    text = (raw or "").strip()
    match = _REVISION_RE.match(text)
    if not match:
        raise VersionGateError(
            f"Could not parse SOLIDWORKS RevisionNumber {raw!r} -- expected "
            "'major.sp.hotfix' (e.g. '33.0.0' for SOLIDWORKS 2025)"
        )
    return SwRelease(
        major=int(match["major"]),
        service_pack=int(match["sp"]),
        hotfix=int(match["hotfix"]),
        raw=text,
    )


def get_connected_release(automation: Any) -> SwRelease:
    """The currently connected SOLIDWORKS release, read off `automation.app`
    (a `SolidWorksAutomation`-like object). Raises `VersionGateError` if
    nothing is connected or `RevisionNumber` can't be read/parsed."""
    app = getattr(automation, "app", automation)
    raw = read_revision_number(app)
    return parse_revision_number(raw)


def effective_min_release(tool_min_release: Optional[int]) -> Optional[int]:
    """The release a given tool actually requires: the project-wide floor
    (`config.min_release`, default 2025) unless the tool declares a higher
    `min_release` of its own -- a tool's own requirement is never silently
    lowered by relaxing the global floor.

    `tool_min_release=0` is a distinct, explicit "exempt from the gate
    entirely" sentinel (not "unspecified" -- that's the default `None`,
    which still gets the floor) and this returns `None` for it, since a
    discovery tool like `get_capabilities` has to stay callable precisely
    when the connected release *fails* the gate. `require_version` treats a
    `None` result as "always passes."
    """
    if tool_min_release == 0:
        return None
    floor = get_config().min_release
    if tool_min_release is None:
        return floor
    return max(floor, tool_min_release)


def _error_result(message: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "error_code": int(SwErrors.swVersionUnsupported),
        "error_name": SwErrors.swVersionUnsupported.name,
        "data": data,
    }


def require_version(
    automation: Any, tool_name: str, tool_min_release: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Gate `tool_name` against `automation`'s connected release.

    Returns the standard tool-result error dict (never raises) naming the
    connected version, the required version, and `tool_name` if the
    connected release is older than `effective_min_release(tool_min_release)`.
    Returns `None` -- gate passes -- when: `tool_min_release=0` exempts the
    tool entirely (`effective_min_release` returns `None`, e.g.
    `get_capabilities`); the connected release satisfies the requirement; or
    nothing is connected yet -- a handler that has not connected can't have
    called a deprecated overload yet either, and forcing a connection here
    (most tools connect lazily, and some, like `set_units`, never need to) is
    `dispatch`'s call to make, not the gate's.
    """
    required = effective_min_release(tool_min_release)
    if required is None:
        return None

    if not getattr(automation, "is_connected", False):
        return None

    try:
        release = get_connected_release(automation)
    except VersionGateError as exc:
        return _error_result(
            f"Could not determine the connected SOLIDWORKS version for '{tool_name}': {exc}",
            {"tool": tool_name, "required_release": required},
        )

    if release.year < required:
        return _error_result(
            f"Tool '{tool_name}' requires SOLIDWORKS {required} or newer; "
            f"connected instance is SOLIDWORKS {release.year} "
            f"(RevisionNumber {release.raw}). Upgrade SOLIDWORKS, or if this "
            "is intentional, lower `min_release` in solidworks_mcp/config.py.",
            {
                "tool": tool_name,
                "connected_release": release.year,
                "revision_number": release.raw,
                "required_release": required,
            },
        )

    return None
