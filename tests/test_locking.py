"""Tests der Sperre gegen gleichzeitige Laeufe."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from proton_sync_ui.models.sync_pair import SyncPair
from proton_sync_ui.storage.database import connect
from proton_sync_ui.storage.locking import (
    PairLockedError,
    acquire,
    current_boot_id,
    is_locked,
    process_start_time,
    read_lock,
    release,
    run_lock,
)
from proton_sync_ui.storage.repository import Repository
from proton_sync_ui.sync.engine import SyncEngine

from .fake_proton_drive import FakeAdapter

MakeFile = Callable[..., Path]

#: Eine Prozess-ID, die mit an Sicherheit grenzender Wahrscheinlichkeit
#: nicht existiert.
DEAD_PID = 4_194_303


def insert_raw_lock(
    connection: sqlite3.Connection,
    pair_uid: str,
    *,
    pid: int,
    boot_id: str,
    pid_start_time: int = 0,
) -> None:
    """Schreibt eine Sperre direkt in die Tabelle -- fuer Testszenarien."""
    connection.execute(
        """
        INSERT INTO run_locks (pair_uid, pid, boot_id, pid_start_time, acquired_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (pair_uid, pid, boot_id, pid_start_time, datetime.now(tz=UTC).isoformat(), "test"),
    )
    connection.commit()


