"""
Regression tests for the drawing document/session tools
(solidworks_mcp/tools/drawing_documents.py), dispatched through the real
`solidworks_mcp.tools` registry (`dispatch()`) against the fake COM harness --
so these exercise both the registry wiring and the `DrawingOperations`
automation methods it calls, and assert COM call order/args against the
fake's call log the same way the automation-layer tests do.

Dispatch goes through the module-level `solidworks_mcp.tools.sw_automation`
singleton (the same instance `server.py` uses), not a fresh
`SolidWorksAutomation()`, so each test connects/disconnects it explicitly via
the `tool_sw` fixture below rather than using `conftest.py`'s `automation`
fixture (which wraps a different, throwaway instance).
"""

import pytest

from solidworks_mcp.constants import SwDocumentTypes
from solidworks_mcp.constants_drawing import (
    SwCustomInfoType,
    SwCustomPropertyAddOption,
    SwDwgPaperSizes,
    SwFileSaveError,
)
from solidworks_mcp.tools import dispatch, sw_automation


@pytest.fixture
def tool_sw(make_sw):
    """Factory mirroring conftest.py's `make_sw`, but connects the shared
    `tools.sw_automation` singleton (what `dispatch()` actually calls
    through) instead of a private `SolidWorksAutomation()` instance."""
    def _make(doc_type="part", **kwargs):
        fake = make_sw(doc_type, **kwargs)
        connected = sw_automation.connect()
        assert connected["success"], connected
        return fake
    yield _make
    sw_automation.disconnect()


class TestNewDrawingFromTemplate:
    def test_happy_path(self, tool_sw):
        fake_sw = tool_sw("part")
        new_doc = fake_sw.new_object("new_drawing")
        new_doc.set_return("GetTitle", "Draw1")
        new_doc.set_return("GetSheetNames", ["Sheet1"])
        fake_sw.set_return("NewDocument", new_doc)

        result = dispatch("new_drawing_from_template", {
            "template_path": "/templates/Drawing.drwdot",
            "paper_size": "A3",
            "orientation": "landscape",
        })

        assert result["success"] is True
        assert result["data"]["name"] == "Draw1"
        assert result["data"]["sheet_name"] == "Sheet1"
        fake_sw.call_log.assert_called_with(
            "NewDocument", "/templates/Drawing.drwdot",
            int(SwDwgPaperSizes.swDwgPaperA3size), 0, 0,
        )

    def test_falls_back_to_template_discovery_and_errors_when_none_found(
        self, tool_sw, monkeypatch,
    ):
        tool_sw("part")
        monkeypatch.setattr("solidworks_mcp.automation.drawings.find_template", lambda t: None)

        result = dispatch("new_drawing_from_template", {})

        assert result["success"] is False
        assert result["error_name"] == "swTemplateNotFound"


class TestGetDocumentType:
    def test_happy_path(self, tool_sw):
        tool_sw("assembly")

        result = dispatch("get_document_type", {})

        assert result["success"] is True
        assert result["data"] == {"type": "Assembly", "type_code": int(SwDocumentTypes.swDocASSEMBLY)}

    def test_no_active_document_fails(self, tool_sw):
        fake_sw = tool_sw("part")
        fake_sw.ActiveDoc = None

        result = dispatch("get_document_type", {})

        assert result["success"] is False
        assert result["error_name"] == "swNoActiveDocument"


