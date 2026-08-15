"""Strukturiertes Logging mit Rotation.

Grundsatz: In den Logs stehen niemals Zugangsdaten, Tokens oder rohe
CLI-Ausgaben, die solche Daten enthalten koennten. Ausgaben der Proton-CLI
werden vor dem Schreiben durch :func:`redact` geleitet.

Dateipfade *duerfen* in den Logs stehen -- das ist fuer die Fehlersuche
notwendig und im README ausdruecklich dokumentiert.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from . import paths

LOG_MAX_BYTES: Final = 2 * 1024 * 1024
LOG_BACKUP_COUNT: Final = 5
_CONFIGURED = False

# Muster, deren Treffer vollstaendig ersetzt werden. Bewusst grosszuegig:
# lieber eine harmlose Zeile schwaerzen als ein Geheimnis durchlassen.
_REDACTION_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # key=value / key: value fuer verdaechtige Schluesselnamen
    (
        re.compile(
            r"(?i)\b(pass(?:word|phrase)?|secret|token|api[_-]?key|auth|bearer"
            r"|cookie|session|credential|refresh[_-]?token|access[_-]?token"
            r"|private[_-]?key|mailbox[_-]?password|totp|2fa|otp)\b"
            r"\s*[:=]\s*\S+"
        ),
        r"\1=<redigiert>",
    ),
    # HTTP-Authorization-Header
    (re.compile(r"(?i)\bauthorization\s*:\s*\S+"), "authorization: <redigiert>"),
    # JWT-artige Zeichenketten
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"), "<redigiert:jwt>"),
    # PEM-Bloecke
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "<redigiert:key>",
    ),
    # Lange hexadezimale oder base64-artige Blobs (>= 40 Zeichen)
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "<redigiert:blob>"),
)

_MAX_CAPTURED_OUTPUT: Final = 2000


def redact(text: str, *, max_length: int | None = _MAX_CAPTURED_OUTPUT) -> str:
    """Entfernt potenziell sensible Bestandteile aus einem Text.

    Wird auf jede CLI-Ausgabe angewandt, bevor sie geloggt oder in der
    Oberflaeche angezeigt wird.
    """
    if not text:
        return text
    cleaned = text
    for pattern, replacement in _REDACTION_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    if max_length is not None and len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + f"… [{len(cleaned)} Zeichen gekuerzt]"
    return cleaned


class JsonLineFormatter(logging.Formatter):
    """Formatiert jeden Eintrag als eine JSON-Zeile.

    Maschinenlesbar fuer die Logansicht der Oberflaeche und trotzdem mit
    ``journalctl``/``less`` brauchbar.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage(), max_length=_MAX_CAPTURED_OUTPUT),
        }
        for key in ("pair_uid", "run_id", "relative_path", "action", "attempt"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(
                self.formatException(record.exc_info), max_length=_MAX_CAPTURED_OUTPUT
            )
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Kompakte, menschenlesbare Ausgabe fuer Terminal und journalctl."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created, tz=UTC).astimezone().strftime("%H:%M:%S")
        message = redact(record.getMessage(), max_length=_MAX_CAPTURED_OUTPUT)
        prefix = f"{stamp} {record.levelname:<7}"
        pair_uid = getattr(record, "pair_uid", None)
        if pair_uid:
            prefix = f"{prefix} [{str(pair_uid)[:8]}]"
        text = f"{prefix} {message}"
        if record.exc_info:
            exc_text = redact(
                self.formatException(record.exc_info), max_length=_MAX_CAPTURED_OUTPUT
            )
            text = f"{text}\n{exc_text}"
        return text


def configure_logging(
    *,
    level: int = logging.INFO,
    console: bool = True,
    log_path: Path | None = None,
) -> Path:
    """Richtet Datei- und Konsolen-Logging ein. Mehrfachaufrufe sind unschaedlich.

    Gibt den Pfad der aktiven Logdatei zurueck.
    """
    global _CONFIGURED  # noqa: PLW0603 -- bewusst prozessweiter Einmal-Zustand

    target = log_path if log_path is not None else paths.log_file()
    if _CONFIGURED:
        return target

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    root = logging.getLogger("proton_sync_ui")
    root.setLevel(level)
    root.propagate = False

    file_handler = logging.handlers.RotatingFileHandler(
        target,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonLineFormatter())
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    # Logdatei kann Dateipfade enthalten -> nur fuer den Besitzer lesbar.
    target.chmod(0o600)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(ConsoleFormatter())
        stream_handler.setLevel(level)
        root.addHandler(stream_handler)

    _CONFIGURED = True
    return target


def get_logger(name: str) -> logging.Logger:
    """Liefert einen Logger unterhalb des Anwendungs-Namensraums."""
    return logging.getLogger(f"proton_sync_ui.{name}")


def read_log_entries(
    *,
    log_path: Path | None = None,
    limit: int = 500,
    levels: frozenset[str] | None = None,
    pair_uid: str | None = None,
) -> list[dict[str, Any]]:
    """Liest die letzten Logeintraege fuer die Logansicht.

    Nicht parsbare Zeilen werden uebersprungen, damit eine beschaedigte Zeile
    die Ansicht nicht unbrauchbar macht.
    """
    target = log_path if log_path is not None else paths.log_file()
    if not target.exists():
        return []

    entries: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:  # noqa: S112 -- s. u.
                # Eine beschaedigte Zeile (etwa durch einen Absturz mitten im
                # Schreiben) darf die Ansicht nicht unbrauchbar machen. Hier zu
                # protokollieren waere unsinnig: wir lesen gerade das Protokoll.
                continue
            if not isinstance(entry, dict):
                continue
            if levels is not None and entry.get("level") not in levels:
                continue
            if pair_uid is not None and entry.get("pair_uid") != pair_uid:
                continue
            entries.append(entry)

    return entries[-limit:]


__all__ = [
    "ConsoleFormatter",
    "JsonLineFormatter",
    "configure_logging",
    "get_logger",
    "read_log_entries",
    "redact",
]
