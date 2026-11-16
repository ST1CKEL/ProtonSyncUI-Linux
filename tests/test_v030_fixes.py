"""Regressionstests zu Version 0.3.0.

Abgedeckt sind die Fehler, die die Synchronisation in der Praxis lahmgelegt
haben (uebersetzte Fehlertexte, Abmeldung mitten im Lauf, haengende Laeufe,
unlesbare Cloud-Ordner) sowie Update-Suche, Autostart und Einstellungen.
"""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from proton_sync_ui import autostart, settings, update
from proton_sync_ui.cli_adapter.adapter import ProtonDriveAdapter, classify_error
from proton_sync_ui.cli_adapter.capabilities import probe
from proton_sync_ui.cli_adapter.errors import (
    NotAuthenticatedError,
    RemotePathExistsError,
    RemotePathNotFoundError,
    TransientError,
)
from proton_sync_ui.models.plan import PlanAction
from proton_sync_ui.models.run import RunStatus
from proton_sync_ui.models.sync_pair import SyncMode, SyncPair
from proton_sync_ui.storage.repository import Repository
from proton_sync_ui.sync import engine as engine_module
from proton_sync_ui.sync.engine import SyncEngine
from proton_sync_ui.sync.remote_scanner import scan_remote_directory
from proton_sync_ui.sync.retry import RetryPolicy

from .conftest import MakeFile
from .fake_proton_drive import FakeAdapter, make_auth_error, make_transient_error

FAST_RETRY = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=0.0)
GERMAN_EXISTS = "Datei oder Ordner mit diesem Namen existiert bereits."


def run_sync(repository: Repository, pair: SyncPair, adapter: FakeAdapter):
    engine = SyncEngine(repository, adapter, retry_policy=FAST_RETRY)  # type: ignore[arg-type]
    return asyncio.run(engine.sync(pair))


class TestErrorClassification:
    """Meldungen der echten CLI muessen richtig eingeordnet werden."""

    def test_real_logged_out_message_is_an_auth_error(self) -> None:
        error = classify_error(returncode=1, output="You need to login first", argv=["x"])
        assert isinstance(error, NotAuthenticatedError)

    def test_german_exists_message(self) -> None:
        error = classify_error(returncode=1, output=GERMAN_EXISTS, argv=["x"])
        assert isinstance(error, RemotePathExistsError)

    def test_german_not_found_message(self) -> None:
        error = classify_error(returncode=1, output="Ordner nicht gefunden", argv=["x"])
        assert isinstance(error, RemotePathNotFoundError)

    def test_child_processes_ask_for_english_messages(self) -> None:
        env = ProtonDriveAdapter()._build_env()
        assert env["LANGUAGE"] == "en"
        assert "LC_ALL" not in env

    def test_binary_is_found_outside_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # systemd und Autostart kennen ~/.local/bin nicht im PATH.
        home = tmp_path / "home"
        binary = home / ".local" / "bin" / "proton-drive"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", str(tmp_path / "leer"))
        assert ProtonDriveAdapter().resolve_binary() == str(binary)

    def test_probe_reports_logged_out_instead_of_unknown(self) -> None:
        caps = asyncio.run(probe(FakeAdapter(authenticated=False)))  # type: ignore[arg-type]
        assert caps.needs_login
        assert not caps.auth_check_failed


class TestExistingRemoteFolders:
    """Uploads in bestehende Ordner scheiterten an 'existiert bereits'."""

    def test_existing_folder_is_not_created_again(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("Projekte/neu.txt")
        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup", "/my-files/Backup/Projekte"},
            # create-folder wuerde mit einer nicht erkannten Meldung scheitern.
            folder_errors={
                "/my-files/Backup": TransientError(GERMAN_EXISTS),
                "/my-files/Backup/Projekte": TransientError(GERMAN_EXISTS),
            },
        )

        record, _plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.SUCCESS
        assert adapter.uploaded_names == ["neu.txt"]
        assert adapter.created_folders == []

    def test_upload_only_mode_also_checks_by_listing(
        self, repository: Repository, sample_pair: SyncPair, make_file: MakeFile
    ) -> None:
        pair = sample_pair.with_changes(sync_mode=SyncMode.UPLOAD_ONLY)
        repository.save_pair(pair)
        make_file("a/b.txt")
        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup", "/my-files/Backup/a"},
            folder_errors={"/my-files/Backup/a": TransientError(GERMAN_EXISTS)},
        )

        record, _plan = run_sync(repository, pair, adapter)

        assert record.status is RunStatus.SUCCESS
        assert adapter.uploaded_names == ["b.txt"]


