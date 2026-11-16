"""Kleine, dateibasierte Einstellungen der Oberflaeche.

Abgelegt als JSON unter ``~/.config/proton-sync-ui/settings.json``. Fehlt die
Datei oder ist sie beschaedigt, gelten die Vorgaben -- die Anwendung startet
in jedem Fall.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths
from .logging_setup import get_logger

log = get_logger("settings")


@dataclass(slots=True)
class Settings:
    """Benutzereinstellungen mit ihren Vorgaben."""

    #: Desktop-Benachrichtigungen bei Fehlern und Konflikten.
    notifications: bool = True
    #: Hoechstens einmal taeglich beim Start nach einer neuen Version sehen.
    auto_update_check: bool = True
    #: Zeitpunkt der letzten automatischen Update-Suche (ISO 8601, UTC).
    last_update_check: str = ""


def settings_path() -> Path:
    """Pfad der Einstellungsdatei."""
    return paths.config_dir() / "settings.json"


def load() -> Settings:
    """Liest die Einstellungen; unbekannte oder falsch getypte Werte werden ignoriert."""
    settings = Settings()
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as error:
        log.warning("Einstellungen nicht lesbar, es gelten die Vorgaben: %s", error)
        return settings
    if not isinstance(raw, dict):
        return settings
    for item in fields(Settings):
        value = raw.get(item.name)
        if isinstance(value, type(getattr(settings, item.name))):
            setattr(settings, item.name, value)
    return settings


def save(settings: Settings) -> None:
    """Schreibt die Einstellungen atomar."""
    target = settings_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(settings), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(target)
    except OSError as error:
        log.warning("Einstellungen konnten nicht gespeichert werden: %s", error)
        with contextlib.suppress(OSError):
            target.with_suffix(".json.tmp").unlink(missing_ok=True)


__all__ = ["Settings", "load", "save", "settings_path"]
