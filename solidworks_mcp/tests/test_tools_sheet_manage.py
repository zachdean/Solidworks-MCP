"""
Regression tests for the sheet copy/delete/rename tools
(solidworks_mcp/tools/drawing_sheets.py: copy_sheet, delete_sheet,
rename_sheet), dispatched through the real `solidworks_mcp.tools` registry
(`dispatch()`) against the fake COM harness -- exercising both the registry
wiring and the `DrawingOperations` automation methods it calls, per
docs/api/01-documents-and-sheets.md's `PasteSheet`/`SetName` records.

`copy_sheet`/`delete_sheet` are both select-then-act *workarounds* (no direct
`CopySheet`/`DeleteSheet` COM API exists) -- these tests assert the exact
`SelectByID2`/`EditCopy`/`PasteSheet`/`DeleteSelection2` call sequence and
argument order, plus the "verify the count/name actually changed" guards
called for by this issue's acceptance criteria.
"""

from solidworks_mcp.tools import dispatch, registered_names

# `tool_sw` (the drawing-mode factory connecting the shared
# `tools.sw_automation` singleton that `dispatch()` calls through) comes from
# conftest.py.


def test_all_three_tools_are_registered():
    names = registered_names()
    assert "copy_sheet" in names
    assert "delete_sheet" in names
    assert "rename_sheet" in names


class TestCopySheet:
    def test_happy_path_single_copy_selects_copies_and_pastes(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1",),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Sheet1(2)"),
        ])
        fake_sw.ActiveDoc.set_sequence("GetSheetCount", [1, 2])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1"})

        assert result["success"] is True
        assert result["data"]["created"] == ["Sheet1(2)"]
        assert result["data"]["sheets"] == ["Sheet1", "Sheet1(2)"]
        [select_call] = fake_sw.call_log.calls_to("SelectByID2")
        assert select_call.args[:7] == ("Sheet1", "SHEET", 0.0, 0.0, 0.0, False, 0)
        assert fake_sw.call_log.calls_to("EditCopy")
        # swInsertOption_MoveToEnd=2, swRenameOption_No=2
        fake_sw.call_log.assert_called_with("PasteSheet", 2, 2)
        names = fake_sw.call_log.ordered_names()
        assert names.index("SelectByID2") < names.index("EditCopy") < names.index("PasteSheet")

    def test_count_three_produces_three_sheets_and_returns_names(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1",),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Sheet1(2)", "Sheet1(3)"),
            ("Sheet1", "Sheet1(2)", "Sheet1(3)", "Sheet1(4)"),
            ("Sheet1", "Sheet1(2)", "Sheet1(3)", "Sheet1(4)"),
        ])
        fake_sw.ActiveDoc.set_sequence("GetSheetCount", [1, 2, 3, 4])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1", "count": 3})

        assert result["success"] is True
        assert result["data"]["created"] == ["Sheet1(2)", "Sheet1(3)", "Sheet1(4)"]
        select_calls = fake_sw.call_log.calls_to("SelectByID2")
        assert [c.args[0] for c in select_calls] == ["Sheet1", "Sheet1", "Sheet1"]

    def test_new_name_renames_the_single_copy(self, tool_sw):
        fake_sw = tool_sw("drawing")
        # Four reads: copy_sheet's own before/after pair, then the delegated
        # rename_sheet's own pre-flight collision read and its post-SetName
        # verification read.
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1",),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Detail"),
        ])
        fake_sw.ActiveDoc.set_sequence("GetSheetCount", [1, 2])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)
        pasted_sheet = fake_sw.new_object("pasted_sheet")
        fake_sw.ActiveDoc.set_return("Sheet", pasted_sheet)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1", "new_name": "Detail"})

        assert result["success"] is True
        assert result["data"]["created"] == ["Detail"]
        assert result["data"]["sheets"] == ["Sheet1", "Detail"]
        fake_sw.call_log.assert_called_with("SetName", "Detail")

    def test_new_name_not_reflected_afterward_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        # SetName raised no exception, but the final sheet list still shows
        # the auto-generated name, not new_name -- SetName is a bare Sub
        # with no return value, so this is the only failure signal available.
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1",),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Sheet1(2)"),
            ("Sheet1", "Sheet1(2)"),
        ])
        fake_sw.ActiveDoc.set_sequence("GetSheetCount", [1, 2])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)
        pasted_sheet = fake_sw.new_object("pasted_sheet")
        fake_sw.ActiveDoc.set_return("Sheet", pasted_sheet)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1", "new_name": "Detail"})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"
        # The copy itself is still reported, so a caller can see what was
        # actually created before the rename failed.
        assert result["data"]["created"] == ["Sheet1(2)"]

    def test_new_name_with_count_other_than_one_errors_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("copy_sheet", {
            "source_sheet": "Sheet1", "new_name": "Detail", "count": 3,
        })

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetSheetNames")

    def test_invalid_count_errors_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1", "count": 0})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("GetSheetNames")

    def test_unknown_source_sheet_errors_listing_available(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))

        result = dispatch("copy_sheet", {"source_sheet": "Bogus"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["available_sheets"] == ["Sheet1"]
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_paste_sheet_returning_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))
        fake_sw.ActiveDoc.set_return("GetSheetCount", 1)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", False)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["created"] == []

    def test_sheet_count_not_increasing_after_paste_fails_the_guard(self, tool_sw):
        fake_sw = tool_sw("drawing")
        # PasteSheet reports success, but GetSheetCount never goes up --
        # this issue's acceptance criteria calls for catching exactly this
        # instead of trusting PasteSheet's own return value alone.
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))
        fake_sw.ActiveDoc.set_return("GetSheetCount", 1)
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert "count" in result["message"]
        assert result["data"]["created"] == []

    def test_sheet_count_increases_but_new_name_is_ambiguous_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        # GetSheetCount went up, but GetSheetNames doesn't show exactly one
        # new name -- can't identify which sheet is the copy.
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1",),
            ("Sheet1",),
        ])
        fake_sw.ActiveDoc.set_sequence("GetSheetCount", [1, 2])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.set_return("PasteSheet", True)

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"
        assert result["data"]["created"] == []

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("copy_sheet", {"source_sheet": "Sheet1"})

        assert result["success"] is False
        assert "Part" in result["message"]


