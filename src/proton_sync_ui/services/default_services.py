"""Standard-Implementierungen der Service-Schnittstellen."""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from ..models.plan import UploadPlan
from ..models.run import RunRecord
from ..models.sync_pair import SyncPair
from ..storage.repository import Repository
from ..sync.engine import SyncProgress
from ..ui.runner import AsyncRunner, DoneHandler, ErrorHandler, ProgressHandler
from .contracts import ConflictItem

log = get_logger("services.default")


class DefaultPairRepository:
    """Implementierung von SyncPairRepository ueber das bestehende Repository."""

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    def list_pairs(self) -> list[SyncPair]:
        return self._repo.list_pairs()

    def get_pair(self, uid: str) -> SyncPair | None:
        return self._repo.get_pair(uid)

    def save_pair(self, pair: SyncPair) -> None:
        self._repo.save_pair(pair)

    def delete_pair(self, uid: str) -> None:
        self._repo.delete_pair(uid)

    def set_pair_enabled(self, uid: str, *, enabled: bool) -> None:
        self._repo.set_pair_enabled(uid, enabled=enabled)


class DefaultActivityRepository:
    """Implementierung von ActivityRepository fuer Laeufe und Verlaeufe."""

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    def list_recent_runs(self, limit: int = 50) -> list[RunRecord]:
        return self._repo.list_runs(limit=limit)

    def get_last_run(self, pair_uid: str) -> RunRecord | None:
        return self._repo.last_run(pair_uid)

    def list_pair_runs(self, pair_uid: str, limit: int = 50) -> list[RunRecord]:
        return self._repo.list_runs(pair_uid=pair_uid, limit=limit)


class DefaultConflictService:
    """Sucht und verwaltet Konfliktdateien (.conflict-*) in konfigurierten Sync-Paaren."""

    def __init__(self, pair_repo: DefaultPairRepository, repository: Repository) -> None:
        self._pair_repo = pair_repo
        self._repo = repository

    def list_conflicts(self) -> list[ConflictItem]:
        conflicts: list[ConflictItem] = []
        for pair in self._pair_repo.list_pairs():
            if not pair.local_path.is_dir():
                continue
            for conflict_file in pair.local_path.rglob("*.conflict-*"):
                if not conflict_file.is_file():
                    continue
                # Ermittle urspruenglichen Namen
                parent = conflict_file.parent
                name = conflict_file.name
                # Format: name.conflict-12345.ext oder name.conflict-12345
                parts = name.split(".conflict-")
                if len(parts) == 2:
                    stem = parts[0]
                    rest = parts[1]
                    ext = f".{rest.split('.', 1)[1]}" if "." in rest else ""
                    orig_name = f"{stem}{ext}"
                    orig_file = parent / orig_name
                    rel_path = orig_file.relative_to(pair.local_path).as_posix()

                    local_size = conflict_file.stat().st_size
                    local_mtime = conflict_file.stat().st_mtime_ns

                    remote_size = orig_file.stat().st_size if orig_file.exists() else 0
                    remote_mtime = ""

                    conflicts.append(
                        ConflictItem(
                            pair_uid=pair.uid,
                            relative_path=rel_path,
                            local_size=local_size,
                            local_mtime_ns=local_mtime,
                            remote_size=remote_size,
                            remote_mtime=remote_mtime,
                            conflict_file_path=str(conflict_file),
                        )
                    )
        return conflicts

    def resolve_conflict(self, conflict: ConflictItem, resolution: str) -> None:
        """Loest einen Konflikt gemaess der gewaehlten Strategie auf."""
        if not conflict.conflict_file_path:
            return
        conflict_path = Path(conflict.conflict_file_path)
        if not conflict_path.exists():
            return

        pair = self._pair_repo.get_pair(conflict.pair_uid)
        if not pair:
            return

        orig_file = pair.local_path / conflict.relative_path

        if resolution == "keep_local":
            # Lokale Fassung (conflict_path) ersetzt aktuelle Datei (orig_file)
            conflict_path.replace(orig_file)
            log.info("Konflikt geloest: Lokale Fassung beibehalten (%s)", conflict.relative_path)
        elif resolution == "keep_remote":
            # Lokale Sicherung (.conflict) wird geloescht, Cloud-Fassung bleibt
            conflict_path.unlink(missing_ok=True)
            log.info("Konflikt geloest: Cloud-Fassung beibehalten (%s)", conflict.relative_path)
        elif resolution == "keep_both":
            # Lokale Fassung wird dauerhaft sauber umbenannt
            clean_name = f"{orig_file.stem} (Lokale Kopie){orig_file.suffix}"
            clean_path = orig_file.with_name(clean_name)
            conflict_path.replace(clean_path)
            log.info("Konflikt geloest: Beide Dateien beibehalten (%s)", clean_name)


class DefaultSyncService:
    """Koppelt den AsyncRunner mit der UI."""

    def __init__(
        self,
        runner: AsyncRunner,
        on_progress: ProgressHandler | None = None,
        on_done: DoneHandler | None = None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        self._runner = runner
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_error = on_error

    def set_callbacks(
        self,
        *,
        on_progress: ProgressHandler | None = None,
        on_done: DoneHandler | None = None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_error = on_error

    def start_sync(self, pair: SyncPair, *, dry_run: bool = False) -> None:
        def default_progress(_p: SyncProgress) -> None:
            pass

        def default_done(_r: RunRecord, _p: UploadPlan) -> None:
            pass

        def default_error(_e: BaseException) -> None:
            pass

        self._runner.submit_sync(
            pair.uid,
            dry_run=dry_run,
            on_progress=self._on_progress or default_progress,
            on_done=self._on_done or default_done,
            on_error=self._on_error or default_error,
        )

    def cancel_sync(self, pair_uid: str) -> None:
        self._runner.cancel(pair_uid)

    def is_running(self, pair_uid: str) -> bool:
        return self._runner.is_running(pair_uid)


__all__ = [
    "DefaultActivityRepository",
    "DefaultConflictService",
    "DefaultPairRepository",
    "DefaultSyncService",
]
