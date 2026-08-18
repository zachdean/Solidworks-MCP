"""
Tests for solidworks_mcp.version_gate.
--------------------------------------
Covers `parse_revision_number`/`read_revision_number` against the format
documented in `docs/api/06-versioning.md`, `effective_min_release`'s
"never silently relaxed below a tool's own requirement" rule, `require_version`
against the fake-COM harness, and the end-to-end `dispatch()` gate (a tool
with `min_release=2025` dispatched against a simulated 2021 session).
"""

import pytest

from solidworks_mcp import config as config_module
from solidworks_mcp import version_gate
from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.tools import dispatch, registered_names
from solidworks_mcp.tools import registry as registry_module


def _dummy_schema():
    return {"type": "object", "properties": {}, "required": []}


@pytest.fixture
def empty_registry(monkeypatch):
    """Swap in a fresh, empty tool registry for the duration of the test, so
    a test-registered tool doesn't pollute the real (process-global,
    import-time-populated) registry `solidworks_mcp.tools`/`server.py` share."""
    monkeypatch.setattr(registry_module, "_TOOLS", {})


class TestParseRevisionNumber:
    def test_sw2025_fcs(self):
        release = version_gate.parse_revision_number("33.0.0")
        assert release.major == 33
        assert release.year == 2025
        assert release.service_pack == 0
        assert release.hotfix == 0

    def test_sw2005_fcs_matches_the_documented_worked_example(self):
        # docs/api/06-versioning.md: SOLIDWORKS 2005 initial release -> "13.0.0"
        release = version_gate.parse_revision_number("13.0.0")
        assert release.year == 2005

    def test_sw2000_sp1_matches_the_documented_worked_example(self):
        # docs/api/06-versioning.md: SOLIDWORKS 2000 SP1 -> "8.1.0"
        release = version_gate.parse_revision_number("8.1.0")
        assert release.year == 2000
        assert release.service_pack == 1
        assert release.hotfix == 0

    def test_service_pack_hotfix_are_parsed_as_separate_components(self):
        release = version_gate.parse_revision_number("33.2.1")
        assert release.service_pack == 2
        assert release.hotfix == 1

    def test_beta_build_negative_service_pack_still_parses(self):
        # docs/api/06-versioning.md: SOLIDWORKS 2015 beta 2 -> "23.-3.0"
        release = version_gate.parse_revision_number("23.-3.0")
        assert release.year == 2015
        assert release.service_pack == -3

    @pytest.mark.parametrize("raw", ["", "not-a-version", "33.0", "33.0.0.0", "33..0"])
    def test_malformed_strings_raise_version_gate_error(self, raw):
        with pytest.raises(version_gate.VersionGateError):
            version_gate.parse_revision_number(raw)

    def test_releases_compare_ordered_oldest_to_newest(self):
        older = version_gate.parse_revision_number("29.0.0")
        newer = version_gate.parse_revision_number("33.2.1")
        assert older < newer
        assert newer > older


class TestReadRevisionNumber:
    def test_none_app_raises_version_gate_error(self):
        with pytest.raises(version_gate.VersionGateError):
            version_gate.read_revision_number(None)

    def test_plain_string_property_is_used_directly(self):
        class Stub:
            RevisionNumber = "33.0.0"

        assert version_gate.read_revision_number(Stub()) == "33.0.0"

    def test_callable_bare_attribute_is_called(self):
        # Some builds surface RevisionNumber as a bound-method-shaped
        # attribute even on bare (non-`()`) access -- see the
        # property-vs-method Gotchas in docs/api/06-versioning.md.
        class Stub:
            RevisionNumber = staticmethod(lambda: "33.1.0")

        assert version_gate.read_revision_number(Stub()) == "33.1.0"

    def test_bare_access_raising_falls_back_to_explicit_call(self):
        class RaisesThenCallable:
            def __init__(self):
                self.accesses = 0

            def __get__(self, obj, objtype=None):
                self.accesses += 1
                if self.accesses == 1:
                    raise RuntimeError("property-style access unsupported")
                return lambda: "33.2.0"

        class Stub:
            RevisionNumber = RaisesThenCallable()

        assert version_gate.read_revision_number(Stub()) == "33.2.0"

    def test_no_such_member_at_all_raises_version_gate_error(self):
        with pytest.raises(version_gate.VersionGateError):
            version_gate.read_revision_number(object())


