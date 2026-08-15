"""Ausfuehrung eines Sync-Laufs (2-Wege-Sync & Einweg).

Ablauf eines Durchgangs:

1. Sperre erwerben (verhindert parallele Laeufe desselben Paars)
2. CLI pruefen (vorhanden? angemeldet?)
3. Lokal und remote scannen und Plan erstellen
4. Bei Dry-Run: Plan zurueckgeben, nichts uebertragen
5. Sonst: benoetigte Zielordner vorbereiten, Downloads und Uploads ausfuehren
6. Zustand fortschreiben und Lauf protokollieren
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from ..cli_adapter import capabilities
from ..cli_adapter.adapter import ProtonDriveAdapter
from ..cli_adapter.commands import remote_parent_and_name
from ..cli_adapter.errors import ProtonCliError
from ..logging_setup import get_logger
from ..models.plan import PlanAction, PlanItem, UploadPlan
from ..models.run import FileError, RunRecord, RunStatus
from ..models.sync_pair import KNOWN_REMOTE_SECTIONS, SyncMode, SyncPair
from ..storage.locking import run_lock
from ..storage.repository import Repository
from .ignore import IgnoreMatcher
from .planner import build_plan
from .remote_scanner import scan_remote_directory
from .retry import RetryPolicy, retry_async
from .scanner import compute_sha256, scan_directory

log = get_logger("sync.engine")

#: Nach so vielen Laeufen wird die Historie eines Paars beschnitten.
RUN_HISTORY_LIMIT: Final = 200


class SyncPhase(StrEnum):
    """Abschnitte eines Laufs -- fuer die Fortschrittsanzeige."""

    PREPARING = "preparing"
    SCANNING = "scanning"
    SCANNING_LOCAL = "scanning_local"
    SCANNING_REMOTE = "scanning_remote"
    PLANNING = "planning"
    FOLDERS = "folders"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    FINISHING = "finishing"
    DONE = "done"


_PHASE_LABELS: dict[SyncPhase, str] = {
    SyncPhase.PREPARING: "Vorbereitung",
    SyncPhase.SCANNING: "Ordner wird gelesen",
    SyncPhase.SCANNING_LOCAL: "Lokaler Ordner wird gelesen",
    SyncPhase.SCANNING_REMOTE: "Proton Drive wird gelesen",
    SyncPhase.PLANNING: "Plan wird erstellt",
    SyncPhase.FOLDERS: "Verzeichnisse werden vorbereitet",
    SyncPhase.DOWNLOADING: "Dateien werden heruntergeladen",
    SyncPhase.UPLOADING: "Dateien werden hochgeladen",
    SyncPhase.FINISHING: "Abschluss",
    SyncPhase.DONE: "Fertig",
}


def phase_label(phase: SyncPhase) -> str:
    """Deutsche Bezeichnung einer Phase."""
    return _PHASE_LABELS.get(phase, phase.value)


@dataclass(frozen=True, slots=True)
class SyncProgress:
    """Momentaufnahme des Fortschritts."""

    pair_uid: str
    phase: SyncPhase
    current: int = 0
    total: int = 0
    relative_path: str = ""
    uploaded_bytes: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    message: str = ""

    @property
    def fraction(self) -> float:
        """Fortschritt zwischen 0.0 und 1.0."""
        if self.total <= 0:
            return 0.0
        return min(1.0, self.current / self.total)


ProgressCallback = Callable[[SyncProgress], None]


class SyncEngine:
    """Fuehrt Dry-Runs und echte Laeufe aus."""

    def __init__(
        self,
        repository: Repository,
        adapter: ProtonDriveAdapter | None = None,
        *,
        retry_policy: RetryPolicy | None = None,
        progress: ProgressCallback | None = None,
        source: str = "cli",
    ) -> None:
        self._repository = repository
        self._adapter = adapter if adapter is not None else ProtonDriveAdapter()
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._progress = progress
        self._source = source
        self._known_folders: set[str] = set()

    # ------------------------------------------------------------------
    # Oeffentliche Schnittstelle
    # ------------------------------------------------------------------

    async def dry_run(self, pair: SyncPair) -> tuple[RunRecord, UploadPlan]:
        """Ermittelt den Plan, ohne etwas zu uebertragen."""
        return await self._execute(pair, dry_run=True)

    async def sync(self, pair: SyncPair) -> tuple[RunRecord, UploadPlan]:
        """Fuehrt einen echten Synchronisationslauf aus."""
        return await self._execute(pair, dry_run=False)

    # ------------------------------------------------------------------
    # Ablauf
    # ------------------------------------------------------------------

    async def _execute(self, pair: SyncPair, *, dry_run: bool) -> tuple[RunRecord, UploadPlan]:
        self._known_folders.clear()
        empty_plan = UploadPlan.from_items(pair.uid, [])

        with run_lock(self._repository.connection, pair.uid, source=self._source):
            run_id = self._repository.start_run(pair.uid, dry_run=dry_run)
            record = RunRecord(pair_uid=pair.uid, run_id=run_id, dry_run=dry_run)
            record.status = RunStatus.RUNNING

            self._emit(SyncProgress(pair.uid, SyncPhase.PREPARING, message="CLI wird geprueft"))

            problem = await self._preflight()
            if problem:
                record.fail(problem)
                self._repository.finish_run(record)
                log.error(
                    "Lauf abgebrochen: %s",
                    problem,
                    extra={"pair_uid": pair.uid, "run_id": run_id},
                )
                return record, empty_plan

            if not pair.local_path.is_dir():
                message = f"Der Quellordner '{pair.local_path}' existiert nicht (mehr)."
                record.fail(message)
                self._repository.finish_run(record)
                log.error(message, extra={"pair_uid": pair.uid, "run_id": run_id})
                return record, empty_plan

            try:
                plan = await self._build_plan(pair)
            except Exception as error:
                message = f"Fehler bei der Planerstellung: {error}"
                record.fail(message)
                self._repository.finish_run(record)
                log.exception(message, extra={"pair_uid": pair.uid, "run_id": run_id})
                return record, empty_plan

            total_planned = len(plan.uploads) + len(plan.downloads)
            record.planned_files = total_planned
            record.skipped_files = len(plan.skipped)
            record.local_deletions = len(plan.local_deletions)

            self._log_local_deletions(pair, plan)

            for warning in plan.scan_errors:
                log.warning(
                    "Scan-Hinweis: %s",
                    warning,
                    extra={"pair_uid": pair.uid, "run_id": run_id},
                )

            if dry_run:
                record.message = f"Dry-Run: {plan.describe()}"
                record.finish()
                self._repository.finish_run(record)
                self._emit(
                    SyncProgress(
                        pair.uid,
                        SyncPhase.DONE,
                        total=record.planned_files,
                        current=record.planned_files,
                        message=plan.describe(),
                    )
                )
                log.info(
                    "Dry-Run abgeschlossen: %s",
                    plan.describe(),
                    extra={"pair_uid": pair.uid, "run_id": run_id},
                )
                return record, plan

            try:
                await self._transfer(pair, plan, record)
            except asyncio.CancelledError:
                record.status = RunStatus.CANCELLED
                record.message = "Der Lauf wurde abgebrochen."
                record.finish()
                self._repository.finish_run(record)
                log.warning("Lauf abgebrochen.", extra={"pair_uid": pair.uid, "run_id": run_id})
                raise

            self._apply_local_deletions(pair, plan)
            self._refresh_unchanged(pair, plan)

            record.finish(message=plan.describe())
            self._repository.finish_run(record)
            self._repository.prune_runs(pair.uid, keep=RUN_HISTORY_LIMIT)

            self._emit(
                SyncProgress(
                    pair.uid,
                    SyncPhase.DONE,
                    current=record.transferred_files,
                    total=record.planned_files,
                    uploaded_bytes=record.uploaded_bytes,
                    downloaded_bytes=record.downloaded_bytes,
                    total_bytes=plan.total_upload_bytes + plan.total_download_bytes,
                    message=record.summary_line(),
                )
            )
            log.info(
                "Lauf beendet: %s",
                record.summary_line(),
                extra={"pair_uid": pair.uid, "run_id": run_id},
            )
            return record, plan

    async def _preflight(self) -> str:
        """Prueft die CLI. Gibt eine leere Zeichenkette zurueck, wenn alles passt."""
        caps = await capabilities.probe(self._adapter)
        if not caps.available:
            return caps.problem
        if not caps.authenticated:
            return caps.problem or "Die Proton-Drive-CLI ist nicht angemeldet."
        return ""

    async def _build_plan(self, pair: SyncPair) -> UploadPlan:
        """Scannt lokalen und entfernten Ordner und erstellt den Plan."""
        matcher = IgnoreMatcher(pair.exclude_patterns)
        if matcher.invalid_patterns:
            log.warning(
                "Ungueltige Ausschlussregeln werden ignoriert: %s",
                ", ".join(matcher.invalid_patterns),
                extra={"pair_uid": pair.uid},
            )

        self._emit(
            SyncProgress(
                pair.uid, SyncPhase.SCANNING_LOCAL, message="Lokale Dateien werden gesucht"
            )
        )
        local_scan = await asyncio.to_thread(
            scan_directory,
            pair.local_path,
            matcher=matcher,
            max_file_size_bytes=pair.max_file_size_bytes,
        )

        remote_scan = None
        if pair.sync_mode is not SyncMode.UPLOAD_ONLY:
            self._emit(
                SyncProgress(
                    pair.uid,
                    SyncPhase.SCANNING_REMOTE,
                    message="Proton-Drive-Dateien werden gesucht",
                )
            )

            def _on_remote_progress(folders: int, count: int) -> None:
                self._emit(
                    SyncProgress(
                        pair.uid,
                        SyncPhase.SCANNING_REMOTE,
                        message=f"Cloud-Dateien werden gesucht ({folders} Ordner, {count} Dateien)",
                    )
                )

            remote_scan = await scan_remote_directory(
                self._adapter,
                pair.remote_path,
                matcher=matcher,
                max_file_size_bytes=pair.max_file_size_bytes,
                concurrency=8,
                progress=_on_remote_progress,
            )

        self._emit(
            SyncProgress(
                pair.uid,
                SyncPhase.PLANNING,
                total=len(local_scan.files) + (len(remote_scan.files) if remote_scan else 0),
                message="Plan wird berechnet",
            )
        )

        states = self._repository.load_file_states(pair.uid)
        return await asyncio.to_thread(
            build_plan,
            pair,
            local_scan,
            states,
            remote_scan=remote_scan,
            hasher=compute_sha256,
        )

    async def _transfer(self, pair: SyncPair, plan: UploadPlan, record: RunRecord) -> None:
        """Fuehrt geplante Downloads und Uploads aus."""
        downloads = plan.downloads
        uploads = plan.uploads
        total_items = len(downloads) + len(uploads)
        if total_items == 0:
            log.info("Nichts zu uebertragen.", extra={"pair_uid": pair.uid})
            return

        total_bytes = plan.total_download_bytes + plan.total_upload_bytes
        processed_items = 0

        # --- Phase 1: Downloads (Cloud -> Lokal) ---
        if downloads:
            for item in downloads:
                relative = item.relative_path
                local_file = pair.local_path / relative
                remote_path = item.remote_path or pair.remote_path_for(relative)

                self._emit(
                    SyncProgress(
                        pair.uid,
                        SyncPhase.DOWNLOADING,
                        current=processed_items,
                        total=total_items,
                        relative_path=relative.as_posix(),
                        uploaded_bytes=record.uploaded_bytes,
                        downloaded_bytes=record.downloaded_bytes,
                        total_bytes=total_bytes,
                        message=f"Download: {relative.as_posix()}",
                    )
                )

                if item.action == PlanAction.CONFLICT_LOCAL_RENAMED and local_file.is_file():
                    # Lokale Datei sicher umbenennen
                    stamp = int(time.time())
                    conflict_name = f"{local_file.stem}.conflict-{stamp}{local_file.suffix}"
                    conflict_file = local_file.with_name(conflict_name)
                    try:
                        local_file.rename(conflict_file)
                        log.warning(
                            "Konflikt: Lokale Datei umbenannt in %s",
                            conflict_file.name,
                            extra={"pair_uid": pair.uid},
                        )
                    except OSError as err:
                        log.error("Konnte Konfliktdatei nicht umbenennen: %s", err)

                error = await self._download_one(
                    pair, item=item, local_file=local_file, remote_path=remote_path
                )

                if error is not None:
                    record.failed_files += 1
                    record.errors.append(error)
                    log.error(
                        "Download fehlgeschlagen: %s -- %s",
                        relative.as_posix(),
                        error.message,
                        extra={
                            "pair_uid": pair.uid,
                            "run_id": record.run_id,
                            "relative_path": relative.as_posix(),
                            "attempt": error.attempts,
                        },
                    )
                else:
                    record.downloaded_files += 1
                    record.downloaded_bytes += item.size_bytes
                    try:
                        stat = local_file.stat()
                        mtime_ns = stat.st_mtime_ns
                    except OSError:
                        mtime_ns = item.mtime_ns

                    self._repository.record_download(
                        pair.uid,
                        relative_path=relative.as_posix(),
                        size_bytes=item.size_bytes,
                        mtime_ns=mtime_ns,
                        remote_path=remote_path,
                        sha256=item.sha256,
                        remote_mtime=item.remote_mtime,
                    )
                    log.info(
                        "Heruntergeladen: %s",
                        relative.as_posix(),
                        extra={
                            "pair_uid": pair.uid,
                            "run_id": record.run_id,
                            "relative_path": relative.as_posix(),
                            "action": item.action.value,
                        },
                    )

                processed_items += 1

        # --- Phase 2: Uploads (Lokal -> Cloud) ---
        if uploads:
            self._emit(
                SyncProgress(
                    pair.uid,
                    SyncPhase.FOLDERS,
                    total=total_items,
                    message="Zielordner werden geprueft",
                )
            )

            for item in uploads:
                relative = item.relative_path
                local_file = pair.local_path / relative
                remote_parent = pair.remote_parent_for(relative)

                self._emit(
                    SyncProgress(
                        pair.uid,
                        SyncPhase.UPLOADING,
                        current=processed_items,
                        total=total_items,
                        relative_path=relative.as_posix(),
                        uploaded_bytes=record.uploaded_bytes,
                        downloaded_bytes=record.downloaded_bytes,
                        total_bytes=total_bytes,
                        message=f"Upload: {relative.as_posix()}",
                    )
                )

                error = await self._upload_one(
                    pair, item=item, local_file=local_file, remote_parent=remote_parent
                )

                if error is not None:
                    record.failed_files += 1
                    record.errors.append(error)
                    log.error(
                        "Upload fehlgeschlagen: %s -- %s",
                        relative.as_posix(),
                        error.message,
                        extra={
                            "pair_uid": pair.uid,
                            "run_id": record.run_id,
                            "relative_path": relative.as_posix(),
                            "attempt": error.attempts,
                        },
                    )
                else:
                    record.uploaded_files += 1
                    record.uploaded_bytes += item.size_bytes
                    self._repository.record_upload(
                        pair.uid,
                        relative_path=relative.as_posix(),
                        size_bytes=item.size_bytes,
                        mtime_ns=item.mtime_ns,
                        remote_path=pair.remote_path_for(relative),
                        sha256=item.sha256,
                    )
                    log.info(
                        "Hochgeladen: %s",
                        relative.as_posix(),
                        extra={
                            "pair_uid": pair.uid,
                            "run_id": record.run_id,
                            "relative_path": relative.as_posix(),
                            "action": item.action.value,
                        },
                    )

                processed_items += 1

        self._emit(
            SyncProgress(
                pair.uid,
                SyncPhase.FINISHING,
                current=total_items,
                total=total_items,
                uploaded_bytes=record.uploaded_bytes,
                downloaded_bytes=record.downloaded_bytes,
                total_bytes=total_bytes,
            )
        )

    async def _download_one(
        self,
        pair: SyncPair,
        item: PlanItem,
        *,
        local_file: Path,
        remote_path: str,
    ) -> FileError | None:
        """Laedt eine Datei von Proton Drive in das lokale Dateisystem herunter."""
        attempts = 1

        def note_retry(attempt: int, delay: float, error: BaseException) -> None:
            nonlocal attempts
            attempts = attempt
            log.warning(
                "Neuer Download-Versuch %d/%d in %.1fs fuer %s: %s",
                attempt,
                self._retry_policy.max_attempts,
                delay,
                item.posix_path,
                error,
                extra={
                    "pair_uid": pair.uid,
                    "relative_path": item.posix_path,
                    "attempt": attempt,
                },
            )

        try:
            local_parent = local_file.parent
            local_parent.mkdir(parents=True, exist_ok=True)

            await retry_async(
                functools.partial(self._adapter.download_file, remote_path, local_parent),
                policy=self._retry_policy,
                on_retry=note_retry,
            )
        except asyncio.CancelledError:
            raise
        except ProtonCliError as error:
            return FileError(
                relative_path=item.posix_path,
                message=str(error),
                attempts=attempts,
                permanent=not error.transient,
            )
        except OSError as error:
            return FileError(
                relative_path=item.posix_path,
                message=f"Lokaler Schreibfehler: {error.strerror or error}",
                attempts=attempts,
                permanent=True,
            )
        return None

    async def _upload_one(
        self,
        pair: SyncPair,
        item: PlanItem,
        *,
        local_file: Path,
        remote_parent: str,
    ) -> FileError | None:
        """Uebertraegt eine lokale Datei zu Proton Drive."""
        attempts = 1

        def note_retry(attempt: int, delay: float, error: BaseException) -> None:
            nonlocal attempts
            attempts = attempt
            log.warning(
                "Neuer Upload-Versuch %d/%d in %.1fs fuer %s: %s",
                attempt,
                self._retry_policy.max_attempts,
                delay,
                item.posix_path,
                error,
                extra={
                    "pair_uid": pair.uid,
                    "relative_path": item.posix_path,
                    "attempt": attempt,
                },
            )

        try:
            if not local_file.is_file():
                return FileError(
                    relative_path=item.posix_path,
                    message="Die Datei ist seit dem Scan verschwunden.",
                    attempts=1,
                    permanent=True,
                )

            await retry_async(
                functools.partial(self._ensure_remote_folder, remote_parent),
                policy=self._retry_policy,
                on_retry=note_retry,
            )
            await retry_async(
                functools.partial(self._adapter.upload_file, local_file, remote_parent),
                policy=self._retry_policy,
                on_retry=note_retry,
            )
        except asyncio.CancelledError:
            raise
        except ProtonCliError as error:
            return FileError(
                relative_path=item.posix_path,
                message=str(error),
                attempts=attempts,
                permanent=not error.transient,
            )
        except OSError as error:
            return FileError(
                relative_path=item.posix_path,
                message=f"Lokaler Dateifehler: {error.strerror or error}",
                attempts=attempts,
                permanent=True,
            )
        return None

    async def _ensure_remote_folder(self, remote_path: str) -> None:
        """Legt einen Zielordner samt fehlender Zwischenebenen an."""
        if remote_path in self._known_folders or remote_path in KNOWN_REMOTE_SECTIONS:
            self._known_folders.add(remote_path)
            return

        parent, name = remote_parent_and_name(remote_path)
        if not name or parent in ("", "/"):
            self._known_folders.add(remote_path)
            return

        await self._ensure_remote_folder(parent)
        created = await self._adapter.create_folder(parent, name)
        self._known_folders.add(remote_path)
        if created:
            log.info("Zielordner angelegt: %s", remote_path)

    # ------------------------------------------------------------------
    # Nachbereitung
    # ------------------------------------------------------------------

    def _log_local_deletions(self, pair: SyncPair, plan: UploadPlan) -> None:
        """Protokolliert lokal geloeschte Dateien -- ohne jede entfernte Wirkung."""
        deletions = plan.local_deletions
        if not deletions:
            return
        log.warning(
            "%d Datei(en) lokal geloescht. Die Kopien bei Proton Drive bleiben bestehen; "
            "ProtonSyncUI loescht niemals entfernte Dateien.",
            len(deletions),
            extra={"pair_uid": pair.uid},
        )
        for item in deletions:
            log.info(
                "Lokal geloescht (ohne entfernte Wirkung): %s",
                item.posix_path,
                extra={
                    "pair_uid": pair.uid,
                    "relative_path": item.posix_path,
                    "action": PlanAction.LOCAL_DELETED.value,
                },
            )

    def _apply_local_deletions(self, pair: SyncPair, plan: UploadPlan) -> None:
        """Entfernt Zustandseintraege verschwundener Dateien."""
        deletions = [item.posix_path for item in plan.local_deletions]
        if deletions:
            self._repository.forget_file_states(pair.uid, deletions)

    def _refresh_unchanged(self, pair: SyncPair, plan: UploadPlan) -> None:
        """Schreibt neue mtimes fuer inhaltsgleiche Dateien fort."""
        for item in plan.items:
            if item.needs_mtime_refresh:
                self._repository.touch_file_state(
                    pair.uid, relative_path=item.posix_path, mtime_ns=item.mtime_ns
                )

    def _emit(self, progress: SyncProgress) -> None:
        """Meldet Fortschritt."""
        if self._progress is None:
            return
        try:
            self._progress(progress)
        except Exception:
            log.exception("Fortschrittsmeldung fehlgeschlagen.")


__all__ = [
    "RUN_HISTORY_LIMIT",
    "ProgressCallback",
    "SyncEngine",
    "SyncPhase",
    "SyncProgress",
    "phase_label",
]
