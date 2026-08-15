"""Das Sync-Paar: lokale Quelle, Proton-Drive-Ziel und Zeitplan."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

# Die tatsaechlichen Top-Level-Bereiche der Proton-Drive-CLI. Ermittelt mit
# `proton-drive filesystem list /` (CLI cli-drive@0.8.0).
KNOWN_REMOTE_SECTIONS: Final[frozenset[str]] = frozenset(
    {
        "/my-files",
        "/devices",
        "/shared-by-me",
        "/shared-with-me",
        "/trash",
        "/albums",
        "/photos",
        "/photos-shared-by-me",
        "/photos-shared-with-me",
        "/photos-trash",
    }
)

# Nur diese Bereiche sind sinnvolle und sichere Upload-Ziele. `/trash` und die
# Foto-/Album-Bereiche sind bewusst ausgeschlossen: dort haette ein Upload
# entweder keine Wirkung oder unerwartete Nebenwirkungen.
UPLOADABLE_REMOTE_SECTIONS: Final[frozenset[str]] = frozenset(
    {"/my-files", "/devices", "/shared-with-me"}
)

DEFAULT_REMOTE_ROOT: Final = "/my-files"

MIN_INTERVAL_MINUTES: Final = 5
MAX_INTERVAL_MINUTES: Final = 60 * 24 * 7

# Zeichen, die in Proton-Drive-Knotennamen nicht zuverlaessig darstellbar sind.
# Der Backslash ist das Escape-Zeichen der CLI fuer "/" in Namen; wie ein
# woertlicher Backslash zu maskieren waere, ist nicht dokumentiert. Statt zu
# raten lehnen wir solche Namen ab (siehe README, Bekannte Grenzen).
_UNSUPPORTED_NAME_CHARS: Final = "\\"

_CONTROL_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")


class ValidationError(ValueError):
    """Eine Benutzereingabe ist ungueltig. Die Meldung ist zur Anzeige geeignet."""


class ScheduleKind(StrEnum):
    """Wie ein Sync-Paar ausgeloest wird."""

    MANUAL = "manual"
    INTERVAL = "interval"


class SyncMode(StrEnum):
    """Richtung des Abgleichs."""

    BIDIRECTIONAL = "bidirectional"
    UPLOAD_ONLY = "upload_only"
    DOWNLOAD_ONLY = "download_only"


_SYNC_MODE_LABELS: dict[SyncMode, str] = {
    SyncMode.BIDIRECTIONAL: "2-Wege-Synchronisation (Cloud ⇄ Lokal)",
    SyncMode.UPLOAD_ONLY: "Nur Upload (Lokal ➔ Cloud)",
    SyncMode.DOWNLOAD_ONLY: "Nur Download (Cloud ➔ Lokal)",
}


def sync_mode_label(mode: SyncMode) -> str:
    """Deutsche Bezeichnung eines Synchronisationsmodus."""
    return _SYNC_MODE_LABELS.get(mode, mode.value)


def name_is_supported(name: str) -> bool:
    """Prueft, ob ein Datei-/Ordnername an die Proton-CLI uebergeben werden darf."""
    if not name or name in (".", ".."):
        return False
    if _CONTROL_CHARS.search(name):
        return False
    return not any(char in name for char in _UNSUPPORTED_NAME_CHARS)


def validate_remote_path(raw: str) -> str:
    """Normalisiert und validiert einen Proton-Drive-Zielpfad.

    Die CLI nutzt immer POSIX-Pfade, unabhaengig vom Betriebssystem. Erlaubt
    sind nur Pfade unterhalb der schreibbaren Bereiche.

    Gibt den normalisierten Pfad ohne abschliessenden Schraegstrich zurueck.
    """
    text = raw.strip()
    if not text:
        raise ValidationError("Der Proton-Drive-Zielpfad darf nicht leer sein.")
    if not text.startswith("/"):
        raise ValidationError(
            "Der Zielpfad muss absolut sein und mit '/' beginnen, "
            f"z. B. {DEFAULT_REMOTE_ROOT}/Backup."
        )
    if _CONTROL_CHARS.search(text):
        raise ValidationError("Der Zielpfad enthaelt nicht darstellbare Steuerzeichen.")
    if "\\" in text:
        raise ValidationError(
            "Backslashes werden im Zielpfad nicht unterstuetzt. "
            "Bitte verwende Ordnernamen ohne '\\'."
        )

    parts = [part for part in text.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ValidationError("Der Zielpfad darf keine Bestandteile '.' oder '..' enthalten.")
    if not parts:
        raise ValidationError(
            "Der Zielpfad darf nicht das Wurzelverzeichnis '/' sein. "
            f"Waehle einen Ordner unterhalb von {DEFAULT_REMOTE_ROOT}."
        )

    normalized = "/" + "/".join(parts)
    section = "/" + parts[0]

    if section not in KNOWN_REMOTE_SECTIONS:
        known = ", ".join(sorted(UPLOADABLE_REMOTE_SECTIONS))
        raise ValidationError(
            f"'{section}' ist kein bekannter Proton-Drive-Bereich. Moegliche Ziele: {known}."
        )
    if section not in UPLOADABLE_REMOTE_SECTIONS:
        known = ", ".join(sorted(UPLOADABLE_REMOTE_SECTIONS))
        raise ValidationError(
            f"In den Bereich '{section}' darf ProtonSyncUI nicht hochladen. "
            f"Moegliche Ziele: {known}."
        )
    if normalized == section and section != DEFAULT_REMOTE_ROOT:
        raise ValidationError(
            f"Bitte waehle einen Unterordner in '{section}', nicht den Bereich selbst."
        )

    for part in parts[1:]:
        if not name_is_supported(part):
            raise ValidationError(f"Der Ordnername '{part}' enthaelt nicht unterstuetzte Zeichen.")

    return normalized


def validate_local_path(raw: str | Path, *, must_exist: bool = True) -> Path:
    """Normalisiert und validiert einen lokalen Quellordner.

    Der Pfad wird expandiert (``~``) und aufgeloest. Symlinks als Wurzel des
    Quellordners werden abgelehnt, weil im MVP keine Symlinks synchronisiert
    werden und ein verlinkter Wurzelordner diese Zusage unterlaufen wuerde.
    """
    text = str(raw).strip()
    if not text:
        raise ValidationError("Der lokale Quellordner darf nicht leer sein.")

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ValidationError("Der lokale Quellordner muss ein absoluter Pfad sein.")

    if candidate.is_symlink():
        raise ValidationError(
            "Der Quellordner ist ein symbolischer Link. "
            "Bitte waehle den tatsaechlichen Ordner aus -- Symlinks werden nicht synchronisiert."
        )

    resolved = candidate.resolve()

    if must_exist:
        if not resolved.exists():
            raise ValidationError(f"Der Ordner '{resolved}' existiert nicht.")
        if not resolved.is_dir():
            raise ValidationError(f"'{resolved}' ist kein Ordner.")

    if resolved == Path("/"):
        raise ValidationError("Das Wurzelverzeichnis '/' ist als Quellordner nicht zulaessig.")

    return resolved


def parse_exclude_patterns(raw: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Zerlegt Ausschlussregeln aus einem mehrzeiligen Text oder einer Liste."""
    lines = raw.splitlines() if isinstance(raw, str) else list(raw)
    return tuple(line.strip() for line in lines if line.strip())


