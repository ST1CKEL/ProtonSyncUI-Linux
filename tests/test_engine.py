"""Tests der Sync-Engine: Uebertragung, Fehlertoleranz, Zustandspflege."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

from proton_sync_ui.models.run import RunStatus
from proton_sync_ui.models.sync_pair import SyncPair
from proton_sync_ui.storage.repository import Repository
from proton_sync_ui.sync.engine import SyncEngine, SyncPhase, SyncProgress
from proton_sync_ui.sync.retry import RetryPolicy

from .fake_proton_drive import (
    FakeAdapter,
    make_permanent_error,
    make_transient_error,
)

MakeFile = Callable[..., Path]

#: Wiederholstrategie ohne echte Wartezeit -- fuer schnelle Tests.
FAST_RETRY = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=0.0)


def run_sync(
    repository: Repository,
    pair: SyncPair,
    adapter: FakeAdapter,
    **kwargs: object,
) -> tuple[object, object]:
    """Fuehrt einen Lauf aus und gibt (Protokoll, Plan) zurueck."""
    engine = SyncEngine(repository, adapter, retry_policy=FAST_RETRY, **kwargs)  # type: ignore[arg-type]
    return asyncio.run(engine.sync(pair))


class TestSuccessfulRun:
    """Der Normalfall."""

    def test_all_files_are_uploaded(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "A")
        make_file("b.txt", "B")
        adapter = FakeAdapter()

        record, _plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.SUCCESS
        assert record.uploaded_files == 2
        assert record.failed_files == 0
        assert sorted(adapter.uploaded_names) == ["a.txt", "b.txt"]

    def test_uploads_go_to_the_right_parent_folder(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("oben.txt")
        make_file("unter/tief.txt")
        adapter = FakeAdapter()

        run_sync(repository, stored_pair, adapter)

        parents = {call.local_path.name: call.remote_parent for call in adapter.uploads}
        assert parents["oben.txt"] == "/my-files/Backup"
        assert parents[["unter", "tief.txt"][-1]] == "/my-files/Backup/unter"

    def test_missing_folders_are_created(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a/b/c/datei.txt")
        adapter = FakeAdapter()

        run_sync(repository, stored_pair, adapter)

        created = {f"{call.parent}/{call.name}" for call in adapter.created_folders}
        assert "/my-files/Backup" in created
        assert "/my-files/Backup/a" in created
        assert "/my-files/Backup/a/b" in created
        assert "/my-files/Backup/a/b/c" in created

    def test_existing_folders_are_not_recreated(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("unter/a.txt")
        make_file("unter/b.txt")
        adapter = FakeAdapter()

        run_sync(repository, stored_pair, adapter)

        # Jeder Ordner wird nur einmal angelegt, obwohl zwei Dateien darin liegen.
        names = [f"{call.parent}/{call.name}" for call in adapter.created_folders]
        assert len(names) == len(set(names))

    def test_uploaded_bytes_are_counted(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "12345")
        make_file("b.txt", "123")

        record, _ = run_sync(repository, stored_pair, FakeAdapter())

        assert record.uploaded_bytes == 8

    def test_state_is_recorded_for_uploaded_files(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "Inhalt")

        run_sync(repository, stored_pair, FakeAdapter())

        states = repository.load_file_states(stored_pair.uid)
        assert "a.txt" in states
        assert states["a.txt"].size_bytes == 6
        assert states["a.txt"].remote_path == "/my-files/Backup/a.txt"

    def test_second_run_uploads_nothing(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "Inhalt")
        run_sync(repository, stored_pair, FakeAdapter())

        adapter = FakeAdapter(existing_folders={"/my-files/Backup"})
        record, plan = run_sync(repository, stored_pair, adapter)

        assert adapter.uploads == []
        assert record.uploaded_files == 0
        assert plan.is_empty

    def test_changed_file_is_uploaded_again(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt", "Erste Fassung")
        run_sync(repository, stored_pair, FakeAdapter())

        make_file("a.txt", "Zweite, laengere Fassung")
        adapter = FakeAdapter(existing_folders={"/my-files/Backup"})
        record, _ = run_sync(repository, stored_pair, adapter)

        assert adapter.uploaded_names == ["a.txt"]
        assert record.uploaded_files == 1


class TestPartialFailures:
    """Ein Dateifehler beendet den Lauf nicht."""

    def test_run_continues_after_a_file_error(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("gut1.txt")
        make_file("schlecht.txt")
        make_file("gut2.txt")
        adapter = FakeAdapter(upload_errors={"schlecht.txt": make_permanent_error()})

        record, _ = run_sync(repository, stored_pair, adapter)

        assert sorted(adapter.uploaded_names) == ["gut1.txt", "gut2.txt"]
        assert record.uploaded_files == 2
        assert record.failed_files == 1
        assert record.status is RunStatus.WARNING

    def test_failed_files_are_listed(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("gut.txt")
        make_file("schlecht.txt")
        adapter = FakeAdapter(
            upload_errors={"schlecht.txt": make_permanent_error("Kontingent voll")}
        )

        record, _ = run_sync(repository, stored_pair, adapter)

        assert len(record.errors) == 1
        assert record.errors[0].relative_path == "schlecht.txt"
        assert "Kontingent voll" in record.errors[0].message
        assert record.errors[0].permanent is True

    def test_failed_file_is_not_marked_as_uploaded(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("schlecht.txt")
        adapter = FakeAdapter(upload_errors={"schlecht.txt": make_permanent_error()})

        run_sync(repository, stored_pair, adapter)

        # Beim naechsten Lauf muss die Datei erneut versucht werden.
        assert "schlecht.txt" not in repository.load_file_states(stored_pair.uid)

    def test_all_files_failing_yields_error_status(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        make_file("b.txt")
        adapter = FakeAdapter(
            upload_errors={
                "a.txt": make_permanent_error(),
                "b.txt": make_permanent_error(),
            }
        )

        record, _ = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert record.failed_files == 2

    def test_errors_are_persisted(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("schlecht.txt")
        adapter = FakeAdapter(upload_errors={"schlecht.txt": make_permanent_error()})

        record, _ = run_sync(repository, stored_pair, adapter)

        stored = repository.list_run_errors(record.run_id)
        assert len(stored) == 1
        assert stored[0].relative_path == "schlecht.txt"

    def test_vanished_file_is_reported_not_fatal(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        target = make_file("fluechtig.txt")
        make_file("bleibt.txt")

        def delete_between_scan_and_upload(progress: SyncProgress) -> None:
            # Die Fortschrittsmeldung kommt unmittelbar vor dem Upload.
            if progress.relative_path == "fluechtig.txt":
                target.unlink(missing_ok=True)

        adapter = FakeAdapter()
        record, _ = run_sync(
            repository, stored_pair, adapter, progress=delete_between_scan_and_upload
        )

        assert record.failed_files == 1
        assert record.errors[0].relative_path == "fluechtig.txt"
        assert "verschwunden" in record.errors[0].message
        # Der Lauf ist trotzdem weitergelaufen.
        assert "bleibt.txt" in adapter.uploaded_names


class TestRetryBehaviour:
    """Zusammenspiel mit der Wiederholstrategie."""

    def test_transient_error_is_retried_and_succeeds(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("wackelig.txt")
        adapter = FakeAdapter(upload_errors={"wackelig.txt": [make_transient_error(), None]})

        record, _ = run_sync(repository, stored_pair, adapter)

        assert record.uploaded_files == 1
        assert record.failed_files == 0
        assert adapter.attempts_for("wackelig.txt") == 2

    def test_permanent_error_is_not_retried(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("hoffnungslos.txt")
        adapter = FakeAdapter(upload_errors={"hoffnungslos.txt": make_permanent_error()})

        run_sync(repository, stored_pair, adapter)

        assert adapter.attempts_for("hoffnungslos.txt") == 1

    def test_transient_error_gives_up_after_max_attempts(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("dauerhaft-gestoert.txt")
        adapter = FakeAdapter(upload_errors={"dauerhaft-gestoert.txt": make_transient_error()})

        record, _ = run_sync(repository, stored_pair, adapter)

        assert adapter.attempts_for("dauerhaft-gestoert.txt") == FAST_RETRY.max_attempts
        assert record.failed_files == 1
        assert record.errors[0].permanent is False


class TestPreflight:
    """Vorabpruefung der CLI."""

    def test_missing_cli_fails_the_run_cleanly(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        adapter = FakeAdapter(available=False)

        record, plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert "nicht gefunden" in record.message
        assert adapter.uploads == []
        assert len(plan) == 0

    def test_unauthenticated_cli_fails_the_run_cleanly(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        adapter = FakeAdapter(authenticated=False)

        record, _ = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert "auth login" in record.message
        assert adapter.uploads == []

    def test_missing_source_directory_is_reported(
        self, repository: Repository, source_dir: Path
    ) -> None:
        pair = SyncPair.create(name="Weg", local_path=source_dir, remote_path="/my-files/Backup")
        repository.save_pair(pair)
        source_dir.rmdir()

        record, _ = run_sync(repository, pair, FakeAdapter())

        assert record.status is RunStatus.ERROR
        assert "existiert nicht" in record.message


class TestProgressReporting:
    """Fortschrittsmeldungen."""

    def test_progress_is_reported_for_each_file(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        make_file("b.txt")
        seen: list[SyncProgress] = []

        run_sync(repository, stored_pair, FakeAdapter(), progress=seen.append)

        uploading = [item for item in seen if item.phase is SyncPhase.UPLOADING]
        assert len(uploading) == 2
        assert {item.relative_path for item in uploading} == {"a.txt", "b.txt"}

    def test_progress_ends_with_done(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        seen: list[SyncProgress] = []

        run_sync(repository, stored_pair, FakeAdapter(), progress=seen.append)

        assert seen[-1].phase is SyncPhase.DONE

    def test_progress_fraction_stays_in_range(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        for index in range(5):
            make_file(f"datei{index}.txt")
        seen: list[SyncProgress] = []

        run_sync(repository, stored_pair, FakeAdapter(), progress=seen.append)

        assert all(0.0 <= item.fraction <= 1.0 for item in seen)

    def test_failing_progress_callback_does_not_break_the_run(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")

        def broken(_progress: SyncProgress) -> None:
            raise RuntimeError("Anzeigefehler")

        record, _ = run_sync(repository, stored_pair, FakeAdapter(), progress=broken)

        assert record.status is RunStatus.SUCCESS
        assert record.uploaded_files == 1


class TestRunHistory:
    """Protokollierung der Laeufe."""

    def test_run_is_stored(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")

        record, _ = run_sync(repository, stored_pair, FakeAdapter())

        stored = repository.last_run(stored_pair.uid)
        assert stored is not None
        assert stored.run_id == record.run_id
        assert stored.status is RunStatus.SUCCESS

    def test_dry_run_is_marked_as_such(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        engine = SyncEngine(repository, FakeAdapter(), retry_policy=FAST_RETRY)

        record, _ = asyncio.run(engine.dry_run(stored_pair))

        assert record.dry_run is True
        stored = repository.last_run(stored_pair.uid)
        assert stored is not None
        assert stored.dry_run is True

    def test_run_has_a_duration(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")

        record, _ = run_sync(repository, stored_pair, FakeAdapter())

        assert record.duration_seconds is not None
        assert record.duration_seconds >= 0

    def test_summary_line_is_readable(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")

        record, _ = run_sync(repository, stored_pair, FakeAdapter())

        line = record.summary_line()
        assert "Erfolgreich" in line
        assert "uebertragen: 1" in line


class TestMtimeRefresh:
    """Verhalten bei geaenderter mtime ohne geaenderten Inhalt.

    Nach einem gewoehnlichen Upload liegt keine Pruefsumme vor -- sie zu
    berechnen wuerde bedeuten, jede hochgeladene Datei ein zweites Mal
    vollstaendig zu lesen. Der erste mtime-Konflikt fuehrt deshalb noch zu
    einer erneuten Uebertragung; dabei entsteht die Pruefsumme. Ab dann wird
    der Fall korrekt als "unveraendert" erkannt.
    """

    def test_first_touch_reuploads_and_stores_a_checksum(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        target = make_file("a.txt", "Unveraenderter Inhalt")
        run_sync(repository, stored_pair, FakeAdapter())
        assert repository.load_file_states(stored_pair.uid)["a.txt"].sha256 is None

        os.utime(target, ns=(999_000_000_000, 999_000_000_000))
        adapter = FakeAdapter(existing_folders={"/my-files/Backup"})
        record, _ = run_sync(repository, stored_pair, adapter)

        assert record.uploaded_files == 1
        state = repository.load_file_states(stored_pair.uid)["a.txt"]
        assert state.sha256 is not None
        assert state.mtime_ns == 999_000_000_000

    def test_further_touches_cause_no_upload(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        target = make_file("a.txt", "Unveraenderter Inhalt")
        run_sync(repository, stored_pair, FakeAdapter())

        # Erster Konflikt: Uebertragung, dabei entsteht die Pruefsumme.
        os.utime(target, ns=(999_000_000_000, 999_000_000_000))
        run_sync(repository, stored_pair, FakeAdapter(existing_folders={"/my-files/Backup"}))

        # Zweiter Konflikt: jetzt greift der Pruefsummenvergleich.
        os.utime(target, ns=(1_555_000_000_000, 1_555_000_000_000))
        adapter = FakeAdapter(existing_folders={"/my-files/Backup"})
        record, _ = run_sync(repository, stored_pair, adapter)

        assert adapter.uploads == []
        assert record.uploaded_files == 0
        # Die neue mtime wurde uebernommen, damit nicht bei jedem Lauf gehasht wird.
        assert repository.load_file_states(stored_pair.uid)["a.txt"].mtime_ns == 1_555_000_000_000
