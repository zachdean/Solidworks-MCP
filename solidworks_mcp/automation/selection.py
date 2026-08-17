"""
SolidWorks Selection Primitives
--------------------------------
Almost every annotation/dimension/GD&T call in the SolidWorks API acts on
whatever `ISelectionMgr` currently holds, not on an object reference passed
in as a parameter. Letting an LLM manage that selection state across
multiple tool calls invites stale-selection bugs (act on a selection left
over from a previous, unrelated call). The fix used throughout this
project: every annotation/view tool selects and acts atomically,
server-side, via the `selected(...)` context manager below -- `select_by_id`
and friends are exposed directly only as an escape hatch.

See `docs/api/03-annotations.md`'s "Selection primitives" section for the
source dossier `select_by_id`/`clear_selection` are built from.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict

from .com_params import ComSignature, Param, REQUIRED, enum_to_int, to_bool, to_meters
from ..constants import SwErrors

logger = logging.getLogger(__name__)

# `IView::GetVisibleEntities2`'s `EntityType` parameter is documented in
# docs/api/03-annotations.md as taking `swViewEntityType_e`, but that enum's
# own page was out of scope for the research pass that produced the dossier
# (see that record's Gotchas) -- these values are NOT sourced from
# docs/api/*.md. They match the well-known SOLIDWORKS `swViewEntityType_e`
# member values but are unverified against this project's own dossier
# standard; treat them as this wrapper's own convention.
_VIEW_ENTITY_TYPES = {
    "edge": 1,
    "face": 2,
    "vertex": 3,
}


class SelectionOperations:
    """
    Mixin class for the atomic select-then-act primitives every
    annotation/dimension/GD&T/view tool is built on.

    Requires parent class to have:
    - self.get_active_doc() / self.get_drawing_doc(): document accessors
    - self._result(): Result factory method
    - self._units: UnitConverter instance
    """

    # `IModelDocExtension::SelectByID2`'s positional signature, in the exact
    # order documented in docs/api/03-annotations.md:
    # Name, Type, X, Y, Z, Append, Mark, Callout, SelectOption.
    SELECT_BY_ID2 = ComSignature("SelectByID2", [
        Param("name"),
        Param("type_str"),
        Param("x", REQUIRED, to_meters),
        Param("y", REQUIRED, to_meters),
        Param("z", REQUIRED, to_meters),
        Param("append", False, to_bool),
        Param("mark", 0, enum_to_int),
        Param("callout", None),
        Param("sel_option", 0, enum_to_int),
    ])

    # ========================================================================
    # Selection primitives
    # ========================================================================

    def select_by_id(self, name: str, type_str: str, x: float, y: float, z: float,
                      append: bool = False, mark: int = 0, callout: Any = None,
                      sel_option: int = 0) -> Dict:
        """
        Select one entity via `IModelDocExtension::SelectByID2`.

        Args:
            name: Object name, or "" if unknown/not auto-named. Not valid for
                faces/edges/vertices -- use `type_str` + `x`/`y`/`z` instead.
            type_str: Uppercase `swSelectType_e` type string (e.g. "EDGE",
                "DRAWINGVIEW", "DIMENSION"), or "" for no type filtering.
            x, y, z: Selection point, in the caller's default unit (converted
                to meters here). Coordinate space depends on `name`: model
                space if `name` is "", else the space `name` was created in.
            append: `False` (default) clears any existing selection and
                selects just this entity. `True` toggles this entity in the
                existing selection list -- see SelectByID2's Append truth
                table in the dossier before using `True`.
            mark: Caller-chosen tag consumed by mark-aware downstream calls.
            callout: `ICallout` pointer, or `None` for none.
            sel_option: `swSelectOptionDefault` (0) or `swSelectOptionExtensive`.

        Returns:
            Result dict. On failure, `error_code` is `swSelectionError` --
            this method never raises for a failed selection.
        """
        doc, err = self.get_active_doc()
        if err:
            return err
        return self._select_by_id(doc, name, type_str, x, y, z,
                                  append, mark, callout, sel_option)

    def _select_by_id(self, doc, name: str, type_str: str, x: float, y: float, z: float,
                       append: bool, mark: int, callout: Any, sel_option: int) -> Dict:
        """`select_by_id` against an already-resolved document.

        `get_active_doc()` is two COM round-trips (the `is_connected`
        liveness probe plus `ActiveDoc`), so the select-then-act primitives
        resolve the document once and drive it directly rather than each
        composing the public, self-resolving methods.
        """
        try:
            args = self.SELECT_BY_ID2.bind(
                units=self._units,
                name=name, type_str=type_str, x=x, y=y, z=z,
                append=append, mark=mark, callout=callout, sel_option=sel_option,
            )
            selected = doc.Extension.SelectByID2(*args)
        except Exception as e:
            logger.error(f"select_by_id error: {e}")
            return self._result(False, f"Selection error: {e}", SwErrors.swSelectionError)

        data = {
            "name": name, "type": type_str,
            "x": x, "y": y, "z": z,
            "append": append, "mark": mark, "sel_option": sel_option,
        }
        display_name = repr(name) if name else "(unnamed)"

        if not selected:
            return self._result(
                False,
                f"Could not select {type_str or 'entity'} "
                f"{display_name} at ({x}, {y}, {z})",
                SwErrors.swSelectionError, data,
            )

        return self._result(
            True, f"Selected {type_str or 'entity'} {display_name}",
            SwErrors.swSuccess, data,
        )

    def clear_selection(self) -> Dict:
        """Clear the entire selection list via `IModelDoc2::ClearSelection2`."""
        doc, err = self.get_active_doc()
        if err:
            return err
        return self._clear_selection(doc)

    def _clear_selection(self, doc) -> Dict:
        """`clear_selection` against an already-resolved document -- see
        `_select_by_id` for why the primitives take `doc` directly."""
        try:
            doc.ClearSelection2(True)
        except Exception as e:
            logger.error(f"clear_selection error: {e}")
            return self._result(False, f"Clear selection error: {e}", SwErrors.swSelectionError)

        return self._result(True, "Selection cleared")

    def get_selection_info(self) -> Dict:
        """
        Report the current selection: count plus each selected object's
        `swSelectType_e` type code, via `ISelectionMgr`.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        try:
            sel_mgr = doc.SelectionManager
            count = int(sel_mgr.GetSelectedObjectCount2(-1))
        except Exception as e:
            logger.error(f"get_selection_info error: {e}")
            return self._result(False, f"Selection info error: {e}", SwErrors.swSelectionError)

        objects = []
        for index in range(1, count + 1):
            try:
                type_code = int(sel_mgr.GetSelectedObjectType3(index, -1))
            except Exception:
                type_code = None
            objects.append({"index": index, "type_code": type_code})

        return self._result(
            True, f"{count} object(s) selected", SwErrors.swSuccess,
            {"count": count, "objects": objects},
        )

    @contextmanager
    def selected(self, name: str, type_str: str, x: float = 0, y: float = 0, z: float = 0,
                 append: bool = False, mark: int = 0, callout: Any = None,
                 sel_option: int = 0):
        """
        Select-then-act context manager: clears any stale selection, selects
        the given entity via `select_by_id`, yields the selection result
        dict, and clears the selection again on exit -- including when the
        wrapped body raises.

        Selection failure itself never raises -- `select_by_id` always
        returns a structured result, so callers must check
        `result["success"]` before proceeding. The exception path this
        context manager guards against is the wrapped body's, not the
        selection call's.

        Every annotation/dimension/GD&T tool should wrap its `Create*`/
        `Insert*`/`Add*` call in this rather than calling `select_by_id` and
        the downstream method separately, so a failure partway through can
        never leave stale selection state for the next tool call.
        """
        doc, err = self.get_active_doc()
        if err:
            yield err
            return

        # One document resolution for all three COM calls; composing the
        # public `clear_selection`/`select_by_id` would re-resolve it three
        # times, and this primitive fronts every annotation tool.
        self._clear_selection(doc)
        result = self._select_by_id(doc, name, type_str, x, y, z,
                                    append, mark, callout, sel_option)
        try:
            yield result
        finally:
            self._clear_selection(doc)

    # ========================================================================
    # View selection / discovery
    # ========================================================================

    def select_view_by_name(self, view_name: str) -> Dict:
        """
        Resolve and activate an `IView` by name via `IDrawingDoc::ActivateView`
        -- the target of most drawing-view-scoped operations.
        """
        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            activated = doc.ActivateView(view_name)
        except Exception as e:
            logger.error(f"select_view_by_name error: {e}")
            return self._result(False, f"Select view error: {e}", SwErrors.swSelectionError)

        if not activated:
            return self._result(
                False,
                f"View {view_name!r} not found in this drawing (or it names a "
                "sheet, not a view -- use ActivateSheet for sheets)",
                SwErrors.swSelectionError, {"view_name": view_name},
            )

        return self._result(
            True, f"Selected view {view_name!r}", SwErrors.swSuccess,
            {"view_name": view_name},
        )

    def list_view_entities(self, view_name: str) -> Dict:
        """
        Enumerate pickable entities (edges, faces, vertices) in a drawing
        view via `IView::GetVisibleEntities2`, with a representative point
        per entity in the unit set by `set_units` -- so an LLM can pick an
        annotation target without a mouse.

        Point extraction is this wrapper's own convention, not documented in
        docs/api/03-annotations.md (that dossier's `GetVisibleEntities2`
        record only covers enumeration, not per-entity geometry access):
        vertex -> `IVertex::GetPoint`, edge -> `IEdge::GetStartPoint`,
        face -> the center of `IFace2::GetBox`'s bounding box.
        """
        # Activate via `select_view_by_name` rather than repeating its
        # `ActivateView` call, so the two tools report a missing view
        # identically by construction.
        activated = self.select_view_by_name(view_name)
        if not activated["success"]:
            return activated

        doc, err = self.get_drawing_doc()
        if err:
            return err

        try:
            view = doc.ActiveDrawingView
            component = view.RootDrawingComponent
            entities = []
            for kind, entity_type in _VIEW_ENTITY_TYPES.items():
                found = view.GetVisibleEntities2(component, entity_type) or []
                for entity in found:
                    x, y, z = self._entity_point(entity, kind)
                    entities.append({
                        "kind": kind,
                        "x": self._units.from_meters(x),
                        "y": self._units.from_meters(y),
                        "z": self._units.from_meters(z),
                    })
        except Exception as e:
            logger.error(f"list_view_entities error: {e}")
            return self._result(False, f"List view entities error: {e}", SwErrors.swSelectionError)

        return self._result(
            True, f"{len(entities)} entit{'y' if len(entities) == 1 else 'ies'} in view {view_name!r}",
            SwErrors.swSuccess, {"view_name": view_name, "entities": entities},
        )

    @staticmethod
    def _entity_point(entity: Any, kind: str) -> tuple:
        """Best-effort representative (x, y, z) in meters for one entity
        returned by `GetVisibleEntities2` -- see `list_view_entities`'
        docstring for the per-kind convention and its sourcing caveat."""
        if kind == "vertex":
            point = entity.GetPoint()
        elif kind == "edge":
            point = entity.GetStartPoint()
        elif kind == "face":
            box = entity.GetBox()
            return (
                (box[0] + box[3]) / 2.0,
                (box[1] + box[4]) / 2.0,
                (box[2] + box[5]) / 2.0,
            )
        else:
            raise ValueError(f"unknown entity kind {kind!r}")
        return point[0], point[1], point[2]
