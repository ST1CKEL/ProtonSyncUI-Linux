"""Tests der Planerstellung: neu, geaendert, unveraendert, lokal geloescht."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from proton_sync_ui.models.plan import PlanAction
from proton_sync_ui.models.sync_pair import SyncPair
from proton_sync_ui.storage.repository import FileState
from proton_sync_ui.sync.ignore import IgnoreMatcher
from proton_sync_ui.sync.planner import build_plan, plan_for_pair
from proton_sync_ui.sync.scanner import compute_sha256, scan_directory

MakeFile = Callable[..., Path]


def state(
    path: str,
    *,
    size: int,
    mtime_ns: int,
    sha256: str | None = None,
) -> FileState:
    """Kurzform fuer einen gespeicherten Dateizustand."""
    return FileState(
        relative_path=path,
        size_bytes=size,
        mtime_ns=mtime_ns,
        sha256=sha256,
        remote_path=f"/my-files/Backup/{path}",
        uploaded_at=datetime.now(tz=UTC),
    )


def actions(plan: object) -> dict[str, PlanAction]:
    """Zuordnung Pfad -> Aktion."""
    return {item.posix_path: item.action for item in plan.items}  # type: ignore[attr-defined]


class TestNewFiles:
    """Unbekannte Dateien."""

    def test_unknown_file_is_new(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("neu.txt", "Inhalt")
        scan = scan_directory(source_dir)

        plan = build_plan(sample_pair, scan, {})

        assert actions(plan)["neu.txt"] is PlanAction.UPLOAD_NEW
        assert len(plan.new_files) == 1
        assert len(plan.uploads) == 1

    def test_all_files_new_on_first_run(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        for name in ("a.txt", "b/c.txt", "b/d/e.txt"):
            make_file(name)
        scan = scan_directory(source_dir)

        plan = build_plan(sample_pair, scan, {})

        assert len(plan.new_files) == 3
        assert plan.changed_files == ()


class TestUnchangedFiles:
    """Identische Groesse und Aenderungszeit."""

    def test_same_size_and_mtime_is_unchanged(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "Inhalt", mtime_ns=1_000_000_000)
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=6, mtime_ns=1_000_000_000)}

        plan = build_plan(sample_pair, scan, states)

        assert actions(plan)["datei.txt"] is PlanAction.SKIP_UNCHANGED
        assert plan.uploads == ()
        assert plan.is_empty

    def test_unchanged_file_needs_no_hashing(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "Inhalt", mtime_ns=1_000_000_000)
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=6, mtime_ns=1_000_000_000)}

        def explode(_path: Path) -> str:
            raise AssertionError("Im Normalfall darf nicht gehasht werden.")

        plan = build_plan(sample_pair, scan, states, hasher=explode)

        assert plan.uploads == ()


class TestChangedFiles:
    """Erkennung geaenderter Inhalte."""

    def test_different_size_is_changed(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "Viel laengerer Inhalt", mtime_ns=1_000_000_000)
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=6, mtime_ns=1_000_000_000)}

        plan = build_plan(sample_pair, scan, states)

        assert actions(plan)["datei.txt"] is PlanAction.UPLOAD_CHANGED

    def test_size_change_needs_no_hashing(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "Anderer Inhalt")
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=1, mtime_ns=1)}

        def explode(_path: Path) -> str:
            raise AssertionError("Bei abweichender Groesse ist der Hash unnoetig.")

        plan = build_plan(sample_pair, scan, states, hasher=explode)

        assert len(plan.changed_files) == 1


class TestAmbiguousFiles:
    """Gleiche Groesse, abweichende mtime -- der SHA-256-Fallback."""

    def test_same_content_despite_new_mtime_is_unchanged(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        target = make_file("datei.txt", "Inhalt", mtime_ns=2_000_000_000)
        digest = compute_sha256(target)
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=6, mtime_ns=1_000_000_000, sha256=digest)}

        plan = build_plan(sample_pair, scan, states)

        item = plan.items[0]
        assert item.action is PlanAction.SKIP_UNCHANGED
        assert item.needs_mtime_refresh is True
        assert plan.uploads == ()

    def test_different_content_same_size_is_changed(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "AAAAAA", mtime_ns=2_000_000_000)
        scan = scan_directory(source_dir)
        states = {
            "datei.txt": state(
                "datei.txt",
                size=6,
                mtime_ns=1_000_000_000,
                sha256="0" * 64,
            )
        }

        plan = build_plan(sample_pair, scan, states)

        item = plan.items[0]
        assert item.action is PlanAction.UPLOAD_CHANGED
        assert item.sha256 is not None

    def test_without_stored_hash_upload_is_the_safe_choice(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("datei.txt", "Inhalt", mtime_ns=2_000_000_000)
        scan = scan_directory(source_dir)
        states = {"datei.txt": state("datei.txt", size=6, mtime_ns=1_000_000_000)}

        plan = build_plan(sample_pair, scan, states)

        item = plan.items[0]
        assert item.action is PlanAction.UPLOAD_CHANGED
        # Der Hash wird berechnet, damit der naechste Lauf vergleichen kann.
        assert item.sha256 is not None

    def test_hash_is_computed_only_for_ambiguous_files(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("gleich.txt", "Inhalt", mtime_ns=1_000_000_000)
        make_file("unklar.txt", "Inhalt", mtime_ns=2_000_000_000)
        scan = scan_directory(source_dir)
        states = {
            "gleich.txt": state("gleich.txt", size=6, mtime_ns=1_000_000_000),
            "unklar.txt": state("unklar.txt", size=6, mtime_ns=1_000_000_000, sha256="0" * 64),
        }

        hashed: list[Path] = []

        def tracking_hasher(path: Path) -> str:
            hashed.append(path)
            return compute_sha256(path)

        build_plan(sample_pair, scan, states, hasher=tracking_hasher)

        assert [path.name for path in hashed] == ["unklar.txt"]


class TestLocalDeletions:
    """Lokal geloeschte Dateien loesen niemals eine entfernte Aktion aus."""

    def test_missing_file_is_marked_deleted(self, sample_pair: SyncPair, source_dir: Path) -> None:
        scan = scan_directory(source_dir)
        states = {"weg.txt": state("weg.txt", size=10, mtime_ns=1)}

        plan = build_plan(sample_pair, scan, states)

        assert actions(plan)["weg.txt"] is PlanAction.LOCAL_DELETED
        assert len(plan.local_deletions) == 1

    def test_deletion_is_never_an_upload(self, sample_pair: SyncPair, source_dir: Path) -> None:
        scan = scan_directory(source_dir)
        states = {"weg.txt": state("weg.txt", size=10, mtime_ns=1)}

        plan = build_plan(sample_pair, scan, states)

        assert plan.uploads == ()
        assert all(not item.is_upload for item in plan.local_deletions)

    def test_deletion_reason_mentions_remote_stays(
        self, sample_pair: SyncPair, source_dir: Path
    ) -> None:
        scan = scan_directory(source_dir)
        states = {"weg.txt": state("weg.txt", size=10, mtime_ns=1)}

        plan = build_plan(sample_pair, scan, states)

        assert "Proton Drive" in plan.local_deletions[0].reason


class TestPlanSummary:
    """Kennzahlen und Beschreibung."""

    def test_summary_counts(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("neu.txt", "Neu")
        make_file("gleich.txt", "Inhalt", mtime_ns=1_000_000_000)
        make_file("gross.bin", "x" * 5000)
        scan = scan_directory(source_dir, max_file_size_bytes=1000)
        states = {
            "gleich.txt": state("gleich.txt", size=6, mtime_ns=1_000_000_000),
            "weg.txt": state("weg.txt", size=1, mtime_ns=1),
        }

        plan = build_plan(sample_pair, scan, states)
        summary = plan.summary()

        assert summary["neu"] == 1
        assert summary["geaendert"] == 0
        assert summary["lokal_geloescht"] == 1
        assert summary["uebersprungen"] == 2  # unveraendert + zu gross

    def test_total_upload_bytes(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "12345")
        make_file("b.txt", "123")
        scan = scan_directory(source_dir)

        plan = build_plan(sample_pair, scan, {})

        assert plan.total_upload_bytes == 8

    def test_items_are_sorted(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        for name in ("z.txt", "a.txt", "m/n.txt"):
            make_file(name)
        scan = scan_directory(source_dir)

        plan = build_plan(sample_pair, scan, {})

        paths = [item.posix_path for item in plan.items]
        assert paths == sorted(paths)


class TestPlanForPair:
    """Der Bequemlichkeitseinstieg mit Ausschlussregeln des Paars."""

    def test_exclusions_of_the_pair_are_applied(
        self, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("behalten.txt")
        make_file("weg.log")
        pair = SyncPair.create(
            name="Mit Filter",
            local_path=source_dir,
            remote_path="/my-files/Backup",
            exclude_patterns=("*.log",),
        )

        plan = plan_for_pair(pair, {})

        assert [item.posix_path for item in plan.uploads] == ["behalten.txt"]

    def test_size_limit_of_the_pair_is_applied(self, source_dir: Path, make_file: MakeFile) -> None:
        make_file("klein.txt", "x" * 10)
        make_file("gross.bin", "x" * 5000)
        pair = SyncPair.create(
            name="Mit Limit",
            local_path=source_dir,
            remote_path="/my-files/Backup",
            max_file_size_bytes=1000,
        )

        plan = plan_for_pair(pair, {})

        assert [item.posix_path for item in plan.uploads] == ["klein.txt"]


class TestRemotePaths:
    """Ableitung der Zielpfade."""

    def test_remote_parent_for_nested_file(self, sample_pair: SyncPair) -> None:
        from pathlib import PurePosixPath

        assert sample_pair.remote_parent_for(PurePosixPath("a/b/c.txt")) == "/my-files/Backup/a/b"

    def test_remote_parent_for_top_level_file(self, sample_pair: SyncPair) -> None:
        from pathlib import PurePosixPath

        assert sample_pair.remote_parent_for(PurePosixPath("c.txt")) == "/my-files/Backup"

    def test_remote_path_for_file(self, sample_pair: SyncPair) -> None:
        from pathlib import PurePosixPath

        assert sample_pair.remote_path_for(PurePosixPath("a/b.txt")) == "/my-files/Backup/a/b.txt"


class TestScanErrorsArePropagated:
    """Lesefehler landen im Plan, nicht in einer Ausnahme."""

    def test_scan_errors_reach_the_plan(
        self, sample_pair: SyncPair, source_dir: Path, make_file: MakeFile
    ) -> None:
        make_file("ok.txt")
        scan = scan_directory(source_dir, matcher=IgnoreMatcher())
        scan_with_error = type(scan)(
            files=scan.files, skips=scan.skips, errors=("beispiel: Zugriff verweigert",)
        )

        plan = build_plan(sample_pair, scan_with_error, {})

        assert plan.scan_errors == ("beispiel: Zugriff verweigert",)
