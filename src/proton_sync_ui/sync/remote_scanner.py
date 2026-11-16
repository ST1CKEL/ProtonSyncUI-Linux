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
from ..cli_adapter.errors import (
    NotAuthenticatedError,
    ProtonCliNotFoundError,
    RemotePathNotFoundError,
)
from ..i18n import tr
from ..logging_setup import get_logger
from ..models.plan import PlanAction
from ..models.sync_pair import name_is_supported
from .ignore import IgnoreMatcher
from .retry import RetryPolicy, retry_async
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
    #: Entfernte Pfade aller Ordner, die in einer Auflistung gesehen wurden.
    folders: tuple[str, ...] = field(default=())
    #: Relative Ordnerpfade, deren Inhalt nicht gelesen werden konnte ("" =
    #: Wurzel). Dateien darunter gelten als *unbekannt*, nicht als fehlend.
    failed_prefixes: tuple[str, ...] = field(default=())

    @property
    def root_failed(self) -> bool:
        """Wahr, wenn schon der Wurzelordner nicht gelesen werden konnte."""
        return "" in self.failed_prefixes

    def is_unreadable(self, key: str) -> bool:
        """Wahr, wenn ``key`` unterhalb eines nicht lesbaren Ordners liegt."""
        for prefix in self.failed_prefixes:
            if prefix in ("", key) or key.startswith(prefix + "/"):
                return True
        return False

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
    retry_policy: RetryPolicy | None = None,
) -> RemoteScanResult:
    """Liest die Verzeichnisstruktur unterhalb von ``remote_root`` parallel aus.

    Voruebergehende Fehler einzelner Ordner werden wiederholt. Bleibt ein
    Ordner unlesbar, wird er in ``failed_prefixes`` vermerkt, damit der Planer
    seine Dateien nicht faelschlich fuer "in der Cloud geloescht" haelt. Ist
    die CLI abgemeldet, bricht der Scan sofort mit der Ausnahme ab.
    """
    rules = matcher if matcher is not None else IgnoreMatcher()
    policy = retry_policy if retry_policy is not None else RetryPolicy()
    folders: list[str] = []
    failed_prefixes: list[str] = []
    fatal: list[BaseException] = []
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

        if fatal:
            return

        prefix_key = "" if prefix == PurePosixPath() else prefix.as_posix()
        try:
            nodes = await retry_async(lambda: adapter.list_dir(current_path), policy=policy)
        except RemotePathNotFoundError:
            log.debug("Entfernter Ordner existiert nicht: %s", current_path)
            nodes = []
        except (NotAuthenticatedError, ProtonCliNotFoundError) as error:
            # Jeder weitere Aufruf wuerde genauso scheitern.
            fatal.append(error)
            return
        except Exception as error:
            label = prefix_key or current_path
            async with lock:
                errors.append(f"{label}: {error}")
                failed_prefixes.append(prefix_key)
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
                            reason=tr("Name enthaelt nicht unterstuetzte Zeichen."),
                        )
                    )
                    continue

                if node.is_folder:
                    folders.append(node.path)
                    if rules.is_dir_ignored(path_text):
                        skips.append(
                            ScanSkip(
                                relative_path=relative,
                                action=PlanAction.SKIP_EXCLUDED,
                                reason=tr("Entfernter Ordner durch Ausschlussregel ausgenommen."),
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
                                tr(
                                    "Proton Docs und Sheets koennen nicht ueber die CLI "
                                    "heruntergeladen werden."
                                )
                            ),
                        )
                    )
                    continue

                if rules.is_ignored(path_text):
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_EXCLUDED,
                            reason=tr("Durch Ausschlussregel ausgenommen."),
                        )
                    )
                    continue

                if max_file_size_bytes is not None and node.size_bytes > max_file_size_bytes:
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_TOO_LARGE,
                            reason=tr("Dateigroesse ueberschreitet Limit."),
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

    if fatal:
        raise fatal[0]

    return RemoteScanResult(
        files=tuple(files),
        skips=tuple(skips),
        errors=tuple(errors),
        folders=tuple(folders),
        failed_prefixes=tuple(failed_prefixes),
    )


__all__ = [
    "RemoteScanProgressCallback",
    "RemoteScanResult",
    "RemoteScannedFile",
    "scan_remote_directory",
]
