"""
COM Parameter Signatures
------------------------
Typed positional-argument wrapper for parameter-heavy SolidWorks COM methods
(``SetupSheet5``, ``CreateSectionViewAt5``, ``InsertBomTable3``, ... -- all
take 10+ positional arguments). Declaring a `ComSignature` once, and binding
it by keyword, turns a parameter-order typo in tool code into a `bind()`
exception instead of a silently-wrong COM call.

    SETUP_SHEET5 = ComSignature("SetupSheet5", [
        Param("name"),
        Param("template", SwDwgPaperSizes.swDwgPaperA4size, enum_to_int),
        Param("scale_num", 1.0),
        Param("scale_denom", 1.0),
        Param("first_angle", True, to_bool),
        Param("width", 0.2794, to_meters),
        Param("height", 0.2159, to_meters),
    ])

    args = SETUP_SHEET5.bind(units=self._units, name="Sheet1")
    sheet = doc.SetupSheet5(*args)
"""

from dataclasses import dataclass
from math import radians
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import com_backend
from ..utils import UnitConverter

__all__ = [
    "REQUIRED",
    "Param",
    "ComSignature",
    "identity",
    "to_meters",
    "to_radians",
    "enum_to_int",
    "to_bool",
    "to_optional_object",
]


REQUIRED = object()
"""Sentinel for `Param.default`: no default value, so `bind()` raises if the
keyword is omitted."""


# ============================================================================
# Converters
# ============================================================================
#
# Every converter has the same shape -- `(value, units) -> converted_value`
# -- so `ComSignature.bind` can call them uniformly regardless of whether a
# given converter actually needs the `UnitConverter`.

def identity(value: Any, units: Optional[UnitConverter] = None) -> Any:
    """Pass the value through unchanged."""
    return value


def to_meters(value: Any, units: Optional[UnitConverter] = None) -> float:
    """Convert a dimension in the caller's default unit to meters -- the unit
    every SolidWorks COM dimension parameter expects.

    Raises:
        ValueError: if `units` is not supplied. There's no safe default unit
            to assume here -- guessing one would reintroduce exactly the
            silently-wrong-COM-call failure mode this module exists to rule
            out, just at conversion time instead of at parameter order.
    """
    if units is None:
        raise ValueError(
            "to_meters requires a UnitConverter -- pass units=self._units to bind()"
        )
    return units.to_meters(value)


def to_radians(value: Any, units: Optional[UnitConverter] = None) -> float:
    """Convert an angle in degrees to radians -- the unit every SolidWorks
    COM angle parameter expects."""
    return radians(value)


def enum_to_int(value: Any, units: Optional[UnitConverter] = None) -> int:
    """Coerce an `IntEnum` member (or a plain int) to the bare `int` COM
    expects."""
    return int(value)


def to_bool(value: Any, units: Optional[UnitConverter] = None) -> bool:
    """Coerce a value to the `bool` COM expects."""
    return bool(value)


def to_optional_object(value: Any, units: Optional[UnitConverter] = None) -> Any:
    """Coerce an optional COM object argument (`SelectByID2`'s `Callout`,
    `SaveAs3`'s `ExportData`, ...): `None` becomes a null `VT_DISPATCH`
    VARIANT, anything else passes through.

    A bare Python `None` is *not* what these arguments want -- SolidWorks'
    COM layer raises a type mismatch for it (the same failure
    `save_document` documents working around in SW 2025), which is why every
    hand-written `SelectByID2` call site in this package builds
    `com_backend.null_dispatch()` first. Declaring the param with this
    converter keeps that requirement in the signature rather than leaving it
    for each call site to remember.
    """
    if value is None:
        return com_backend.null_dispatch()
    return value


