"""
Recording fake-COM harness for SolidWorks objects
---------------------------------------------------
Every drawing/feature/sketch tool in this project is ultimately a thin
wrapper around calls onto a `win32com.client` COM object (`SldWorks.Application`,
its `ActiveDoc`, `FeatureManager`, `SketchManager`, ...). None of that is
available off Windows, so the only way to verify a tool without a real
SolidWorks install is to replace the COM object with something that:

1. never raises `AttributeError` for an unknown COM member (SolidWorks
   objects are deep, and the tools chain through them freely, e.g.
   `doc.SketchManager.InsertSketch(True)`),
2. can be asked, after the fact, exactly which methods were called, with
   which positional arguments, in which order (this project cares a lot
   about unit conversion to meters -- an argument being `50` instead of
   `0.05` is a real bug), and
3. can be scripted ahead of time to return specific values, return a
   different value on each successive call, or raise, so both the happy
   path and the error-handling path of a tool can be exercised.

This module provides that: `FakeComObject` (the recording, auto-vivifying
stand-in for any COM object/interface), `CallLog` (the record of what
happened), and `FakeSldWorks` (a factory that wires up a plausible
`SldWorks.Application` -> `ActiveDoc` object graph so most tools work
against it with no further setup).

The property-vs-method problem
===============================
SolidWorks' COM type library is inconsistent about whether a given member
is exposed as a property or a method across versions -- see
`tools/features.py::_list_features_fixed`, which has to try `feat.GetTypeName2` as
a property and fall back to `feat.GetTypeName2()` as a method. A fake
attribute therefore has to work usable *both* ways: `x.Foo` on its own
(compared, stringified, used as a value) and `x.Foo()` (called). Every
attribute `FakeComObject` hands back is such a dual-purpose object: it is
always callable, and it also behaves like whatever value has been scripted
for it (or, if nothing has been scripted, like a fresh child object you can
keep chaining through).

Quick start
===========

    from solidworks_mcp.testing.fake_com import FakeSldWorks

    app = FakeSldWorks("part")
    doc = app.ActiveDoc

    # Script what CreateCircle should hand back so the tool's success path runs.
    doc.SketchManager.set_return("CreateCircle", object())

    result = my_tool(app)  # calls doc.SketchManager.InsertSketch(True), etc.

    log = app.call_log
    log.assert_called_with("InsertSketch", True)
    assert log.arg_of("CreateCircle", 0) == 0.025          # 25mm -> meters
    assert log.ordered_names() == ["InsertSketch", "CreateCircle"]

Scripting successive calls (e.g. walking a `FirstFeature` / `GetNextFeature`
chain) and forcing an error path:

    feat1, feat2 = app.new_object("feat1"), None
    doc.set_sequence("GetNextFeature", [feat1, feat2])

    doc.SketchManager.set_raises("InsertSketch", RuntimeError("no active sketch"))

`set_return` / `set_sequence` / `set_raises` all key on a *name*, matched
(most specific first) against the exact object-graph path
(`"app.ActiveDoc.SketchManager.InsertSketch"`), a declared COM interface
name (`"IDrawingDoc.CreateDrawViewFromModelView3"`, once the owning object
has been `.tag()`-ed), or the bare method name (`"InsertSketch"`) -- pick
whichever is precise enough for the scenario. `FakeSldWorks` pre-scripts
`FirstFeature` to return `None`, so feature-walking loops terminate
immediately unless a test explicitly scripts a chain.

Limitations
===========
A bare, uncalled attribute access (`feat = doc.FirstFeature`, with no `()`
and no `callable(...)` check afterwards) hands back the dual-purpose
wrapper itself, not the raw scripted value -- there is no way to make a
wrapper satisfy `is None`/`is True` (those are identity checks on Python
singletons, which cannot be spoofed), so compare it with `==`/`bool()`
instead. The explicit call form (`x.Foo()`) always resolves to the real
scripted value directly. If a value needs to be a genuine Python primitive
(e.g. for JSON serialization, or because calling code only ever does bare
`feat.Name` with no callable-check), script it explicitly with
`set_return`/`set_sequence` rather than relying on auto-vivify defaults.
`FakeSldWorks` also pre-scripts `GetNextFeature` to return `None`, so a
`FirstFeature`/`GetNextFeature` walk that uses the callable-check idiom
(`feat = feat.GetNextFeature; if callable(feat): feat = feat()`) is bounded
to at most one iteration by default instead of looping forever.

The *unguarded* form of that walk -- `while feat is not None: feat =
feat.GetNextFeature`, which `automation/features.py` uses -- can't be
terminated by any scripted value, because each bare access hands back a new
truthy wrapper. Auto-vivification is therefore capped at
`_MAX_CHAIN_DEPTH` levels, past which the chain raises
`FakeComHarnessError` instead of growing forever; production's bare
`except:` around those walks turns that into a clean loop exit. To exercise
such a walk deliberately, assign the raw terminator
(`feat.GetNextFeature = None`), which stores the literal value rather than
a wrapper -- see `tests/test_features.py::_install_profile_sketch`.
"""

