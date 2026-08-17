"""
Shared pytest fixtures for the automation tool tests.
---------------------------------------------------------
Wires the `FakeSldWorks` recording harness into `com_backend`'s test-injection
seam (via `solidworks_mcp.testing.install_fake_backend`) so
`SolidWorksAutomation.connect()` succeeds against a fake COM object graph
instead of real pywin32.
"""

import pytest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.testing import install_fake_backend
from solidworks_mcp.tools import sw_automation


@pytest.fixture
def make_sw():
    """Factory for a `FakeSldWorks` installed as the active com_backend, torn
    down after the test. Takes the same arguments as `FakeSldWorks`, so a
    drawing-mode test is `make_sw("drawing")`."""
    with_stack = []

    def _make(doc_type="part", **kwargs):
        ctx = install_fake_backend(doc_type, **kwargs)
        with_stack.append(ctx)
        return ctx.__enter__()

    yield _make
    for ctx in reversed(with_stack):
        ctx.__exit__(None, None, None)


@pytest.fixture
def fake_sw(make_sw):
    """A part-mode `FakeSldWorks` installed as the active com_backend."""
    return make_sw("part")


@pytest.fixture
def automation(fake_sw):
    """A `SolidWorksAutomation` already connected to `fake_sw`."""
    auto = SolidWorksAutomation()
    result = auto.connect()
    assert result["success"], result
    return auto


@pytest.fixture
def tool_sw(make_sw):
    """Factory connecting the shared `tools.sw_automation` singleton -- what
    `dispatch()` actually calls through -- to a fresh fake
    `SldWorks.Application`, disconnected after the test.

    Defaults to a drawing document, since that's what the drawing tools
    require; pass `tool_sw("part")` for the wrong-document-type cases. A test
    module needing a different default can still define its own `tool_sw`,
    which shadows this one.
    """
    def _make(doc_type="drawing", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake

    yield _make
    sw_automation.disconnect()
