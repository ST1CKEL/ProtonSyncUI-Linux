"""Regressionstests ueber mehrere aufeinanderfolgende Laeufe.

Jeder Test hier bildet einen Fehler nach, der nur sichtbar wird, wenn man
mehrere Laeufe hintereinander betrachtet: Ein einzelner Lauf sah jeweils
korrekt aus, erst der naechste hat Daten verloren oder Dateien wiederbelebt.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from proton_sync_ui.models.plan import PlanAction
from proton_sync_ui.models.run import RunStatus
from proton_sync_ui.models.sync_pair import SyncMode, SyncPair
from proton_sync_ui.storage.database import SCHEMA_VERSION, connect
from proton_sync_ui.storage.repository import Repository
from proton_sync_ui.sync import engine as engine_module
from proton_sync_ui.sync.engine import SyncEngine
from proton_sync_ui.sync.ignore import IgnoreMatcher
from proton_sync_ui.sync.remote_scanner import scan_remote_directory
from proton_sync_ui.sync.retry import RetryPolicy

from .fake_proton_drive import FakeAdapter

REMOTE_ROOT = "/my-files/Backup"


@pytest.fixture
def bidi_pair(repository: Repository, source_dir: Path) -> SyncPair:
    return repository.save_pair(
        SyncPair.create(
            name="ZweiWege",
            local_path=source_dir,
            remote_path=REMOTE_ROOT,
            sync_mode=SyncMode.BIDIRECTIONAL,
        )
    )


def _run(repository: Repository, adapter: FakeAdapter, pair: SyncPair) -> dict[str, PlanAction]:
    engine = SyncEngine(repository, adapter, retry_policy=RetryPolicy(max_attempts=1))
    _record, plan = asyncio.run(engine.sync(pair))
    return {item.posix_path: item.action for item in plan.items}


def _adapter(**files: int) -> FakeAdapter:
    return FakeAdapter(
        existing_folders={REMOTE_ROOT},
        existing_files={f"{REMOTE_ROOT}/{name}": size for name, size in files.items()},
    )


class TestLocalDeletionStaysDeleted:
    """Eine lokale Loeschung darf nicht durch erneutes Herunterladen verpuffen."""

    def test_deleted_file_is_not_downloaded_again(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        adapter = _adapter(**{"a.txt": 18})
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.DOWNLOAD_NEW

        (source_dir / "a.txt").unlink()
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.LOCAL_DELETED
        assert repository.load_file_states(bidi_pair.uid)["a.txt"].deleted is True

        for _ in range(2):
            assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.SKIP_UNCHANGED
        assert not (source_dir / "a.txt").exists()
        # Die Cloud-Kopie bleibt unangetastet.
        assert f"{REMOTE_ROOT}/a.txt" in adapter.existing_files

    def test_cloud_change_after_deletion_is_downloaded(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        adapter = _adapter(**{"a.txt": 18})
        _run(repository, adapter, bidi_pair)
        (source_dir / "a.txt").unlink()
        _run(repository, adapter, bidi_pair)

        adapter.existing_files[f"{REMOTE_ROOT}/a.txt"] = 40
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.DOWNLOAD_NEW
        assert (source_dir / "a.txt").stat().st_size == 40
        assert repository.load_file_states(bidi_pair.uid)["a.txt"].deleted is False

    def test_recreated_file_is_uploaded(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        adapter = _adapter()
        (source_dir / "a.txt").write_text("eins", encoding="utf-8")
        _run(repository, adapter, bidi_pair)
        adapter.existing_files.clear()  # in der Cloud ebenfalls verschwunden
        (source_dir / "a.txt").unlink()
        _run(repository, adapter, bidi_pair)

        (source_dir / "a.txt").write_text("neu angelegt", encoding="utf-8")
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.UPLOAD_NEW


class TestCloudChangesAreApplied:
    """Ein geplanter Download muss die lokale Fassung wirklich ersetzen."""

    def test_changed_cloud_file_replaces_local_and_is_not_reuploaded(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        adapter = _adapter(**{"a.txt": 18})
        _run(repository, adapter, bidi_pair)

        adapter.existing_files[f"{REMOTE_ROOT}/a.txt"] = 50
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.DOWNLOAD_CHANGED
        assert (source_dir / "a.txt").stat().st_size == 50

        adapter.uploads.clear()
        assert _run(repository, adapter, bidi_pair)["a.txt"] is PlanAction.SKIP_UNCHANGED
        assert adapter.uploads == []

    def test_no_staging_directories_are_left_behind(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        adapter = _adapter(**{"a.txt": 18})
        _run(repository, adapter, bidi_pair)
        leftovers = [p for p in source_dir.iterdir() if p.name.startswith(".proton-sync-ui-dl-")]
        assert leftovers == []

    def test_failed_conflict_backup_keeps_local_file(
        self,
        repository: Repository,
        bidi_pair: SyncPair,
        source_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (source_dir / "a.txt").write_text("lokale Arbeit", encoding="utf-8")
        adapter = _adapter(**{"a.txt": 99})  # abweichende Groesse -> Konflikt

        def unusable(local_file: Path) -> Path:
            return local_file.parent / "gibt-es-nicht" / "sicherung.txt"

        monkeypatch.setattr(engine_module, "conflict_path_for", unusable)
        engine = SyncEngine(repository, adapter, retry_policy=RetryPolicy(max_attempts=1))
        record, _plan = asyncio.run(engine.sync(bidi_pair))

        assert record.failed_files == 1
        assert (source_dir / "a.txt").read_text(encoding="utf-8") == "lokale Arbeit"


class TestInitialSync:
    """Erster Lauf mit Dateien, die auf beiden Seiten schon existieren."""

    def test_equal_files_get_a_state(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        (source_dir / "c.txt").write_bytes(b"x" * 10)
        adapter = _adapter(**{"c.txt": 10})
        _run(repository, adapter, bidi_pair)
        assert "c.txt" in repository.load_file_states(bidi_pair.uid)

        # Eine spaetere lokale Aenderung wird hochgeladen statt ueberschrieben.
        (source_dir / "c.txt").write_bytes(b"lokal bearbeitet, laenger")
        assert _run(repository, adapter, bidi_pair)["c.txt"] is PlanAction.UPLOAD_CHANGED
        assert (source_dir / "c.txt").read_bytes() == b"lokal bearbeitet, laenger"

    def test_different_files_keep_a_local_backup(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        (source_dir / "c.txt").write_bytes(b"lokale Fassung")
        adapter = _adapter(**{"c.txt": 30})
        actions = _run(repository, adapter, bidi_pair)
        assert actions["c.txt"] is PlanAction.CONFLICT_LOCAL_RENAMED

        backups = list(source_dir.glob("c.conflict-*.txt"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == b"lokale Fassung"
        assert (source_dir / "c.txt").stat().st_size == 30

    def test_conflict_backups_are_not_uploaded(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        (source_dir / "c.txt").write_bytes(b"lokale Fassung")
        adapter = _adapter(**{"c.txt": 30})
        _run(repository, adapter, bidi_pair)
        adapter.uploads.clear()
        _run(repository, adapter, bidi_pair)
        assert adapter.uploads == []


class TestRemoteMtimeIsTracked:
    """Nach einem Upload muss die entfernte Aenderungszeit nachgetragen werden."""

    def test_remote_mtime_is_backfilled(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        (source_dir / "a.txt").write_text("hallo", encoding="utf-8")
        adapter = _adapter()
        _run(repository, adapter, bidi_pair)
        assert repository.load_file_states(bidi_pair.uid)["a.txt"].remote_mtime is None

        _run(repository, adapter, bidi_pair)
        assert repository.load_file_states(bidi_pair.uid)["a.txt"].remote_mtime


class TestRunIsAlwaysFinished:
    """Kein Lauf darf nach einem unerwarteten Fehler als 'laeuft' stehen bleiben."""

    def test_unexpected_error_marks_run_failed(
        self,
        repository: Repository,
        bidi_pair: SyncPair,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(*_args: object, **_kwargs: object) -> None:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(repository, "record_download", broken)
        adapter = _adapter(**{"a.txt": 18})
        engine = SyncEngine(repository, adapter, retry_policy=RetryPolicy(max_attempts=1))
        record, _plan = asyncio.run(engine.sync(bidi_pair))

        assert record.status is RunStatus.ERROR
        last = repository.last_run(bidi_pair.uid)
        assert last is not None
        assert last.status is RunStatus.ERROR


class TestRemoteScannerCancellation:
    """Ein abgebrochener Cloud-Scan darf keine Worker zuruecklassen."""

    def test_workers_are_cancelled(self) -> None:
        class SlowAdapter(FakeAdapter):
            async def list_dir(self, remote_path: str):  # type: ignore[override]
                await asyncio.sleep(3600)
                return []

        async def scenario() -> set[asyncio.Task[object]]:
            scan = asyncio.create_task(scan_remote_directory(SlowAdapter(), REMOTE_ROOT))
            await asyncio.sleep(0.01)
            scan.cancel()
            with pytest.raises(asyncio.CancelledError):
                await scan
            current = asyncio.current_task()
            return {task for task in asyncio.all_tasks() if task is not current}

        assert asyncio.run(scenario()) == set()


class TestIgnoreDefaults:
    """Interne Dateien werden nie synchronisiert."""

    def test_conflict_backups_and_staging_are_ignored(self) -> None:
        matcher = IgnoreMatcher()
        assert matcher.is_ignored("ordner/bericht.conflict-1763200000.pdf")
        assert matcher.is_dir_ignored(".proton-sync-ui-dl-abc123")
        assert not matcher.is_ignored("notes.conflict-ideen.txt")


class TestMigration:
    """Bestehende Datenbanken erhalten die Grabstein-Spalte."""

    def test_v2_database_is_migrated(self, tmp_path: Path) -> None:
        db = tmp_path / "alt.db"
        connection = connect(db)
        connection.execute("ALTER TABLE file_states DROP COLUMN deleted")
        connection.execute("UPDATE schema_version SET version = 2")
        connection.close()

        connection = connect(db)
        try:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(file_states)")}
            version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
        finally:
            connection.close()
        assert "deleted" in columns
        assert version == SCHEMA_VERSION


class TestConflictService:
    """Konfliktdateien erkennen und aufloesen, ohne fremde Dateien anzufassen."""

    @pytest.fixture
    def service(self, repository: Repository):  # type: ignore[no-untyped-def]
        pytest.importorskip("gi")
        from proton_sync_ui.services.default_services import (
            DefaultConflictService,
            DefaultPairRepository,
        )

        return DefaultConflictService(DefaultPairRepository(repository), repository)

    def test_ordinary_files_are_not_conflicts(
        self, service, bidi_pair: SyncPair, source_dir: Path
    ) -> None:  # type: ignore[no-untyped-def]
        (source_dir / "notes.conflict-ideen.txt").write_text("x", encoding="utf-8")
        assert service.list_conflicts() == []

    def test_keep_both_never_overwrites_an_older_copy(
        self, service, bidi_pair: SyncPair, source_dir: Path
    ) -> None:  # type: ignore[no-untyped-def]
        (source_dir / "a.txt").write_text("cloud", encoding="utf-8")
        (source_dir / "a (Lokale Kopie).txt").write_text("alte Kopie", encoding="utf-8")
        (source_dir / "a.conflict-1763200000.txt").write_text("lokal", encoding="utf-8")

        conflicts = service.list_conflicts()
        assert [c.relative_path for c in conflicts] == ["a.txt"]
        service.resolve_conflict(conflicts[0], "keep_both")

        assert (source_dir / "a (Lokale Kopie).txt").read_text(encoding="utf-8") == "alte Kopie"
        assert (source_dir / "a (Lokale Kopie 2).txt").read_text(encoding="utf-8") == "lokal"
