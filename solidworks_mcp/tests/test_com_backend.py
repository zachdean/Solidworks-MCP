"""
Tests for the COM injection seam (`solidworks_mcp.com_backend`) and the fake
module pair that plugs into it (`solidworks_mcp.testing.fake_backend`).

The seam's whole job is to be swappable, so the thing worth pinning down is
that swapping it *unwinds* correctly: `conftest.py::make_sw` keeps a stack of
`install_fake_backend` context managers, so overlapping installs are ordinary
usage, not a corner case.
"""

import pytest

from solidworks_mcp import com_backend
from solidworks_mcp.testing import install_fake_backend


class TestBackendInjection:
    def test_install_makes_com_available_and_exit_restores(self):
        with install_fake_backend("part"):
            assert com_backend.is_com_available()
        assert not com_backend.is_com_available()

    def test_nested_installs_unwind_to_the_outer_backend(self):
        with install_fake_backend("part") as outer:
            with install_fake_backend("drawing") as inner:
                assert com_backend.get_win32com().Dispatch("SldWorks.Application") is inner
            # The inner teardown must not take the outer backend with it.
            assert com_backend.is_com_available()
            assert com_backend.get_win32com().Dispatch("SldWorks.Application") is outer
        assert not com_backend.is_com_available()

    def test_set_backend_token_round_trips(self):
        first_win32, first_pythoncom = object(), object()
        com_backend.set_backend(first_win32, first_pythoncom)
        try:
            previous = com_backend.set_backend(object(), object())
            com_backend.reset_backend(previous)
            assert com_backend.get_win32com() is first_win32
            assert com_backend.get_pythoncom() is first_pythoncom
        finally:
            com_backend.reset_backend()

    def test_missing_backend_raises_com_unavailable_error(self):
        com_backend.reset_backend()
        # `_load` only reaches a real import off an override, and pywin32 is
        # absent everywhere but Windows -- so only assert the error type where
        # there is genuinely nothing to import.
        if com_backend.is_com_available():
            pytest.skip("real pywin32 is installed on this host")
        with pytest.raises(com_backend.ComUnavailableError):
            com_backend.get_win32com()


class TestFakeVariants:
    def test_byref_int_exposes_a_mutable_value_box(self):
        """`documents.py::open_document` writes a VARIANT into an out-param
        and then reads `errors.value` back -- that attribute is the contract."""
        with install_fake_backend("part"):
            errors = com_backend.byref_int()
            assert errors.value == 0
            errors.value = 3
            assert errors.value == 3

    def test_null_dispatch_carries_a_none_value(self):
        with install_fake_backend("part"):
            assert com_backend.null_dispatch().value is None
