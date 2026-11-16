"""Sprache der Oberflaeche: deutsche Quelltexte mit englischem Katalog.

Der deutsche Text im Code ist zugleich der Schluessel. Dadurch bleibt jede
Aufrufstelle lesbar, und eine fehlende Uebersetzung faellt auf Deutsch
zurueck, statt zu scheitern.

Reihenfolge der Sprachwahl:

1. Umgebungsvariable ``PROTON_SYNC_UI_LANGUAGE`` (Skripte, Testsuite)
2. gespeicherte Wahl in ``settings.json`` (Einstellungen der Anwendung)
3. Sprache der Sitzung: Deutsch bei deutscher Arbeitsflaeche, sonst Englisch

Das Modul ist bewusst eigenstaendig und importiert nichts aus dem Paket --
``paths`` und die Modelle benutzen :func:`tr` selbst.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

from .i18n_en import ENGLISH

LANGUAGES: Final[dict[str, str]] = {"de": "Deutsch", "en": "English"}
ENVIRONMENT_VARIABLE: Final = "PROTON_SYNC_UI_LANGUAGE"

_current: str | None = None


def settings_file() -> Path:
    """Pfad der Einstellungsdatei (ohne Import von ``paths``)."""
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(raw) if raw.startswith("/") else Path.home() / ".config"
    return base / "proton-sync-ui" / "settings.json"


def system_language() -> str:
    """Deutsch fuer eine deutsche Sitzung, Englisch fuer alle anderen."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(variable, "")
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return "de" if value.lower().startswith("de") else "en"
    return "en"


def stored_language(path: Path | None = None) -> str | None:
    """Die in den Einstellungen gewaehlte Sprache oder ``None`` (= automatisch)."""
    try:
        loaded = json.loads((path or settings_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = loaded.get("language") if isinstance(loaded, dict) else None
    return value if value in LANGUAGES else None


def resolve(path: Path | None = None) -> str:
    """Ermittelt die wirksame Sprache."""
    override = os.environ.get(ENVIRONMENT_VARIABLE, "")
    if override in LANGUAGES:
        return override
    return stored_language(path) or system_language()


def init(path: Path | None = None) -> str:
    """Laedt die wirksame Sprache neu und gibt sie zurueck."""
    return set_language(resolve(path))


def set_language(code: str) -> str:
    """Setzt die Sprache fuer diesen Prozess."""
    global _current  # noqa: PLW0603 -- prozessweite Einstellung
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language: {code}")
    _current = code
    return code


def language() -> str:
    """Die aktuell wirksame Sprache (``de`` oder ``en``)."""
    return _current if _current is not None else init()


def tr(text: str) -> str:
    """Uebersetzt einen deutschen Quelltext in die wirksame Sprache."""
    if language() == "de":
        return text
    return ENGLISH.get(text, text)


__all__ = [
    "ENVIRONMENT_VARIABLE",
    "LANGUAGES",
    "init",
    "language",
    "resolve",
    "set_language",
    "settings_file",
    "stored_language",
    "system_language",
    "tr",
]