class TestDeleteSheet:
    def test_happy_path_deletes_and_returns_remaining_sheets(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1", "Sheet2"),
            ("Sheet2",),
        ])
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_sheet", {"name": "Sheet1"})

        assert result["success"] is True
        assert result["data"]["sheets"] == ["Sheet2"]
        [select_call] = fake_sw.call_log.calls_to("SelectByID2")
        assert select_call.args[:7] == ("Sheet1", "SHEET", 0.0, 0.0, 0.0, False, 0)
        fake_sw.call_log.assert_called_with("DeleteSelection2", 0)

    def test_sheet_still_present_after_a_successful_delete_fails_the_guard(self, tool_sw):
        # DeleteSelection2 reports success but the sheet is still there --
        # SelectByID2 resolves by name and nothing guarantees the "SHEET"
        # selection landed on this sheet, so the post-delete re-read (which
        # delete_sheet performs anyway to report data["sheets"]) is checked
        # rather than ignored.
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", True)

        result = dispatch("delete_sheet", {"name": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"
        assert result["data"]["sheets"] == ["Sheet1", "Sheet2"]
        assert "still appears" in result["message"]

    def test_deleting_the_only_sheet_errors_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))

        result = dispatch("delete_sheet", {"name": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("SelectByID2")
        assert not fake_sw.call_log.calls_to("DeleteSelection2")

    def test_unknown_sheet_errors_listing_available(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))

        result = dispatch("delete_sheet", {"name": "Bogus"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["available_sheets"] == ["Sheet1", "Sheet2"]
        assert not fake_sw.call_log.calls_to("SelectByID2")

    def test_delete_selection2_returning_false_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))
        fake_sw.ActiveDoc.Extension.set_return("SelectByID2", True)
        fake_sw.ActiveDoc.Extension.set_return("DeleteSelection2", False)

        result = dispatch("delete_sheet", {"name": "Sheet1"})

        assert result["success"] is False
        assert result["error_name"] == "swFeatureError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("assembly")

        result = dispatch("delete_sheet", {"name": "Sheet1"})

        assert result["success"] is False
        assert "Assembly" in result["message"]


class TestRenameSheet:
    def test_happy_path_renames_and_reports_sheets(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_sequence("GetSheetNames", [
            ("Sheet1", "Sheet2"),
            ("Renamed", "Sheet2"),
        ])
        sheet = fake_sw.new_object("sheet1")
        fake_sw.ActiveDoc.set_return("Sheet", sheet)

        result = dispatch("rename_sheet", {"old_name": "Sheet1", "new_name": "Renamed"})

        assert result["success"] is True
        assert result["data"]["sheets"] == ["Renamed", "Sheet2"]
        fake_sw.call_log.assert_called_with("Sheet", "Sheet1")
        fake_sw.call_log.assert_called_with("SetName", "Renamed")

    def test_name_collision_errors_without_com_call(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))

        result = dispatch("rename_sheet", {"old_name": "Sheet1", "new_name": "Sheet2"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert not fake_sw.call_log.calls_to("Sheet")
        assert not fake_sw.call_log.calls_to("SetName")

    def test_unknown_old_name_errors_listing_available(self, tool_sw):
        fake_sw = tool_sw("drawing")
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1",))

        result = dispatch("rename_sheet", {"old_name": "Bogus", "new_name": "New"})

        assert result["success"] is False
        assert result["error_name"] == "swInvalidInput"
        assert result["data"]["available_sheets"] == ["Sheet1"]
        assert not fake_sw.call_log.calls_to("SetName")

    def test_setname_not_reflected_afterward_fails(self, tool_sw):
        fake_sw = tool_sw("drawing")
        # SetName raised no exception, but the sheet list somehow doesn't
        # show the rename -- SetName is a bare Sub with no return value, so
        # this is the only failure signal rename_sheet has available.
        fake_sw.ActiveDoc.set_return("GetSheetNames", ("Sheet1", "Sheet2"))
        sheet = fake_sw.new_object("sheet1")
        fake_sw.ActiveDoc.set_return("Sheet", sheet)

        result = dispatch("rename_sheet", {"old_name": "Sheet1", "new_name": "Renamed"})

        assert result["success"] is False
        assert result["error_name"] == "swUnknownError"

    def test_rejects_when_active_document_is_not_a_drawing(self, tool_sw):
        tool_sw("part")

        result = dispatch("rename_sheet", {"old_name": "Sheet1", "new_name": "Renamed"})

        assert result["success"] is False
        assert "Part" in result["message"]