from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

__all__ = [
    "Call",
    "CallLog",
    "FakeComHarnessError",
    "FakeComObject",
    "FakeSldWorks",
]


class FakeComHarnessError(BaseException):
    """The harness itself was driven past what it can honestly answer -- a
    `set_sequence` ran out of scripted values, or an unscripted attribute
    chain auto-vivified past `_MAX_CHAIN_DEPTH`.

    Deliberately a `BaseException` rather than an `Exception`: every COM call
    site in `automation/` is wrapped in `except Exception` (or a bare
    `except:`), so an `Exception` here would be swallowed and re-emerge as a
    plausible-looking `swFeatureError` result -- a test asserting on the
    error path would then pass for entirely the wrong reason. Production's
    *bare* `except:` clauses still catch this, which is what bounds the
    runaway walks described in the module docstring's Limitations section.
    """


# ============================================================================
# Call log
# ============================================================================

class Call(NamedTuple):
    """One recorded interaction with a `FakeComObject`.

    `args`/`kwargs` are `None` for a bare attribute read (e.g. `x.Foo`
    without calling it) and a `(tuple, dict)` pair -- possibly empty -- for
    an actual invocation (`x.Foo()`). This is how the log tells "was this
    ever called" apart from "was this ever merely referenced".
    """
    path: str
    name: str
    args: Optional[Tuple[Any, ...]]
    kwargs: Optional[Dict[str, Any]]


class CallLog:
    """Ordered record of every attribute access and invocation across a
    `FakeComObject` graph, plus query helpers for assertions."""

    def __init__(self) -> None:
        self.calls: List[Call] = []

    def record(self, path: str, name: str, args, kwargs) -> Call:
        call = Call(path, name, args, kwargs)
        self.calls.append(call)
        return call

    def invocations(self) -> List[Call]:
        """All log entries that are actual `()` invocations."""
        return [c for c in self.calls if c.args is not None]

    def calls_to(self, name: str) -> List[Call]:
        """Invocations of `name`, in call order."""
        return [c for c in self.invocations() if c.name == name]

    def ordered_names(self) -> List[str]:
        """Method names in the order they were actually invoked."""
        return [c.name for c in self.invocations()]

    def assert_called_with(self, name: str, *args) -> Call:
        """Assert `name` was invoked at least once with exactly `args`
        (positional only). Returns the matching `Call`."""
        matches = self.calls_to(name)
        if not matches:
            raise AssertionError(
                f"{name!r} was never called; calls made: {self.ordered_names()!r}"
            )
        for call in matches:
            if call.args == args:
                return call
        raise AssertionError(
            f"{name!r} was called, but never with args {args!r}; "
            f"actual calls: {[call.args for call in matches]!r}"
        )

    def arg_of(self, name: str, index: int, call_index: int = 0) -> Any:
        """The positional argument at `index` of the `call_index`-th
        invocation of `name` (default: the first invocation)."""
        matches = self.calls_to(name)
        if not matches:
            raise AssertionError(f"{name!r} was never called")
        try:
            call = matches[call_index]
        except IndexError:
            raise AssertionError(
                f"{name!r} was only called {len(matches)} time(s); no call #{call_index}"
            )
        try:
            return call.args[index]
        except IndexError:
            raise AssertionError(
                f"{name!r} call #{call_index} only has {len(call.args)} positional arg(s)"
            )


