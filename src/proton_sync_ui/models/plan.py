"""Der Sync-Plan: was ein Lauf tun wuerde, bevor er es tut."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath


class PlanAction(StrEnum):
    """Was mit einer Datei geschehen soll.

    Es gibt bewusst keine Aktion, die eine entfernte Datei loescht.
    ``LOCAL_DELETED`` ist ein reiner Protokollhinweis.
    """

    UPLOAD_NEW = "upload_new"
    UPLOAD_CHANGED = "upload_changed"
    DOWNLOAD_NEW = "download_new"
    DOWNLOAD_CHANGED = "download_changed"
    CONFLICT_LOCAL_RENAMED = "conflict_local_renamed"
    SKIP_UNCHANGED = "skip_unchanged"
    SKIP_EXCLUDED = "skip_excluded"
    SKIP_TOO_LARGE = "skip_too_large"
    SKIP_SYMLINK = "skip_symlink"
    SKIP_UNSUPPORTED_NAME = "skip_unsupported_name"
    SKIP_UNREADABLE = "skip_unreadable"
    SKIP_DOCS_SHEETS = "skip_docs_sheets"
    LOCAL_DELETED = "local_deleted"


#: Aktionen, die einen CLI-Upload ausloesen.
UPLOAD_ACTIONS: frozenset[PlanAction] = frozenset(
    {PlanAction.UPLOAD_NEW, PlanAction.UPLOAD_CHANGED}
)

#: Aktionen, die einen CLI-Download ausloesen.
DOWNLOAD_ACTIONS: frozenset[PlanAction] = frozenset(
    {PlanAction.DOWNLOAD_NEW, PlanAction.DOWNLOAD_CHANGED, PlanAction.CONFLICT_LOCAL_RENAMED}
)

#: Alle uebertragenden Aktionen.
TRANSFER_ACTIONS: frozenset[PlanAction] = UPLOAD_ACTIONS | DOWNLOAD_ACTIONS

#: Aktionen, die uebersprungen werden.
SKIP_ACTIONS: frozenset[PlanAction] = frozenset(
    {
        PlanAction.SKIP_UNCHANGED,
        PlanAction.SKIP_EXCLUDED,
        PlanAction.SKIP_TOO_LARGE,
        PlanAction.SKIP_SYMLINK,
        PlanAction.SKIP_UNSUPPORTED_NAME,
        PlanAction.SKIP_UNREADABLE,
        PlanAction.SKIP_DOCS_SHEETS,
    }
)

_ACTION_LABELS: dict[PlanAction, str] = {
    PlanAction.UPLOAD_NEW: "Upload (neu)",
    PlanAction.UPLOAD_CHANGED: "Upload (geaendert)",
    PlanAction.DOWNLOAD_NEW: "Download (neu)",
    PlanAction.DOWNLOAD_CHANGED: "Download (geaendert)",
    PlanAction.CONFLICT_LOCAL_RENAMED: "Konflikt (lokal umbenannt)",
    PlanAction.SKIP_UNCHANGED: "Unveraendert",
    PlanAction.SKIP_EXCLUDED: "Ausgeschlossen",
    PlanAction.SKIP_TOO_LARGE: "Zu gross",
    PlanAction.SKIP_SYMLINK: "Symlink",
    PlanAction.SKIP_UNSUPPORTED_NAME: "Name nicht unterstuetzt",
    PlanAction.SKIP_UNREADABLE: "Nicht lesbar",
    PlanAction.SKIP_DOCS_SHEETS: "Proton Doc/Sheet (nicht downloadbar)",
    PlanAction.LOCAL_DELETED: "Lokal geloescht",
}


def action_label(action: PlanAction) -> str:
    """Deutsche Bezeichnung einer Plan-Aktion fuer die Oberflaeche."""
    return _ACTION_LABELS.get(action, action.value)


@dataclass(frozen=True, slots=True)
class PlanItem:
    """Eine geplante Entscheidung fuer genau eine relative Datei."""

    relative_path: PurePosixPath
    action: PlanAction
    size_bytes: int = 0
    mtime_ns: int = 0
    remote_mtime: str = ""
    remote_path: str = ""
    reason: str = ""
    #: Bereits berechnete Pruefsumme, damit der Lauf nicht erneut hashen muss.
    sha256: str | None = None
    #: Inhalt unveraendert, aber die gespeicherte mtime ist veraltet.
    needs_mtime_refresh: bool = False

    @property
    def is_upload(self) -> bool:
        """Wahr, wenn dieser Eintrag einen Upload ausloest."""
        return self.action in UPLOAD_ACTIONS

    @property
    def is_download(self) -> bool:
        """Wahr, wenn dieser Eintrag einen Download ausloest."""
        return self.action in DOWNLOAD_ACTIONS

    @property
    def is_transfer(self) -> bool:
        """Wahr, wenn dieser Eintrag eine Uebertragung ausloest."""
        return self.action in TRANSFER_ACTIONS

    @property
    def posix_path(self) -> str:
        """Relativer Pfad als POSIX-Zeichenkette."""
        return self.relative_path.as_posix()


@dataclass(frozen=True, slots=True)
class UploadPlan:
    """Das vollstaendige Ergebnis der Planungsphase eines Laufs."""

    pair_uid: str
    items: tuple[PlanItem, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    scan_errors: tuple[str, ...] = ()

    @classmethod
    def from_items(
        cls,
        pair_uid: str,
        items: Sequence[PlanItem],
        *,
        scan_errors: Sequence[str] = (),
    ) -> UploadPlan:
        """Erzeugt einen Plan aus einer Sequenz von Eintraegen.

        Die Eintraege werden nach Pfad sortiert, damit Laeufe reproduzierbar
        und Testvergleiche stabil sind.
        """
        ordered = tuple(sorted(items, key=lambda item: item.relative_path.as_posix()))
        return cls(pair_uid=pair_uid, items=ordered, scan_errors=tuple(scan_errors))

    def by_action(self, action: PlanAction) -> tuple[PlanItem, ...]:
        """Alle Eintraege mit einer bestimmten Aktion."""
        return tuple(item for item in self.items if item.action is action)

    @property
    def uploads(self) -> tuple[PlanItem, ...]:
        """Alle hochzuladenden Eintraege."""
        return tuple(item for item in self.items if item.is_upload)

    @property
    def downloads(self) -> tuple[PlanItem, ...]:
        """Alle herunterzuladenden Eintraege."""
        return tuple(item for item in self.items if item.is_download)

    @property
    def new_uploads(self) -> tuple[PlanItem, ...]:
        """Lokal neue Dateien fuer den Upload."""
        return self.by_action(PlanAction.UPLOAD_NEW)

    @property
    def new_files(self) -> tuple[PlanItem, ...]:
        """Alias fuer new_uploads."""
        return self.new_uploads

    @property
    def changed_uploads(self) -> tuple[PlanItem, ...]:
        """Lokal geaenderte Dateien fuer den Upload."""
        return self.by_action(PlanAction.UPLOAD_CHANGED)

    @property
    def changed_files(self) -> tuple[PlanItem, ...]:
        """Alias fuer changed_uploads."""
        return self.changed_uploads

    @property
    def new_downloads(self) -> tuple[PlanItem, ...]:
        """Entfernt neue Dateien fuer den Download."""
        return self.by_action(PlanAction.DOWNLOAD_NEW)

    @property
    def changed_downloads(self) -> tuple[PlanItem, ...]:
        """Entfernt geaenderte Dateien fuer den Download."""
        return self.by_action(PlanAction.DOWNLOAD_CHANGED)

    @property
    def skipped(self) -> tuple[PlanItem, ...]:
        """Alle uebersprungenen Eintraege."""
        return tuple(item for item in self.items if item.action in SKIP_ACTIONS)

    @property
    def local_deletions(self) -> tuple[PlanItem, ...]:
        """Lokal geloeschte Dateien -- reiner Hinweis, ohne entfernte Wirkung."""
        return self.by_action(PlanAction.LOCAL_DELETED)

    @property
    def total_upload_bytes(self) -> int:
        """Summe der hochzuladenden Bytes."""
        return sum(item.size_bytes for item in self.uploads)

    @property
    def total_download_bytes(self) -> int:
        """Summe der herunterzuladenden Bytes."""
        return sum(item.size_bytes for item in self.downloads)

    @property
    def download_count(self) -> int:
        """Anzahl der herunterzuladenden Dateien."""
        return len(self.downloads)

    @property
    def upload_count(self) -> int:
        """Anzahl der hochzuladenden Dateien."""
        return len(self.uploads)

    @property
    def skip_count(self) -> int:
        """Anzahl der uebersprungenen Dateien."""
        return len(self.skipped)

    @property
    def is_empty(self) -> bool:
        """Wahr, wenn nichts zu uebertragen ist."""
        return not self.uploads and not self.downloads

    def summary(self) -> dict[str, int]:
        """Kennzahlen des Plans fuer Anzeige und Protokoll."""
        return {
            "neu": len(self.new_uploads),
            "geaendert": len(self.changed_uploads),
            "upload_neu": len(self.new_uploads),
            "upload_geaendert": len(self.changed_uploads),
            "download_neu": len(self.new_downloads),
            "download_geaendert": len(self.changed_downloads),
            "uebersprungen": len(self.skipped),
            "lokal_geloescht": len(self.local_deletions),
            "bytes": self.total_upload_bytes + self.total_download_bytes,
            "upload_bytes": self.total_upload_bytes,
            "download_bytes": self.total_download_bytes,
        }

    def describe(self) -> str:
        """Einzeilige Zusammenfassung fuer Protokoll und Kommandozeile."""
        parts: list[str] = []
        if self.downloads:
            parts.append(
                f"Download: {len(self.new_downloads)} neu, {len(self.changed_downloads)} geaendert"
            )
        if self.uploads:
            parts.append(
                f"Upload: {len(self.new_uploads)} neu, {len(self.changed_uploads)} geaendert"
            )
        if not parts:
            parts.append("Keine Uebertragungen noetig")
        if self.skipped:
            parts.append(f"{len(self.skipped)} uebersprungen")
        if self.local_deletions:
            parts.append(f"{len(self.local_deletions)} lokal geloescht")
        return ", ".join(parts)

    def __iter__(self) -> Iterator[PlanItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


# Alias fuer Rueckwaertskompatibilitaet
SyncPlan = UploadPlan

__all__ = [
    "DOWNLOAD_ACTIONS",
    "SKIP_ACTIONS",
    "TRANSFER_ACTIONS",
    "UPLOAD_ACTIONS",
    "PlanAction",
    "PlanItem",
    "SyncPlan",
    "UploadPlan",
    "action_label",
]
