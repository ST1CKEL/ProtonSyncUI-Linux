"""Bruecke zwischen asyncio-Sync-Laeufen und dem GTK-Hauptthread.

GTK verlangt, dass jede Aenderung an der Oberflaeche im Hauptthread
geschieht, waehrend die Sync-Laeufe blockierende Prozessarbeit leisten. Die
Loesung: ein eigener Arbeitsthread mit eigener asyncio-Ereignisschleife.
Ergebnisse und Fortschritt wandern ueber :func:`GLib.idle_add` zurueck.

Jeder Auftrag oeffnet seine *eigene* Datenbankverbindung. So teilen sich
Oberflaeche und Lauf keine SQLite-Verbindung ueber Threadgrenzen hinweg.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from gi.repository import GLib

from ..cli_adapter.adapter import ProtonDriveAdapter
from ..logging_setup import get_logger
from ..models.plan import UploadPlan
from ..models.run import RunRecord
from ..storage.database import connect
from ..storage.locking import PairLockedError
from ..storage.repository import Repository
from ..sync.engine import SyncEngine, SyncProgress

log = get_logger("ui.runner")

ProgressHandler = Callable[[SyncProgress], None]
DoneHandler = Callable[[RunRecord, UploadPlan], None]
ErrorHandler = Callable[[BaseException], None]


def idle_call(func: Callable[..., Any], *args: Any) -> None:
    """Fuehrt ``func`` im GTK-Hauptthread aus."""

    def wrapper() -> bool:
        try:
            func(*args)
        except Exception:
            log.exception("Fehler in einer Oberflaechen-Rueckmeldung")
        return GLib.SOURCE_REMOVE

    GLib.idle_add(wrapper)


@dataclass(slots=True)
class JobHandle:
    """Ein laufender Auftrag, der abgebrochen werden kann."""

    pair_uid: str
    dry_run: bool
    future: Future[tuple[RunRecord, UploadPlan]]
    _task: asyncio.Task[Any] | None = None
    _loop: asyncio.AbstractEventLoop | None = None

    def cancel(self) -> None:
        """Bricht den Lauf ab. Bereits uebertragene Dateien bleiben uebertragen."""
        if self._task is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        else:
            self.future.cancel()

    @property
    def running(self) -> bool:
        """Wahr, solange der Auftrag laeuft."""
        return not self.future.done()


class AsyncRunner:
    """Verwaltet den Arbeitsthread und die laufenden Auftraege."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, JobHandle] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Startet den Arbeitsthread."""
        if self._thread is not None:
            return
        ready = threading.Event()

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            ready.set()
            try:
                loop.run_forever()
            finally:
                # Abgebrochene Aufgaben zu Ende laufen lassen, bevor die
                # Schleife schliesst. Sonst meldet asyncio beim Beenden
                # "Task was destroyed but it is pending".
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                if pending:
                    for task in pending:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

        self._thread = threading.Thread(target=run, name="proton-sync-worker", daemon=True)
        self._thread.start()
        ready.wait(timeout=5.0)
        log.debug("Arbeitsthread gestartet.")

    def stop(self, *, timeout: float = 5.0) -> None:
        """Beendet laufende Auftraege und den Arbeitsthread.

        Es werden *alle* Aufgaben der Ereignisschleife abgebrochen, nicht nur
        die Sync-Laeufe: auch kurze Hintergrundabfragen wie die CLI-Pruefung
        sollen sauber enden, statt beim Schliessen der Schleife als
        unerledigt liegenzubleiben.
        """
        with self._lock:
            handles = list(self._jobs.values())
        for handle in handles:
            handle.cancel()

        loop = self._loop
        if loop is not None:
            drained = threading.Event()

            def cancel_everything() -> None:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                drained.set()

            loop.call_soon_threadsafe(cancel_everything)
            drained.wait(timeout=min(timeout, 2.0))
            # Den abgebrochenen Aufgaben einen Durchlauf zum Aufraeumen geben.
            loop.call_soon_threadsafe(loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None
        log.debug("Arbeitsthread beendet.")

    # ------------------------------------------------------------------
    # Auftraege
    # ------------------------------------------------------------------

    def is_running(self, pair_uid: str) -> bool:
        """Wahr, wenn fuer dieses Paar bereits ein Auftrag laeuft."""
        with self._lock:
            handle = self._jobs.get(pair_uid)
        return handle is not None and handle.running

    def cancel(self, pair_uid: str) -> bool:
        """Bricht den laufenden Auftrag eines Paars ab.

        Gibt ``False`` zurueck, wenn gerade nichts laeuft.
        """
        with self._lock:
            handle = self._jobs.get(pair_uid)
        if handle is None or not handle.running:
            return False
        handle.cancel()
        return True

    def submit_sync(
        self,
        pair_uid: str,
        *,
        dry_run: bool,
        on_progress: ProgressHandler,
        on_done: DoneHandler,
        on_error: ErrorHandler,
    ) -> JobHandle | None:
        """Startet einen Lauf im Hintergrund.

        Gibt ``None`` zurueck, wenn fuer das Paar bereits ein Auftrag laeuft.
        """
        if self._loop is None:
            self.start()
        loop = self._loop
        if loop is None:  # pragma: no cover -- start() setzt die Schleife
            raise RuntimeError("Der Arbeitsthread konnte nicht gestartet werden.")

        with self._lock:
            existing = self._jobs.get(pair_uid)
            if existing is not None and existing.running:
                return None

        future: Future[tuple[RunRecord, UploadPlan]] = Future()
        handle = JobHandle(pair_uid=pair_uid, dry_run=dry_run, future=future, _loop=loop)

        async def job() -> tuple[RunRecord, UploadPlan]:
            handle._task = asyncio.current_task()
            repository = Repository(connect())
            try:
                pair = repository.get_pair(pair_uid)
                if pair is None:
                    raise LookupError(f"Das Sync-Paar {pair_uid} existiert nicht mehr.")

                def forward(progress: SyncProgress) -> None:
                    idle_call(on_progress, progress)

                engine = SyncEngine(
                    repository,
                    ProtonDriveAdapter(),
                    progress=forward,
                    source="gui",
                )
                if dry_run:
                    return await engine.dry_run(pair)
                return await engine.sync(pair)
            finally:
                repository.close()

        def schedule() -> None:
            task = loop.create_task(job())
            handle._task = task

            def finished(completed: asyncio.Task[tuple[RunRecord, UploadPlan]]) -> None:
                with self._lock:
                    self._jobs.pop(pair_uid, None)
                if completed.cancelled():
                    future.cancel()
                    idle_call(on_error, asyncio.CancelledError())
                    return
                error = completed.exception()
                if error is not None:
                    future.set_exception(error)
                    if isinstance(error, PairLockedError):
                        log.info("Auftrag abgelehnt: %s", error, extra={"pair_uid": pair_uid})
                    else:
                        log.error("Auftrag fehlgeschlagen: %s", error, extra={"pair_uid": pair_uid})
                    idle_call(on_error, error)
                    return
                result = completed.result()
                future.set_result(result)
                idle_call(on_done, result[0], result[1])

            task.add_done_callback(finished)

        with self._lock:
            self._jobs[pair_uid] = handle
        loop.call_soon_threadsafe(schedule)
        return handle

    def submit_coroutine(
        self,
        factory: Callable[[], Any],
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        """Fuehrt eine beliebige Koroutine im Arbeitsthread aus.

        Wird fuer kurze Abfragen wie die CLI-Pruefung benutzt.
        """
        if self._loop is None:
            self.start()
        loop = self._loop
        if loop is None:  # pragma: no cover
            raise RuntimeError("Der Arbeitsthread konnte nicht gestartet werden.")

        def schedule() -> None:
            task = loop.create_task(factory())

            def finished(completed: asyncio.Task[Any]) -> None:
                if completed.cancelled():
                    return
                error = completed.exception()
                if error is not None:
                    if on_error is not None:
                        idle_call(on_error, error)
                    else:
                        log.error("Hintergrundaufgabe fehlgeschlagen: %s", error)
                    return
                if on_done is not None:
                    idle_call(on_done, completed.result())

            task.add_done_callback(finished)

        loop.call_soon_threadsafe(schedule)


__all__ = [
    "AsyncRunner",
    "DoneHandler",
    "ErrorHandler",
    "JobHandle",
    "ProgressHandler",
    "idle_call",
]
