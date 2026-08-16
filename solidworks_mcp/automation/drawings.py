"""
SolidWorks Drawing Operations
------------------------------
Access and operate on drawing (.slddrw) documents.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from ..constants import SwErrors, SwDocumentTypes

logger = logging.getLogger(__name__)

_DOC_TYPE_NAMES = {
    SwDocumentTypes.swDocNONE: "no document",
    SwDocumentTypes.swDocPART: "Part",
    SwDocumentTypes.swDocASSEMBLY: "Assembly",
    SwDocumentTypes.swDocDRAWING: "Drawing",
    SwDocumentTypes.swDocSDM: "SDM",
    SwDocumentTypes.swDocLAYOUT: "Layout",
    SwDocumentTypes.swDocIMPORTED_PART: "Imported Part",
    SwDocumentTypes.swDocIMPORTED_ASSEMBLY: "Imported Assembly",
}


class DrawingOperations:
    """
    Mixin class for drawing document operations

    Requires parent class to have:
    - self._sw_app: SolidWorks application object
    - self.is_connected: Connection status property
    - self.connect(): Connection method
    - self._result(): Result factory method
    - self._units: UnitConverter instance

    Also uses `self.get_active_doc()` (defined on the base automation class)
    the same way the other operation mixins do.
    """

    def get_drawing_doc(self) -> Tuple[Any, Optional[Dict]]:
        """
        Get the active document with auto-connect, verifying it is a drawing.

        Like `get_active_doc`, but also checks `IModelDoc2::GetType` and
        fails with a clear error if the active document is not a drawing.

        Returns:
            Tuple of (document, error_result)
            - If successful: (document, None)
            - If failed (not connected, no active doc, or the active
              document isn't a drawing): (None, error_dict)
        """
        doc, err = self.get_active_doc()
        if err:
            return None, err

        doc_type = self._get_doc_type(doc)
        if doc_type != int(SwDocumentTypes.swDocDRAWING):
            type_name = _DOC_TYPE_NAMES.get(doc_type, f"unknown type {doc_type!r}")
            return None, self._result(
                False,
                f"Active document is a {type_name}, not a drawing. "
                "Open or create a drawing document first.",
                SwErrors.swInvalidInput,
            )

        return doc, None

    def _get_doc_type(self, doc) -> Optional[int]:
        """Get document type code (handles property/method difference)"""
        try:
            doc_type = doc.GetType
            if callable(doc_type):
                return doc_type()
            return doc_type
        except:
            return None
