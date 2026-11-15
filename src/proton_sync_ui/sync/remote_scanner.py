"""Durchlauf entfernter Ordner bei Proton Drive.

Der RemoteScanner liest rekursiv die Verzeichnisstruktur bei Proton Drive aus
und sammelt vorhandene Dateien, Ausschluesse und Fehler parallel ueber Worker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..cli_adapter.adapter import ProtonDriveAdapter
from ..cli_adapter.errors import RemotePathNotFoundError
from ..logging_setup import get_logger
from ..models.plan import PlanAction
from ..models.sync_pair import name_is_supported
from .ignore import IgnoreMatcher
from .scanner import ScanSkip

log = get_logger("sync.remote_scanner")

RemoteScanProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class RemoteScannedFile:
    """Eine gefundene entfernte Datei."""

    relative_path: PurePosixPath
    remote_path: str
    size_bytes: int
    modification_time: str
    uid: str = ""
    media_type: str = ""

    @property
    def key(self) -> str:
        """Relativer Pfad als POSIX-Zeichenkette."""
        return self.relative_path.as_posix()


@dataclass(frozen=True, slots=True)
class RemoteScanResult:
    """Ergebnis des entfernten Durchlaufs."""

    files: tuple[RemoteScannedFile, ...] = ()
    skips: tuple[ScanSkip, ...] = ()
    errors: tuple[str, ...] = field(default=())

    @property
    def total_bytes(self) -> int:
        """Summe der Groessen aller gefundenen Dateien."""
        return sum(item.size_bytes for item in self.files)

    def by_key(self) -> dict[str, RemoteScannedFile]:
        """Gefundene Dateien nach relativem Pfad."""
        return {item.key: item for item in self.files}


async def scan_remote_directory(
    adapter: ProtonDriveAdapter,
    remote_root: str,
    *,
    matcher: IgnoreMatcher | None = None,
    max_file_size_bytes: int | None = None,
    concurrency: int = 8,
    progress: RemoteScanProgressCallback | None = None,
) -> RemoteScanResult:
    """Liest die Verzeichnisstruktur unterhalb von ``remote_root`` parallel aus."""
    rules = matcher if matcher is not None else IgnoreMatcher()
    files: list[RemoteScannedFile] = []
    skips: list[ScanSkip] = []
    errors: list[str] = []

    lock = asyncio.Lock()
    queue: asyncio.Queue[tuple[str, PurePosixPath]] = asyncio.Queue()
    queue.put_nowait((remote_root, PurePosixPath()))
    visited_paths: set[str] = set()
    scanned_folders = 0

    async def process(current_path: str, prefix: PurePosixPath) -> None:
        nonlocal scanned_folders
        async with lock:
            if current_path in visited_paths:
                return
            visited_paths.add(current_path)

        try:
            nodes = await adapter.list_dir(current_path)
        except RemotePathNotFoundError:
            log.debug("Entfernter Ordner existiert nicht: %s", current_path)
            nodes = []
        except Exception as error:
            label = prefix.as_posix() or current_path
            async with lock:
                errors.append(f"{label}: {error}")
            log.warning("Fehler beim Lesen des entfernten Ordners %s: %s", current_path, error)
            nodes = []

        async with lock:
            scanned_folders += 1
            for node in nodes:
                name = node.name
                if not name:
                    continue

                relative = prefix / name
                path_text = relative.as_posix()

                if not name_is_supported(name):
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_UNSUPPORTED_NAME,
                            reason="Name enthaelt nicht unterstuetzte Zeichen.",
                        )
                    )
                    continue

                if node.is_folder:
                    if rules.is_dir_ignored(path_text):
                        skips.append(
                            ScanSkip(
                                relative_path=relative,
                                action=PlanAction.SKIP_EXCLUDED,
                                reason="Entfernter Ordner durch Ausschlussregel ausgenommen.",
                            )
                        )
                        continue
                    queue.put_nowait((node.path, relative))
                    continue

                if node.is_docs_or_sheet:
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_DOCS_SHEETS,
                            reason=(
                                "Proton Docs und Sheets koennen nicht ueber die CLI "
                                "heruntergeladen werden."
                            ),
                        )
                    )
                    continue

                if rules.is_ignored(path_text):
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_EXCLUDED,
                            reason="Durch Ausschlussregel ausgenommen.",
                        )
                    )
                    continue

                if max_file_size_bytes is not None and node.size_bytes > max_file_size_bytes:
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_TOO_LARGE,
                            reason="Dateigroesse ueberschreitet Limit.",
                            size_bytes=node.size_bytes,
                        )
                    )
                    continue

                files.append(
                    RemoteScannedFile(
                        relative_path=relative,
                        remote_path=node.path,
                        size_bytes=node.size_bytes,
                        modification_time=node.modification_time,
                        uid=node.uid,
                        media_type=node.media_type,
                    )
                )

            if progress is not None:
                try:
                    progress(scanned_folders, len(files))
                except Exception:
                    log.exception("Fortschrittsmeldung des Cloud-Scans fehlgeschlagen.")

    async def worker() -> None:
        while True:
            current_path, prefix = await queue.get()
            try:
                await process(current_path, prefix)
            except Exception as error:
                # Unerwartete Fehler duerfen den Worker nicht beenden, sonst
                # wartet queue.join() ewig auf ein task_done().
                async with lock:
                    errors.append(f"{prefix.as_posix() or current_path}: {error}")
                log.exception("Unerwarteter Fehler beim Cloud-Scan von %s", current_path)
            finally:
                queue.task_done()

    num_workers = max(1, min(concurrency, 16))
    workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
    try:
        await queue.join()
    finally:
        # Auch bei Abbruch des Scans: keine verwaisten Worker (und damit keine
        # weiterlaufenden CLI-Prozesse) zuruecklassen.
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    return RemoteScanResult(files=tuple(files), skips=tuple(skips), errors=tuple(errors))


__all__ = [
    "RemoteScanProgressCallback",
    "RemoteScanResult",
    "RemoteScannedFile",
    "scan_remote_directory",
]
