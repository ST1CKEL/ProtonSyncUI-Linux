"""Tests des lokalen Ordnerdurchlaufs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from proton_sync_ui.models.plan import PlanAction
from proton_sync_ui.sync.ignore import IgnoreMatcher
from proton_sync_ui.sync.scanner import compute_sha256, scan_directory

#: Signatur der make_file-Fixture aus conftest.py.
MakeFile = Callable[..., Path]


class TestBasicScanning:
    """Grundlegendes Auffinden von Dateien."""

    def test_finds_files_recursively(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("oben.txt")
        make_file("unter/mitte.txt")
        make_file("unter/tief/tief.txt")

        result = scan_directory(source_dir)

        assert sorted(item.key for item in result.files) == [
            "oben.txt",
            "unter/mitte.txt",
            "unter/tief/tief.txt",
        ]

    def test_empty_directory_yields_nothing(self, source_dir: Path) -> None:
        result = scan_directory(source_dir)
        assert result.files == ()
        assert result.errors == ()

    def test_records_size_and_mtime(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("datei.txt", "12345", mtime_ns=1_700_000_000_000_000_000)

        result = scan_directory(source_dir)

        found = result.files[0]
        assert found.size_bytes == 5
        assert found.mtime_ns == 1_700_000_000_000_000_000

    def test_paths_are_relative_posix(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("a/b/c.txt")
        result = scan_directory(source_dir)
        assert result.files[0].key == "a/b/c.txt"
        assert result.files[0].absolute_path == source_dir / "a" / "b" / "c.txt"

    def test_total_bytes(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("a.txt", "12345")
        make_file("b.txt", "123")
        assert scan_directory(source_dir).total_bytes == 8


class TestSymlinks:
    """Symlinks werden im MVP nie synchronisiert."""

    def test_file_symlink_is_skipped(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("echt.txt", "Inhalt")
        (source_dir / "verweis.txt").symlink_to(source_dir / "echt.txt")

        result = scan_directory(source_dir)

        assert [item.key for item in result.files] == ["echt.txt"]
        skips = [skip for skip in result.skips if skip.action is PlanAction.SKIP_SYMLINK]
        assert len(skips) == 1
        assert skips[0].relative_path.as_posix() == "verweis.txt"

    def test_directory_symlink_is_not_followed(
        self, source_dir: Path, make_file: MakeFile, tmp_path: Path
    ) -> None:
        make_file("drin.txt")
        aussen = tmp_path / "aussen"
        aussen.mkdir()
        (aussen / "geheim.txt").write_text("darf nicht hochgeladen werden")
        (source_dir / "verweis").symlink_to(aussen)

        result = scan_directory(source_dir)

        assert [item.key for item in result.files] == ["drin.txt"]
        assert not any("geheim" in item.key for item in result.files)

    def test_broken_symlink_is_skipped(self, source_dir: Path) -> None:
        (source_dir / "kaputt.txt").symlink_to(source_dir / "gibtsnicht.txt")

        result = scan_directory(source_dir)

        assert result.files == ()
        assert any(skip.action is PlanAction.SKIP_SYMLINK for skip in result.skips)

    def test_symlink_loop_does_not_hang(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("datei.txt")
        (source_dir / "schleife").symlink_to(source_dir)

        result = scan_directory(source_dir)

        assert [item.key for item in result.files] == ["datei.txt"]


class TestSizeLimit:
    """Groessenlimit pro Datei."""

    def test_large_file_is_skipped(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("klein.txt", "x" * 10)
        make_file("gross.bin", "x" * 5000)

        result = scan_directory(source_dir, max_file_size_bytes=1000)

        assert [item.key for item in result.files] == ["klein.txt"]
        skips = [skip for skip in result.skips if skip.action is PlanAction.SKIP_TOO_LARGE]
        assert len(skips) == 1
        assert skips[0].size_bytes == 5000

    def test_file_exactly_at_limit_is_included(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("genau.bin", "x" * 1000)
        result = scan_directory(source_dir, max_file_size_bytes=1000)
        assert [item.key for item in result.files] == ["genau.bin"]

    def test_no_limit_includes_everything(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("gross.bin", "x" * 100_000)
        result = scan_directory(source_dir, max_file_size_bytes=None)
        assert len(result.files) == 1


class TestExclusions:
    """Zusammenspiel mit den Ausschlussregeln."""

    def test_excluded_file(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("behalten.txt")
        make_file("weg.log")

        matcher = IgnoreMatcher(["*.log"], use_defaults=False)
        result = scan_directory(source_dir, matcher=matcher)

        assert [item.key for item in result.files] == ["behalten.txt"]
        assert any(skip.action is PlanAction.SKIP_EXCLUDED for skip in result.skips)

    def test_excluded_directory_is_not_entered(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("behalten.txt")
        make_file("build/a.o")
        make_file("build/tief/b.o")

        matcher = IgnoreMatcher(["build/"], use_defaults=False)
        result = scan_directory(source_dir, matcher=matcher)

        assert [item.key for item in result.files] == ["behalten.txt"]
        # Genau ein Skip-Eintrag: das Verzeichnis selbst, nicht jede Datei darin.
        excluded = [skip for skip in result.skips if skip.action is PlanAction.SKIP_EXCLUDED]
        assert len(excluded) == 1
        assert excluded[0].relative_path.as_posix() == "build"

    def test_default_patterns_skip_vcs(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("code.py")
        make_file(".git/config")

        result = scan_directory(source_dir, matcher=IgnoreMatcher())

        assert [item.key for item in result.files] == ["code.py"]


class TestUnsupportedEntries:
    """Namen und Dateiarten, die nicht uebertragen werden koennen."""

    def test_backslash_in_name_is_skipped(self, source_dir: Path) -> None:
        # Ein Backslash ist das Escape-Zeichen der CLI; solche Namen lehnen
        # wir ab, statt eine Maskierung zu raten.
        (source_dir / "mit\\backslash.txt").write_text("Inhalt")

        result = scan_directory(source_dir)

        assert result.files == ()
        assert any(skip.action is PlanAction.SKIP_UNSUPPORTED_NAME for skip in result.skips)

    def test_fifo_is_skipped(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("normal.txt")
        os.mkfifo(source_dir / "rohr")

        result = scan_directory(source_dir)

        assert [item.key for item in result.files] == ["normal.txt"]

    def test_unreadable_file_is_reported(self, source_dir: Path, make_file: MakeFile) -> None:
        target = make_file("geheim.txt", "Inhalt")
        make_file("offen.txt")
        target.chmod(0o000)
        try:
            result = scan_directory(source_dir)
            if os.getuid() == 0:  # root darf trotzdem lesen
                return
            assert [item.key for item in result.files] == ["offen.txt"]
            assert any(skip.action is PlanAction.SKIP_UNREADABLE for skip in result.skips)
        finally:
            target.chmod(0o644)

    def test_unreadable_directory_is_recorded_as_error(
        self, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("offen.txt")
        blocked = source_dir / "gesperrt"
        blocked.mkdir()
        (blocked / "drin.txt").write_text("x")
        blocked.chmod(0o000)
        try:
            result = scan_directory(source_dir)
            if os.getuid() == 0:
                return
            assert [item.key for item in result.files] == ["offen.txt"]
            assert result.errors  # der Fehler wurde gesammelt, nicht geworfen
        finally:
            blocked.chmod(0o755)


class TestHashing:
    """SHA-256-Berechnung."""

    def test_hash_is_stable(self, source_dir: Path, make_file: MakeFile) -> None:
        target = make_file("datei.txt", "Reproduzierbarer Inhalt")
        assert compute_sha256(target) == compute_sha256(target)

    def test_hash_differs_for_different_content(
        self, source_dir: Path, make_file: MakeFile
    ) -> None:
        first = make_file("a.txt", "Inhalt A")
        second = make_file("b.txt", "Inhalt B")
        assert compute_sha256(first) != compute_sha256(second)

    def test_known_digest(self, source_dir: Path, make_file: MakeFile) -> None:
        target = make_file("leer.txt", "")
        assert compute_sha256(target) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_large_file_is_chunked(self, source_dir: Path, make_file: MakeFile) -> None:
        target = make_file("gross.bin", b"x" * (3 * 1024 * 1024))
        assert len(compute_sha256(target, chunk_size=1024)) == 64
