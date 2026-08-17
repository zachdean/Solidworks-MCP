"""
SolidWorks MCP Drawing Constants
---------------------------------
IntEnum classes for the SolidWorks (`swconst`) drawing-related enums used by the
drawing tool layer: sheets, views, annotations, tables, and export/layers.

Every class and member here is sourced verbatim from the research dossiers under
``docs/api/`` produced for the drawing-infrastructure epic:

- ``docs/api/01-documents-and-sheets.md`` (documents, sheets, custom properties)
- ``docs/api/02-views.md`` (drawing view creation)
- ``docs/api/03-annotations.md`` (annotations, dimensions, GD&T)
- ``docs/api/04-tables.md`` (BOM, balloons, hole, revision, cut list tables)
- ``docs/api/05-export-and-layers.md`` (export, layers, line format)

No values are invented: where a dossier flagged a requested enum name as
nonexistent (e.g. ``swGtolShape_e``, ``swCreateDrawViewOption_e``,
``swSectionViewOptions_e``, ``swTableAnnotationAnchorType_e``,
``swHoleTableAnchorType_e``, ``swRevisionTableChangeType_e``), no class is defined
for it here -- see the corresponding dossier's ``## Enums`` section for the
verification trail. Where a dossier flagged an individual member's numeric value
as unverified (e.g. ``swBF_UserDef`` on ``swBalloonFit_e``) or "Obsolete" with no
published value, that member is omitted rather than guessed.

``SwDocumentTypes`` (``swDocumentTypes_e``, from ``01-documents-and-sheets.md``) is
not redefined here -- it already lives in ``solidworks_mcp.constants`` and is kept
there as the single source of truth.
"""

from enum import IntEnum


# ============================================================================
# 01-documents-and-sheets.md
# ============================================================================


class SwDwgTemplates(IntEnum):
    """Drawing sheet templates (swDwgTemplates_e).

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swDwgTemplateAsize = 0
    swDwgTemplateAsizeVertical = 1
    swDwgTemplateBsize = 2
    swDwgTemplateCsize = 3
    swDwgTemplateDsize = 4
    swDwgTemplateEsize = 5
    swDwgTemplateA4size = 6
    swDwgTemplateA4sizeVertical = 7
    swDwgTemplateA3size = 8
    swDwgTemplateA2size = 9
    swDwgTemplateA1size = 10
    swDwgTemplateA0size = 11
    swDwgTemplateCustom = 12
    swDwgTemplateNone = 13


class SwDwgPaperSizes(IntEnum):
    """Drawing sheet paper sizes (swDwgPaperSizes_e).

    Numerically parallel to :class:`SwDwgTemplates` for values 0-11 only; they
    diverge at value 12 (see docs/api/01-documents-and-sheets.md).

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swDwgPaperAsize = 0
    swDwgPaperAsizeVertical = 1
    swDwgPaperBsize = 2
    swDwgPaperCsize = 3
    swDwgPaperDsize = 4
    swDwgPaperEsize = 5
    swDwgPaperA4size = 6
    swDwgPaperA4sizeVertical = 7
    swDwgPaperA3size = 8
    swDwgPaperA2size = 9
    swDwgPaperA1size = 10
    swDwgPaperA0size = 11
    swDwgPapersUserDefined = 12


class SwDrawingProjectionType(IntEnum):
    """Drawing projection angle (swDrawingProjectionType_e).

    Requested in the source research issue as ``swDwgProjectionType_e``, which
    does not exist -- the real enum is ``swDrawingProjectionType_e``.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swDrawing1stAngleProjection = 1
    swDrawing3rdAngleProjection = 2


class SwInsertOptions(IntEnum):
    """Where to insert a pasted sheet relative to the selected sheet
    (swInsertOptions_e), used by IDrawingDoc::PasteSheet.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swInsertOption_BeforeSelectedSheet = 0
    swInsertOption_AfterSelectedSheet = 1
    swInsertOption_MoveToEnd = 2


class SwRenameOptions(IntEnum):
    """Whether IDrawingDoc::PasteSheet renames duplicate section/detail/
    auxiliary view names on the pasted sheet (swRenameOptions_e) -- not the
    sheet's own name.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swRenameOption_Yes = 1
    swRenameOption_No = 2


class SwSaveAsOptions(IntEnum):
    """Bitmask options for IModelDoc2::Save3 / IModelDocExtension::SaveAs3 (swSaveAsOptions_e).

    Bitmask enum -- combine members with bitwise OR. Obsolete members
    (``swSaveAsOptions_DetachedDrawing``, ``swSaveAsOptions_SaveEmodelData``) have
    no published numeric value and are omitted.

    Source: docs/api/01-documents-and-sheets.md and docs/api/05-export-and-layers.md
    (Enums sections; identical member set/values in both dossiers).
    """

    swSaveAsOptions_Silent = 1
    swSaveAsOptions_Copy = 2
    swSaveAsOptions_SaveReferenced = 4
    swSaveAsOptions_AvoidRebuildOnSave = 8
    swSaveAsOptions_UpdateInactiveViews = 16
    swSaveAsOptions_OverrideSaveEmodel = 32
    swSaveAsOptions_IgnoreBiography = 256
    swSaveAsOptions_CopyAndOpen = 512
    swSaveAsOptions_IncludeVirtualSubAsmComps = 1024
    swSaveAsOptions_ExportTo2DPdfFromInspection = 2048


class SwSaveAsVersion(IntEnum):
    """Format/version for IModelDocExtension::SaveAs3 (swSaveAsVersion_e).

    ``swSaveAsSW98plus`` is obsolete/no longer supported with no published value
    and is omitted.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swSaveAsCurrentVersion = 0
    swSaveAsFormatProE = 2
    swSaveAsStandardDrawing = 3
    swSaveAsDetachedDrawing = 4