# JSON-schema `type` implied by a converter, used by `ComSignature.describe`.
# `identity` is intentionally absent -- its schema type (if any) is inferred
# from the param's default instead, since identity covers everything from
# strings to raw enum values.
_SCHEMA_TYPE_BY_CONVERTER: Dict[Callable, str] = {
    to_meters: "number",
    to_radians: "number",
    enum_to_int: "integer",
    to_bool: "boolean",
}


def _infer_schema_type(value: Any) -> Optional[str]:
    """Best-effort JSON-schema `type` for a plain Python default value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


# ============================================================================
# Param / ComSignature
# ============================================================================

@dataclass(frozen=True)
class Param:
    """One positional parameter of a COM method.

    Args:
        name: keyword name tool code binds by; also the property name in
            `ComSignature.describe()`.
        default: value substituted when `bind()`'s caller omits this
            keyword. `REQUIRED` (the default) means `bind()` raises if the
            keyword is missing.
        converter: `(value, units) -> converted_value`, applied to whatever
            `bind()` receives -- including a filled-in `default`, so e.g. a
            `to_meters` default of `0` still comes out as `0.0`, not raw
            millimeters.
    """

    name: str
    default: Any = REQUIRED
    converter: Callable[[Any, Optional[UnitConverter]], Any] = identity


class ComSignature:
    """Ordered parameter declaration for one COM method.

    `bind(**kwargs)` resolves `kwargs` against the declared params -- filling
    in defaults, applying converters, and validating -- and returns the
    positional-argument tuple ready to splat into the COM call.
    """

    def __init__(self, method_name: str, params: List[Param]):
        self.method_name = method_name
        self.params: Tuple[Param, ...] = tuple(params)

        names = [p.name for p in self.params]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"{method_name}: duplicate param name(s) {dupes!r}")

        self._by_name: Dict[str, Param] = {p.name: p for p in self.params}

    def bind(self, units: Optional[UnitConverter] = None, **kwargs: Any) -> Tuple[Any, ...]:
        """Resolve `kwargs` into the method's positional-argument tuple.

        Args:
            units: `UnitConverter` used by any `to_meters` param. Required
                if the signature has one; ignored otherwise. Note this is a
                real keyword-only parameter of `bind` itself, not part of
                `**kwargs` -- a `Param` literally named `"units"` would be
                unreachable (none of this project's COM signatures has one).
            **kwargs: values keyed by `Param.name`. Any name not declared on
                this signature raises `TypeError` -- a typo becomes a
                failure here rather than a silently-wrong COM call.

        Returns:
            Positional args in declaration order, each run through its
            `Param`'s converter.
        """
        unknown = sorted(set(kwargs) - set(self._by_name))
        if unknown:
            raise TypeError(
                f"{self.method_name}: unknown parameter(s) {unknown!r}; "
                f"expected one of {[p.name for p in self.params]!r}"
            )

        missing = []
        values = []
        for param in self.params:
            if param.name in kwargs:
                raw = kwargs[param.name]
            elif param.default is not REQUIRED:
                raw = param.default
            else:
                missing.append(param.name)
                continue
            values.append(param.converter(raw, units))

        if missing:
            raise TypeError(
                f"{self.method_name}: missing required parameter(s) {sorted(missing)!r}"
            )

        return tuple(values)

    def describe(self) -> Dict[str, Dict[str, Any]]:
        """JSON-schema `properties`-block shape for this signature:
        `{param_name: {"type": ..., "default": ...}}` (either key may be
        absent when it can't be inferred), suitable for building an MCP
        tool's `inputSchema`."""
        properties: Dict[str, Dict[str, Any]] = {}
        for param in self.params:
            schema: Dict[str, Any] = {}

            schema_type = _SCHEMA_TYPE_BY_CONVERTER.get(param.converter)
            if schema_type is None and param.default is not REQUIRED:
                schema_type = _infer_schema_type(param.default)
            if schema_type is not None:
                schema["type"] = schema_type

            if param.default is not REQUIRED:
                schema["default"] = param.default

            properties[param.name] = schema

        return properties
