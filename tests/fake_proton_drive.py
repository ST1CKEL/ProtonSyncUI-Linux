"""Vollstaendiger Ersatz der Proton-Drive-CLI fuer Tests.

Zwei Varianten:

* :class:`FakeAdapter` -- ersetzt :class:`ProtonDriveAdapter` auf Objektebene.
  Schnell, und protokolliert jeden fachlichen Aufruf.
* :func:`write_fake_cli` -- schreibt ein echtes, ausfuehrbares Skript, das
  sich wie ``proton-drive`` verhaelt. Damit laesst sich der echte
  Prozessstart samt Argumentuebergabe pruefen, ohne Proton zu kontaktieren.

Kein Test ruft jemals die tatsaechliche Proton-Drive-CLI auf.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from proton_sync_ui.cli_adapter.adapter import CommandResult, RemoteNode
from proton_sync_ui.cli_adapter.errors import (
    NotAuthenticatedError,
    ProtonCliError,
    ProtonCliNotFoundError,
    RemotePathExistsError,
    TransientError,
)

FAKE_VERSION = "Proton Drive CLI cli-drive@0.8.0+testbuild\nProton Drive SDK js@0.21.0+testbuild"


@dataclass
class UploadCall:
    """Ein aufgezeichneter Upload."""

    local_path: Path
    remote_parent: str


@dataclass
class DownloadCall:
    """Ein aufgezeichneter Download."""

    remote_path: str
    local_parent: Path


@dataclass
class FolderCall:
    """Ein aufgezeichnetes Anlegen eines Ordners."""

    parent: str
    name: str


@dataclass
class FakeAdapter:
    """Nachbildung von :class:`ProtonDriveAdapter` ohne Prozessstart.

    Verhalten laesst sich ueber die Attribute steuern:

    ``available``        Programm vorhanden?
    ``authenticated``    angemeldet?
    ``upload_errors``    Zuordnung relativer Dateiname -> Fehler (oder Liste
                         von Fehlern fuer aufeinanderfolgende Versuche)
    ``folder_errors``    Zuordnung Ordnerpfad -> Fehler
    """

    available: bool = True
    authenticated: bool = True
    upload_errors: dict[str, BaseException | list[BaseException | None]] = field(
        default_factory=dict
    )
    folder_errors: dict[str, BaseException] = field(default_factory=dict)
    existing_folders: set[str] = field(default_factory=set)
    existing_files: dict[str, int] = field(default_factory=dict)

    uploads: list[UploadCall] = field(default_factory=list)
    downloads: list[DownloadCall] = field(default_factory=list)
    created_folders: list[FolderCall] = field(default_factory=list)
    argv_log: list[tuple[str, ...]] = field(default_factory=list)
    _attempts: dict[str, int] = field(default_factory=dict)

    # -- Schnittstelle des echten Adapters ------------------------------

    def resolve_binary(self) -> str:
        """Wie das Original: Pfad oder Fehler."""
        if not self.available:
            raise ProtonCliNotFoundError("Das Programm 'proton-drive' wurde nicht gefunden.")
        return "/usr/bin/proton-drive-fake"

    @property
    def binary_available(self) -> bool:
        return self.available

    async def version(self) -> str:
        self.resolve_binary()
        return FAKE_VERSION

    async def check_authenticated(self) -> bool:
        self.resolve_binary()
        return self.authenticated

    async def list_dir(self, remote_path: str) -> list[RemoteNode]:
        self.argv_log.append(("filesystem", "list", remote_path, "-j"))
        clean_remote = remote_path.rstrip("/")
        folder_nodes = [
            RemoteNode(path=f"{clean_remote}/{name}", name=name, node_type="folder")
            for name in sorted(
                folder.rsplit("/", 1)[-1]
                for folder in self.existing_folders
                if folder.rsplit("/", 1)[0] == clean_remote
            )
        ]
        file_nodes = [
            RemoteNode(
                path=f"{clean_remote}/{name}",
                name=name,
                node_type="file",
                size_bytes=size,
                modification_time="2026-08-15T12:00:00.000Z",
            )
            for name, size in sorted(
                (filepath.rsplit("/", 1)[-1], size)
                for filepath, size in self.existing_files.items()
                if filepath.rsplit("/", 1)[0] == clean_remote
            )
        ]
        return folder_nodes + file_nodes

    async def exists(self, remote_path: str) -> bool:
        clean = remote_path.rstrip("/")
        return clean in self.existing_folders or clean in self.existing_files

    async def create_folder(self, parent_path: str, name: str) -> bool:
        """Legt einen Ordner an. ``False`` bedeutet: war schon vorhanden."""
        full = f"{parent_path.rstrip('/')}/{name}"
        self.argv_log.append(("filesystem", "create-folder", parent_path, name))

        error = self.folder_errors.get(full)
        if error is not None:
            raise error

        if full in self.existing_folders:
            return False

        self.created_folders.append(FolderCall(parent=parent_path, name=name))
        self.existing_folders.add(full)
        return True

    async def upload_file(self, local_path: Path, remote_parent: str) -> CommandResult:
        """Nimmt einen Upload entgegen oder wirft den konfigurierten Fehler."""
        key = local_path.name
        self.argv_log.append(
            (
                "filesystem",
                "upload",
                "-f",
                "create-new-revision",
                "-d",
                "merge",
                str(local_path),
                remote_parent,
            )
        )

        error = self._next_error(key)
        if error is not None:
            raise error

        full_path = f"{remote_parent.rstrip('/')}/{local_path.name}"
        size = local_path.stat().st_size if local_path.exists() else 0
        self.existing_files[full_path] = size
        self.existing_folders.add(remote_parent.rstrip("/"))

        self.uploads.append(UploadCall(local_path=local_path, remote_parent=remote_parent))
        return CommandResult(
            argv=("filesystem", "upload"),
            returncode=0,
            stdout=f"Uploaded {local_path.name}",
            stderr="",
            duration_seconds=0.01,
        )

    async def download_file(
        self, remote_path: str, local_parent: Path, *, file_strategy: str = "skip"
    ) -> CommandResult:
        self.argv_log.append(
            (
                "filesystem",
                "download",
                "-f",
                file_strategy,
                "-d",
                "merge",
                remote_path,
                str(local_parent),
            )
        )
        name = remote_path.rsplit("/", 1)[-1]
        target = local_parent / name
        # Wie die echte CLI mit "-f skip": eine vorhandene Datei bleibt stehen.
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            size = self.existing_files.get(remote_path.rstrip("/"))
            if size is None:
                target.write_text("downloaded content", encoding="utf-8")
            else:
                target.write_bytes(b"d" * size)
        self.downloads.append(DownloadCall(remote_path=remote_path, local_parent=local_parent))
        return CommandResult(
            argv=("filesystem", "download"),
            returncode=0,
            stdout=f"Downloaded {remote_path}",
            stderr="",
            duration_seconds=0.01,
        )

    # -- Hilfen ----------------------------------------------------------

    def _next_error(self, key: str) -> BaseException | None:
        """Liefert den Fehler fuer den naechsten Versuch dieser Datei."""
        configured = self.upload_errors.get(key)
        if configured is None:
            return None

        attempt = self._attempts.get(key, 0)
        self._attempts[key] = attempt + 1

        if isinstance(configured, list):
            if attempt < len(configured):
                return configured[attempt]
            return None
        return configured

    def attempts_for(self, name: str) -> int:
        """Wie oft eine Datei versucht wurde."""
        return self._attempts.get(name, 0)

    @property
    def uploaded_names(self) -> list[str]:
        """Namen aller tatsaechlich hochgeladenen Dateien."""
        return [call.local_path.name for call in self.uploads]

    def forbidden_calls(self) -> list[tuple[str, ...]]:
        """Alle aufgezeichneten Aufrufe, die entfernte Daten veraendert haetten."""
        forbidden = {"trash", "delete", "empty-trash", "rename", "move", "restore"}
        return [argv for argv in self.argv_log if len(argv) > 1 and argv[1] in forbidden]


def make_transient_error(message: str = "Netzwerkfehler") -> ProtonCliError:
    """Ein wiederholbarer Fehler."""
    return TransientError(message)


def make_permanent_error(message: str = "Kontingent erschoepft") -> ProtonCliError:
    """Ein nicht wiederholbarer Fehler."""
    from proton_sync_ui.cli_adapter.errors import PermanentError

    return PermanentError(message)


def make_auth_error() -> ProtonCliError:
    """Ein Anmeldefehler."""
    return NotAuthenticatedError("Die Proton-Drive-CLI ist nicht angemeldet.")


def make_exists_error(path: str) -> ProtonCliError:
    """Ordner existiert bereits."""
    return RemotePathExistsError(f"already exists: {path}")


# ---------------------------------------------------------------------------
# Echtes Skript
# ---------------------------------------------------------------------------

_FAKE_CLI_SOURCE = '''\
#!/usr/bin/env python3
"""Nachbildung von proton-drive fuer Tests -- kontaktiert niemals Proton."""
import json
import os
import sys

record_path = os.environ.get("FAKE_CLI_RECORD")
if record_path:
    with open(record_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")

args = sys.argv[1:]

if "--version" in args:
    print("Proton Drive CLI cli-drive@0.8.0+testbuild")
    print("Proton Drive SDK js@0.21.0+testbuild")
    sys.exit(0)

# Konfigurierbares Verhalten ueber die Umgebung.
exit_code = int(os.environ.get("FAKE_CLI_EXIT", "0"))
stdout_text = os.environ.get("FAKE_CLI_STDOUT", "")
stderr_text = os.environ.get("FAKE_CLI_STDERR", "")

if args[:2] == ["filesystem", "list"] and not stdout_text:
    stdout_text = json.dumps([{"path": "/my-files"}, {"path": "/devices"}])

if stdout_text:
    print(stdout_text)
if stderr_text:
    print(stderr_text, file=sys.stderr)

sys.exit(exit_code)
'''


def write_fake_cli(directory: Path, *, name: str = "proton-drive") -> Path:
    """Schreibt ein ausfuehrbares Fake-``proton-drive`` und gibt den Pfad zurueck."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text(_FAKE_CLI_SOURCE, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def read_recorded_calls(record_path: Path) -> list[list[str]]:
    """Liest die vom Fake-Skript aufgezeichneten Argumentlisten."""
    if not record_path.exists():
        return []
    calls: list[list[str]] = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            calls.append(json.loads(line)["argv"])
    return calls