class TestOpenOrActivateDocument:
    def test_opens_when_not_already_loaded(self, tool_sw, tmp_path):
        fake_sw = tool_sw("part")
        filepath = tmp_path / "Bracket.sldprt"
        filepath.write_text("stub")
        opened_doc = fake_sw.new_object("opened")
        opened_doc.set_return("GetTitle", "Bracket.SLDPRT")
        fake_sw.set_return("OpenDoc6", opened_doc)

        result = dispatch("open_or_activate_document", {
            "filepath": str(filepath), "read_only": True, "lightweight": True,
        })

        assert result["success"] is True
        assert result["data"]["activated"] is False
        log = fake_sw.call_log
        assert log.arg_of("OpenDoc6", 0) == str(filepath)
        assert log.arg_of("OpenDoc6", 1) == int(SwDocumentTypes.swDocPART)
        assert log.arg_of("OpenDoc6", 2) == 2 | 128  # read_only | lightweight bits
        assert log.arg_of("OpenDoc6", 3) == ""

    def test_activates_when_already_loaded(self, tool_sw, tmp_path):
        """`GetTitle` reports SolidWorks' own casing (e.g. the uppercased
        extension), which won't match a caller-supplied lowercase path
        byte-for-byte -- the match (and the `ActivateDoc3` call) must be
        case-insensitive, and must pass SolidWorks' own reported title back,
        not the caller's guessed casing."""
        fake_sw = tool_sw("part")
        filepath = tmp_path / "Bracket.sldprt"
        filepath.write_text("stub")
        existing = fake_sw.new_object("existing")
        existing.set_return("GetTitle", "Bracket.SLDPRT")
        fake_sw.set_return("GetFirstDocument", existing)
        fake_sw.set_return("ActivateDoc3", existing)

        result = dispatch("open_or_activate_document", {"filepath": str(filepath)})

        assert result["success"] is True
        assert result["data"]["activated"] is True
        assert result["data"]["name"] == "Bracket.SLDPRT"
        log = fake_sw.call_log
        assert log.arg_of("ActivateDoc3", 0) == "Bracket.SLDPRT"
        assert log.arg_of("ActivateDoc3", 1) is True
        assert not log.calls_to("OpenDoc6")

    def test_file_not_found_fails(self, tool_sw, tmp_path):
        tool_sw("part")
        missing = tmp_path / "DoesNotExist.sldprt"

        result = dispatch("open_or_activate_document", {"filepath": str(missing)})

        assert result["success"] is False
        assert result["error_name"] == "swFileNotFoundError"


class TestRebuildDocument:
    def test_force_rebuild_happy_path(self, tool_sw):
        fake_sw = tool_sw("assembly")
        fake_sw.ActiveDoc.set_return("ForceRebuild3", True)

        result = dispatch("rebuild_document", {"force": True, "top_level_only": True})

        assert result["success"] is True
        fake_sw.call_log.assert_called_with("ForceRebuild3", True)
        assert not fake_sw.call_log.calls_to("EditRebuild3")

    def test_incremental_rebuild_failure(self, tool_sw):
        fake_sw = tool_sw("part")
        fake_sw.ActiveDoc.set_return("EditRebuild3", False)

        result = dispatch("rebuild_document", {"force": False})

        assert result["success"] is False
        fake_sw.call_log.assert_called_with("EditRebuild3")


class TestSaveDrawing:
    def test_save_in_place_happy_path(self, tool_sw):
        fake_sw = tool_sw("drawing")
        doc = fake_sw.ActiveDoc
        doc.set_return("Save3", True)
        doc.set_return("GetPathName", "/models/Draw1.slddrw")

        result = dispatch("save_drawing", {})

        assert result["success"] is True
        assert result["data"]["path"] == "/models/Draw1.slddrw"
        assert result["data"]["errors"] == 0
        assert "success" in result["data"]["decoded_errors"]

    def test_save_as_happy_path_passes_errors_and_warnings_byref(self, tool_sw, tmp_path):
        fake_sw = tool_sw("drawing")
        doc = fake_sw.ActiveDoc
        doc.Extension.set_return("SaveAs3", True)
        filepath = tmp_path / "out" / "Draw1.slddrw"

        result = dispatch("save_drawing", {"filepath": str(filepath)})

        assert result["success"] is True
        assert result["data"]["path"] == str(filepath)
        log = fake_sw.call_log
        assert log.arg_of("SaveAs3", 0) == str(filepath)
        assert log.arg_of("SaveAs3", 1) == 0  # swSaveAsCurrentVersion

    def test_nonzero_save_error_fails_even_if_return_value_is_truthy(self, tool_sw):
        fake_sw = tool_sw("drawing")
        doc = fake_sw.ActiveDoc
        # Deliberately contradictory scripting: a truthy return alongside a
        # nonzero Errors byref -- the "silent pass" bug this tool must not have.
        doc.set_return("Save3", True)
        doc.set_byref("Save3", {1: int(SwFileSaveError.swReadOnlySaveError), 2: 0})

        result = dispatch("save_drawing", {})

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
        assert result["data"]["errors"] == int(SwFileSaveError.swReadOnlySaveError)
        assert "swReadOnlySaveError" in result["data"]["decoded_errors"]
        assert "swReadOnlySaveError" in result["message"]


