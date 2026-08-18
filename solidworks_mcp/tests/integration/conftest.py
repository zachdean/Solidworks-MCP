"""
Shared fixtures for the Windows integration suite
---------------------------------------------------
Every test in this package drives the real `sw_automation` singleton
(`solidworks_mcp.tools._automation.sw_automation`) -- the same instance
`dispatch()` calls through -- against a real, running SolidWorks. Nothing
here is a fake/mock: `solidworks_mcp/testing/fake_com.py` is deliberately
not imported anywhere in this package.

Every test module under this package must set, at module scope::

    pytestmark = [
        pytest.mark.windows,
        pytest.mark.skipif(sys.platform != "win32", reason="requires Windows + SolidWorks"),
    ]

`skipif` short-circuits before any fixture (including the autouse ones
below) runs, so a skipped module never touches COM -- but the fixtures here
also check the platform themselves as a second line of defense, since a
test module that forgot the marker would otherwise be the only thing
standing between a `pytest -m windows` run and an attempted COM connection
on macOS.
"""
import sys
from pathlib import Path

import pytest

from solidworks_mcp.tools._automation import sw_automation
from solidworks_mcp.tools.registry import dispatch

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATED_DIR = REPO_ROOT / "tests" / "fixtures" / "generated"
BRACKET_PART = GENERATED_DIR / "bracket.sldprt"
BRACKET_ASSEMBLY = GENERATED_DIR / "bracket_assembly.sldasm"

_NOT_WINDOWS_REASON = "requires Windows + SolidWorks"


@pytest.fixture(scope="session", autouse=True)
def _require_windows():
    if sys.platform != "win32":
        pytest.skip(_NOT_WINDOWS_REASON)


@pytest.fixture(scope="session", autouse=True)
def _require_generated_fixtures(_require_windows):
    """Skip the whole suite with an actionable message if `scripts/
    make_test_geometry.py` hasn't been run yet, rather than failing every
    test with a confusing COM error from deep inside a missing-file open."""
    missing = [str(p) for p in (BRACKET_PART, BRACKET_ASSEMBLY) if not p.exists()]
    if missing:
        pytest.skip(
            f"Generated test geometry not found: {missing}. Run "
            "'python scripts/make_test_geometry.py' first."
        )


@pytest.fixture(scope="session", autouse=True)
def _connected(_require_generated_fixtures):
    """Connect the shared automation singleton once for the whole session,
    in the unit the generated fixtures were built in (mm)."""
    result = dispatch("connect_solidworks", {})
    assert result["success"], result["message"]
    units_result = dispatch("set_units", {"unit": "mm"})
    assert units_result["success"], units_result["message"]
    yield
    sw_automation.disconnect()


@pytest.fixture(autouse=True)
def _close_documents_after_test():
    """Close every document opened during a test, without saving -- so a
    test never leaks an open drawing/model into the next one, and a failed
    test doesn't leave dirty SolidWorks state behind. Bounded at 20 closes
    so a `close_document` that mysteriously never reduces the open-document
    count can't hang the suite."""
    yield
    for _ in range(20):
        info = dispatch("list_open_documents", {})
        documents = (info.get("data") or {}).get("documents", [])
        if not documents:
            break
        dispatch("close_document", {"save": False})


@pytest.fixture
def created_files():
    """A list a test appends output file paths to; every path still present
    is deleted after the test, regardless of pass/fail."""
    paths = []
    yield paths
    for raw_path in paths:
        path = Path(raw_path)
        if path.exists():
            path.unlink()
