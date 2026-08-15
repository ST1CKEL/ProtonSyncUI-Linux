"""Ausfuehrung der Proton-Drive-CLI.

Alle Aufrufe laufen ueber :func:`asyncio.create_subprocess_exec` mit einer
Argumentliste. ``shell=True`` oder ``os.system`` kommen im gesamten Projekt
nicht vor -- damit gibt es keine Shell, die Sonderzeichen in Dateinamen
interpretieren koennte.

Vor jedem Prozessstart prueft :func:`~.commands.assert_command_allowed` die
Argumentliste. Kommandos, die entfernte Daten veraendern oder loeschen
koennten, werden abgelehnt, statt ausgefuehrt zu werden.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ..logging_setup import get_logger, redact
from . import commands
from .errors import (
    CommandTimeoutError,
    NotAuthenticatedError,
    PermanentError,
    ProtonCliError,
    ProtonCliNotFoundError,
    RemotePathExistsError,
    RemotePathNotFoundError,
    TransientError,
)

log = get_logger("cli_adapter.adapter")

#: Zeitlimit fuer kurze Abfragen (list, info, create-folder).
DEFAULT_QUERY_TIMEOUT: Final = 120.0

#: Zeitlimit fuer einen Upload. Grosszuegig, weil grosse Dateien ueber
#: langsame Leitungen lange brauchen duerfen.
DEFAULT_UPLOAD_TIMEOUT: Final = 3600.0

# Textmuster zur Einordnung von Fehlern. Bewusst in Kleinschreibung geprueft.
_AUTH_MARKERS: Final[tuple[str, ...]] = (
    "not logged in",
    "not authenticated",
    "unauthorized",
    "authentication required",
    "please log in",
    "auth login",
    "session expired",
    "invalid session",
    "401",
)

_NOT_FOUND_MARKERS: Final[tuple[str, ...]] = (
    "node not found",
    "not found",
    "no such file",
    "does not exist",
    "enoent",
)

_EXISTS_MARKERS: Final[tuple[str, ...]] = (
    "already exists",
    "name is already taken",
    "duplicate",
    "eexist",
)

_TRANSIENT_MARKERS: Final[tuple[str, ...]] = (
    "network",
    "timeout",
    "timed out",
    "etimedout",
    "econnreset",
    "econnrefused",
    "enotfound",
    "eai_again",
    "socket hang up",
    "rate limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "service unavailable",
    "bad gateway",
    "temporarily",
    "try again",
    "connection",
)

_PERMANENT_MARKERS: Final[tuple[str, ...]] = (
    "quota",
    "insufficient storage",
    "storage full",
    "permission denied",
    "forbidden",
    "403",
    "file too large",
    "invalid name",
    "unsupported",
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Ergebnis eines CLI-Aufrufs. ``stdout``/``stderr`` sind bereits redigiert."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def ok(self) -> bool:
        """Wahr bei Beendigungscode 0."""
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        """stdout und stderr zusammengefasst -- die CLI nutzt beide Kanaele."""
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()


@dataclass(frozen=True, slots=True)
class RemoteNode:
    """Ein Eintrag aus ``filesystem list``."""

    path: str
    name: str = ""
    node_type: str = ""
    size_bytes: int = 0
    modification_time: str = ""
    uid: str = ""
    media_type: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_file(self) -> bool:
        """Wahr, wenn es sich um eine regulaere Datei handelt."""
        return self.node_type == "file"

    @property
    def is_folder(self) -> bool:
        """Wahr, wenn es sich um einen Ordner handelt."""
        return self.node_type == "folder"

    @property
    def is_docs_or_sheet(self) -> bool:
        """Wahr bei Proton Docs oder Sheets (nicht downloadbar)."""
        return self.media_type in ("application/vnd.proton.doc", "application/vnd.proton.sheet")


def classify_error(*, returncode: int, output: str, argv: Sequence[str]) -> ProtonCliError:
    """Ordnet eine fehlgeschlagene Ausfuehrung einer Fehlerklasse zu.

    Unbekannte Fehler gelten als voruebergehend. Ein zusaetzlicher Versuch ist
    billig und unschaedlich -- ``create-new-revision`` ueberschreibt nichts,
    und die CLI ueberspringt inhaltsgleiche Dateien von sich aus.
    """
    haystack = output.lower()
    argv_tuple = tuple(argv)
    message = redact(output.strip()) or f"Die CLI endete mit Code {returncode}."

    def has(markers: tuple[str, ...]) -> bool:
        return any(marker in haystack for marker in markers)

    if has(_AUTH_MARKERS):
        return NotAuthenticatedError(
            "Die Proton-Drive-CLI ist nicht angemeldet. "
            "Bitte einmalig 'proton-drive auth login' im Terminal ausfuehren.",
            argv=argv_tuple,
            stderr=message,
        )
    if has(_EXISTS_MARKERS):
        return RemotePathExistsError(message, argv=argv_tuple, stderr=message)
    if has(_NOT_FOUND_MARKERS):
        return RemotePathNotFoundError(message, argv=argv_tuple, stderr=message)
    if has(_PERMANENT_MARKERS):
        return PermanentError(message, argv=argv_tuple, stderr=message)
    if has(_TRANSIENT_MARKERS):
        return TransientError(message, argv=argv_tuple, stderr=message)
    return TransientError(message, argv=argv_tuple, stderr=message)


class ProtonDriveAdapter:
    """Duenne, sichere Huelle um das Programm ``proton-drive``.

    Die Klasse kennt keine Sync-Logik. Sie startet Prozesse, wertet
    Beendigungscodes aus und uebersetzt Fehlertexte in Ausnahmen.
    """

    def __init__(
        self,
        binary: str | Path | None = None,
        *,
        query_timeout: float = DEFAULT_QUERY_TIMEOUT,
        upload_timeout: float = DEFAULT_UPLOAD_TIMEOUT,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._binary_setting = str(binary) if binary is not None else commands.DEFAULT_BINARY
        self._resolved_binary: str | None = None
        self.query_timeout = query_timeout
        self.upload_timeout = upload_timeout
        self._env_override = dict(env) if env is not None else None

    # ------------------------------------------------------------------
    # Programm und Umgebung
    # ------------------------------------------------------------------

    def resolve_binary(self) -> str:
        """Loest den Programmpfad ueber PATH auf.

        Wirft :class:`ProtonCliNotFoundError` mit einer Meldung, die direkt in
        der Oberflaeche angezeigt werden kann.
        """
        if self._resolved_binary is not None:
            return self._resolved_binary

        candidate = self._binary_setting
        if "/" in candidate:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                self._resolved_binary = str(path)
                return self._resolved_binary
            raise ProtonCliNotFoundError(
                f"Die Proton-Drive-CLI wurde unter '{candidate}' nicht gefunden "
                "oder ist nicht ausfuehrbar."
            )

        found = shutil.which(candidate)
        if found is None:
            raise ProtonCliNotFoundError(
                "Das Programm 'proton-drive' wurde nicht gefunden.\n\n"
                "ProtonSyncUI benoetigt die offizielle Proton-Drive-Kommandozeile. "
                "Bitte installiere sie und stelle sicher, dass sie im PATH liegt "
                "(haeufig ~/.local/bin). Danach einmalig anmelden mit:\n\n"
                "    proton-drive auth login"
            )
        self._resolved_binary = found
        return found

    @property
    def binary_available(self) -> bool:
        """Wahr, wenn das Programm auffindbar ist."""
        try:
            self.resolve_binary()
        except ProtonCliNotFoundError:
            return False
        return True

    def _build_env(self) -> dict[str, str]:
        """Umgebung fuer den Kindprozess.

        Die vorhandene Umgebung wird uebernommen, weil die CLI ``HOME`` und
        die XDG-Variablen fuer ihre eigene Sitzungsablage braucht. Ergaenzt
        werden nur Schalter fuer maschinell auswertbare Ausgaben.
        """
        env = dict(os.environ) if self._env_override is None else dict(self._env_override)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        env.setdefault("CI", "1")
        return env

    # ------------------------------------------------------------------
    # Ausfuehrung
    # ------------------------------------------------------------------

    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        """Fuehrt einen CLI-Aufruf aus und liefert das Ergebnis.

        Wirft nur bei Problemen der Ausfuehrung selbst (Programm fehlt,
        gesperrtes Kommando, Zeitlimit). Ein von Null verschiedener
        Beendigungscode wird *nicht* geworfen, sondern im Ergebnis gemeldet --
        die Einordnung uebernehmen die Aufrufer.
        """
        commands.assert_command_allowed(argv)
        binary = self.resolve_binary()
        full_argv = (binary, *argv)
        limit = timeout if timeout is not None else self.query_timeout

        log.debug("Starte CLI: %s", " ".join(argv))
        started = time.monotonic()

        process = await asyncio.create_subprocess_exec(
            *full_argv,
            stdin=asyncio.subprocess.DEVNULL,  # niemals interaktiv nachfragen
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(),
            cwd=str(cwd) if cwd is not None else None,
        )

        try:
            raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=limit)
        except TimeoutError:
            await self._terminate(process)
            raise CommandTimeoutError(
                f"Der CLI-Aufruf hat das Zeitlimit von {limit:.0f} Sekunden ueberschritten "
                "und wurde beendet.",
                argv=tuple(argv),
            ) from None
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        duration = time.monotonic() - started
        result = CommandResult(
            argv=tuple(argv),
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=redact(raw_out.decode("utf-8", errors="replace").strip(), max_length=None),
            stderr=redact(raw_err.decode("utf-8", errors="replace").strip(), max_length=None),
            duration_seconds=duration,
        )
        log.debug("CLI beendet: Code %d nach %.2fs", result.returncode, duration)
        return result

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        """Beendet einen Kindprozess zuverlaessig."""
        if process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except (TimeoutError, ProcessLookupError):
            with contextlib.suppress(ProcessLookupError):
                process.kill()
                await process.wait()

    async def run_checked(
        self, argv: Sequence[str], *, timeout: float | None = None
    ) -> CommandResult:
        """Wie :meth:`run`, wirft aber bei einem Fehlercode eine passende Ausnahme."""
        result = await self.run(argv, timeout=timeout)
        if not result.ok:
            raise classify_error(
                returncode=result.returncode,
                output=result.combined_output,
                argv=result.argv,
            )
        return result

    # ------------------------------------------------------------------
    # Fachliche Aufrufe
    # ------------------------------------------------------------------

    async def version(self) -> str:
        """Rohe Versionsausgabe der CLI."""
        result = await self.run(commands.version_args(), timeout=30.0)
        if not result.ok:
            raise classify_error(
                returncode=result.returncode, output=result.combined_output, argv=result.argv
            )
        return result.combined_output

    async def check_authenticated(self) -> bool:
        """Prueft den Anmeldezustand ueber einen billigen, lesenden Aufruf.

        Es werden keine Zugangsdaten gelesen oder gespeichert -- nur der
        Beendigungscode wird ausgewertet.
        """
        result = await self.run(commands.auth_probe_args(), timeout=self.query_timeout)
        if result.ok:
            return True
        error = classify_error(
            returncode=result.returncode, output=result.combined_output, argv=result.argv
        )
        if isinstance(error, NotAuthenticatedError):
            return False
        raise error

    async def list_dir(self, remote_path: str) -> list[RemoteNode]:
        """Listet den Inhalt eines entfernten Ordners."""
        result = await self.run(commands.list_args(remote_path), timeout=self.query_timeout)
        if not result.ok:
            raise classify_error(
                returncode=result.returncode, output=result.combined_output, argv=result.argv
            )
        return _parse_nodes(result.stdout, remote_parent=remote_path)

    async def exists(self, remote_path: str) -> bool:
        """Prueft, ob ein entfernter Pfad existiert."""
        result = await self.run(commands.info_args(remote_path), timeout=self.query_timeout)
        if result.ok:
            return True
        error = classify_error(
            returncode=result.returncode, output=result.combined_output, argv=result.argv
        )
        if isinstance(error, RemotePathNotFoundError):
            return False
        raise error

    async def create_folder(self, parent_path: str, name: str) -> bool:
        """Legt einen entfernten Ordner an.

        Liefert ``True``, wenn der Ordner neu angelegt wurde, und ``False``,
        wenn er bereits vorhanden war. Ein bestehender Ordner ist kein Fehler.
        """
        result = await self.run(
            commands.create_folder_args(parent_path, name), timeout=self.query_timeout
        )
        if result.ok:
            return True
        error = classify_error(
            returncode=result.returncode, output=result.combined_output, argv=result.argv
        )
        if isinstance(error, RemotePathExistsError):
            return False
        raise error

    async def upload_file(self, local_path: Path, remote_parent: str) -> CommandResult:
        """Laedt genau eine Datei in einen entfernten Ordner hoch.

        Bewusst eine Datei pro Aufruf: so laesst sich jeder Fehler genau einer
        Datei zuordnen, und der Fortschritt bleibt feingranular. Bestehende
        entfernte Dateien werden als neue Revision fortgeschrieben, niemals
        ersetzt oder geloescht.
        """
        argv = commands.upload_args([local_path], remote_parent)
        result = await self.run(argv, timeout=self.upload_timeout)
        if not result.ok:
            raise classify_error(
                returncode=result.returncode, output=result.combined_output, argv=result.argv
            )
        return result

    async def download_file(
        self, remote_path: str, local_parent: Path, *, file_strategy: str = "skip"
    ) -> CommandResult:
        """Laedt genau eine Datei aus Proton Drive in einen lokalen Ordner herunter."""
        argv = commands.download_args([remote_path], local_parent, file_strategy=file_strategy)
        result = await self.run(argv, timeout=self.upload_timeout)
        if not result.ok:
            raise classify_error(
                returncode=result.returncode, output=result.combined_output, argv=result.argv
            )
        return result


def _parse_nodes(stdout: str, remote_parent: str = "") -> list[RemoteNode]:
    """Wertet die JSON-Ausgabe von ``filesystem list`` aus.

    Die CLI liefert ein JSON-Array von Objekten, die Metadaten wie Name,
    Typ, Groesse und Aenderungszeitpunkt enthalten.
    """
    text = stdout.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Aeltere oder abweichende Fassungen geben eine Zeile je Pfad aus.
        return [
            RemoteNode(path=line.strip(), name=line.strip().rsplit("/", 1)[-1])
            for line in text.splitlines()
            if line.strip().startswith("/")
        ]

    if isinstance(payload, dict):
        payload = payload.get("nodes", payload.get("items", []))
    if not isinstance(payload, list):
        return []

    nodes: list[RemoteNode] = []
    for entry in payload:
        if isinstance(entry, str):
            name = entry.rsplit("/", 1)[-1]
            path = entry if entry.startswith("/") else f"{remote_parent.rstrip('/')}/{name}"
            nodes.append(RemoteNode(path=path, name=name))
            continue
        if not isinstance(entry, dict):
            continue

        name_val = entry.get("name")
        name = str(name_val.get("value", "")) if isinstance(name_val, dict) else str(name_val or "")

        path_val = entry.get("path")
        if path_val:
            path = str(path_val)
        elif remote_parent and name:
            path = f"{remote_parent.rstrip('/')}/{name}"
        else:
            path = name

        node_type = str(entry.get("type", entry.get("nodeType", "")))
        uid = str(entry.get("uid", ""))
        media_type = str(entry.get("mediaType", ""))

        # Groesse ermitteln (entweder direct oder aus activeRevision)
        size = int(entry.get("totalStorageSize") or entry.get("size") or 0)
        active_rev = entry.get("activeRevision")
        if isinstance(active_rev, dict):
            rev_size = active_rev.get("claimedSize") or active_rev.get("storageSize")
            if rev_size is not None:
                size = int(rev_size)
            mtime = str(
                active_rev.get("claimedModificationTime") or entry.get("modificationTime") or ""
            )
        else:
            mtime = str(entry.get("modificationTime") or "")

        nodes.append(
            RemoteNode(
                path=path,
                name=name,
                node_type=node_type,
                size_bytes=size,
                modification_time=mtime,
                uid=uid,
                media_type=media_type,
                raw=entry,
            )
        )
    return nodes


__all__ = [
    "DEFAULT_QUERY_TIMEOUT",
    "DEFAULT_UPLOAD_TIMEOUT",
    "CommandResult",
    "ProtonDriveAdapter",
    "RemoteNode",
    "classify_error",
]