class TestGetCustomProperties:
    def test_happy_path(self, tool_sw):
        fake_sw = tool_sw("part")
        doc = fake_sw.ActiveDoc
        mgr = fake_sw.new_object("mgr")
        doc.Extension.set_return("CustomPropertyManager", mgr)
        mgr.set_return("GetNames", ["PartNo", "Description"])
        mgr.set_byref("Get6", {2: "raw", 3: "resolved-value"})

        result = dispatch("get_custom_properties", {})

        assert result["success"] is True
        assert result["data"]["properties"] == {
            "PartNo": "resolved-value", "Description": "resolved-value",
        }
        log = fake_sw.call_log
        assert log.arg_of("CustomPropertyManager", 0) == ""
        assert len(log.calls_to("Get6")) == 2

    def test_manager_access_failure(self, tool_sw):
        fake_sw = tool_sw("part")
        fake_sw.ActiveDoc.Extension.set_raises("CustomPropertyManager", RuntimeError("boom"))

        result = dispatch("get_custom_properties", {"configuration": "Config1"})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"


class TestSetCustomProperties:
    def test_happy_path(self, tool_sw):
        fake_sw = tool_sw("part")
        doc = fake_sw.ActiveDoc
        mgr = fake_sw.new_object("mgr")
        doc.Extension.set_return("CustomPropertyManager", mgr)
        mgr.set_return("Add3", 0)

        result = dispatch("set_custom_properties", {
            "properties": {"PartNo": "12345", "Description": "Bracket"},
        })

        assert result["success"] is True
        assert result["data"]["results"]["PartNo"] == {"success": True, "result_code": 0}
        assert result["data"]["results"]["Description"] == {"success": True, "result_code": 0}
        log = fake_sw.call_log
        assert log.arg_of("Add3", 0, call_index=0) == "PartNo"
        assert log.arg_of("Add3", 1, call_index=0) == int(SwCustomInfoType.swCustomInfoText)
        assert log.arg_of("Add3", 2, call_index=0) == "12345"
        assert log.arg_of("Add3", 3, call_index=0) == int(SwCustomPropertyAddOption.swCustomPropertyReplaceValue)

    def test_tolerates_missing_properties_key(self, tool_sw):
        tool_sw("part")

        result = dispatch("set_custom_properties", {})

        assert result["success"] is True
        assert result["data"]["results"] == {}

    def test_one_failing_key_fails_the_overall_result(self, tool_sw):
        """A single failing Add3 call must not be masked by other keys
        succeeding -- the same "no silent pass" requirement save_drawing has."""
        fake_sw = tool_sw("part")
        doc = fake_sw.ActiveDoc
        mgr = fake_sw.new_object("mgr")
        doc.Extension.set_return("CustomPropertyManager", mgr)
        mgr.set_raises("Add3", RuntimeError("boom"))

        result = dispatch("set_custom_properties", {"properties": {"PartNo": "12345"}})

        assert result["success"] is False
        assert result["data"]["results"]["PartNo"]["success"] is False

    def test_manager_access_failure(self, tool_sw):
        fake_sw = tool_sw("part")
        fake_sw.ActiveDoc.Extension.set_raises("CustomPropertyManager", RuntimeError("boom"))

        result = dispatch("set_custom_properties", {"properties": {"PartNo": "12345"}})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"
