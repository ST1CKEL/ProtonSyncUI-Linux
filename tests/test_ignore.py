"""Tests der Ausschlussregeln im .gitignore-Stil."""

from __future__ import annotations

import pytest

from proton_sync_ui.sync.ignore import DEFAULT_PATTERNS, IgnoreMatcher, compile_rule


def match(patterns: list[str], path: str, *, is_dir: bool = False) -> bool:
    """Kurzform ohne die Standardregeln."""
    return IgnoreMatcher(patterns, use_defaults=False).is_ignored(path, is_dir=is_dir)


class TestBasicPatterns:
    """Einfache Muster."""

    def test_exact_name_matches_at_any_depth(self) -> None:
        assert match(["notizen.txt"], "notizen.txt")
        assert match(["notizen.txt"], "unterordner/notizen.txt")
        assert match(["notizen.txt"], "a/b/c/notizen.txt")

    def test_unrelated_file_is_kept(self) -> None:
        assert not match(["notizen.txt"], "andere.txt")

    def test_wildcard_matches_within_segment(self) -> None:
        assert match(["*.log"], "server.log")
        assert match(["*.log"], "logs/server.log")
        assert not match(["*.log"], "server.log.gz")

    def test_wildcard_does_not_cross_directories(self) -> None:
        assert not match(["a*c"], "a/b/c")

    def test_question_mark_matches_single_character(self) -> None:
        assert match(["datei?.txt"], "datei1.txt")
        assert not match(["datei?.txt"], "datei12.txt")

    def test_character_class(self) -> None:
        assert match(["datei[0-9].txt"], "datei7.txt")
        assert not match(["datei[0-9].txt"], "dateiX.txt")

    def test_negated_character_class(self) -> None:
        assert match(["datei[!0-9].txt"], "dateiX.txt")
        assert not match(["datei[!0-9].txt"], "datei7.txt")


class TestAnchoring:
    """Bindung an das Wurzelverzeichnis."""

    def test_leading_slash_anchors_to_root(self) -> None:
        assert match(["/oben.txt"], "oben.txt")
        assert not match(["/oben.txt"], "unten/oben.txt")

    def test_inner_slash_anchors_to_root(self) -> None:
        assert match(["doc/api.md"], "doc/api.md")
        assert not match(["doc/api.md"], "projekt/doc/api.md")

    def test_pattern_without_slash_matches_anywhere(self) -> None:
        assert match(["api.md"], "projekt/doc/api.md")


class TestDirectories:
    """Nur-Verzeichnis-Regeln."""

    def test_trailing_slash_matches_directory(self) -> None:
        assert match(["build/"], "build", is_dir=True)

    def test_trailing_slash_covers_contents(self) -> None:
        assert match(["build/"], "build/app.bin")
        assert match(["build/"], "build/tief/verschachtelt.o")

    def test_trailing_slash_does_not_match_same_named_file(self) -> None:
        assert not match(["build/"], "build")

    def test_directory_rule_applies_at_any_depth(self) -> None:
        assert match(["cache/"], "projekt/modul/cache/daten.bin")


class TestNegation:
    """Wiedereinschluss mit '!'."""

    def test_negation_reincludes_file(self) -> None:
        assert not match(["*.log", "!wichtig.log"], "wichtig.log")

    def test_negation_only_affects_matching_files(self) -> None:
        assert match(["*.log", "!wichtig.log"], "anderes.log")

    def test_last_matching_rule_wins(self) -> None:
        assert match(["*.log", "!wichtig.log", "wichtig.log"], "wichtig.log")

    def test_order_matters(self) -> None:
        # Negation vor der Ausschlussregel bleibt wirkungslos.
        assert match(["!wichtig.log", "*.log"], "wichtig.log")


class TestGlobstar:
    """'**' ueber mehrere Ebenen."""

    def test_leading_globstar(self) -> None:
        assert match(["**/tmp"], "tmp")
        assert match(["**/tmp"], "a/b/tmp")

    def test_trailing_globstar(self) -> None:
        assert match(["daten/**"], "daten/a/b/c.txt")

    def test_middle_globstar(self) -> None:
        assert match(["a/**/z.txt"], "a/z.txt")
        assert match(["a/**/z.txt"], "a/b/z.txt")
        assert match(["a/**/z.txt"], "a/b/c/z.txt")
        assert not match(["a/**/z.txt"], "x/b/z.txt")


class TestComments:
    """Kommentare, Leerzeilen und Maskierung."""

    def test_comment_is_ignored(self) -> None:
        assert not match(["# *.txt"], "notiz.txt")

    def test_blank_lines_are_ignored(self) -> None:
        assert compile_rule("") is None
        assert compile_rule("   ") is None

    def test_escaped_hash_is_literal(self) -> None:
        assert match([r"\#notiz"], "#notiz")

    def test_trailing_whitespace_is_stripped(self) -> None:
        assert match(["*.txt   "], "notiz.txt")

    def test_escaped_special_character(self) -> None:
        assert match([r"datei\*.txt"], "datei*.txt")
        assert not match([r"datei\*.txt"], "dateiXYZ.txt")


class TestDefaults:
    """Die eingebauten Standardregeln."""

    def test_defaults_are_applied(self) -> None:
        matcher = IgnoreMatcher()
        assert matcher.is_ignored(".git/config")
        assert matcher.is_ignored("__pycache__/modul.pyc")
        assert matcher.is_ignored("modul.pyc")
        assert matcher.is_ignored("dokument.txt~")

    def test_defaults_keep_normal_files(self) -> None:
        matcher = IgnoreMatcher()
        assert not matcher.is_ignored("dokumente/bericht.pdf")

    def test_defaults_can_be_disabled(self) -> None:
        matcher = IgnoreMatcher(use_defaults=False)
        assert not matcher.is_ignored(".git/config")

    @pytest.mark.parametrize("pattern", DEFAULT_PATTERNS)
    def test_every_default_pattern_compiles(self, pattern: str) -> None:
        assert compile_rule(pattern) is not None


class TestRobustness:
    """Randfaelle."""

    def test_empty_path_is_never_ignored(self) -> None:
        assert not match(["*"], "")

    def test_leading_slash_in_path_is_tolerated(self) -> None:
        assert match(["*.txt"], "/notiz.txt")

    def test_unclosed_bracket_is_literal(self) -> None:
        assert match(["datei[.txt"], "datei[.txt")

    def test_invalid_patterns_are_reported_not_raised(self) -> None:
        matcher = IgnoreMatcher(["gueltig.txt", "["], use_defaults=False)
        assert matcher.is_ignored("gueltig.txt")

    def test_is_dir_ignored_shortcut(self) -> None:
        matcher = IgnoreMatcher(["build/"], use_defaults=False)
        assert matcher.is_dir_ignored("build")
        assert not matcher.is_dir_ignored("src")
