"""SQLite-Verbindung, Schema-Initialisierung und Migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Final

from .. import paths
from ..logging_setup import get_logger

log = get_logger("storage.database")

SCHEMA_VERSION: Final = 3

#: Wartezeit, bis eine gesperrte Datenbank aufgegeben wird. Grosszuegig, weil
#: Oberflaeche und systemd-Dienst gleichzeitig zugreifen koennen.
BUSY_TIMEOUT_SECONDS: Final = 30.0


def _load_schema() -> str:
    """Laedt schema.sql aus dem installierten Paket."""
    return resources.files("proton_sync_ui.storage").joinpath("schema.sql").read_text("utf-8")


def connect(
    db_path: Path | None = None, *, timeout: float = BUSY_TIMEOUT_SECONDS
) -> sqlite3.Connection:
    """Oeffnet eine konfigurierte Verbindung und legt das Schema an, falls noetig.

    WAL erlaubt gleichzeitiges Lesen waehrend ein Lauf schreibt -- die
    Oberflaeche bleibt dadurch bedienbar, waehrend im Hintergrund
    synchronisiert wird.
    """
    target = db_path if db_path is not None else paths.database_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    is_new = not target.exists()

    connection = sqlite3.connect(
        target,
        timeout=timeout,
        isolation_level=None,  # explizite Transaktionssteuerung
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")

    if is_new:
        # Die Datenbank enthaelt Dateipfade des Benutzers.
        target.chmod(0o600)

    initialize(connection)
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Legt das Schema an oder migriert eine bestehende Datenbank."""
    connection.executescript(_load_schema())

    row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        return

    current = int(row["version"])
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Die Datenbank verwendet Schema-Version {current}, diese Anwendung kennt nur "
            f"Version {SCHEMA_VERSION}. Bitte ProtonSyncUI aktualisieren."
        )
    if current < SCHEMA_VERSION:
        _migrate(connection, from_version=current)


def _migrate(connection: sqlite3.Connection, *, from_version: int) -> None:
    """Fuehrt Migrationen aus.

    Version 1 ist das Ausgangsschema; Schritte werden hier nacheinander ergaenzt.
    """
    log.info("Migriere Datenbank von Version %d auf %d", from_version, SCHEMA_VERSION)
    if from_version < 2:
        sync_pair_cols = {
            row["name"] for row in connection.execute("PRAGMA table_info(sync_pairs)").fetchall()
        }
        if "sync_mode" not in sync_pair_cols:
            connection.execute(
                "ALTER TABLE sync_pairs ADD COLUMN sync_mode TEXT NOT NULL DEFAULT 'bidirectional'"
            )

        run_cols = {row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        if "downloaded_files" not in run_cols:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN downloaded_files INTEGER NOT NULL DEFAULT 0"
            )
        if "downloaded_bytes" not in run_cols:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN downloaded_bytes INTEGER NOT NULL DEFAULT 0"
            )

        file_state_cols = {
            row["name"] for row in connection.execute("PRAGMA table_info(file_states)").fetchall()
        }
        if "remote_mtime" not in file_state_cols:
            connection.execute("ALTER TABLE file_states ADD COLUMN remote_mtime TEXT")

    if from_version < 3:
        file_state_cols = {
            row["name"] for row in connection.execute("PRAGMA table_info(file_states)").fetchall()
        }
        if "deleted" not in file_state_cols:
            connection.execute(
                "ALTER TABLE file_states ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 "
                "CHECK (deleted IN (0, 1))"
            )

    connection.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


@contextmanager
def transaction(
    connection: sqlite3.Connection, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """Fuehrt einen Block in einer Transaktion aus.

    ``immediate=True`` erwirbt die Schreibsperre sofort statt erst beim ersten
    Schreibzugriff. Genau das braucht das Lauf-Locking, um atomar zu sein.
    """
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


__all__ = ["BUSY_TIMEOUT_SECONDS", "SCHEMA_VERSION", "connect", "initialize", "transaction"]