class SwFileSaveError(IntEnum):
    """Bitmask save-error codes returned by Save3/SaveAs3's Errors out-param (swFileSaveError_e).

    Bitmask enum; not every set bit is a fatal failure -- see :func:`decode_save_error`.
    Note the documented bit gap at 0x40 (64): no member is published at that bit.
    ``swFileSaveWithRebuildError`` is obsolete (superseded by ``swFileSaveWarning_e``)
    with no published value and is omitted.

    Source: docs/api/01-documents-and-sheets.md and docs/api/05-export-and-layers.md
    (Enums sections; identical member set/values in both dossiers).
    """

    swGenericSaveError = 1
    swReadOnlySaveError = 2
    swFileNameEmpty = 4
    swFileNameContainsAtSign = 8
    swFileLockError = 16
    swFileSaveFormatNotAvailable = 32
    swFileSaveAsDoNotOverwrite = 128
    swFileSaveAsInvalidFileExtension = 256
    swFileSaveAsNoSelection = 512
    swFileSaveAsBadEDrawingsVersion = 1024
    swFileSaveAsNameExceedsMaxPathLength = 2048
    swFileSaveAsNotSupported = 4096
    swFileSaveRequiresSavingReferences = 8192
    swFileSaveAsDetachedDrawingsNotSupported = 16384


class SwFileSaveWarning(IntEnum):
    """Bitmask save-warning codes returned by Save3/SaveAs3's Warnings out-param (swFileSaveWarning_e).

    Bitmask enum; these do not cause the save to fail.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swFileSaveWarning_RebuildError = 1
    swFileSaveWarning_NeedsRebuild = 2
    swFileSaveWarning_ViewsNeedUpdate = 4
    swFileSaveWarning_AnimatorNeedToSolve = 8
    swFileSaveWarning_AnimatorFeatureEdits = 16
    swFileSaveWarning_EdrwingsBadSelection = 32
    swFileSaveWarning_AnimatorLightEdits = 64
    swFileSaveWarning_AnimatorCameraViews = 128
    swFileSaveWarning_AnimatorSectionViews = 256
    swFileSaveWarning_MissingOLEObjects = 512
    swFileSaveWarning_OpenedViewOnly = 1024
    swFileSaveWarning_XmlInvalid = 2048


class SwCustomInfoType(IntEnum):
    """Custom property value types (swCustomInfoType_e).

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swCustomInfoUnknown = 0
    swCustomInfoNumber = 3
    swCustomInfoDouble = 5
    swCustomInfoYesOrNo = 11
    swCustomInfoText = 30
    swCustomInfoDate = 64
    swCustomInfoEquation = 105


