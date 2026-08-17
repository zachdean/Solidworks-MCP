"""
Regression tests for `SolidWorksFinder._find_table_template` -- the
drawing-table template discovery sw-mio.1/.3 added for the insert_*_table
tools' `template_path`-omitted fallback.

Unlike part/assembly/drawing templates, table templates have no fixed
filename: they are found by extension inside `<install>/lang/<locale>/`. The
tool-level tests all monkeypatch `find_template` away, so the picking rules
themselves (locale preference, preferred stem, alphabetical fallback) are
only covered here, against a real temporary directory tree.
"""

from solidworks_mcp.utils.sw_finder import SolidWorksFinder


def _install(tmp_path, files_by_locale):
    """Build a fake `<install>/lang/<locale>/...` tree and return the path to
    the (never-executed) exe inside it, as `sw_exe_path` expects."""
    for locale, filenames in files_by_locale.items():
        locale_dir = tmp_path / "lang" / locale
        locale_dir.mkdir(parents=True)
        for filename in filenames:
            (locale_dir / filename).write_text("")
    exe = tmp_path / "SLDWORKS.exe"
    exe.write_text("")
    return str(exe)


class TestFindTableTemplate:
    def test_prefers_the_standard_bom_template_over_the_alphabetical_first(self, tmp_path):
        """A stock install ships several `.sldbomtbt` templates. Picking the
        alphabetically-first would hand `insert_bom_table()`'s default
        `bom_type="top_level"` the *indented* template, silently
        contradicting the requested layout."""
        exe = _install(tmp_path, {"english": [
            "bom-indented.sldbomtbt",
            "bom-material.sldbomtbt",
            "bom-partsonly.sldbomtbt",
            "bom-standard.sldbomtbt",
        ]})

        found = SolidWorksFinder.find_template("bom", sw_exe_path=exe)

        assert found is not None
        assert found.endswith("bom-standard.sldbomtbt")

    def test_prefers_the_installed_weldment_cut_list_template(self, tmp_path):
        exe = _install(tmp_path, {"english": [
            "cut list.sldwldtbt",
            "aaa-custom.sldwldtbt",
        ]})

        found = SolidWorksFinder.find_template("weldment", sw_exe_path=exe)

        assert found is not None
        assert found.endswith("cut list.sldwldtbt")

    def test_falls_back_to_first_in_sort_order_when_preferred_stem_absent(self, tmp_path):
        """A type with no preferred stem installed (or none configured at
        all) still resolves deterministically rather than not at all."""
        exe = _install(tmp_path, {"english": [
            "zzz-custom.sldbomtbt",
            "aaa-custom.sldbomtbt",
        ]})

        found = SolidWorksFinder.find_template("bom", sw_exe_path=exe)

        assert found is not None
        assert found.endswith("aaa-custom.sldbomtbt")

    def test_revision_and_hole_templates_resolve_by_their_own_extension(self, tmp_path):
        exe = _install(tmp_path, {"english": [
            "standard.sldrevtbt",
            "standard.sldholtbt",
            "bom-standard.sldbomtbt",
        ]})

        assert SolidWorksFinder.find_template(
            "revision", sw_exe_path=exe).endswith(".sldrevtbt")
        assert SolidWorksFinder.find_template(
            "hole", sw_exe_path=exe).endswith(".sldholtbt")

    def test_english_locale_wins_over_other_installed_languages(self, tmp_path):
        exe = _install(tmp_path, {
            "deutsch": ["bom-standard.sldbomtbt"],
            "english": ["bom-standard.sldbomtbt"],
        })

        found = SolidWorksFinder.find_template("bom", sw_exe_path=exe)

        assert "english" in found

    def test_no_matching_extension_anywhere_returns_none(self, tmp_path):
        exe = _install(tmp_path, {"english": ["Drawing.drwdot"]})

        assert SolidWorksFinder.find_template("bom", sw_exe_path=exe) is None

    def test_missing_lang_dir_returns_none(self, tmp_path):
        exe = tmp_path / "SLDWORKS.exe"
        exe.write_text("")

        assert SolidWorksFinder.find_template("bom", sw_exe_path=str(exe)) is None