# ============================================================================
# Scripted returns / sequences / raises
# ============================================================================

_UNSET = object()


class _ScriptedSequence:
    """A finite list of scripted values with a cursor, supporting a
    non-destructive `peek()` alongside the consuming `advance()`, so
    property-style access can preview the next value without consuming it."""

    def __init__(self, values: Iterable[Any]) -> None:
        self._values: List[Any] = list(values)
        self._index = 0

    def peek(self) -> Any:
        if self._index >= len(self._values):
            return _UNSET
        return self._values[self._index]

    def advance(self, key: str) -> Any:
        if self._index >= len(self._values):
            raise FakeComHarnessError(f"scripted sequence for {key!r} is exhausted")
        value = self._values[self._index]
        self._index += 1
        return value


class _ScriptRegistry:
    """Scripted returns/sequences/raises, shared by every `FakeComObject`
    in one object graph so scripting can be done from any node."""

    def __init__(self) -> None:
        self.returns: Dict[str, Any] = {}
        self.sequences: Dict[str, _ScriptedSequence] = {}
        self.raises: Dict[str, BaseException] = {}


# ============================================================================
# FakeComObject
# ============================================================================

_INTERNAL_ATTRS = frozenset({
    "_scripts", "_log", "_path", "_owner_path", "_name", "_owner_com_type",
    "_com_type", "_children", "_depth",
})

# How deep an *unscripted* attribute/call chain may auto-vivify before the
# harness calls it a runaway. Real SolidWorks chains are a handful of levels
# (`app.ActiveDoc.SketchManager.InsertSketch`), so this only ever trips on a
# loop -- the `while feat is not None: feat = feat.GetNextFeature` walks in
# `automation/features.py`, which no fake can terminate (see the module
# docstring's Limitations section: bare access cannot satisfy `is None`).
# Without the cap those loops spin until the process is killed.
_MAX_CHAIN_DEPTH = 64


