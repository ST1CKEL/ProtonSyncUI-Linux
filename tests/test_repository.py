"""Tests der Persistenzschicht."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from proton_sync_ui.models.run import FileError, RunRecord, RunStatus
from proton_sync_ui.models.sync_pair import (
    ScheduleKind,
    SyncPair,
    ValidationError,
    validate_local_path,
    validate_remote_path,
)
from proton_sync_ui.storage.database import SCHEMA_VERSION, connect
from proton_sync_ui.storage.repository import Repository

MakeFile = Callable[..., Path]


class TestDatabaseSetup:
    """Anlegen und Oeffnen der Datenbank."""

    def test_schema_is_created(self, db_path: Path) -> None:
        connection = connect(db_path)
        try:
            tables = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert {
                "sync_pairs",
                "file_states",
                "runs",
                "run_errors",
                "run_locks",
                "schema_version",
            } <= tables
        finally:
            connection.close()

    def test_schema_version_is_recorded(self, db_path: Path) -> None:
        connection = connect(db_path)
        try:
            version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
            assert version == SCHEMA_VERSION
        finally:
            connection.close()

    def test_reopening_is_idempotent(self, db_path: Path) -> None:
        connect(db_path).close()
        connection = connect(db_path)
        try:
            rows = connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            assert rows == 1
        finally:
            connection.close()

    def test_foreign_keys_are_enabled(self, db_path: Path) -> None:
        connection = connect(db_path)
        try:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            connection.close()

    def test_database_file_is_private(self, db_path: Path) -> None:
        connect(db_path).close()
        assert db_path.stat().st_mode & 0o077 == 0


class TestPairPersistence:
    """Speichern und Laden von Sync-Paaren."""

    def test_save_and_load(self, repository: Repository, sample_pair: SyncPair) -> None:
        repository.save_pair(sample_pair)

        loaded = repository.get_pair(sample_pair.uid)

        assert loaded is not None
        assert loaded.uid == sample_pair.uid
        assert loaded.name == sample_pair.name
        assert loaded.local_path == sample_pair.local_path
        assert loaded.remote_path == sample_pair.remote_path

    def test_unknown_uid_returns_none(self, repository: Repository) -> None:
        assert repository.get_pair("gibt-es-nicht") is None

    def test_update_overwrites(self, repository: Repository, sample_pair: SyncPair) -> None:
        repository.save_pair(sample_pair)
        changed = sample_pair.with_changes(name="Neuer Name")

        repository.save_pair(changed)

        loaded = repository.get_pair(sample_pair.uid)
        assert loaded is not None
        assert loaded.name == "Neuer Name"
        assert len(repository.list_pairs()) == 1

    def test_exclude_patterns_round_trip(self, repository: Repository, source_dir: Path) -> None:
        pair = SyncPair.create(
            name="Mit Filtern",
            local_path=source_dir,
            remote_path="/my-files/Backup",
            exclude_patterns=("*.log", "cache/", "!wichtig.log"),
        )
        repository.save_pair(pair)

        loaded = repository.get_pair(pair.uid)

        assert loaded is not None
        assert loaded.exclude_patterns == ("*.log", "cache/", "!wichtig.log")

    def test_schedule_round_trip(self, repository: Repository, scheduled_pair: SyncPair) -> None:
        repository.save_pair(scheduled_pair)

        loaded = repository.get_pair(scheduled_pair.uid)

        assert loaded is not None
        assert loaded.schedule_kind is ScheduleKind.INTERVAL
        assert loaded.interval_minutes == 60

    def test_size_limit_round_trip(self, repository: Repository, source_dir: Path) -> None:
        pair = SyncPair.create(
            name="Mit Limit",
            local_path=source_dir,
            remote_path="/my-files/Backup",
            max_file_size_bytes=1024 * 1024,
        )
        repository.save_pair(pair)

        loaded = repository.get_pair(pair.uid)
        assert loaded is not None
        assert loaded.max_file_size_bytes == 1024 * 1024

    def test_list_is_sorted_by_name(self, repository: Repository, source_dir: Path) -> None:
        for name in ("Zebra", "Anton", "Mitte"):
            repository.save_pair(
                SyncPair.create(name=name, local_path=source_dir, remote_path=f"/my-files/{name}")
            )

        assert [pair.name for pair in repository.list_pairs()] == ["Anton", "Mitte", "Zebra"]

    def test_enabled_only_filter(self, repository: Repository, source_dir: Path) -> None:
        active = SyncPair.create(name="Aktiv", local_path=source_dir, remote_path="/my-files/A")
        inactive = SyncPair.create(
            name="Inaktiv", local_path=source_dir, remote_path="/my-files/B", enabled=False
        )
        repository.save_pair(active)
        repository.save_pair(inactive)

        assert [pair.name for pair in repository.list_pairs(enabled_only=True)] == ["Aktiv"]

    def test_set_enabled(self, repository: Repository, stored_pair: SyncPair) -> None:
        repository.set_pair_enabled(stored_pair.uid, enabled=False)

        loaded = repository.get_pair(stored_pair.uid)
        assert loaded is not None
        assert loaded.enabled is False

    def test_delete_removes_pair(self, repository: Repository, stored_pair: SyncPair) -> None:
        assert repository.delete_pair(stored_pair.uid) is True
        assert repository.get_pair(stored_pair.uid) is None

    def test_delete_cascades_to_file_states(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        repository.record_upload(
            stored_pair.uid,
            relative_path="a.txt",
            size_bytes=1,
            mtime_ns=1,
            remote_path="/my-files/Backup/a.txt",
        )

        repository.delete_pair(stored_pair.uid)

        assert repository.load_file_states(stored_pair.uid) == {}

    def test_delete_unknown_returns_false(self, repository: Repository) -> None:
        assert repository.delete_pair("gibt-es-nicht") is False


class TestFileStates:
    """Zustandstabelle der uebertragenen Dateien."""

    def test_record_and_load(self, repository: Repository, stored_pair: SyncPair) -> None:
        repository.record_upload(
            stored_pair.uid,
            relative_path="a.txt",
            size_bytes=42,
            mtime_ns=1234,
            remote_path="/my-files/Backup/a.txt",
            sha256="abc",
        )

        states = repository.load_file_states(stored_pair.uid)

        assert states["a.txt"].size_bytes == 42
        assert states["a.txt"].mtime_ns == 1234
        assert states["a.txt"].sha256 == "abc"

    def test_record_twice_updates(self, repository: Repository, stored_pair: SyncPair) -> None:
        for size in (1, 2):
            repository.record_upload(
                stored_pair.uid,
                relative_path="a.txt",
                size_bytes=size,
                mtime_ns=size,
                remote_path="/my-files/Backup/a.txt",
            )

        states = repository.load_file_states(stored_pair.uid)
        assert len(states) == 1
        assert states["a.txt"].size_bytes == 2

    def test_touch_updates_only_mtime(self, repository: Repository, stored_pair: SyncPair) -> None:
        repository.record_upload(
            stored_pair.uid,
            relative_path="a.txt",
            size_bytes=42,
            mtime_ns=1,
            remote_path="/my-files/Backup/a.txt",
            sha256="abc",
        )

        repository.touch_file_state(stored_pair.uid, relative_path="a.txt", mtime_ns=999)

        state = repository.load_file_states(stored_pair.uid)["a.txt"]
        assert state.mtime_ns == 999
        assert state.size_bytes == 42
        assert state.sha256 == "abc"

    def test_forget_removes_entries(self, repository: Repository, stored_pair: SyncPair) -> None:
        for name in ("a.txt", "b.txt"):
            repository.record_upload(
                stored_pair.uid,
                relative_path=name,
                size_bytes=1,
                mtime_ns=1,
                remote_path=f"/my-files/Backup/{name}",
            )

        repository.forget_file_states(stored_pair.uid, ["a.txt"])

        assert set(repository.load_file_states(stored_pair.uid)) == {"b.txt"}

    def test_forget_with_empty_list_is_a_noop(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        repository.forget_file_states(stored_pair.uid, [])
        assert repository.load_file_states(stored_pair.uid) == {}

    def test_clear_removes_everything(self, repository: Repository, stored_pair: SyncPair) -> None:
        repository.record_upload(
            stored_pair.uid,
            relative_path="a.txt",
            size_bytes=1,
            mtime_ns=1,
            remote_path="/my-files/Backup/a.txt",
        )

        repository.clear_file_states(stored_pair.uid)

        assert repository.load_file_states(stored_pair.uid) == {}

    def test_states_are_isolated_per_pair(self, repository: Repository, source_dir: Path) -> None:
        first = SyncPair.create(name="A", local_path=source_dir, remote_path="/my-files/A")
        second = SyncPair.create(name="B", local_path=source_dir, remote_path="/my-files/B")
        repository.save_pair(first)
        repository.save_pair(second)
        repository.record_upload(
            first.uid,
            relative_path="a.txt",
            size_bytes=1,
            mtime_ns=1,
            remote_path="/my-files/A/a.txt",
        )

        assert repository.load_file_states(second.uid) == {}


class TestRunHistory:
    """Laufprotokolle."""

    def test_start_and_finish(self, repository: Repository, stored_pair: SyncPair) -> None:
        run_id = repository.start_run(stored_pair.uid, dry_run=False)
        record = RunRecord(pair_uid=stored_pair.uid, run_id=run_id, uploaded_files=3)
        record.finish()

        repository.finish_run(record)

        stored = repository.last_run(stored_pair.uid)
        assert stored is not None
        assert stored.uploaded_files == 3
        assert stored.status is RunStatus.SUCCESS
        assert stored.finished_at is not None

    def test_errors_are_stored_and_loaded(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        run_id = repository.start_run(stored_pair.uid, dry_run=False)
        record = RunRecord(pair_uid=stored_pair.uid, run_id=run_id, uploaded_files=1)
        record.errors = [
            FileError(relative_path="a.txt", message="kaputt", attempts=3, permanent=True)
        ]
        record.failed_files = 1
        record.finish()

        repository.finish_run(record)

        stored = repository.last_run(stored_pair.uid)
        assert stored is not None
        assert len(stored.errors) == 1
        assert stored.errors[0].attempts == 3
        assert stored.errors[0].permanent is True

    def test_finish_without_run_id_is_rejected(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        with pytest.raises(ValueError, match="run_id"):
            repository.finish_run(RunRecord(pair_uid=stored_pair.uid))

    def test_last_run_is_the_newest(self, repository: Repository, stored_pair: SyncPair) -> None:
        for index in range(3):
            run_id = repository.start_run(stored_pair.uid, dry_run=False)
            record = RunRecord(pair_uid=stored_pair.uid, run_id=run_id, uploaded_files=index)
            record.finish()
            repository.finish_run(record)

        stored = repository.last_run(stored_pair.uid)
        assert stored is not None
        assert stored.uploaded_files == 2

    def test_last_run_can_exclude_dry_runs(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        real_id = repository.start_run(stored_pair.uid, dry_run=False)
        real = RunRecord(pair_uid=stored_pair.uid, run_id=real_id, uploaded_files=5)
        real.finish()
        repository.finish_run(real)

        dry_id = repository.start_run(stored_pair.uid, dry_run=True)
        dry = RunRecord(pair_uid=stored_pair.uid, run_id=dry_id, dry_run=True)
        dry.finish()
        repository.finish_run(dry)

        assert repository.last_run(stored_pair.uid).dry_run is True
        assert repository.last_run(stored_pair.uid, include_dry_runs=False).uploaded_files == 5

    def test_last_runs_covers_all_pairs(self, repository: Repository, source_dir: Path) -> None:
        pairs = []
        for name in ("A", "B"):
            pair = SyncPair.create(
                name=name, local_path=source_dir, remote_path=f"/my-files/{name}"
            )
            repository.save_pair(pair)
            pairs.append(pair)
            run_id = repository.start_run(pair.uid, dry_run=False)
            record = RunRecord(pair_uid=pair.uid, run_id=run_id)
            record.finish()
            repository.finish_run(record)

        last = repository.last_runs()

        assert set(last) == {pair.uid for pair in pairs}

    def test_prune_keeps_the_newest(self, repository: Repository, stored_pair: SyncPair) -> None:
        for _ in range(10):
            run_id = repository.start_run(stored_pair.uid, dry_run=False)
            record = RunRecord(pair_uid=stored_pair.uid, run_id=run_id)
            record.finish()
            repository.finish_run(record)

        repository.prune_runs(stored_pair.uid, keep=3)

        assert len(repository.list_runs(stored_pair.uid, limit=100)) == 3


class TestValidation:
    """Validierung der Eingaben."""

    def test_empty_name_is_rejected(self, source_dir: Path) -> None:
        with pytest.raises(ValidationError, match="Anzeigename"):
            SyncPair.create(name="  ", local_path=source_dir, remote_path="/my-files/A")

    def test_relative_local_path_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="absoluter Pfad"):
            validate_local_path("relativ/pfad")

    def test_missing_local_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="existiert nicht"):
            validate_local_path(tmp_path / "gibtsnicht")

    def test_file_as_local_path_is_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "datei.txt"
        target.write_text("x")
        with pytest.raises(ValidationError, match="kein Ordner"):
            validate_local_path(target)

    def test_symlinked_source_is_rejected(self, tmp_path: Path, source_dir: Path) -> None:
        link = tmp_path / "verweis"
        link.symlink_to(source_dir)
        with pytest.raises(ValidationError, match="symbolischer Link"):
            validate_local_path(link)

    def test_root_as_local_path_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Wurzelverzeichnis"):
            validate_local_path("/")

    def test_local_path_is_normalized(self, source_dir: Path) -> None:
        messy = f"{source_dir}/./unterordner/.."
        (source_dir / "unterordner").mkdir()
        assert validate_local_path(messy) == source_dir

    @pytest.mark.parametrize(
        "path,message",
        [
            ("", "leer"),
            ("relativ", "absolut"),
            ("/", "Wurzelverzeichnis"),
            ("/my-files/../etc", ".."),
            ("/unbekannt/x", "kein bekannter"),
            ("/trash/x", "nicht hochladen"),
            ("/photos/x", "nicht hochladen"),
            ("/my-files/mit\\backslash", "Backslash"),
        ],
    )
    def test_invalid_remote_paths(self, path: str, message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            validate_remote_path(path)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/my-files", "/my-files"),
            ("/my-files/Backup", "/my-files/Backup"),
            ("/my-files/Backup/", "/my-files/Backup"),
            ("  /my-files//Backup  ", "/my-files/Backup"),
            ("/devices/Rechner/Daten", "/devices/Rechner/Daten"),
        ],
    )
    def test_valid_remote_paths_are_normalized(self, raw: str, expected: str) -> None:
        assert validate_remote_path(raw) == expected

    def test_interval_below_minimum_is_rejected(self, source_dir: Path) -> None:
        with pytest.raises(ValidationError, match="Intervall"):
            SyncPair.create(
                name="Zu haeufig",
                local_path=source_dir,
                remote_path="/my-files/A",
                schedule_kind=ScheduleKind.INTERVAL,
                interval_minutes=1,
            )

    def test_interval_without_value_is_rejected(self, source_dir: Path) -> None:
        with pytest.raises(ValidationError, match="Minuten"):
            SyncPair.create(
                name="Ohne Wert",
                local_path=source_dir,
                remote_path="/my-files/A",
                schedule_kind=ScheduleKind.INTERVAL,
            )

    def test_zero_size_limit_is_rejected(self, source_dir: Path) -> None:
        with pytest.raises(ValidationError, match="Groessenlimit"):
            SyncPair.create(
                name="Null",
                local_path=source_dir,
                remote_path="/my-files/A",
                max_file_size_bytes=0,
            )

    def test_manual_schedule_clears_the_interval(self, source_dir: Path) -> None:
        pair = SyncPair.create(
            name="Manuell",
            local_path=source_dir,
            remote_path="/my-files/A",
            schedule_kind=ScheduleKind.MANUAL,
            interval_minutes=60,
        )
        assert pair.interval_minutes is None
        assert pair.is_scheduled is False