class SwCustomPropertyAddOption(IntEnum):
    """Behavior when adding a custom property that may already exist (swCustomPropertyAddOption_e).

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swCustomPropertyOnlyIfNew = 0
    swCustomPropertyDeleteAndAdd = 1
    swCustomPropertyReplaceValue = 2


class SwRebuildOptions(IntEnum):
    """Bitmask rebuild options consumed elsewhere in the API (swRebuildOptions_e).

    Bitmask enum. Not consumed by any method fetched in this dossier
    (``ForceRebuild3`` uses a plain ``TopOnly`` boolean instead) -- included for
    completeness since it is documented in the Enums section.

    Source: docs/api/01-documents-and-sheets.md (Enums section).
    """

    swRebuildAll = 1
    swForceRebuildAll = 2
    swUpdateMates = 4
    swCurrentSheetDisp = 8
    swUpdateDirtyOnly = 16


# ============================================================================
# 02-views.md
# ============================================================================


class SwDrawingViewTypes(IntEnum):
    """Drawing view kind, returned by IView::Type (swDrawingViewTypes_e).

    Source: docs/api/02-views.md (Enums section).
    """

    swDrawingSheet = 1
    swDrawingSectionView = 2
    swDrawingDetailView = 3
    swDrawingProjectedView = 4
    swDrawingAuxiliaryView = 5
    swDrawingStandardView = 6
    swDrawingNamedView = 7
    swDrawingRelativeView = 8
    swDrawingDetachedView = 9
    swDrawingAlternatePositionView = 10


class SwViewDisplayMode(IntEnum):
    """Drawing view display mode (swViewDisplayMode_e).

    Distinct from the legacy ``swDisplayMode_e`` used by
    ``IView::SetDisplayMode3``/``4`` -- do not conflate the two.

    Source: docs/api/02-views.md (Enums section).
    """

    swViewDisplayMode_Wireframe = 1
    swViewDisplayMode_HiddenLinesRemoved = 2
    swViewDisplayMode_HiddenLinesGrayed = 3
    swViewDisplayMode_Shaded = 4
    swViewDisplayMode_ShadedWithEdges = 5
    swViewDisplayMode_ShadedCurvatureOn = 6
    swViewDisplayMode_ShadedCurvatureOFF = 7
    swViewDisplayMode_StripesOn = 8
    swViewDisplayMode_StripesOff = 9
    swViewDisplayMode_PerspectiveOn = 10
    swViewDisplayMode_PerspectiveOff = 11
    swViewDisplayMode_Faceted = 12
    swViewDisplayMode_IntegratedPreview = 13


class SwDisplayStateOpts(IntEnum):
    """How a display state is specified for an operation (swDisplayStateOpts_e).

    Source: docs/api/02-views.md (Enums section).
    """

    swThisDisplayState = 1
    swAllDisplayState = 2
    swSpecifyDisplayState = 3


class SwDetCircleShowType(IntEnum):
    """Detail-view circle/profile sketch type (swDetCircleShowType_e).

    Requested as ``swDetailCircleStyle_e``, which does not exist -- the real
    enum backing ``IDrawingDoc::CreateDetailViewAt4``'s ``Showtype`` parameter is
    ``swDetCircleShowType_e``.

    Source: docs/api/02-views.md (Enums section).
    """

    swDetCirclePROFILE = 0
    swDetCircleCIRCLE = 1
    swDetCircleDONTSHOW = 2


class SwDetViewStyle(IntEnum):
    """Detail view border/leader style, for IDrawingDoc::CreateDetailViewAt4's
    ``Style`` parameter (swDetViewStyle_e) -- distinct from
    ``swDetCircleShowType_e`` (:class:`SwDetCircleShowType`, above), which
    governs the circle/profile sketch concept instead. Not the same enum as
    the task-spec-requested "style" name that turned out to actually mean
    ``Showtype``; see :class:`SwDetCircleShowType`'s own docstring.

    Not independently confirmed against a primary help.solidworks.com page
    body (the standing WAF block noted throughout docs/api/02-views.md) --
    corroborated by two independent secondary sources (an AI-search summary
    of a compiled SwConst.tlb transcription, and a direct fetch of a
    type-library-derived Pascal source mirror on GitHub) that agree on every
    member and value, and whose adjacent swDetCircleShowType_e listing
    matches this file's already-committed :class:`SwDetCircleShowType`
    exactly -- the same cross-check tier as ``SwUserPreferenceToggle``/
    ``CreateAuxiliaryViewAt2`` elsewhere in this module.

    Source: docs/api/02-views.md (Enums section, swDetViewStyle_e).
    """

    swDetViewSTANDARD = 0
    swDetViewBROKEN = 1
    swDetViewLEADER = 2
    swDetViewNOLEADER = 3
    swDetViewCONNECTED = 4


class SwCreateSectionViewAtOptions(IntEnum):
    """Bitmask options for IDrawingDoc::CreateSectionViewAt5 (swCreateSectionViewAtOptions_e).

    Requested as ``swSectionViewOptions_e``, which does not exist -- the real,
    current enum is ``swCreateSectionViewAtOptions_e``. Bitmask enum.

    Source: docs/api/02-views.md (Enums section).
    """

    swCreateSectionView_NotAligned = 1
    swCreateSectionView_OffsetSection = 2
    swCreateSectionView_ChangeDirection = 4
    swCreateSectionView_ScaleWithModel = 8
    swCreateSectionView_Partial = 16
    swCreateSectionView_DisplaySurfaceCut = 32
    swCreateSectionView_ExcludeFasteners = 64
    swCreateSectionView_CutSurfaceBodies = 128


class SwAlignViewTypes(IntEnum):
    """Drawing view alignment relative to a base view (swAlignViewTypes_e).

    Source: docs/api/02-views.md (Enums section).
    """

    swNoViewAlignment = 0
    swDefaultViewAlignment = 1
    swAlignViewHorizontalCenter = 2
    swAlignViewVerticalCenter = 3
    swAlignViewHorizontalOrigin = 4
    swAlignViewVerticalOrigin = 5


class SwBreakLineStyle(IntEnum):
    """Break line style for a drawing view break (swBreakLineStyle_e).

    Source: docs/api/02-views.md (Enums section).
    """

    swBreakLine_Straight = 1
    swBreakLine_ZigZag = 2
    swBreakLine_Curve = 3
    swBreakLine_SmallZigZag = 4
    swBreakLine_Jagged = 5


class SwUserPreferenceToggle(IntEnum):
    """Curated subset of application-level toggle system options
    (swUserPreferenceToggle_e), consumed by ISldWorks::GetUserPreferenceToggle /
    SetUserPreferenceToggle.

    This enum has hundreds of members and its own help.solidworks.com
    enumeration page publishes no numeric values for any of them (confirmed
    directly, and independently again in docs/api/05-export-and-layers.md's own
    curated subset of this same enum). Members here were tracked down via a
    third-party compiled SwConst.tlb transcription, not an official source --
    see docs/api/02-views.md's Enums section (swAutomaticScaling3ViewDrawings)
    and docs/api/05-export-and-layers.md's Enums section
    (swPDFExportHighQuality, cross-corroborated against
    swAutomaticScaling3ViewDrawings's already-trusted value from the same
    file) for the sourcing caveats.

    Source: docs/api/02-views.md and docs/api/05-export-and-layers.md
    (Enums sections, swUserPreferenceToggle_e).
    """

    swAutomaticScaling3ViewDrawings = 86
    swPDFExportHighQuality = 325

    #: `export_dxf_dwg`'s layer-mapping toggles (sw-jcq.2). Enable custom
    #: SOLIDWORKS-to-DXF/DWG layer mapping.
    swDxfMapping = 8
    #: Suppress the layer-mapping dialog popup on each save when
    #: `swDxfMapping = True` -- critical for unattended batch export.
    swDXFDontShowMap = 0x15


class SwBreakLineOrientation(IntEnum):
    """Break line orientation (swBreakLineOrientation_e).

    Requested as ``swBreakDir_e``, which does not exist -- the real enum is
    ``swBreakLineOrientation_e``.

    Source: docs/api/02-views.md (Enums section).
    """

    swBreakLineHorizontal = 1
    swBreakLineVertical = 2


class SwCropViewErrors(IntEnum):
    """Crop status returned by IView::Crop2 (swCropViewErrors_e).

    Success is ``swCropViewErrors_NoError`` (1), NOT 0/falsy -- 0 is
    ``swCropViewErrors_Unknown``, a distinct non-success value.

    Source: docs/api/02-views.md (``IView::Crop2`` record and Enums section).
    """

    swCropViewErrors_Unknown = 0
    swCropViewErrors_NoError = 1
    swCropViewErrors_CannotCropDetailOrBrokenView = 2
    swCropViewErrors_CannotUnfoldView = 3
    swCropViewErrors_IncorrectProfile = 4


class SwCommands(IntEnum):
    """Curated subset of `swCommands_e` command IDs consumed via
    ``ISldWorks::RunCommand``.

    Only the member this dossier's crop-removal workaround needs is listed
    here -- `swCommands_e` has hundreds of members and no accessible source
    publishes the full list; add more as specific tools need them.

    Source: docs/api/02-views.md (``ISldWorks::RunCommand`` record --
    ``swCommands_Tools_Crop_Delete`` maps to "RMB menu > Crop View > Remove Crop").
    """

    swCommands_Tools_Crop_Delete = 1389


class SwViewAlignment(IntEnum):
    """Alignment state returned by IView::GetAlignment (swViewAlignment_e).

    Distinct from :class:`SwAlignViewTypes` (``AlignWithView``'s input type) --
    this one reports whether a view is aligned to a parent and/or has aligned
    children, not what alignment to set.

    Not independently confirmed against a primary help.solidworks.com page body
    (added for sw-8ww.6; same corroboration tier as :class:`SwDetViewStyle`) --
    member names from a type-library mirror, numeric values from an independent
    search-engine synthesis of the (blocked) official enumeration page, in
    agreeing order. Treat the numeric values with more caution than this
    module's directly-fetched enums until verified against a live SolidWorks
    session.

    Source: docs/api/02-views.md (Enums section, swViewAlignment_e).
    """

    swViewAlignNone = 0
    swViewAlignedChildren = 1
    swViewAligned = 2
    swViewAlignBoth = 3


class SwDisplayMode(IntEnum):
    """Drawing view display mode for IView::SetDisplayMode3/4's ``Mode``
    parameter (swDisplayMode_e).

    Distinct from :class:`SwViewDisplayMode` (``swViewDisplayMode_e``, above) --
    ``SetDisplayMode3``/``4`` take this legacy enum specifically, not
    ``swViewDisplayMode_e``; see :class:`SwViewDisplayMode`'s own docstring.

    Source: docs/api/02-views.md (SetDisplayMode3 record's Gotchas, and the
    Enums section's swDisplayMode_e entry added for sw-8ww.6).
    """

    swWIREFRAME = 0
    swHIDDEN_GREYED = 1
    swHIDDEN = 2
    swSHADED = 3
    swFACETED_WIREFRAME = 4
    swFACETED_HIDDEN_GREYED = 5
    swFACETED_HIDDEN = 6
    swSHADED_EDGES = 7
    swDisplayModeDEFAULT = 8
    swDisplayModeUNKNOWN = -1


# ============================================================================
# 03-annotations.md
# ============================================================================


class SwInsertAnnotation(IntEnum):
    """Bitmask annotation types to insert via InsertModelAnnotations3/4 (swInsertAnnotation_e).

    Bitmask enum.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swInsertCThreads = 1
    swInsertDatums = 2
    swInsertDatumTargets = 4
    swInsertDimensions = 8
    swInsertInstanceCounts = 16
    swInsertGTols = 32
    swInsertNotes = 64
    swInsertSFSymbols = 128
    swInsertWelds = 256
    swInsertAxes = 512
    swInsertCurves = 1024
    swInsertPlanes = 2048
    swInsertSurfaces = 4096
    swInsertPoints = 8192
    swInsertOrigins = 16384
    swInsertDimensionsMarkedForDrawing = 32768
    swInsertHoleWizardProfileDimensions = 65536
    swInsertHoleWizardLocationDimensions = 131072
    swInsertRefPoints = 262144
    swInsertDimensionsNotMarkedForDrawing = 524288
    swInsertholeCallout = 1048576
    swInsertWeldBeads = 2097152
    swInsertSketches = 4194304
    swInsertWeldBeads_ET = 8388608
    swInsertTolerancedDims = 16777216
    swInsertCenterOfMass = 33554432


class SwImportModelItemsSource(IntEnum):
    """Source of dimensions for InsertModelAnnotations3/4's Option parameter (swImportModelItemsSource_e).

    Members 1 and 2 are the *corrected* meanings per the method's own Remarks --
    pre-2008-SP3 documentation had them swapped.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swImportModelItemsFromEntireModel = 0
    swImportModelItemsFromSelectedFeature = 1
    swImportModelItemsFromSelectedComponent = 2
    swImportModelItemsFromAssemblyOnly = 3


class SwAutodimScheme(IntEnum):
    """Autodimension scheme for ISketch::AutoDimension2 / IDrawingDoc::AutoDimension (swAutodimScheme_e).

    ``swAutodimSchemeCenterline`` is not supported in sketches or drawings.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swAutodimSchemeBaseline = 1
    swAutodimSchemeOrdinate = 2
    swAutodimSchemeChain = 3
    swAutodimSchemeCenterline = 4


class SwAutodimEntities(IntEnum):
    """Which entities to autodimension (swAutodimEntities_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swAutodimEntitiesBasedOnPreselect = 0
    swAutodimEntitiesAll = 1
    swAutodimEntitiesSelected = 2


class SwAutodimHorizontalPlacement(IntEnum):
    """Placement of the horizontal dimensions IDrawingDoc::AutoDimension creates
    (swAutodimHorizontalPlacement_e).

    Fetched independently (sw-1xx.2) -- out of scope for the original research
    pass, per that record's own Gotchas.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimHorizontalPlacement_e.html
    """

    swAutodimHorizontalPlacementBelow = -1
    swAutodimHorizontalPlacementAbove = 1


class SwAutodimVerticalPlacement(IntEnum):
    """Placement of the vertical dimensions IDrawingDoc::AutoDimension creates
    (swAutodimVerticalPlacement_e).

    Fetched independently (sw-1xx.2) -- see SwAutodimHorizontalPlacement.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimVerticalPlacement_e.html
    """

    swAutodimVerticalPlacementLeft = -1
    swAutodimVerticalPlacementRight = 1


class SwAutodimStatus(IntEnum):
    """Status returned by IDrawingDoc::AutoDimension (swAutodimStatus_e).

    Fetched independently (sw-1xx.2) -- see SwAutodimHorizontalPlacement.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swAutodimStatus_e.html
    """

    swAutodimStatusSuccess = 0
    swAutodimStatusBadOptionValue = 1
    swAutodimStatusNoActiveDoc = 2
    swAutodimStatusDocTypeNotSupported = 3
    swAutodimStatusNoActiveSketch = 4
    swAutodimStatus3DSketchNotSupported = 5
    swAutodimStatusSketchIsEmpty = 6
    swAutodimStatusSketchIsOverDefined = 7
    swAutodimStatusNoEntities = 8
    swAutodimStatusEntitiesNotValid = 9
    swAutodimStatusCenterlineNotAllowed = 10
    swAutodimStatusDatumNotSupplied = 11
    swAutodimStatusDatumNotUnique = 12
    swAutodimStatusDatumNotValidType = 13
    swAutodimStatusDatumLineNotCenterline = 14
    swAutodimStatusDatumLineNotVertical = 15
    swAutodimStatusDatumLineNotHorizontal = 16
    swAutodimStatusAlgorithmFailed = 17
    swAutodimStatusSketchNoSolutionFound = 18


class SwDimensionType(IntEnum):
    """Concrete dimension kind, around IDimension/IDisplayDimension (swDimensionType_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swDimensionTypeUnknown = 0
    swOrdinateDimension = 1
    swLinearDimension = 2
    swAngularDimension = 3
    swArcLengthDimension = 4
    swRadialDimension = 5
    swDiameterDimension = 6
    swHorOrdinateDimension = 7
    swVertOrdinateDimension = 8
    swZAxisDimension = 9
    swChamferDimension = 10
    swHorLinearDimension = 11
    swVertLinearDimension = 12
    swScalarDimension = 13
    swRadialLinearDimension = 14
    swDiametricLinearDimension = 15
    swAngularOrdinateDimension = 16


class SwSetValueInConfiguration(IntEnum):
    """WhichConfigurations for IDimension::SetValue3/SetSystemValue3
    (swSetValueInConfiguration_e).

    Fetched independently (sw-1xx.2) -- out of scope for the original research
    pass. ``swSetValue_NoConfiguration`` is `-1`, not a bit position -- this is a
    flat selector enum, not a bitmask.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSetValueInConfiguration_e.html
    """

    swSetValue_NoConfiguration = -1
    swSetValue_UseCurrentSetting = 0
    swSetValue_InThisConfiguration = 1
    swSetValue_InAllConfigurations = 2
    swSetValue_InSpecificConfigurations = 3


class SwInConfigurationOpts(IntEnum):
    """WhichConfigurations for IDimension::GetSystemValue3/GetValue3
    (swInConfigurationOpts_e) -- a *different* enum than the SetValue3/
    SetSystemValue3 setter side's ``swSetValueInConfiguration_e``, despite the
    shared "this configuration"/"all configurations" concepts (values happen to
    agree for ``swThisConfiguration`` == ``swSetValue_InThisConfiguration`` ==
    `1`, but do not assume the rest line up).

    Fetched independently (sw-1xx.2), while resolving IDimension::
    GetSystemValue3's own `WhichConfigurations` enum ref.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swInConfigurationOpts_e.html
    """

    swConfigPropertySuppressFeatures = 0
    swThisConfiguration = 1
    swAllConfiguration = 2
    swSpecifyConfiguration = 3
    swLinkedToParent = 4
    swSpeedpakConfiguration = 5


class SwSetValueReturnStatus(IntEnum):
    """Return status of IDimension::SetValue3/SetSystemValue3
    (swSetValueReturnStatus_e).

    Fetched independently (sw-1xx.2) -- see SwSetValueInConfiguration.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSetValueReturnStatus_e.html
    """

    swSetValue_Successful = 0
    swSetValue_Failure = 1
    swSetValue_InvalidValue = 2
    swSetValue_DrivenDimension = 3
    swSetValue_ModelNotLoaded = 4
    swSetValue_FrozenFeatureOwner = 5


class SwAddOrdinateDims(IntEnum):
    """DimType for IModelDocExtension::AddOrdinateDimension (swAddOrdinateDims_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swOrdinate = 1
    swVerticalOrdinate = 2
    swHorizontalOrdinate = 3
    swAngularOrdinate = 4


class SwCreateOrdDimError(IntEnum):
    """Return code of IModelDocExtension::AddOrdinateDimension
    (swCreateOrdDimError_e).

    Fetched independently (sw-1xx.2) -- out of scope for the original research
    pass. The page gives no description text per member beyond the name itself.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateOrdDimError_e.html
    """

    swCreateOrdDimErr_Undefined = -1
    swCreateOrdDimErr_Success = 0
    swCreateOrdDimErr_OrdFailure = 1
    swCreateOrdDimErr_GenNoInternalDims = 2
    swCreateOrdDimErr_GenBadSel = 3
    swCreateOrdDimErr_GenNeedModelLoaded = 4
    swCreateOrdDimErr_GenSamePartOnly = 5
    swCreateOrdDimErr_GenExtraSelection = 6
    swCreateOrdDimErr_GenFailure = 7
    swCreateOrdDimErr_OrdDupInGroup = 8
    swCreateOrdDimErr_OrdBadDir = 9


class SwTextJustification(IntEnum):
    """Note text justification, set post-creation via INote::SetTextJustification (swTextJustification_e).

    Requested as ``swTextAlign_e``, which does not exist.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swTextJustificationNone = 0
    swTextJustificationLeft = 1
    swTextJustificationCenter = 2
    swTextJustificationRight = 3


class SwDimensionTextParts(IntEnum):
    """WhichText for IDisplayDimension::SetText/GetText (swDimensionTextParts_e).

    Fetched independently (sw-1xx.2) -- out of scope for the original research
    pass. ``swDimensionTextAll`` is only valid for `SetText`, not `GetText` --
    see that record's own Gotchas in docs/api/03-annotations.md.

    Source: https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swDimensionTextParts_e.html
    """

    swDimensionTextAll = 0
    swDimensionTextPrefix = 1
    swDimensionTextSuffix = 2
    swDimensionTextCalloutAbove = 3
    swDimensionTextCalloutBelow = 4
    swDimensionTextPrefixDefinition = 5
    swDimensionTextSuffixDefinition = 6
    swDimensionTextCalloutAboveDefinition = 7
    swDimensionTextCalloutBelowDefinition = 8


class SwLeaderStyle(IntEnum):
    """Bitmask leader style/attachment (swLeaderStyle_e).

    The low-value members (``swNO_LEADER``..``swVDA``) are the leader shape; the
    ``swAttachLeader*`` and ``swAlwaysAttachToBalloon`` members are combined with a
    shape member via bitwise AND/OR, not used standalone.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swNO_LEADER = 0
    swSTRAIGHT = 1
    swBENT = 2
    swUNDERLINED = 3
    swSPLINE = 4
    swVDA = 8
    swAttachLeaderTop = 256
    swAttachLeaderCenter = 512
    swAttachLeaderBottom = 1024
    swAttachLeaderNearest = 2048
    swAlwaysAttachToBalloon = 4100


class SwDatumDisplayType(IntEnum):
    """Datum tag leader/shoulder display style (swDatumDisplayType_e).

    Requested as ``swDatumTagStyle_e``, which does not exist.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swDatumDisplayType_Default = 0
    swDatumDisplayType_Square = 1
    swDatumDisplayType_Round = 2


class SwSFSymType(IntEnum):
    """Surface finish symbol type for InsertSurfaceFinishSymbol3 (swSFSymType_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swSFBasic = 0
    swSFJIS_Machining_Req = 1
    swSFDont_Machine = 2
    swSFJIS_Surface_Texture_1 = 3
    swSFJIS_Surface_Texture_2 = 4
    swSFJIS_Surface_Texture_3 = 5
    swSFJIS_Surface_Texture_4 = 6
    swSFJIS_No_Machining = 7
    swSFJIS_Basic = 8
    swSFMachining_Req = 9


class SwSFLaySym(IntEnum):
    """Surface finish direction-of-lay symbol for InsertSurfaceFinishSymbol3 (swSFLaySym_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swSFNone = 0
    swSFCircular = 1
    swSFCross = 2
    swSFMultiDir = 3
    swSFParallel = 4
    swSFPerp = 5
    swSFRadial = 6
    swSFParticulate = 7


class SwArrowStyle(IntEnum):
    """Arrowhead style for InsertSurfaceFinishSymbol3, InsertDatumTargetSymbol3, and
    IAnnotation::SetArrowHeadStyleAtIndex (swArrowStyle_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swOPEN_ARROWHEAD = 0
    swCLOSED_ARROWHEAD = 1
    swSLASH_ARROWHEAD = 2
    swDOT_ARROWHEAD = 3
    swORIGIN_ARROWHEAD = 4
    swWIDE_ARROWHEAD = 5
    swISOWIDE_ARROWHEAD = 6
    swRUS_ARROWHEAD = 7
    swCLOSETOP_ARROWHEAD = 8
    swCLOSEBOT_ARROWHEAD = 9
    swNO_ARROWHEAD = 10
    swSHOULDER_ARROWHEAD = 11
    swSMART_ARROWHEAD = 12


class SwWeldSymbolContourTypes(IntEnum):
    """Weld symbol contour, consumed by IWeldSymbol::SetText's Contour parameter (swWeldSymbolContourTypes_e).

    Requested as ``swWeldSymbolType_e``, which does not exist -- a weld symbol's
    type/name is a fixed ISO string set, not an enum.

    Source: docs/api/03-annotations.md (Enums section).
    """

    swWeldContourNone = 1
    swWeldContourFlat = 2
    swWeldContourConvex = 3
    swWeldContourConcave = 4


class SwWeldSymbolField(IntEnum):
    """Field/site weld marking for IWeldSymbol::SetFieldWeld (swWeldSymbolField_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swFieldWeldNone = 1
    swFieldWeldUp = 2
    swFieldWeldDown = 3


class SwWeldSymbolSymmetric(IntEnum):
    """Symmetric weld characteristic for IWeldSymbol::SetSymmetric (swWeldSymbolSymmetric_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swWeldSymmetric = 1
    swWeldDashedLineOnTop = 2
    swWeldDashedLineOnBottom = 3


class SwCenterMarkStyle(IntEnum):
    """Center mark style for IDrawingDoc::InsertCenterMark3 (swCenterMarkStyle_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swCenterMark_NonAnnotation = 1
    swCenterMark_Single = 2
    swCenterMark_LinearGroup = 3
    swCenterMark_CircularGroup = 4


class SwCenterMarkConnectionLine(IntEnum):
    """Center mark connection-line visibility bitmask, for
    `ICenterMark::ConnectionLines` (swCenterMarkConnectionLine_e).

    Source: docs/api/03-annotations.md (sw-1xx.6 addendum, Enums section).
    """

    swCenterMark_ShowNoConnectLines = 0
    swCenterMark_ShowLinearConnectLines = 1
    swCenterMark_ShowCircularConnectLines = 2
    swCenterMark_ShowRadialConnectLines = 4
    swCenterMark_ShowBaseCenterMarkLines = 8


class SwAnnotationType(IntEnum):
    """Concrete annotation subtype (swAnnotationType_e).

    Source: docs/api/03-annotations.md (Enums section).
    """

    swCThread = 1
    swDatumTag = 2
    swDatumTargetSym = 3
    swDisplayDimension = 4
    swGTol = 5
    swNote = 6
    swSFSymbol = 7
    swWeldSymbol = 8
    swCustomSymbol = 9
    swDowelSym = 10
    swLeader = 11
    swBlock = 12
    swCenterMarkSym = 13
    swTableAnnotation = 14
    swCenterLine = 15
    swDatumOrigin = 16
    swWeldBeadSymbol = 17
    swRevisionCloud = 18
    swPMIOnly = 19


# ============================================================================
# 04-tables.md
# ============================================================================


class SwBomType(IntEnum):
    """BOM table type for InsertBomTable4/6's BomType parameter (swBomType_e).

    Source: docs/api/04-tables.md (Enums section).
    """

    swBomType_PartsOnly = 1
    swBomType_TopLevelOnly = 2
    swBomType_Indented = 3
    swBomType_Flattened = 4


class SwBOMConfigurationAnchorType(IntEnum):
    """Table anchor corner, shared by every table type's AnchorType (swBOMConfigurationAnchorType_e).

    Despite the task-spec-requested table-type-specific names
    (``swHoleTableAnchorType_e``, ``swTableAnnotationAnchorType_e``), every table
    type -- BOM, hole, weldment, revision, and general table annotations --
    consumes this single enum.

    Source: docs/api/04-tables.md (Enums section).
    """

    swBOMConfigurationAnchor_TopLeft = 1
    swBOMConfigurationAnchor_TopRight = 2
    swBOMConfigurationAnchor_BottomLeft = 3
    swBOMConfigurationAnchor_BottomRight = 4


class SwNumberingType(IntEnum):
    """Indented BOM numbering type (swNumberingType_e).

    Valid only when BomType is swBomType_Indented.

    Source: docs/api/04-tables.md (Enums section).
    """

    swNumberingType_None = 0
    swNumberingType_Detailed = 1
    swNumberingType_Flat = 2


class SwBalloonStyle(IntEnum):
    """Balloon shape style for InsertBOMBalloon / IAutoBalloonOptions::Style (swBalloonStyle_e).

    Source: docs/api/04-tables.md (Enums section).
    """

    swBS_None = 0
    swBS_Circular = 1
    swBS_Triangle = 2
    swBS_Hexagon = 3
    swBS_Box = 4
    swBS_Diamond = 5
    swBS_Pentagon = 6
    swBS_SplitCirc = 7
    swBS_FlagPentagon = 8
    swBS_FlagTriangle = 9
    swBS_Underline = 10
    swBS_Square = 11
    swBS_SCircle = 12
    swBS_Inspection = 13
    swBS_ArcBracket = 14
    swBS_RectBracket = 15
    swBS_ArclenSym = 16
    swBS_FixedSym = 17
    swBS_DoubleArrow = 18
    swBS_SplitSquare = 19
    swBS_Verbose = 20


class SwBalloonFit(IntEnum):
    """Balloon size for InsertBOMBalloon / IAutoBalloonOptions::Size (swBalloonFit_e).

    ``swBF_UserDef`` is a real member (referenced by ``CustomSize`` properties) but
    its numeric value was not independently confirmed on the enum's own page and
    is omitted here rather than guessed.

    Source: docs/api/04-tables.md (Enums section).
    """

    swBF_Tightest = 0
    swBF_1Char = 1
    swBF_2Chars = 2
    swBF_3Chars = 3
    swBF_4Chars = 4
    swBF_5Chars = 5


class SwBalloonTextContent(IntEnum):
    """Balloon upper/lower text content source (swBalloonTextContent_e).

    Source: docs/api/04-tables.md (Enums section).
    """

    swBalloonTextCustom = 0
    swBalloonTextItemNumber = 1
    swBalloonTextQuantity = 2
    swBalloonTextCustomProperties = 3
    swBalloonTextComponentReference = 4
    swBalloonTextSpoolReference = 5
    swBalloonTextPartNumberBOM = 6
    swBalloonTextFileName = 7
    swBalloonTextCutlistProperties = 8
    swBalloonTextViewSheet = 9
    swBalloonTextViewSheetWithLabel = 10
    swBalloonTextViewZone = 11
    swBalloonTextViewViewLetter = 12


class SwBalloonLayoutType(IntEnum):
    """Auto-balloon layout for AutoBalloon4 / IAutoBalloonOptions::Layout (swBalloonLayoutType_e).

    Source: docs/api/04-tables.md (Enums section).
    """

    swDetailingBalloonLayout_Square = 1
    swDetailingBalloonLayout_Circle = 2
    swDetailingBalloonLayout_Top = 3
    swDetailingBalloonLayout_Bottom = 4
    swDetailingBalloonLayout_Right = 5
    swDetailingBalloonLayout_Left = 6


class SwTableAnnotationType(IntEnum):
    """Concrete table kind, returned by ITableAnnotation::Type (swTableAnnotationType_e).

    Source: docs/api/04-tables.md (Enums section).
    """

    swTableAnnotation_General = 0
    swTableAnnotation_HoleChart = 1
    swTableAnnotation_BillOfMaterials = 2
    swTableAnnotation_RevisionBlock = 3
    swTableAnnotation_WeldmentCutList = 4
    swTableAnnotation_TitleBlock = 5
    swTableAnnotation_WeldTable = 6
    swTableAnnotation_BendTable = 7
    swTableAnnotation_PunchTable = 8
    swTableAnnotation_GeneralTolerance = 9
    swTableAnnotation_FamilyTable = 10


# ============================================================================
# 05-export-and-layers.md
# ============================================================================


class SwExportDataFileType(IntEnum):
    """File type for ISldWorks::GetExportFileData's FileType parameter (swExportDataFileType_e).

    Source: docs/api/05-export-and-layers.md (Enums section).
    """

    swExportPdfData = 1


class SwExportDataSheetsToExport(IntEnum):
    """Which sheets to export, for IExportPdfData::SetSheets's Which parameter (swExportDataSheetsToExport_e).

    Source: docs/api/05-export-and-layers.md (Enums section).
    """

    swExportData_ExportAllSheets = 1
    swExportData_ExportCurrentSheet = 2
    swExportData_ExportSpecifiedSheets = 3


class SwDxfMultisheet(IntEnum):
    """Per-sheet vs. whole-document DXF/DWG export mode (swDxfMultisheet_e).

    Set via swUserPreferenceIntegerValue_e.swDxfMultiSheetOption before calling
    SaveAs/SaveAs3/SaveAs4 on a multi-sheet drawing.

    Source: docs/api/05-export-and-layers.md (Enums section).
    """

    swDxfActiveSheetOnly = 0
    swDxfSeparateSheets = 1
    swDxfMultiSheet = 2


class SwUserPreferenceIntegerValue(IntEnum):
    """Curated subset of application-level integer-valued system options
    (swUserPreferenceIntegerValue_e), consumed by
    ISldWorks::GetUserPreferenceIntegerValue / SetUserPreferenceIntegerValue.

    Same "own enumeration page publishes no numeric values" situation as
    SwUserPreferenceToggle above (confirmed independently in
    docs/api/05-export-and-layers.md). Members here were tracked down via the
    same third-party SwConst_TLB.pas transcription already trusted for
    SwUserPreferenceToggle -- see that class's docstring and
    docs/api/05-export-and-layers.md's Enums section (swUserPreferenceIntegerValue_e
    numeric-values note, sw-jcq.2) for the sourcing/corroboration caveats.

    Source: docs/api/05-export-and-layers.md (Enums section,
    swUserPreferenceIntegerValue_e table).
    """

    swDxfVersion = 0
    swDxfOutputFonts = 1
    swDxfMappingFileIndex = 2
    swDxfOutputLineStyles = 0x87
    swDxfOutputNoScale = 0x88
    swEdrawingsSaveAsSelectionOption = 0xED
    swDxfMultiSheetOption = 0xFD


class SwUserPreferenceStringListValue(IntEnum):
    """String-list-valued application system options
    (swUserPreferenceStringListValue_e), consumed by
    ISldWorks::GetUserPreferenceStringListValue / SetUserPreferenceStringListValue.

    Source: docs/api/05-export-and-layers.md (Enums section,
    swUserPreferenceStringListValue_e -- status: unverified, see that
    record's Gotchas for the sourcing/parameter-shape caveats).
    """

    swDxfMappingFiles = 0


class SwEdrawingSaveAsOption(IntEnum):
    """Which sheets/content an eDrawings export includes
    (swEdrawingSaveAsOption_e), consumed as the Value argument of
    ISldWorks::SetUserPreferenceIntegerValue when UserPreferenceValue is
    SwUserPreferenceIntegerValue.swEdrawingsSaveAsSelectionOption.

    Source: docs/api/05-export-and-layers.md (Enums section,
    swEdrawingSaveAsOption_e -- status: unverified, see that record's
    Gotchas for the sourcing caveats).
    """

    swEdrawingSaveActive = 1
    swEdrawingSaveAll = 2
    swEdrawingSaveSelected = 3


class SwLineWeights(IntEnum):
    """Line weights used in layers (swLineWeights_e).

    Consumed by ILayerMgr::AddLayer's WidthIn, ILayer::Width, and
    IDrawingDoc::SetLineWidth's Width.

    Source: docs/api/05-export-and-layers.md (Enums section).
    """

    swLW_NONE = -1
    swLW_THIN = 0
    swLW_NORMAL = 1
    swLW_THICK = 2
    swLW_THICK2 = 3
    swLW_THICK3 = 4
    swLW_THICK4 = 5
    swLW_THICK5 = 6
    swLW_THICK6 = 7
    swLW_NUMBER = 8
    swLW_LAYER = 9
    swLW_CUSTOM = 10


class SwLineStyles(IntEnum):
    """Line styles used in drawings (swLineStyles_e).

    Consumed by ILayerMgr::AddLayer's StyleIn, ILayer::Style, and
    IDrawingDoc::SetLineStyle's StyleName.

    Source: docs/api/05-export-and-layers.md (Enums section).
    """

    swLineCONTINUOUS = 0
    swLineHIDDEN = 1
    swLinePHANTOM = 2
    swLineCHAIN = 3
    swLineCENTER = 4
    swLineSTITCH = 5
    swLineCHAINTHICK = 6
    swLineDEFAULT = 7


class SwDxfFormat(IntEnum):
    """DXF/DWG output format version, for swUserPreferenceIntegerValue_e.swDxfVersion (swDxfFormat_e).

    The dossier spells out only the first member in full
    (``swDxfFormat_R12`` = 0) and abbreviates the rest ("R13"=1, "R14"=2, ...
    "R2018"=8); the remaining member names below follow that same
    ``swDxfFormat_<release>`` pattern. All numeric values are as stated in the
    dossier.

    Source: docs/api/05-export-and-layers.md (Enums section, swUserPreferenceIntegerValue_e table).
    """

    swDxfFormat_R12 = 0
    swDxfFormat_R13 = 1
    swDxfFormat_R14 = 2
    swDxfFormat_R2000 = 3
    swDxfFormat_R2004 = 4
    swDxfFormat_R2007 = 5
    swDxfFormat_R2010 = 6
    swDxfFormat_R2013 = 7
    swDxfFormat_R2018 = 8


# ============================================================================
# Save-error decoding
# ============================================================================


def decode_save_error(code: int) -> str:
    """Decode a swFileSaveError_e bitmask value into a human-readable description.

    ``code`` is the ``Errors`` out-parameter from ``IModelDoc2::Save3`` or
    ``IModelDocExtension::SaveAs3`` -- a bitwise OR of :class:`SwFileSaveError`
    members. Per the dossier, the bit range has a documented gap at ``0x40``
    (64) and future SOLIDWORKS versions may add bits not covered by this
    module, so any bit not matching a known :class:`SwFileSaveError` member is
    reported explicitly rather than silently dropped.
    """
    if code == 0:
        return "0: success (no save errors)"

    parts = []
    remaining = code
    for member in sorted(SwFileSaveError, key=lambda m: m.value):
        if member.value and (code & member.value) == member.value:
            parts.append(f"{member.name} (0x{member.value:x})")
            remaining &= ~member.value

    if remaining:
        parts.append(f"unknown bit(s) (0x{remaining:x})")

    return f"{code}: " + "; ".join(parts)


# Derived rather than hand-listed: every public name *defined in this module*
# (the `__module__` test excludes the imported `IntEnum`). `solidworks_mcp`'s
# package `__init__` re-exports this wholesale, so adding an enum here needs no
# edit anywhere else -- it previously took two more alphabetized lists.
__all__ = sorted(
    name for name, obj in list(globals().items())
    if not name.startswith("_") and getattr(obj, "__module__", None) == __name__
)