class TestGetConnectedRelease:
    def test_reads_the_scripted_revision_number_off_a_connected_app(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "33.2.1")
        auto = SolidWorksAutomation()
        connected = auto.connect()
        assert connected["success"], connected

        release = version_gate.get_connected_release(auto)

        assert release.year == 2025
        assert release.service_pack == 2
        assert release.hotfix == 1

    def test_defaults_to_the_fake_harnesss_current_release(self, automation):
        # testing/fake_com.py pre-scripts RevisionNumber to "33.0.0" (SW2025
        # FCS) precisely so every other test's dispatch() calls pass the
        # gate without needing to know about it.
        release = version_gate.get_connected_release(automation)
        assert release.year == 2025


class TestEffectiveMinRelease:
    def test_defaults_to_the_project_wide_floor_when_tool_has_no_override(self):
        assert version_gate.effective_min_release(None) == config_module.get_config().min_release

    def test_a_tools_own_higher_requirement_wins(self, monkeypatch):
        monkeypatch.setattr(config_module.config, "min_release", 2020)
        assert version_gate.effective_min_release(2030) == 2030

    def test_lowering_the_global_floor_does_not_relax_a_stricter_tool(self, monkeypatch):
        monkeypatch.setattr(config_module.config, "min_release", 2025)
        # A tool declaring a *lower* min_release than the project floor must
        # not be silently allowed to run on an older release than the floor.
        assert version_gate.effective_min_release(2015) == 2025

    def test_raising_the_global_floor_raises_every_unannotated_tool_too(self, monkeypatch):
        monkeypatch.setattr(config_module.config, "min_release", 2030)
        assert version_gate.effective_min_release(None) == 2030

    def test_zero_is_a_distinct_exempt_sentinel_not_unspecified(self, monkeypatch):
        monkeypatch.setattr(config_module.config, "min_release", 2025)
        # `None` -> floor (2025); `0` -> exempt (None) -- these must not collapse.
        assert version_gate.effective_min_release(None) == 2025
        assert version_gate.effective_min_release(0) is None


class TestRequireVersion:
    def test_skips_the_gate_when_nothing_is_connected(self):
        auto = SolidWorksAutomation()
        assert version_gate.require_version(auto, "some_tool", 2025) is None

    def test_blocks_an_older_connected_release_and_names_tool_and_versions(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "29.0.0")  # SOLIDWORKS 2021
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        result = version_gate.require_version(auto, "some_tool", 2025)

        assert result is not None
        assert result["success"] is False
        assert result["error_name"] == "swVersionUnsupported"
        assert "some_tool" in result["message"]
        assert "2025" in result["message"]
        assert "2021" in result["message"]

    def test_allows_a_release_meeting_the_minimum(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "33.0.0")  # SOLIDWORKS 2025
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        assert version_gate.require_version(auto, "some_tool", 2025) is None

    def test_allows_a_release_newer_than_the_minimum(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "34.0.0")  # SOLIDWORKS 2026
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        assert version_gate.require_version(auto, "some_tool", 2025) is None

    def test_min_release_zero_exempts_the_tool_even_on_an_old_release(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "1.0.0")  # ancient (pre-SW2000 placeholder value)
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        assert version_gate.require_version(auto, "exempt_tool", 0) is None

    def test_min_release_zero_exempts_the_tool_even_when_unparseable(self, make_sw):
        # The case that matters most for get_capabilities: a connected
        # release whose RevisionNumber the regex can't even parse must not
        # take down the one tool meant to diagnose why.
        app = make_sw("part")
        app.set_return("RevisionNumber", "not-a-version")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        assert version_gate.require_version(auto, "exempt_tool", 0) is None

    def test_unparseable_connected_version_is_a_clear_error_not_a_crash(self, make_sw):
        app = make_sw("part")
        app.set_return("RevisionNumber", "not-a-version")
        auto = SolidWorksAutomation()
        assert auto.connect()["success"]

        result = version_gate.require_version(auto, "some_tool", 2025)

        assert result is not None
        assert result["success"] is False
        assert "some_tool" in result["message"]