class FakeComObject:
    """Recording, auto-vivifying stand-in for a SolidWorks COM object.

    Every attribute access records itself onto the shared `CallLog` and
    hands back a child `FakeComObject` (cached, so repeated access returns
    the same object) that is *both* usable as a value (compared, stringified,
    truth-tested against whatever has been `set_return`/`set_sequence`
    scripted for it) and callable (recording the call, and resolving
    `set_raises` / `set_sequence` / `set_return`, in that priority order, or
    auto-vivifying a fresh child if nothing was scripted).
    """

    def __init__(
        self,
        scripts: _ScriptRegistry,
        log: CallLog,
        path: str,
        name: str = "",
        owner_path: str = "",
        owner_com_type: Optional[str] = None,
        com_type: Optional[str] = None,
        depth: int = 0,
    ) -> None:
        object.__setattr__(self, "_depth", depth)
        object.__setattr__(self, "_scripts", scripts)
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_owner_path", owner_path)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_owner_com_type", owner_com_type)
        object.__setattr__(self, "_com_type", com_type)
        object.__setattr__(self, "_children", {})

    # -- graph traversal ---------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        children = self._children
        if name not in children:
            # Only the auto-vivify path is capped -- an explicitly assigned or
            # already-cached child is a deliberate, finite piece of scripting.
            if self._depth >= _MAX_CHAIN_DEPTH:
                raise FakeComHarnessError(
                    f"unscripted attribute chain ran past {_MAX_CHAIN_DEPTH} levels at "
                    f"{self._path}.{name} -- a caller is almost certainly looping over "
                    f"an auto-vivified chain that can never compare `is None`. Script "
                    f"the terminator explicitly, e.g. `obj.{name} = None`."
                )
            children[name] = FakeComObject(
                self._scripts,
                self._log,
                f"{self._path}.{name}",
                name=name,
                owner_path=self._path,
                owner_com_type=self._com_type,
                depth=self._depth + 1,
            )
        self._log.record(self._path, name, None, None)
        return children[name]

    def __setattr__(self, name: str, value: Any) -> None:
        # `app.Visible = True` etc: real COM property sets. The value is
        # stored as-is, so a subsequent read returns exactly what was set
        # rather than a dual-purpose wrapper.
        if name in _INTERNAL_ATTRS:
            object.__setattr__(self, name, value)
        else:
            self._children[name] = value

    # -- scripting -----------------------------------------------------------

    def set_return(self, key: str, value: Any) -> "FakeComObject":
        """Script a constant return value for `key` (matched by exact path,
        `"Type.Method"`, or bare method name)."""
        self._scripts.returns[key] = value
        return self

    def set_sequence(self, key: str, values: Iterable[Any]) -> "FakeComObject":
        """Script successive call return values for `key`: the first call
        returns `values[0]`, the second `values[1]`, etc."""
        self._scripts.sequences[key] = _ScriptedSequence(values)
        return self

    def set_raises(self, key: str, exc: BaseException) -> "FakeComObject":
        """Script `key` to raise `exc` when invoked."""
        self._scripts.raises[key] = exc
        return self

    def new_object(self, path: str) -> "FakeComObject":
        """A standalone `FakeComObject` sharing this graph's script registry
        and call log, but not wired into any parent's children -- for use as
        a scripted return value (e.g. the object `GetCurrentSheet` hands
        back, or the features a `GetNextFeature` chain walks)."""
        return FakeComObject(
            self._scripts, self._log, path, name=path.rsplit(".", 1)[-1]
        )

    def tag(self, com_type: str) -> "FakeComObject":
        """Declare this object's COM interface name (e.g. `"IDrawingDoc"`),
        enabling `"Type.Method"`-style scripting keys for its members."""
        self._com_type = com_type
        return self

    @property
    def call_log(self) -> CallLog:
        return self._log

    # -- call / value duality ------------------------------------------------

    def _candidate_keys(self) -> List[str]:
        keys = [self._path]
        if self._owner_com_type and self._name:
            keys.append(f"{self._owner_com_type}.{self._name}")
        if self._name:
            keys.append(self._name)
        return keys

    def _peek(self) -> Any:
        """Non-consuming, non-raising lookup used for property-style access
        (`x.Foo`, never called)."""
        for key in self._candidate_keys():
            seq = self._scripts.sequences.get(key)
            if seq is not None:
                value = seq.peek()
                if value is not _UNSET:
                    return value
        for key in self._candidate_keys():
            if key in self._scripts.returns:
                return self._scripts.returns[key]
        return _UNSET

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._log.record(self._owner_path, self._name, args, kwargs)
        keys = self._candidate_keys()
        for key in keys:
            if key in self._scripts.raises:
                raise self._scripts.raises[key]
        for key in keys:
            seq = self._scripts.sequences.get(key)
            if seq is not None:
                return seq.advance(key)
        for key in keys:
            if key in self._scripts.returns:
                return self._scripts.returns[key]
        # Nothing scripted: auto-vivify a fresh chainable result so callers
        # that keep chaining (`doc.SketchManager.InsertSketch(True).Foo`)
        # don't crash, and `is None` / truthiness checks see a real object.
        return FakeComObject(
            self._scripts, self._log, f"{self._path}()",
            name=self._name, depth=self._depth + 1,
        )

    def __eq__(self, other: Any) -> bool:
        value = self._peek()
        if value is not _UNSET:
            return value == other
        return self is other

    def __hash__(self) -> int:
        # Must agree with `__eq__`: a wrapper scripted to "ProfileFeature"
        # compares equal to that string, so it has to hash like it too, or
        # production code doing `value in {...}` / `dict[value]` silently
        # misses against the fake while working against real COM.
        value = self._peek()
        if value is not _UNSET:
            try:
                return hash(value)
            except TypeError:  # scripted to an unhashable value (list, dict)
                return id(self)
        return id(self)

    def __bool__(self) -> bool:
        value = self._peek()
        if value is not _UNSET:
            return bool(value)
        return True

    def __repr__(self) -> str:
        value = self._peek()
        if value is not _UNSET:
            return f"<FakeComObject {self._path!r} -> {value!r}>"
        return f"<FakeComObject {self._path!r}>"

    def __str__(self) -> str:
        value = self._peek()
        if value is not _UNSET:
            return str(value)
        return repr(self)