@dataclass(frozen=True, slots=True)
class SyncPair:
    """Ein Sync-Auftrag zwischen einem lokalen Ordner und Proton Drive."""

    uid: str
    name: str
    local_path: Path
    remote_path: str
    enabled: bool = True
    sync_mode: SyncMode = SyncMode.BIDIRECTIONAL
    schedule_kind: ScheduleKind = ScheduleKind.MANUAL
    interval_minutes: int | None = None
    exclude_patterns: tuple[str, ...] = ()
    max_file_size_bytes: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("Der Anzeigename darf nicht leer sein.")
        if self.schedule_kind is ScheduleKind.INTERVAL:
            if self.interval_minutes is None:
                raise ValidationError("Fuer den Zeitplan 'Intervall' fehlt die Angabe in Minuten.")
            if not MIN_INTERVAL_MINUTES <= self.interval_minutes <= MAX_INTERVAL_MINUTES:
                raise ValidationError(
                    f"Das Intervall muss zwischen {MIN_INTERVAL_MINUTES} und "
                    f"{MAX_INTERVAL_MINUTES} Minuten liegen."
                )
        if self.max_file_size_bytes is not None and self.max_file_size_bytes <= 0:
            raise ValidationError("Das Groessenlimit pro Datei muss groesser als 0 sein.")
        if not self.local_path.is_absolute():
            raise ValidationError("Der lokale Quellordner muss ein absoluter Pfad sein.")

    @classmethod
    def create(
        cls,
        *,
        name: str,
        local_path: str | Path,
        remote_path: str,
        enabled: bool = True,
        sync_mode: SyncMode = SyncMode.BIDIRECTIONAL,
        schedule_kind: ScheduleKind = ScheduleKind.MANUAL,
        interval_minutes: int | None = None,
        exclude_patterns: str | list[str] | tuple[str, ...] = (),
        max_file_size_bytes: int | None = None,
        uid: str | None = None,
        must_exist: bool = True,
    ) -> SyncPair:
        """Erzeugt ein validiertes Sync-Paar aus Benutzereingaben."""
        now = datetime.now(tz=UTC)
        return cls(
            uid=uid or str(uuid.uuid4()),
            name=name.strip(),
            local_path=validate_local_path(local_path, must_exist=must_exist),
            remote_path=validate_remote_path(remote_path),
            enabled=enabled,
            sync_mode=sync_mode,
            schedule_kind=schedule_kind,
            interval_minutes=interval_minutes if schedule_kind is ScheduleKind.INTERVAL else None,
            exclude_patterns=parse_exclude_patterns(exclude_patterns),
            max_file_size_bytes=max_file_size_bytes,
            created_at=now,
            updated_at=now,
        )

    def with_changes(self, **changes: object) -> SyncPair:
        """Liefert eine geaenderte Kopie mit aktualisiertem Zeitstempel."""
        changes.setdefault("updated_at", datetime.now(tz=UTC))
        return replace(self, **changes)  # type: ignore[arg-type]

    def remote_path_for(self, relative: PurePosixPath) -> str:
        """Absoluter Proton-Drive-Pfad einer relativen Datei."""
        parts = [part for part in relative.parts if part not in (".", "")]
        if not parts:
            return self.remote_path
        return f"{self.remote_path}/" + "/".join(parts)

    def remote_parent_for(self, relative: PurePosixPath) -> str:
        """Proton-Drive-Elternordner einer relativen Datei.

        Die CLI erwartet bei ``filesystem upload`` einen Elternordner, nicht
        den Zieldateinamen.
        """
        parent = relative.parent
        if str(parent) in (".", ""):
            return self.remote_path
        return f"{self.remote_path}/" + "/".join(parent.parts)

    @property
    def is_scheduled(self) -> bool:
        """Wahr, wenn ein systemd-Timer erzeugt werden soll."""
        return self.enabled and self.schedule_kind is ScheduleKind.INTERVAL

    @property
    def short_uid(self) -> str:
        """Gekuerzte UUID fuer kompakte Anzeigen."""
        return self.uid[:8]


__all__ = [
    "DEFAULT_REMOTE_ROOT",
    "KNOWN_REMOTE_SECTIONS",
    "MAX_INTERVAL_MINUTES",
    "MIN_INTERVAL_MINUTES",
    "UPLOADABLE_REMOTE_SECTIONS",
    "ScheduleKind",
    "SyncMode",
    "SyncPair",
    "ValidationError",
    "name_is_supported",
    "parse_exclude_patterns",
    "sync_mode_label",
    "validate_local_path",
    "validate_remote_path",
]
