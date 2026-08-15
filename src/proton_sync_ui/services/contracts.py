"""Vertraege und Datenstrukturen fuer die Service-Schicht."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models.run import RunRecord
from ..models.sync_pair import SyncPair
from ..sync.engine import SyncProgress


@dataclass(frozen=True, slots=True)
class ConflictItem:
    """Repraesentiert einen erkannten Dateikonflikt."""

    pair_uid: str
    relative_path: str
    local_size: int
    local_mtime_ns: int
    remote_size: int
    remote_mtime: str
    conflict_file_path: str | None = None
    created_at_iso: str = ""


class SyncPairRepository(Protocol):
    """Schnittstelle fuer Persistenz von Sync-Paaren."""

    def list_pairs(self) -> list[SyncPair]: ...
    def get_pair(self, uid: str) -> SyncPair | None: ...
    def save_pair(self, pair: SyncPair) -> None: ...
    def delete_pair(self, uid: str) -> None: ...
    def set_pair_enabled(self, uid: str, *, enabled: bool) -> None: ...


class ActivityRepository(Protocol):
    """Schnittstelle fuer Zugriff auf Laeufe und Fehler."""

    def list_recent_runs(self, limit: int = 50) -> list[RunRecord]: ...
    def get_last_run(self, pair_uid: str) -> RunRecord | None: ...
    def list_pair_runs(self, pair_uid: str, limit: int = 50) -> list[RunRecord]: ...


class ConflictService(Protocol):
    """Schnittstelle fuer Konflikterkennung und -aufloesung."""

    def list_conflicts(self) -> list[ConflictItem]: ...
    def resolve_conflict(self, conflict: ConflictItem, resolution: str) -> None: ...


class SyncService(Protocol):
    """Schnittstelle zur Steuerung von Synchronisationslaeufen."""

    def start_sync(self, pair: SyncPair, *, dry_run: bool = False) -> None: ...
    def cancel_sync(self, pair_uid: str) -> None: ...
    def is_running(self, pair_uid: str) -> bool: ...


__all__ = [
    "ActivityRepository",
    "ConflictItem",
    "ConflictService",
    "SyncPairRepository",
    "SyncProgress",
    "SyncService",
]