class TestAcquireAndRelease:
    """Grundlegender Lebenszyklus."""

    def test_acquire_creates_a_lock(self, repository: Repository, stored_pair: SyncPair) -> None:
        info = acquire(repository.connection, stored_pair.uid, source="test")

        assert info.pid == os.getpid()
        assert info.boot_id == current_boot_id()
        assert is_locked(repository.connection, stored_pair.uid)

    def test_release_removes_the_lock(self, repository: Repository, stored_pair: SyncPair) -> None:
        acquire(repository.connection, stored_pair.uid)
        assert release(repository.connection, stored_pair.uid) is True
        assert not is_locked(repository.connection, stored_pair.uid)

    def test_release_without_lock_returns_false(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        assert release(repository.connection, stored_pair.uid) is False

    def test_second_acquire_is_refused(self, repository: Repository, stored_pair: SyncPair) -> None:
        acquire(repository.connection, stored_pair.uid, source="erster")

        with pytest.raises(PairLockedError) as error:
            acquire(repository.connection, stored_pair.uid, source="zweiter")

        assert stored_pair.uid == error.value.pair_uid
        assert "laeuft bereits" in str(error.value)

    def test_different_pairs_lock_independently(
        self, repository: Repository, source_dir: Path
    ) -> None:
        first = SyncPair.create(name="A", local_path=source_dir, remote_path="/my-files/A")
        second = SyncPair.create(name="B", local_path=source_dir, remote_path="/my-files/B")
        repository.save_pair(first)
        repository.save_pair(second)

        acquire(repository.connection, first.uid)
        acquire(repository.connection, second.uid)  # darf nicht scheitern

        assert is_locked(repository.connection, first.uid)
        assert is_locked(repository.connection, second.uid)


class TestContextManager:
    """Der Kontextmanager gibt die Sperre zuverlaessig frei."""

    def test_lock_is_released_on_exit(self, repository: Repository, stored_pair: SyncPair) -> None:
        with run_lock(repository.connection, stored_pair.uid, source="test"):
            assert is_locked(repository.connection, stored_pair.uid)

        assert not is_locked(repository.connection, stored_pair.uid)

    def test_lock_is_released_after_an_exception(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        with pytest.raises(RuntimeError), run_lock(repository.connection, stored_pair.uid):
            raise RuntimeError("etwas ist schiefgegangen")

        assert not is_locked(repository.connection, stored_pair.uid)

    def test_nested_lock_on_same_pair_is_refused(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        with run_lock(repository.connection, stored_pair.uid), pytest.raises(PairLockedError):
            acquire(repository.connection, stored_pair.uid)


class TestStaleLocks:
    """Verwaiste Sperren werden erkannt und aufgeraeumt."""

    def test_lock_from_a_previous_boot_is_stale(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        insert_raw_lock(
            repository.connection,
            stored_pair.uid,
            pid=os.getpid(),
            boot_id="00000000-0000-0000-0000-000000000000",
        )

        assert not is_locked(repository.connection, stored_pair.uid)
        # Und der Erwerb gelingt wieder.
        acquire(repository.connection, stored_pair.uid)
        assert is_locked(repository.connection, stored_pair.uid)

    def test_lock_of_a_dead_process_is_stale(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        insert_raw_lock(
            repository.connection,
            stored_pair.uid,
            pid=DEAD_PID,
            boot_id=current_boot_id(),
        )

        assert not is_locked(repository.connection, stored_pair.uid)
        acquire(repository.connection, stored_pair.uid)

    def test_recycled_pid_is_detected(self, repository: Repository, stored_pair: SyncPair) -> None:
        # Gleiche PID, aber eine andere Startzeit: der urspruengliche Prozess
        # ist tot, die Nummer wurde neu vergeben.
        insert_raw_lock(
            repository.connection,
            stored_pair.uid,
            pid=os.getpid(),
            boot_id=current_boot_id(),
            pid_start_time=process_start_time(os.getpid()) + 999_999,
        )

        assert not is_locked(repository.connection, stored_pair.uid)

    def test_live_lock_of_the_current_process_is_kept(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        insert_raw_lock(
            repository.connection,
            stored_pair.uid,
            pid=os.getpid(),
            boot_id=current_boot_id(),
            pid_start_time=process_start_time(os.getpid()),
        )

        assert is_locked(repository.connection, stored_pair.uid)

    def test_stale_lock_is_replaced_not_duplicated(
        self, repository: Repository, stored_pair: SyncPair
    ) -> None:
        insert_raw_lock(
            repository.connection, stored_pair.uid, pid=DEAD_PID, boot_id=current_boot_id()
        )

        acquire(repository.connection, stored_pair.uid)

        info = read_lock(repository.connection, stored_pair.uid)
        assert info is not None
        assert info.pid == os.getpid()
        count = repository.connection.execute(
            "SELECT COUNT(*) FROM run_locks WHERE pair_uid = ?", (stored_pair.uid,)
        ).fetchone()[0]
        assert count == 1


class TestCrossConnectionLocking:
    """Die Sperre wirkt zwischen getrennten Verbindungen und Prozessen."""

    def test_second_connection_sees_the_lock(self, db_path: Path, source_dir: Path) -> None:
        first = Repository(connect(db_path))
        pair = SyncPair.create(
            name="Gemeinsam", local_path=source_dir, remote_path="/my-files/Backup"
        )
        first.save_pair(pair)

        second = Repository(connect(db_path))
        try:
            acquire(first.connection, pair.uid, source="gui")

            with pytest.raises(PairLockedError):
                acquire(second.connection, pair.uid, source="systemd")
        finally:
            first.close()
            second.close()

    def test_release_frees_it_for_the_other_connection(
        self, db_path: Path, source_dir: Path
    ) -> None:
        first = Repository(connect(db_path))
        pair = SyncPair.create(
            name="Gemeinsam", local_path=source_dir, remote_path="/my-files/Backup"
        )
        first.save_pair(pair)
        second = Repository(connect(db_path))
        try:
            acquire(first.connection, pair.uid)
            release(first.connection, pair.uid)
            acquire(second.connection, pair.uid)  # gelingt jetzt
        finally:
            first.close()
            second.close()


class TestEngineRespectsTheLock:
    """Die Sync-Engine verweigert parallele Laeufe."""

    def test_engine_refuses_while_locked(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("datei.txt")
        acquire(repository.connection, stored_pair.uid, source="fremder-lauf")

        engine = SyncEngine(repository, FakeAdapter())

        with pytest.raises(PairLockedError):
            asyncio.run(engine.sync(stored_pair))

    def test_engine_releases_the_lock_afterwards(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("datei.txt")
        engine = SyncEngine(repository, FakeAdapter())

        asyncio.run(engine.sync(stored_pair))

        assert not is_locked(repository.connection, stored_pair.uid)

    def test_engine_releases_the_lock_after_a_failure(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("datei.txt")
        engine = SyncEngine(repository, FakeAdapter(available=False))

        record, _plan = asyncio.run(engine.sync(stored_pair))

        assert record.status.value == "error"
        assert not is_locked(repository.connection, stored_pair.uid)

    def test_two_sequential_runs_both_succeed(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("datei.txt")

        first, _ = asyncio.run(SyncEngine(repository, FakeAdapter()).sync(stored_pair))
        second, _ = asyncio.run(SyncEngine(repository, FakeAdapter()).sync(stored_pair))

        assert first.status.value == "success"
        assert second.status.value == "success"

    def test_dry_run_also_takes_the_lock(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("datei.txt")
        acquire(repository.connection, stored_pair.uid, source="fremder-lauf")

        with pytest.raises(PairLockedError):
            asyncio.run(SyncEngine(repository, FakeAdapter()).dry_run(stored_pair))