def fake_cli_env(record_path: Path, **overrides: str) -> dict[str, str]:
    """Erzeugt die Umgebung fuer das Fake-Skript."""
    env = dict(os.environ)
    env["FAKE_CLI_RECORD"] = str(record_path)
    env.update(overrides)
    return env


SleepRecorder = Callable[[float], None]


def collecting_sleep(collected: list[float]) -> Callable[[float], object]:
    """Ersatz fuer ``asyncio.sleep``, der die Wartezeiten aufzeichnet."""

    async def sleep(delay: float) -> None:
        collected.append(delay)

    return sleep


def argv_contains_shell_metacharacters(argv: Sequence[str]) -> bool:
    """Prueft, ob eine Argumentliste Shell-Sonderzeichen enthaelt.

    Wird von den Tests benutzt, um zu belegen, dass solche Zeichen unveraendert
    durchgereicht werden -- ein Beleg dafuer, dass keine Shell beteiligt ist.
    """
    metacharacters = set(";|&$`><*?()[]{}!\\\"'\n")
    return any(any(char in metacharacters for char in arg) for arg in argv)


__all__ = [
    "FAKE_VERSION",
    "FakeAdapter",
    "FolderCall",
    "UploadCall",
    "argv_contains_shell_metacharacters",
    "collecting_sleep",
    "fake_cli_env",
    "make_auth_error",
    "make_exists_error",
    "make_permanent_error",
    "make_transient_error",
    "read_recorded_calls",
    "write_fake_cli",
]
