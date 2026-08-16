"""
Regression tests for solidworks_mcp.constants_drawing.

Numeric values below are cross-checked against the `## Enums` sections of the
docs/api/ dossiers this module is sourced from, so a value changing here without
a corresponding dossier update should fail loudly.
"""

import enum

from solidworks_mcp import constants_drawing as cd
from solidworks_mcp.constants_drawing import decode_save_error


class TestWellKnownMemberValues:
    """Spot-check specific members against the dossier tables (docs/api/*.md)."""

    def test_paper_sizes(self):
        assert cd.SwDwgPaperSizes.swDwgPaperA4size == 6
        assert cd.SwDwgPaperSizes.swDwgPapersUserDefined == 12

    def test_projection_type(self):
        assert cd.SwDrawingProjectionType.swDrawing1stAngleProjection == 1
        assert cd.SwDrawingProjectionType.swDrawing3rdAngleProjection == 2

    def test_drawing_view_types(self):
        assert cd.SwDrawingViewTypes.swDrawingSectionView == 2
        assert cd.SwDrawingViewTypes.swDrawingDetailView == 3

    def test_view_display_mode(self):
        assert cd.SwViewDisplayMode.swViewDisplayMode_Wireframe == 1
        assert cd.SwViewDisplayMode.swViewDisplayMode_Shaded == 4

    def test_bom_type(self):
        assert cd.SwBomType.swBomType_Indented == 3
        assert cd.SwBomType.swBomType_Flattened == 4

    def test_bom_configuration_anchor_type(self):
        assert cd.SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_TopLeft == 1
        assert cd.SwBOMConfigurationAnchorType.swBOMConfigurationAnchor_BottomRight == 4

    def test_balloon_style(self):
        assert cd.SwBalloonStyle.swBS_Circular == 1
        assert cd.SwBalloonStyle.swBS_Verbose == 20

    def test_export_data_sheets_to_export(self):
        assert cd.SwExportDataSheetsToExport.swExportData_ExportSpecifiedSheets == 3

    def test_save_as_version(self):
        assert cd.SwSaveAsVersion.swSaveAsCurrentVersion == 0
        assert cd.SwSaveAsVersion.swSaveAsDetachedDrawing == 4

    def test_file_save_error_bits(self):
        assert cd.SwFileSaveError.swGenericSaveError == 1
        assert cd.SwFileSaveError.swReadOnlySaveError == 2
        assert cd.SwFileSaveError.swFileSaveAsDetachedDrawingsNotSupported == 16384

    def test_line_weights_includes_negative_none_value(self):
        assert cd.SwLineWeights.swLW_NONE == -1
        assert cd.SwLineWeights.swLW_NORMAL == 1

    def test_line_styles(self):
        assert cd.SwLineStyles.swLineCONTINUOUS == 0
        assert cd.SwLineStyles.swLineHIDDEN == 1

    def test_dxf_format(self):
        assert cd.SwDxfFormat.swDxfFormat_R12 == 0
        assert cd.SwDxfFormat.swDxfFormat_R2018 == 8


class TestModuleShape:
    def test_defines_at_least_25_enum_classes(self):
        classes = [
            v
            for v in vars(cd).values()
            if isinstance(v, type) and issubclass(v, enum.IntEnum) and v is not enum.IntEnum
        ]
        assert len(classes) >= 25

    def test_every_enum_class_is_an_intenum_with_int_members(self):
        classes = [
            v
            for v in vars(cd).values()
            if isinstance(v, type) and issubclass(v, enum.IntEnum) and v is not enum.IntEnum
        ]
        for enum_cls in classes:
            for member in enum_cls:
                assert isinstance(member.value, int)


class TestDecodeSaveError:
    def test_zero_is_success(self):
        result = decode_save_error(0)
        assert "success" in result.lower()

    def test_single_bit(self):
        result = decode_save_error(cd.SwFileSaveError.swGenericSaveError)
        assert "swGenericSaveError" in result

    def test_multi_bit_lists_every_set_bit(self):
        code = (
            cd.SwFileSaveError.swGenericSaveError
            | cd.SwFileSaveError.swReadOnlySaveError
            | cd.SwFileSaveError.swFileLockError
        )
        result = decode_save_error(code)
        assert "swGenericSaveError" in result
        assert "swReadOnlySaveError" in result
        assert "swFileLockError" in result

    def test_value_three_matches_verification_example(self):
        result = decode_save_error(3)
        assert "swGenericSaveError" in result
        assert "swReadOnlySaveError" in result
        assert "swFileNameEmpty" not in result

    def test_undocumented_bit_gap_is_surfaced_not_dropped(self):
        result = decode_save_error(0x40)
        assert "0x40" in result
        assert "unknown" in result.lower()

    def test_known_bits_combined_with_unknown_bit_reports_both(self):
        code = cd.SwFileSaveError.swGenericSaveError | 0x40
        result = decode_save_error(code)
        assert "swGenericSaveError" in result
        assert "unknown" in result.lower()