class TestDispatchVersionGate:
    """Integration: `registry.dispatch()` actually wires the gate in."""

    def test_dispatch_blocks_a_gated_tool_on_an_old_connected_release(self, empty_registry, tool_sw):
        called = []

        @registry_module.tool("gated_tool", "a gated tool", _dummy_schema(), min_release=2025)
        def handler(arguments):
            called.append(arguments)
            return {"success": True, "message": "ran", "error_code": 0, "error_name": "swSuccess"}

        app = tool_sw("part")
        app.set_return("RevisionNumber", "29.0.0")  # SOLIDWORKS 2021

        result = registry_module.dispatch("gated_tool", {})

        assert result["success"] is False
        assert result["error_name"] == "swVersionUnsupported"
        assert "gated_tool" in result["message"]
        assert "2025" in result["message"]
        assert "2021" in result["message"]
        assert called == []

    def test_dispatch_allows_a_gated_tool_on_a_current_release(self, empty_registry, tool_sw):
        @registry_module.tool("gated_tool", "a gated tool", _dummy_schema(), min_release=2025)
        def handler(arguments):
            return {"success": True, "message": "ran", "error_code": 0, "error_name": "swSuccess"}

        app = tool_sw("part")
        app.set_return("RevisionNumber", "33.0.0")  # SOLIDWORKS 2025

        result = registry_module.dispatch("gated_tool", {})

        assert result["success"] is True
        assert result["message"] == "ran"

    def test_dispatch_does_not_gate_when_nothing_is_connected(self, empty_registry):
        called = []

        @registry_module.tool("gated_tool", "a gated tool", _dummy_schema(), min_release=2025)
        def handler(arguments):
            called.append(arguments)
            return {"success": True, "message": "ran", "error_code": 0, "error_name": "swSuccess"}

        result = registry_module.dispatch("gated_tool", {})

        assert result["success"] is True
        assert called == [{}]


class TestGetCapabilities:
    """`get_capabilities` (AC: "lists every registered tool with its
    usability flag") must itself survive dispatch on an unsupported release
    -- that's the one session where its usability flags carry information."""

    def test_stays_usable_on_an_unsupported_connected_release(self, tool_sw):
        app = tool_sw("part")
        app.set_return("RevisionNumber", "29.0.0")  # SOLIDWORKS 2021

        result = dispatch("get_capabilities", {})

        assert result["success"] is True

    def test_lists_every_registered_tool(self, tool_sw):
        tool_sw("part")

        result = dispatch("get_capabilities", {})

        names = {entry["name"] for entry in result["data"]["tools"]}
        assert names == set(registered_names())
        assert len(result["data"]["tools"]) == len(registered_names())

    def test_gated_tools_are_unusable_on_an_old_release_but_it_is_still_usable(self, tool_sw):
        app = tool_sw("part")
        app.set_return("RevisionNumber", "29.0.0")  # SOLIDWORKS 2021

        result = dispatch("get_capabilities", {})

        by_name = {entry["name"]: entry for entry in result["data"]["tools"]}
        assert by_name["connect_solidworks"]["usable"] is False
        assert by_name["get_capabilities"]["usable"] is True
        assert result["data"]["connected_release"] == 2021

    def test_gated_tools_are_usable_on_a_current_release(self, tool_sw):
        app = tool_sw("part")
        app.set_return("RevisionNumber", "33.0.0")  # SOLIDWORKS 2025

        result = dispatch("get_capabilities", {})

        by_name = {entry["name"]: entry for entry in result["data"]["tools"]}
        assert by_name["connect_solidworks"]["usable"] is True
        assert result["data"]["connected_release"] == 2025

    def test_unreadable_version_reports_connected_not_disconnected(self, tool_sw):
        """Connected, but `RevisionNumber` doesn't parse. Reporting "not
        connected" here sent the caller off to reconnect when the real fault
        is an unreadable version -- and this tool exists precisely to say
        why everything else is refused."""
        app = tool_sw("part")
        app.set_return("RevisionNumber", "not-a-version")

        result = dispatch("get_capabilities", {})

        assert result["success"] is True
        assert result["data"]["connected"] is True
        assert result["data"]["connected_release"] is None
        assert result["data"]["version_error"]
        assert "could not be read" in result["message"]
        assert "Not connected" not in result["message"]

    def test_unreadable_version_marks_gated_tools_unusable(self, tool_sw):
        app = tool_sw("part")
        app.set_return("RevisionNumber", "not-a-version")

        result = dispatch("get_capabilities", {})

        by_name = {entry["name"]: entry for entry in result["data"]["tools"]}
        # The gate refuses these (it can't read a version to judge), but the
        # exempt tool must still report itself usable.
        assert by_name["connect_solidworks"]["usable"] is False
        assert by_name["get_capabilities"]["usable"] is True

    def test_nothing_connected_reports_tools_as_usable(self):
        """`usable` must mirror what `dispatch` actually enforces. While
        nothing is connected `require_version` passes every tool through, so
        reporting the whole toolset unusable -- in a fresh session, the exact
        moment the docstring says to call this -- was wrong."""
        result = dispatch("get_capabilities", {})

        assert result["data"]["connected"] is False
        assert result["data"]["version_error"] is None
        by_name = {entry["name"]: entry for entry in result["data"]["tools"]}
        assert by_name["connect_solidworks"]["usable"] is True
        assert by_name["get_capabilities"]["usable"] is True
