"""Sperre gegen gleichzeitige Laeufe desselben Sync-Paars.

Warum SQLite statt einer Lockdatei: Oberflaeche und systemd-Timer sind
getrennte Prozesse, die ohnehin dieselbe Datenbank benutzen. ``BEGIN
IMMEDIATE`` macht Pruefen und Setzen der Sperre atomar, ohne dass eine zweite
Datei konsistent gehalten werden muesste.

Verwaiste Sperren nach ``kill -9`` oder Systemabsturz werden zuverlaessig
erkannt: Eine Sperre gilt nur dann als lebendig, wenn Boot-Kennung, Prozess-ID
*und* Prozess-Startzeit noch passen. Die Startzeit schliesst aus, dass eine
neu vergebene, gleichlautende Prozess-ID faelschlich als Sperrhalter gilt.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ..i18n import tr
from ..logging_setup import get_logger
from .database import transaction

log = get_logger("storage.locking")

_BOOT_ID_PATH: Final = Path("/proc/sys/kernel/random/boot_id")
_UNKNOWN_BOOT_ID: Final = "unknown-boot-id"


class LockError(RuntimeError):
    """Basisklasse fuer Sperrfehler."""


class PairLockedError(LockError):
    """Fuer dieses Sync-Paar laeuft bereits ein Durchgang."""

    def __init__(self, pair_uid: str, holder: LockInfo) -> None:
        self.pair_uid = pair_uid
        self.holder = holder
        super().__init__(
            tr(
                "Fuer dieses Sync-Paar laeuft bereits ein Durchgang (Prozess {0}, "
                "gestartet {1:%H:%M:%S}, Quelle: {2})."
            ).format(holder.pid, holder.acquired_at, holder.source)
        )


@dataclass(frozen=True, slots=True)
class LockInfo:
    """Beschreibt eine bestehende Sperre."""

    pair_uid: str
    pid: int
    boot_id: str
    pid_start_time: int
    acquired_at: datetime
    source: str


def current_boot_id() -> str:
    """Kennung des laufenden Systemstarts.

    Aendert sich bei jedem Neustart und entwertet damit alle Sperren, die ein
    abgestuerztes System hinterlassen hat.
    """
    try:
        return _BOOT_ID_PATH.read_text(encoding="ascii").strip() or _UNKNOWN_BOOT_ID
    except OSError:
        return _UNKNOWN_BOOT_ID


def process_start_time(pid: int) -> int:
    """Startzeit eines Prozesses in Uhr-Ticks seit Systemstart.

    Liefert ``0``, wenn der Prozess nicht existiert oder ``/proc`` nicht
    lesbar ist. Feld 22 aus ``/proc/<pid>/stat``; da der Prozessname in
    Klammern Leerzeichen enthalten darf, wird hinter der letzten
    schliessenden Klammer getrennt.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    closing = raw.rfind(")")
    if closing == -1:
        return 0
    fields = raw[closing + 2 :].split()
    # Nach dem Namen ist das erste Feld "state"; starttime ist Feld 22 der
    # Gesamtzaehlung, hier also Index 19.
    if len(fields) < 20:
        return 0
    try:
        return int(fields[19])
    except ValueError:
        return 0