class TestRunAbort:
    """Aussichtslose Laeufe enden sofort statt tausende Anfragen zu senden."""

    def test_logout_during_run_stops_immediately(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        for index in range(10):
            make_file(f"datei{index:02d}.txt")
        adapter = FakeAdapter(upload_errors={"datei03.txt": make_auth_error()})

        record, _plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert "nicht angemeldet" in record.message
        assert record.uploaded_files == 3
        # Nach dem Anmeldefehler wurde keine weitere Datei versucht.
        assert len(adapter.uploaded_names) == 3
        assert adapter.attempts_for("datei03.txt") == 1

    def test_many_consecutive_failures_end_the_run(
        self,
        repository: Repository,
        stored_pair: SyncPair,
        make_file: MakeFile,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(engine_module, "MAX_CONSECUTIVE_FAILURES", 4)
        names = [f"f{index:02d}.txt" for index in range(12)]
        for name in names:
            make_file(name)
        adapter = FakeAdapter(upload_errors={name: make_transient_error() for name in names})

        record, _plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert record.failed_files == 4
        assert "in Folge" in record.message

    def test_interrupted_runs_are_closed_by_the_next_run(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        stale = repository.start_run(stored_pair.uid, dry_run=False)  # nie beendet
        make_file("a.txt")

        run_sync(repository, stored_pair, FakeAdapter())

        runs = {run.run_id: run for run in repository.list_runs(stored_pair.uid)}
        assert runs[stale].status is RunStatus.CANCELLED
        assert runs[stale].finished_at is not None


class _FlakyListing(FakeAdapter):
    """Adapter, dessen Auflistung fuer bestimmte Ordner dauerhaft scheitert."""

    broken: frozenset[str] = frozenset()

    async def list_dir(self, remote_path: str):
        if remote_path in self.broken:
            raise TransientError("socket hang up")
        return await super().list_dir(remote_path)


class TestUnreadableRemoteFolders:
    """Ein nicht lesbarer Cloud-Ordner darf nicht wie 'leer' behandelt werden."""

    def test_scanner_reports_failed_prefix(self) -> None:
        adapter = _FlakyListing(
            existing_folders={"/r/ok", "/r/kaputt"}, existing_files={"/r/ok/a.txt": 1}
        )
        adapter.broken = frozenset({"/r/kaputt"})

        result = asyncio.run(scan_remote_directory(adapter, "/r", retry_policy=FAST_RETRY))  # type: ignore[arg-type]

        assert result.failed_prefixes == ("kaputt",)
        assert result.is_unreadable("kaputt/x/y.txt")
        assert not result.is_unreadable("kaputt2/y.txt")
        assert not result.root_failed
        assert [item.key for item in result.files] == ["ok/a.txt"]

    def test_logged_out_scan_raises(self) -> None:
        class LoggedOut(FakeAdapter):
            async def list_dir(self, remote_path: str):
                raise make_auth_error()

        with pytest.raises(NotAuthenticatedError):
            asyncio.run(scan_remote_directory(LoggedOut(), "/r", retry_policy=FAST_RETRY))  # type: ignore[arg-type]

    def test_files_below_unreadable_folder_are_deferred(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("kaputt/lokal.txt")
        make_file("ok/neu.txt")
        adapter = _FlakyListing(
            existing_folders={"/my-files/Backup", "/my-files/Backup/kaputt", "/my-files/Backup/ok"}
        )
        adapter.broken = frozenset({"/my-files/Backup/kaputt"})

        record, plan = run_sync(repository, stored_pair, adapter)

        assert adapter.uploaded_names == ["neu.txt"]
        deferred = plan.by_action(PlanAction.SKIP_REMOTE_UNKNOWN)
        assert [item.posix_path for item in deferred] == ["kaputt/lokal.txt"]
        assert record.status is RunStatus.WARNING

    def test_unreadable_root_fails_the_run(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        adapter = _FlakyListing()
        adapter.broken = frozenset({"/my-files/Backup"})

        record, _plan = run_sync(repository, stored_pair, adapter)

        assert record.status is RunStatus.ERROR
        assert adapter.uploaded_names == []


class TestUpdate:
    """Update-Suche ohne Netz: der Abruf wird ersetzt."""

    @pytest.mark.parametrize(
        ("candidate", "current", "expected"),
        [
            ("0.3.0", "0.2.0", True),
            ("v0.10.0", "0.9.9", True),
            ("0.3", "0.3.0", False),
            ("0.3.0", "0.3.0", False),
            ("0.2.9", "0.3.0", False),
            ("1.0.0-beta", "0.9", True),
            ("kaputt", "0.1", False),
        ],
    )
    def test_version_comparison(self, candidate: str, current: str, expected: bool) -> None:
        assert update.is_newer(candidate, current) is expected

    def test_release_is_preferred(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(update, "__version__", "0.3.0")

        def fetch(url: str, *, timeout: float) -> bytes:
            assert url == update.RELEASE_API_URL
            return json.dumps({"tag_name": "v9.1.0", "body": "Neu"}).encode()

        info = update.check_for_update(fetch=fetch)
        assert info.available
        assert info.latest_version == "9.1.0"
        assert info.archive_url.endswith("/archive/refs/tags/v9.1.0.tar.gz")

    def test_falls_back_to_branch_without_release(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(update, "__version__", "0.3.0")

        def fetch(url: str, *, timeout: float) -> bytes:
            if url == update.RELEASE_API_URL:
                raise urllib.error.HTTPError(url, 404, "Not Found", Message(), io.BytesIO())
            return b'__version__ = "0.3.0"\n'

        info = update.check_for_update(fetch=fetch)
        assert not info.available
        assert info.source == "branch"

    def test_network_failure_is_reported(self) -> None:
        def fetch(url: str, *, timeout: float) -> bytes:
            raise OSError("kein Netz")

        with pytest.raises(update.UpdateError):
            update.check_for_update(fetch=fetch)

    def test_plain_http_is_refused(self) -> None:
        with pytest.raises(update.UpdateError):
            update._fetch("http://example.invalid/x", timeout=1)


class TestAutostart:
    def test_enable_writes_absolute_exec(self) -> None:
        path = autostart.enable(minimized=True, executable="/opt/x/proton-sync-ui-gui")
        text = path.read_text(encoding="utf-8")
        assert "Exec=/opt/x/proton-sync-ui-gui --minimized\n" in text
        assert autostart.is_enabled()
        assert autostart.is_minimized()

    def test_window_mode_and_disable(self) -> None:
        autostart.enable(minimized=False, executable="/opt/x/gui")
        assert not autostart.is_minimized()
        assert autostart.disable() is True
        assert not autostart.is_enabled()
        assert autostart.disable() is False

    def test_refresh_only_touches_existing_entry(self) -> None:
        assert autostart.refresh() is False
        assert not autostart.autostart_file().exists()


class TestSettings:
    def test_roundtrip(self) -> None:
        current = settings.load()
        assert current.notifications is True
        current.notifications = False
        settings.save(current)
        assert settings.load().notifications is False

    def test_broken_file_falls_back_to_defaults(self) -> None:
        path = settings.settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"notifications": "ja", ', encoding="utf-8")
        assert settings.load() == settings.Settings()


class TestReviewFindings:
    """Fehler aus der Durchsicht nach 0.3.0."""

    def test_listing_keeps_hex_file_names(self) -> None:
        # Die Log-Schwaerzung ersetzt lange Hex-Folgen. Auf die JSON-Auflistung
        # angewandt, wurden daraus Dateien namens "<redigiert:blob>".
        from proton_sync_ui.cli_adapter.adapter import CommandResult, _parse_nodes
        from proton_sync_ui.logging_setup import redact

        name = "f2a73b2ae8a30f8377b25e87b35cb3a305c1ac8ba3e151e4c410d1ff9e633ffa"
        raw = json.dumps([{"name": name, "type": "file", "totalStorageSize": 3}])
        result = CommandResult(
            argv=("filesystem", "list"),
            returncode=0,
            stdout=redact(raw, max_length=None),
            stderr="",
            duration_seconds=0.0,
            raw_stdout=raw,
        )
        assert name not in result.stdout
        nodes = _parse_nodes(result.raw_stdout, remote_parent="/my-files/x")
        assert [node.name for node in nodes] == [name]
        assert nodes[0].path == f"/my-files/x/{name}"

    def test_locally_skipped_file_is_not_replaced_by_cloud_copy(
        self, repository: Repository, stored_pair: SyncPair, source_dir: Path
    ) -> None:
        # Lokal ein Symlink (wird nie synchronisiert), in der Cloud eine Datei
        # gleichen Namens: der Symlink darf nicht ersetzt werden.
        target = source_dir.parent / "ziel.txt"
        target.write_text("ziel")
        (source_dir / "link.txt").symlink_to(target)
        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup"},
            existing_files={"/my-files/Backup/link.txt": 99},
        )

        record, plan = run_sync(repository, stored_pair, adapter)

        assert adapter.downloads == []
        assert (source_dir / "link.txt").is_symlink()
        assert record.status is RunStatus.SUCCESS
        assert len(plan.downloads) == 0

    def test_changing_the_target_discards_old_file_states(
        self, repository: Repository, stored_pair: SyncPair, make_file: MakeFile
    ) -> None:
        make_file("a.txt")
        run_sync(repository, stored_pair, FakeAdapter())
        assert repository.load_file_states(stored_pair.uid)

        renamed = stored_pair.with_changes(name="Anderer Name")
        repository.save_pair(renamed)
        assert repository.load_file_states(stored_pair.uid)  # Name allein aendert nichts

        moved = renamed.with_changes(remote_path="/my-files/Woanders")
        repository.save_pair(moved)
        assert repository.load_file_states(stored_pair.uid) == {}

        adapter = FakeAdapter()
        record, _plan = run_sync(repository, moved, adapter)
        assert adapter.uploaded_names == ["a.txt"]
        assert record.uploaded_files == 1
