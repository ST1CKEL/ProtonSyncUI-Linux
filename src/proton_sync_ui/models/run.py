"""Laufprotokoll: Status, Kennzahlen und Fehler eines einzelnen Durchgangs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RunStatus(StrEnum):
    """Ergebnis eines Laufs."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CANCELLED = "cancelled"


class PairStatus(StrEnum):
    """Zustand eines Sync-Paars in der Uebersicht."""

    IDLE = "idle"
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"


_STATUS_LABELS: dict[PairStatus, str] = {
    PairStatus.IDLE: "Inaktiv",
    PairStatus.WAITING: "Wartet",
    PairStatus.RUNNING: "Laeuft",
    PairStatus.SUCCESS: "Erfolgreich",
    PairStatus.WARNING: "Warnung",
    PairStatus.ERROR: "Fehler",
    PairStatus.DISABLED: "Deaktiviert",
}

_RUN_STATUS_LABELS: dict[RunStatus, str] = {
    RunStatus.PENDING: "Wartet",
    RunStatus.RUNNING: "Laeuft",
    RunStatus.SUCCESS: "Erfolgreich",
    RunStatus.WARNING: "Warnung",
    RunStatus.ERROR: "Fehler",
    RunStatus.CANCELLED: "Abgebrochen",
}


def pair_status_label(status: PairStatus) -> str:
    """Deutsche Bezeichnung eines Paar-Status."""
    return _STATUS_LABELS.get(status, status.value)


def run_status_label(status: RunStatus) -> str:
    """Deutsche Bezeichnung eines Lauf-Status."""
    return _RUN_STATUS_LABELS.get(status, status.value)


def pair_status_from_run(status: RunStatus | None, *, enabled: bool) -> PairStatus:
    """Leitet den Anzeigestatus eines Paars aus dem letzten Lauf ab.

    Die Zuordnung ist bewusst vollstaendig statt mit Auffangzweig: Kommt ein
    neuer :class:`RunStatus` hinzu, meldet die Typpruefung einen fehlenden
    Rueckgabewert, statt ihn still als "Inaktiv" darzustellen.
    """
    if not enabled:
        return PairStatus.DISABLED
    match status:
        case None:
            return PairStatus.IDLE
        case RunStatus.RUNNING:
            return PairStatus.RUNNING
        case RunStatus.PENDING:
            return PairStatus.WAITING
        case RunStatus.SUCCESS:
            return PairStatus.SUCCESS
        case RunStatus.WARNING:
            return PairStatus.WARNING
        case RunStatus.ERROR | RunStatus.CANCELLED:
            return PairStatus.ERROR


@dataclass(frozen=True, slots=True)
class FileError:
    """Ein Fehler, der genau eine Datei betrifft und den Lauf nicht abbricht."""

    relative_path: str
    message: str
    attempts: int = 1
    permanent: bool = False


@dataclass(slots=True)
class RunRecord:
    """Ein Lauf eines Sync-Paars -- Dry-Run oder echte Uebertragung."""

    pair_uid: str
    run_id: int | None = None
    dry_run: bool = False
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None
    planned_files: int = 0
    uploaded_files: int = 0
    downloaded_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    local_deletions: int = 0
    uploaded_bytes: int = 0
    downloaded_bytes: int = 0
    errors: list[FileError] = field(default_factory=list)
    message: str = ""

    @property
    def transferred_files(self) -> int:
        """Summe aller erfolgreich uebertragenen Dateien (Uploads + Downloads)."""
        return self.uploaded_files + self.downloaded_files

    @property
    def transferred_bytes(self) -> int:
        """Summe aller uebertragenen Bytes."""
        return self.uploaded_bytes + self.downloaded_bytes

    @property
    def duration_seconds(self) -> float | None:
        """Laufzeit in Sekunden, sofern der Lauf beendet ist."""
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def has_errors(self) -> bool:
        """Wahr, wenn mindestens eine Datei fehlgeschlagen ist."""
        return bool(self.errors)

    def finish(self, *, message: str = "") -> RunRecord:
        """Schliesst den Lauf ab und leitet den Endstatus aus den Kennzahlen ab.

        Ein einzelner Dateifehler fuehrt zu ``WARNING``, nicht zu ``ERROR``:
        der Lauf hat gearbeitet, nur unvollstaendig. ``ERROR`` bleibt Faellen
        vorbehalten, in denen gar nichts uebertragen werden konnte.
        """
        self.finished_at = datetime.now(tz=UTC)
        if message:
            self.message = message
        if self.status in (RunStatus.ERROR, RunStatus.CANCELLED):
            return self
        if self.failed_files == 0:
            self.status = RunStatus.SUCCESS
        elif self.transferred_files > 0:
            self.status = RunStatus.WARNING
        else:
            self.status = RunStatus.ERROR
        return self

    def fail(self, message: str) -> RunRecord:
        """Markiert den Lauf als vollstaendig gescheitert."""
        self.status = RunStatus.ERROR
        self.message = message
        self.finished_at = datetime.now(tz=UTC)
        return self

    def summary_line(self) -> str:
        """Einzeilige Zusammenfassung fuer Kommandozeile und Oberflaeche."""
        kind = "Dry-Run" if self.dry_run else "Lauf"
        parts = [
            f"{kind} {run_status_label(self.status)}",
            f"geplant: {self.planned_files}",
        ]
        if self.downloaded_files > 0 and self.uploaded_files > 0:
            parts.append(
                f"uebertragen: {self.transferred_files} "
                f"({self.downloaded_files} empfangen, {self.uploaded_files} gesendet)"
            )
        elif self.downloaded_files > 0:
            parts.append(f"uebertragen: {self.downloaded_files} heruntergeladen")
        else:
            parts.append(f"uebertragen: {self.uploaded_files}")

        parts.extend(
            [
                f"fehlgeschlagen: {self.failed_files}",
                f"uebersprungen: {self.skipped_files}",
            ]
        )
        duration = self.duration_seconds
        if duration is not None:
            parts.append(f"Dauer: {duration:.1f}s")
        return " | ".join(parts)


__all__ = [
    "FileError",
    "PairStatus",
    "RunRecord",
    "RunStatus",
    "pair_status_from_run",
    "pair_status_label",
    "run_status_label",
]