def _process_is_alive(pid: int) -> bool:
    """Prueft, ob ein Prozess existiert, ohne ihn zu beeinflussen."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Existiert, gehoert aber einem anderen Benutzer.
        return True
    return True


def _lock_is_stale(info: LockInfo) -> bool:
    """Entscheidet, ob eine eingetragene Sperre verwaist ist."""
    if info.boot_id != current_boot_id():
        return True
    if not _process_is_alive(info.pid):
        return True
    # Prozess-ID wurde nach einem Absturz neu vergeben.
    recorded = info.pid_start_time
    return bool(recorded and process_start_time(info.pid) != recorded)


def _row_to_info(row: sqlite3.Row) -> LockInfo:
    return LockInfo(
        pair_uid=row["pair_uid"],
        pid=row["pid"],
        boot_id=row["boot_id"],
        pid_start_time=row["pid_start_time"],
        acquired_at=datetime.fromisoformat(row["acquired_at"]),
        source=row["source"],
    )


def read_lock(connection: sqlite3.Connection, pair_uid: str) -> LockInfo | None:
    """Liest die eingetragene Sperre eines Paars, ohne sie zu bewerten."""
    row = connection.execute("SELECT * FROM run_locks WHERE pair_uid = ?", (pair_uid,)).fetchone()
    return _row_to_info(row) if row is not None else None


def is_locked(connection: sqlite3.Connection, pair_uid: str) -> bool:
    """Wahr, wenn gerade ein lebendiger Lauf fuer das Paar existiert."""
    info = read_lock(connection, pair_uid)
    if info is None:
        return False
    return not _lock_is_stale(info)


def acquire(connection: sqlite3.Connection, pair_uid: str, *, source: str = "unknown") -> LockInfo:
    """Erwirbt die Sperre oder wirft :class:`PairLockedError`.

    Pruefen, Aufraeumen und Setzen laufen in einer einzigen ``BEGIN
    IMMEDIATE``-Transaktion und sind damit auch zwischen Prozessen atomar.
    """
    pid = os.getpid()
    info = LockInfo(
        pair_uid=pair_uid,
        pid=pid,
        boot_id=current_boot_id(),
        pid_start_time=process_start_time(pid),
        acquired_at=datetime.now(tz=UTC),
        source=source,
    )

    with transaction(connection, immediate=True):
        existing_row = connection.execute(
            "SELECT * FROM run_locks WHERE pair_uid = ?", (pair_uid,)
        ).fetchone()
        if existing_row is not None:
            existing = _row_to_info(existing_row)
            if not _lock_is_stale(existing):
                raise PairLockedError(pair_uid, existing)
            log.warning(
                "Verwaiste Sperre von Prozess %d wird entfernt.",
                existing.pid,
                extra={"pair_uid": pair_uid},
            )
            connection.execute("DELETE FROM run_locks WHERE pair_uid = ?", (pair_uid,))

        connection.execute(
            """
            INSERT INTO run_locks (pair_uid, pid, boot_id, pid_start_time, acquired_at, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                info.pair_uid,
                info.pid,
                info.boot_id,
                info.pid_start_time,
                info.acquired_at.isoformat(),
                info.source,
            ),
        )
    return info


def release(connection: sqlite3.Connection, pair_uid: str, *, pid: int | None = None) -> bool:
    """Gibt die eigene Sperre frei.

    Es wird nur die Sperre des angegebenen Prozesses entfernt, damit ein
    verspaeteter Aufraeumversuch nicht die Sperre eines anderen Laufs loescht.
    """
    owner = os.getpid() if pid is None else pid
    with transaction(connection):
        cursor = connection.execute(
            "DELETE FROM run_locks WHERE pair_uid = ? AND pid = ? AND boot_id = ?",
            (pair_uid, owner, current_boot_id()),
        )
    return cursor.rowcount > 0


@contextlib.contextmanager
def run_lock(
    connection: sqlite3.Connection, pair_uid: str, *, source: str = "unknown"
) -> Iterator[LockInfo]:
    """Kontextmanager fuer einen exklusiven Lauf.

    Beispiel::

        with run_lock(connection, pair.uid, source="gui"):
            ...
    """
    info = acquire(connection, pair_uid, source=source)
    try:
        yield info
    finally:
        try:
            release(connection, pair_uid, pid=info.pid)
        except sqlite3.Error:  # pragma: no cover -- Aufraeumen darf nie maskieren
            log.exception("Sperre konnte nicht freigegeben werden.", extra={"pair_uid": pair_uid})


__all__ = [
    "LockError",
    "LockInfo",
    "PairLockedError",
    "acquire",
    "current_boot_id",
    "is_locked",
    "process_start_time",
    "read_lock",
    "release",
    "run_lock",
]