# ============================================================================
# FakeSldWorks factory
# ============================================================================

# (swDocPART, swDocASSEMBLY, swDocDRAWING), COM interface name, and the
# untitled-document name SolidWorks itself would use.
_DOC_TYPES = {
    "part": (1, "IPartDoc", "Part1"),
    "assembly": (2, "IAssemblyDoc", "Assem1"),
    "drawing": (3, "IDrawingDoc", "Draw1"),
}


def FakeSldWorks(doc_type: str = "part", *, sheet_names: Optional[List[str]] = None) -> FakeComObject:
    """Build a fake `SldWorks.Application` with a single `ActiveDoc` wired
    up plausibly enough that most tools run against it with no further
    setup.

    Args:
        doc_type: "part", "assembly", or "drawing" -- controls `ActiveDoc`'s
            `GetType` and which drawing-only members get pre-scripted.
        sheet_names: for `doc_type="drawing"`, the names `GetSheetNames()`
            returns (default `["Sheet1"]`).

    `ActiveDoc.FirstFeature`, `.GetNextFeature` and `GetFirstDocument` are
    pre-scripted to `None` so naive walks over them terminate (in at most one
    iteration -- see the module docstring's Limitations section) instead of
    looping over auto-vivified objects -- `set_sequence` on `GetNextFeature`
    to exercise a real, multi-feature list.

    `ActiveDoc.GetTitle`/`GetPathName` are pre-scripted to a real `str` (an
    unsaved document named the way SolidWorks would name it), since tool
    results carrying them get JSON-serialized and a wrapper would not
    survive that. Override either with `set_return` for a saved-document
    scenario.
    """
    if doc_type not in _DOC_TYPES:
        raise ValueError(f"doc_type must be one of {sorted(_DOC_TYPES)}, got {doc_type!r}")
    sw_doc_type, com_type, doc_title = _DOC_TYPES[doc_type]

    scripts = _ScriptRegistry()
    log = CallLog()

    app = FakeComObject(scripts, log, path="app", name="app")
    app.tag("ISldWorks")
    app.Visible = True

    # An open-documents walk (`GetFirstDocument`/`GetNext`) terminates
    # immediately unless a test scripts one, same as the feature walk below.
    app.set_return("GetFirstDocument", None)

    doc = app.ActiveDoc
    doc.tag(com_type)
    doc.set_return("GetType", sw_doc_type)
    doc.set_return("FirstFeature", None)
    doc.set_return("GetNextFeature", None)
    # Real strings, not auto-vivified wrappers: tool results carrying the
    # title/path get `json.dumps`-ed by `server.py::format_result`, which a
    # `FakeComObject` cannot survive.
    doc.set_return("GetTitle", doc_title)
    doc.set_return("GetPathName", "")

    doc.Extension.tag("IModelDocExtension")
    doc.SelectionManager.tag("ISelectionMgr")
    doc.FeatureManager.tag("IFeatureManager")
    doc.SketchManager.tag("ISketchManager")

    if doc_type == "drawing":
        names = list(sheet_names) if sheet_names else ["Sheet1"]
        sheet = doc.new_object(f"{doc._path}.<{names[0]}>")
        sheet.tag("ISheet")
        doc.set_return("GetCurrentSheet", sheet)
        doc.set_return("GetSheetNames", names)
        doc.set_return("IGetViews", [])

    return app
