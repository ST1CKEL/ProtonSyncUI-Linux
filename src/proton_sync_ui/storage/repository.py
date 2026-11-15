"""Lese- und Schreibzugriffe auf Sync-Paare, Dateizustaende und Laeufe."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..models.run import FileError, RunRecord, RunStatus
from ..models.sync_pair import ScheduleKind, SyncMode, SyncPair
from .database import transaction


def _to_iso(value: datetime) -> str:
    """Zeitstempel als ISO-8601 in UTC."""
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str) -> datetime:
    """Liest einen ISO-8601-Zeitstempel und erzwingt Zeitzonenbewusstsein."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@dataclass(frozen=True, slots=True)
class FileState:
    """Der zuletzt erfolgreich synchronisierte Zustand einer Datei."""

    relative_path: str
    size_bytes: int
    mtime_ns: int
    sha256: str | None
    remote_path: str
    uploaded_at: datetime
    remote_mtime: str | None = None
    #: Lokal geloescht, Cloud-Kopie besteht weiter ("Grabstein").
    deleted: bool = False


class Repository:
    """Alle Datenbankzugriffe der Anwendung."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Die zugrunde liegende Verbindung (fuer Locking und Tests)."""
        return self._connection

    def close(self) -> None:
        """Schliesst die Verbindung."""
        self._connection.close()

    # ------------------------------------------------------------------
    # Sync-Paare
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_pair(row: sqlite3.Row) -> SyncPair:
        patterns = tuple(line for line in str(row["exclude_patterns"]).splitlines() if line.strip())
        try:
            sync_mode = SyncMode(row["sync_mode"])
        except (ValueError, KeyError, IndexError):
            sync_mode = SyncMode.BIDIRECTIONAL

        return SyncPair(
            uid=row["uid"],
            name=row["name"],
            local_path=Path(row["local_path"]),
            remote_path=row["remote_path"],
            enabled=bool(row["enabled"]),
            sync_mode=sync_mode,
            schedule_kind=ScheduleKind(row["schedule_kind"]),
            interval_minutes=row["interval_minutes"],
            exclude_patterns=patterns,
            max_file_size_bytes=row["max_file_size_bytes"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )

    def save_pair(self, pair: SyncPair) -> SyncPair:
        """Legt ein Sync-Paar an oder aktualisiert es."""
        with transaction(self._connection):
            self._connection.execute(
                """
                INSERT INTO sync_pairs (
                    uid, name, local_path, remote_path, enabled, sync_mode, schedule_kind,
                    interval_minutes, exclude_patterns, max_file_size_bytes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (uid) DO UPDATE SET
                    name                = excluded.name,
                    local_path          = excluded.local_path,
                    remote_path         = excluded.remote_path,
                    enabled             = excluded.enabled,
                    sync_mode           = excluded.sync_mode,
                    schedule_kind       = excluded.schedule_kind,
                    interval_minutes    = excluded.interval_minutes,
                    exclude_patterns    = excluded.exclude_patterns,
                    max_file_size_bytes = excluded.max_file_size_bytes,
                    updated_at          = excluded.updated_at
                """,
                (
                    pair.uid,
                    pair.name,
                    str(pair.local_path),
                    pair.remote_path,
                    int(pair.enabled),
                    pair.sync_mode.value,
                    pair.schedule_kind.value,
                    pair.interval_minutes,
                    "\n".join(pair.exclude_patterns),
                    pair.max_file_size_bytes,
                    _to_iso(pair.created_at),
                    _to_iso(pair.updated_at),
                ),
            )
        return pair

    def get_pair(self, uid: str) -> SyncPair | None:
        """Liefert ein Sync-Paar oder ``None``."""
        row = self._connection.execute("SELECT * FROM sync_pairs WHERE uid = ?", (uid,)).fetchone()
        return self._row_to_pair(row) if row is not None else None

    def list_pairs(self, *, enabled_only: bool = False) -> list[SyncPair]:
        """Alle Sync-Paare, alphabetisch nach Anzeigename."""
        query = "SELECT * FROM sync_pairs"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name COLLATE NOCASE"
        return [self._row_to_pair(row) for row in self._connection.execute(query)]

    def delete_pair(self, uid: str) -> bool:
        """Entfernt ein Sync-Paar samt Zustand und Historie."""
        with transaction(self._connection):
            cursor = self._connection.execute("DELETE FROM sync_pairs WHERE uid = ?", (uid,))
        return cursor.rowcount > 0

    def set_pair_enabled(self, uid: str, *, enabled: bool) -> None:
        """Aktiviert oder deaktiviert ein Sync-Paar."""
        with transaction(self._connection):
            self._connection.execute(
                "UPDATE sync_pairs SET enabled = ?, updated_at = ? WHERE uid = ?",
                (int(enabled), _to_iso(datetime.now(tz=UTC)), uid),
            )

    # ------------------------------------------------------------------
    # Dateizustaende
    # ------------------------------------------------------------------

    def load_file_states(self, pair_uid: str) -> dict[str, FileState]:
        """Alle bekannten Dateizustaende eines Paars, nach relativem Pfad."""
        rows = self._connection.execute(
            """
            SELECT relative_path, size_bytes, mtime_ns, sha256, remote_path,
                   remote_mtime, uploaded_at, deleted
            FROM file_states WHERE pair_uid = ?
            """,
            (pair_uid,),
        )
        return {
            row["relative_path"]: FileState(
                relative_path=row["relative_path"],
                size_bytes=row["size_bytes"],
                mtime_ns=row["mtime_ns"],
                sha256=row["sha256"],
                remote_path=row["remote_path"],
                remote_mtime=row["remote_mtime"],
                uploaded_at=_from_iso(row["uploaded_at"]),
                deleted=bool(row["deleted"]),
            )
            for row in rows
        }

    def record_upload(
        self,
        pair_uid: str,
        *,
        relative_path: str,
        size_bytes: int,
        mtime_ns: int,
        remote_path: str,
        sha256: str | None = None,
        remote_mtime: str | None = None,
    ) -> None:
        """Vermerkt eine erfolgreich synchronisierte Datei."""
        with transaction(self._connection):
            self._connection.execute(
                """
                INSERT INTO file_states (
                    pair_uid, relative_path, size_bytes, mtime_ns, sha256,
                    remote_path, remote_mtime, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (pair_uid, relative_path) DO UPDATE SET
                    size_bytes   = excluded.size_bytes,
                    mtime_ns     = excluded.mtime_ns,
                    sha256       = excluded.sha256,
                    remote_path  = excluded.remote_path,
                    remote_mtime = excluded.remote_mtime,
                    uploaded_at  = excluded.uploaded_at,
                    deleted      = 0
                """,
                (
                    pair_uid,
                    relative_path,
                    size_bytes,
                    mtime_ns,
                    sha256,
                    remote_path,
                    remote_mtime,
                    _to_iso(datetime.now(tz=UTC)),
                ),
            )

    def record_download(
        self,
        pair_uid: str,
        *,
        relative_path: str,
        size_bytes: int,
        mtime_ns: int,
        remote_path: str,
        sha256: str | None = None,
        remote_mtime: str | None = None,
    ) -> None:
        """Vermerkt eine erfolgreich heruntergeladene Datei."""
        self.record_upload(
            pair_uid,
            relative_path=relative_path,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            remote_path=remote_path,
            sha256=sha256,
            remote_mtime=remote_mtime,
        )

    def touch_file_state(self, pair_uid: str, *, relative_path: str, mtime_ns: int) -> None:
        """Aktualisiert nur die mtime eines unveraenderten Inhalts."""
        with transaction(self._connection):
            self._connection.execute(
                "UPDATE file_states SET mtime_ns = ? WHERE pair_uid = ? AND relative_path = ?",
                (mtime_ns, pair_uid, relative_path),
            )

    def set_remote_mtime(self, pair_uid: str, *, relative_path: str, remote_mtime: str) -> None:
        """Traegt die entfernte Aenderungszeit einer unveraenderten Datei nach.

        Nach einem Upload ist sie unbekannt; ohne sie liessen sich spaetere
        Cloud-Aenderungen gleicher Groesse nicht erkennen.
        """
        with transaction(self._connection):
            self._connection.execute(
                "UPDATE file_states SET remote_mtime = ? WHERE pair_uid = ? AND relative_path = ?",
                (remote_mtime, pair_uid, relative_path),
            )

    def mark_deleted(self, pair_uid: str, relative_paths: Iterable[str]) -> None:
        """Vermerkt lokal geloeschte Dateien, deren Cloud-Kopie bestehen bleibt.

        Der Eintrag bleibt als Grabstein erhalten, damit die Datei nicht beim
        naechsten Lauf erneut heruntergeladen wird.
        """
        items = [(pair_uid, path) for path in relative_paths]
        if not items:
            return
        with transaction(self._connection):
            self._connection.executemany(
                "UPDATE file_states SET deleted = 1 WHERE pair_uid = ? AND relative_path = ?",
                items,
            )

    def forget_file_states(self, pair_uid: str, relative_paths: Iterable[str]) -> None:
        """Entfernt Zustandseintraege lokal geloeschter Dateien."""
        items = [(pair_uid, path) for path in relative_paths]
        if not items:
            return
        with transaction(self._connection):
            self._connection.executemany(
                "DELETE FROM file_states WHERE pair_uid = ? AND relative_path = ?", items
            )

    def clear_file_states(self, pair_uid: str) -> None:
        """Verwirft den gesamten Zustand eines Paars (erzwingt vollen Neuabgleich)."""
        with transaction(self._connection):
            self._connection.execute("DELETE FROM file_states WHERE pair_uid = ?", (pair_uid,))

    # ------------------------------------------------------------------
    # Laeufe
    # ------------------------------------------------------------------

    def start_run(self, pair_uid: str, *, dry_run: bool) -> int:
        """Legt einen Laufeintrag an und liefert dessen Kennung."""
        with transaction(self._connection):
            cursor = self._connection.execute(
                """
                INSERT INTO runs (pair_uid, dry_run, status, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    pair_uid,
                    int(dry_run),
                    RunStatus.RUNNING.value,
                    _to_iso(datetime.now(tz=UTC)),
                ),
            )
        run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover
            raise RuntimeError("SQLite hat keine Lauf-Kennung geliefert.")
        return run_id

    def finish_run(self, record: RunRecord) -> None:
        """Schreibt Endstatus, Kennzahlen und Dateifehler eines Laufs."""
        if record.run_id is None:
            raise ValueError("RunRecord ohne run_id kann nicht gespeichert werden.")
        with transaction(self._connection):
            self._connection.execute(
                """
                UPDATE runs SET
                    status = ?, finished_at = ?, planned_files = ?, uploaded_files = ?,
                    downloaded_files = ?, failed_files = ?, skipped_files = ?,
                    local_deletions = ?, uploaded_bytes = ?, downloaded_bytes = ?, message = ?
                WHERE id = ?
                """,
                (
                    record.status.value,
                    _to_iso(record.finished_at) if record.finished_at else None,
                    record.planned_files,
                    record.uploaded_files,
                    record.downloaded_files,
                    record.failed_files,
                    record.skipped_files,
                    record.local_deletions,
                    record.uploaded_bytes,
                    record.downloaded_bytes,
                    record.message,
                    record.run_id,
                ),
            )
            self._connection.execute("DELETE FROM run_errors WHERE run_id = ?", (record.run_id,))
            if record.errors:
                self._connection.executemany(
                    """
                    INSERT INTO run_errors (run_id, relative_path, message, attempts, permanent)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            record.run_id,
                            error.relative_path,
                            error.message,
                            error.attempts,
                            int(error.permanent),
                        )
                        for error in record.errors
                    ],
                )

    def _row_to_run(self, row: sqlite3.Row, *, with_errors: bool = True) -> RunRecord:
        record = RunRecord(
            pair_uid=row["pair_uid"],
            run_id=row["id"],
            dry_run=bool(row["dry_run"]),
            status=RunStatus(row["status"]),
            started_at=_from_iso(row["started_at"]),
            finished_at=_from_iso(row["finished_at"]) if row["finished_at"] else None,
            planned_files=row["planned_files"],
            uploaded_files=row["uploaded_files"],
            downloaded_files=row["downloaded_files"],
            failed_files=row["failed_files"],
            skipped_files=row["skipped_files"],
            local_deletions=row["local_deletions"],
            uploaded_bytes=row["uploaded_bytes"],
            downloaded_bytes=row["downloaded_bytes"],
            message=row["message"],
        )
        if with_errors:
            record.errors = self.list_run_errors(row["id"])
        return record

    def list_run_errors(self, run_id: int) -> list[FileError]:
        """Alle Dateifehler eines Laufs."""
        rows = self._connection.execute(
            """
            SELECT relative_path, message, attempts, permanent
            FROM run_errors WHERE run_id = ? ORDER BY id
            """,
            (run_id,),
        )
        return [
            FileError(
                relative_path=row["relative_path"],
                message=row["message"],
                attempts=row["attempts"],
                permanent=bool(row["permanent"]),
            )
            for row in rows
        ]

    def last_run(self, pair_uid: str, *, include_dry_runs: bool = True) -> RunRecord | None:
        """Der juengste Lauf eines Paars."""
        query = "SELECT * FROM runs WHERE pair_uid = ?"
        params: list[object] = [pair_uid]
        if not include_dry_runs:
            query += " AND dry_run = 0"
        query += " ORDER BY started_at DESC, id DESC LIMIT 1"
        row = self._connection.execute(query, params).fetchone()
        return self._row_to_run(row) if row is not None else None

    def last_runs(self, *, include_dry_runs: bool = True) -> Mapping[str, RunRecord]:
        """Der juengste Lauf je Paar -- eine Abfrage fuer die gesamte Uebersicht."""
        query = (
            """
            SELECT r.* FROM runs r
            INNER JOIN (
                SELECT pair_uid, MAX(id) AS max_id FROM runs
                GROUP BY pair_uid
            ) latest ON latest.max_id = r.id
            """
            if include_dry_runs
            else """
            SELECT r.* FROM runs r
            INNER JOIN (
                SELECT pair_uid, MAX(id) AS max_id FROM runs
                WHERE dry_run = 0
                GROUP BY pair_uid
            ) latest ON latest.max_id = r.id
            """
        )
        return {
            row["pair_uid"]: self._row_to_run(row, with_errors=False)
            for row in self._connection.execute(query)
        }

    def list_runs(self, pair_uid: str | None = None, *, limit: int = 50) -> list[RunRecord]:
        """Die letzten Laeufe eines Paars oder aller Paare, neueste zuerst."""
        if pair_uid is not None:
            rows = self._connection.execute(
                "SELECT * FROM runs WHERE pair_uid = ? ORDER BY started_at DESC, id DESC LIMIT ?",
                (pair_uid, limit),
            )
        else:
            rows = self._connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_run(row, with_errors=False) for row in rows]

    def prune_runs(self, pair_uid: str, *, keep: int = 100) -> int:
        """Begrenzt die Historie eines Paars auf die letzten ``keep`` Laeufe."""
        with transaction(self._connection):
            cursor = self._connection.execute(
                """
                DELETE FROM runs WHERE pair_uid = ? AND id NOT IN (
                    SELECT id FROM runs WHERE pair_uid = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (pair_uid, pair_uid, keep),
            )
        return cursor.rowcount


__all__ = ["FileState", "Repository"]
