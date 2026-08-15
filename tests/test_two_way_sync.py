"""Tests fuer 2-Wege-Synchronisation, Remote-Scanner und Download-Ausfuehrung."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from proton_sync_ui.models.plan import PlanAction
from proton_sync_ui.models.run import RunStatus
from proton_sync_ui.models.sync_pair import SyncMode, SyncPair
from proton_sync_ui.storage.repository import FileState, Repository
from proton_sync_ui.sync.engine import SyncEngine
from proton_sync_ui.sync.planner import build_plan
from proton_sync_ui.sync.remote_scanner import (
    RemoteScannedFile,
    RemoteScanResult,
    scan_remote_directory,
)
from proton_sync_ui.sync.scanner import scan_directory

from .fake_proton_drive import FakeAdapter


@pytest.fixture
def bidi_pair(source_dir: Path) -> SyncPair:
    return SyncPair.create(
        name="ZweiWege",
        local_path=source_dir,
        remote_path="/my-files/Backup",
        sync_mode=SyncMode.BIDIRECTIONAL,
    )


class TestRemoteScanner:
    """Prueft das Erkennen entfernter Ordnerinhalte."""

    def test_scans_remote_files(self) -> None:
        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup", "/my-files/Backup/sub"},
            existing_files={
                "/my-files/Backup/file1.txt": 100,
                "/my-files/Backup/sub/file2.png": 200,
            },
        )
        result = asyncio.run(scan_remote_directory(adapter, "/my-files/Backup"))

        assert len(result.files) == 2
        keys = {f.key for f in result.files}
        assert keys == {"file1.txt", "sub/file2.png"}
        assert result.total_bytes == 300

    def test_ignores_excluded_remote_files(self) -> None:
        from proton_sync_ui.sync.ignore import IgnoreMatcher

        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup"},
            existing_files={
                "/my-files/Backup/wichtig.txt": 100,
                "/my-files/Backup/temp.tmp": 50,
            },
        )
        matcher = IgnoreMatcher(["*.tmp"])
        result = asyncio.run(scan_remote_directory(adapter, "/my-files/Backup", matcher=matcher))

        assert len(result.files) == 1
        assert result.files[0].key == "wichtig.txt"
        assert len(result.skips) == 1
        assert result.skips[0].action is PlanAction.SKIP_EXCLUDED


class TestBidirectionalPlanner:
    """Prueft die 3-Wege-Entscheidungen im Planer."""

    def test_remote_only_file_is_download_new(self, bidi_pair: SyncPair, source_dir: Path) -> None:
        local_scan = scan_directory(source_dir)
        remote_scan = RemoteScanResult(
            files=(
                RemoteScannedFile(
                    relative_path=Path("cloud_datei.pdf"),  # type: ignore[arg-type]
                    remote_path="/my-files/Backup/cloud_datei.pdf",
                    size_bytes=500,
                    modification_time="2026-08-15T12:00:00Z",
                ),
            )
        )

        plan = build_plan(bidi_pair, local_scan, {}, remote_scan=remote_scan)

        assert len(plan.downloads) == 1
        assert plan.downloads[0].action is PlanAction.DOWNLOAD_NEW
        assert plan.downloads[0].posix_path == "cloud_datei.pdf"
        assert plan.total_download_bytes == 500

    def test_remote_changed_file_is_download_changed(
        self, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        # Lokale Datei existiert und ist unveraendert gegenueber DB
        local_file = source_dir / "gemeinsam.txt"
        local_file.write_text("lokal", encoding="utf-8")
        local_stat = local_file.stat()

        local_scan = scan_directory(source_dir)
        remote_scan = RemoteScanResult(
            files=(
                RemoteScannedFile(
                    relative_path=Path("gemeinsam.txt"),  # type: ignore[arg-type]
                    remote_path="/my-files/Backup/gemeinsam.txt",
                    size_bytes=1000,  # Remote ist gewachsen!
                    modification_time="2026-08-15T14:00:00Z",
                ),
            )
        )
        states = {
            "gemeinsam.txt": FileState(
                relative_path="gemeinsam.txt",
                size_bytes=local_stat.st_size,
                mtime_ns=local_stat.st_mtime_ns,
                sha256=None,
                remote_path="/my-files/Backup/gemeinsam.txt",
                remote_mtime="2026-08-15T10:00:00Z",
                uploaded_at=None,  # type: ignore[arg-type]
            )
        }

        plan = build_plan(bidi_pair, local_scan, states, remote_scan=remote_scan)

        assert len(plan.downloads) == 1
        assert plan.downloads[0].action is PlanAction.DOWNLOAD_CHANGED

    def test_both_changed_is_conflict(self, bidi_pair: SyncPair, source_dir: Path) -> None:
        local_file = source_dir / "konflikt.txt"
        local_file.write_text("neuer lokaler text", encoding="utf-8")

        local_scan = scan_directory(source_dir)
        remote_scan = RemoteScanResult(
            files=(
                RemoteScannedFile(
                    relative_path=Path("konflikt.txt"),  # type: ignore[arg-type]
                    remote_path="/my-files/Backup/konflikt.txt",
                    size_bytes=999,
                    modification_time="2026-08-15T14:00:00Z",
                ),
            )
        )
        states = {
            "konflikt.txt": FileState(
                relative_path="konflikt.txt",
                size_bytes=10,  # Urspruengliche Groesse
                mtime_ns=1_000_000,  # Urspruengliche Zeit
                sha256="oldhash",
                remote_path="/my-files/Backup/konflikt.txt",
                remote_mtime="2026-08-15T10:00:00Z",
                uploaded_at=None,  # type: ignore[arg-type]
            )
        }

        plan = build_plan(bidi_pair, local_scan, states, remote_scan=remote_scan)

        assert len(plan.items) == 1
        assert plan.items[0].action is PlanAction.CONFLICT_LOCAL_RENAMED


class TestBidirectionalExecution:
    """Prueft die tatsaechliche Ausfuehrung von 2-Wege-Syncs."""

    def test_downloads_cloud_files(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        repository.save_pair(bidi_pair)
        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup"},
            existing_files={"/my-files/Backup/vom_server.txt": 42},
        )
        engine = SyncEngine(repository, adapter)

        record, _ = asyncio.run(engine.sync(bidi_pair))

        assert record.status is RunStatus.SUCCESS
        assert record.downloaded_files == 1
        assert (source_dir / "vom_server.txt").exists()
        assert len(adapter.downloads) == 1

        # Dateizustand muss in DB gespeichert sein
        states = repository.load_file_states(bidi_pair.uid)
        assert "vom_server.txt" in states

    def test_conflict_renames_local_file_and_downloads(
        self, repository: Repository, bidi_pair: SyncPair, source_dir: Path
    ) -> None:
        repository.save_pair(bidi_pair)
        local_file = source_dir / "dok.txt"
        local_file.write_text("lokale aenderung", encoding="utf-8")

        adapter = FakeAdapter(
            existing_folders={"/my-files/Backup"},
            existing_files={"/my-files/Backup/dok.txt": 500},
        )
        repository.record_upload(
            bidi_pair.uid,
            relative_path="dok.txt",
            size_bytes=10,
            mtime_ns=1,
            remote_path="/my-files/Backup/dok.txt",
            remote_mtime="2026-08-15T08:00:00Z",
        )

        engine = SyncEngine(repository, adapter)
        record, _ = asyncio.run(engine.sync(bidi_pair))

        assert record.status is RunStatus.SUCCESS
        assert record.downloaded_files == 1

        # Lokale Datei muss umbenannt worden sein in .conflict-...
        conflict_files = list(source_dir.glob("dok.conflict-*.txt"))
        assert len(conflict_files) == 1
        assert conflict_files[0].read_text(encoding="utf-8") == "lokale aenderung"
        assert local_file.exists()
