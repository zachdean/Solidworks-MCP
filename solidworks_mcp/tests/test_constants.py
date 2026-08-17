"""
Regression tests for the shared lookups on solidworks_mcp.constants.

`SwDocumentTypes.name_of` and `SwFileTypes.doc_type_for` replaced three
partial doc-type-name literals and two extension maps that had been
open-coded across `automation/documents.py` and `automation/drawings.py`.
These tests pin the consolidated behaviour so the copies can't quietly
come back.
"""

from solidworks_mcp import constants_drawing as cd
from solidworks_mcp.constants import SwDocumentTypes, SwFileTypes


class TestDocumentTypeNames:
    def test_every_member_has_a_name(self):
        for member in SwDocumentTypes:
            name = SwDocumentTypes.name_of(member)
            assert name and not name.startswith("unknown type")

    def test_names_of_the_three_common_types(self):
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocPART) == "Part"
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocASSEMBLY) == "Assembly"
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocDRAWING) == "Drawing"

    def test_accepts_a_raw_int_code(self):
        """`IModelDoc2::GetType` hands back a plain int, not an enum member."""
        assert SwDocumentTypes.name_of(3) == "Drawing"

    def test_covers_the_members_the_old_partial_maps_missed(self):
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocSDM) == "SDM"
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocLAYOUT) == "Layout"
        assert SwDocumentTypes.name_of(SwDocumentTypes.swDocIMPORTED_PART) == "Imported Part"

    def test_unknown_code_reports_the_code(self):
        assert SwDocumentTypes.name_of(99) == "unknown type 99"

    def test_non_numeric_code_does_not_raise(self):
        assert SwDocumentTypes.name_of(None) == "unknown type None"


class TestDocTypeForExtension:
    def test_maps_the_three_native_extensions(self):
        assert SwFileTypes.doc_type_for(".sldprt") == SwDocumentTypes.swDocPART
        assert SwFileTypes.doc_type_for(".sldasm") == SwDocumentTypes.swDocASSEMBLY
        assert SwFileTypes.doc_type_for(".slddrw") == SwDocumentTypes.swDocDRAWING

    def test_is_case_insensitive(self):
        assert SwFileTypes.doc_type_for(".SLDDRW") == SwDocumentTypes.swDocDRAWING

    def test_unknown_extension_falls_back_to_part(self):
        """The behaviour both former copies of this map already had."""
        assert SwFileTypes.doc_type_for(".step") == SwDocumentTypes.swDocPART
        assert SwFileTypes.doc_type_for("") == SwDocumentTypes.swDocPART


class TestDrawingConstantsExportSurface:
    def test_all_is_derived_from_the_module_contents(self):
        """`__all__` is computed, not hand-listed -- a new enum must appear in
        it (and hence in the package namespace) without any other edit."""
        public = {
            name for name, obj in vars(cd).items()
            if not name.startswith("_")
            and getattr(obj, "__module__", None) == cd.__name__
        }
        assert set(cd.__all__) == public

    def test_package_reexports_every_drawing_constant(self):
        import solidworks_mcp

        for name in cd.__all__:
            assert name in solidworks_mcp.__all__
            assert getattr(solidworks_mcp, name) is getattr(cd, name)
