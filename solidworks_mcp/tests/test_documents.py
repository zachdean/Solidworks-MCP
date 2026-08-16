"""
Regression tests for solidworks_mcp.automation.documents (DocumentOperations),
exercised through `SolidWorksAutomation` bound to the fake COM harness.
"""

from solidworks_mcp.testing.fake_com import FakeComObject


class TestCreateNewPart:
    def test_happy_path(self, automation, fake_sw):
        new_doc = FakeComObject(fake_sw._scripts, fake_sw._log, "new_part", name="new_part")
        new_doc.set_return("GetTitle", "Part1")
        fake_sw.set_return("NewDocument", new_doc)

        result = automation.create_new_part()

        assert result["success"] is True
        assert result["data"] == {"name": "Part1", "type": "Part"}

    def test_com_returns_none(self, automation, fake_sw):
        fake_sw.set_return("NewDocument", None)

        result = automation.create_new_part()

        assert result["success"] is False
        assert result["error_name"] == "swFileLoadError"


class TestOpenDocument:
    def test_happy_path(self, automation, fake_sw, tmp_path):
        filepath = tmp_path / "Bracket.sldprt"
        filepath.write_text("stub")

        opened_doc = FakeComObject(fake_sw._scripts, fake_sw._log, "opened_doc", name="opened_doc")
        opened_doc.set_return("GetTitle", "Bracket")
        fake_sw.set_return("OpenDoc6", opened_doc)

        result = automation.open_document(str(filepath))

        assert result["success"] is True
        assert result["data"]["name"] == "Bracket"
        assert result["data"]["path"] == str(filepath)

    def test_file_not_found(self, automation, tmp_path):
        missing = tmp_path / "DoesNotExist.sldprt"

        result = automation.open_document(str(missing))

        assert result["success"] is False
        assert result["error_name"] == "swFileNotFoundError"

    def test_com_returns_none(self, automation, fake_sw, tmp_path):
        filepath = tmp_path / "Bracket.sldprt"
        filepath.write_text("stub")
        fake_sw.set_return("OpenDoc6", None)

        result = automation.open_document(str(filepath))

        assert result["success"] is False
        assert result["error_name"] == "swFileLoadError"


class TestSaveDocument:
    def test_save_as_happy_path(self, automation, fake_sw, tmp_path):
        doc = fake_sw.ActiveDoc
        doc.set_return("SaveAs", True)
        filepath = tmp_path / "out" / "Part1.sldprt"

        result = automation.save_document(str(filepath))

        assert result["success"] is True
        assert result["data"]["method"] == "SaveAs"
        assert result["data"]["path"] == str(filepath.resolve())

    def test_save_as_all_methods_fail(self, automation, fake_sw, tmp_path):
        doc = fake_sw.ActiveDoc
        # "SaveAs" bare-name key covers both doc.SaveAs and doc.Extension.SaveAs.
        doc.set_return("SaveAs", False)
        doc.set_return("SaveAs2", False)
        filepath = tmp_path / "Part1.sldprt"

        result = automation.save_document(str(filepath))

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"

    def test_save_in_place_happy_path(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.set_return("Save3", 0)
        doc.set_return("GetPathName", "/models/Part1.sldprt")

        result = automation.save_document()

        assert result["success"] is True
        assert result["data"]["path"] == "/models/Part1.sldprt"

    def test_save_in_place_nonzero_result_fails(self, automation, fake_sw):
        doc = fake_sw.ActiveDoc
        doc.set_return("Save3", 1)

        result = automation.save_document()

        assert result["success"] is False
        assert result["error_name"] == "swFileSaveError"
