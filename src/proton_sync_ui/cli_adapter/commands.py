"""Aufbau der Argumentlisten fuer die Proton-Drive-CLI.

===========================================================================
=== ANPASSUNGSPUNKT BEI CLI-AENDERUNGEN ===================================
===========================================================================

Dies ist die einzige Datei des Projekts, die die konkrete Syntax von
``proton-drive`` kennt. Aendert Proton die Kommandozeile, genuegt es, die
Funktionen hier anzupassen -- Sync-Logik, Speicher und Oberflaeche bleiben
unveraendert.

Die Funktionen bauen ausschliesslich Argumentlisten und starten selbst
niemals einen Prozess. Dadurch sind sie ohne jedes Mocking testbar
(siehe ``tests/test_cli_adapter.py``).

---------------------------------------------------------------------------
Gepruefte Grundlage
---------------------------------------------------------------------------
Ermittelt mit ``proton-drive --help``, ``proton-drive filesystem upload
--help`` und ``proton-drive auth --help`` gegen::

    Proton Drive CLI  cli-drive@0.8.0+06e8c605
    Proton Drive SDK  js@0.21.0+06e8c605

Belegte Syntax::

    filesystem list [-t TYPE] path
    filesystem info path
    filesystem create-folder parentPath name
    filesystem upload [-f STRATEGY] [-d STRATEGY] [-t] localPath... parentPath
    auth login
    auth logout

Weitere gepruefte Eigenschaften:

* Beendigungscode 0 bei Erfolg, 1 bei Fehler.
* ``-j/--json`` wirkt nur *nach* dem Unterkommando
  (``filesystem list / -j`` funktioniert, ``-j filesystem list /`` nicht).
* Entfernte Pfade sind immer POSIX-Pfade; die Wurzel heisst ``/my-files``.
* Es gibt **kein** ``auth status``. Der Anmeldezustand laesst sich nur
  indirekt ueber einen lesenden Aufruf ermitteln (siehe
  :func:`auth_probe_args`).
* ``filesystem upload`` erwartet als letztes Argument einen *Elternordner*,
  nicht den Zieldateinamen. Der entfernte Name folgt dem lokalen Dateinamen.

Sollte eine kuenftige CLI-Fassung abweichen, sind ausschliesslich die
folgenden Funktionen zu aendern -- und :data:`ALLOWED_COMMANDS` entsprechend
mitzupflegen.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final

from .errors import ForbiddenCommandError

#: Standardname des Programms. Wird ueber PATH aufgeloest.
DEFAULT_BINARY: Final = "proton-drive"

# ---------------------------------------------------------------------------
# Konfliktstrategien
# ---------------------------------------------------------------------------

#: Strategie fuer Dateien. ``create-new-revision`` legt eine neue Fassung der
#: bestehenden Datei an und erhaelt damit die Versionshistorie bei Proton
#: Drive. Bewusst NICHT ``replace``: das wuerde die entfernte Datei in den
#: Papierkorb verschieben und widerspraeche der Zusage, niemals entfernte
#: Daten zu loeschen.
FILE_CONFLICT_STRATEGY: Final = "create-new-revision"

#: Strategie fuer Ordner. ``merge`` fuegt Inhalte zusammen, ohne Bestehendes
#: zu entfernen.
FOLDER_CONFLICT_STRATEGY: Final = "merge"

#: Strategien, die entfernte Daten in den Papierkorb verschieben wuerden.
#: Diese Anwendung erzeugt sie unter keinen Umstaenden.
FORBIDDEN_STRATEGIES: Final[frozenset[str]] = frozenset({"replace"})

#: Von der CLI unterstuetzte Dateistrategien (aus ``upload --help``).
KNOWN_FILE_STRATEGIES: Final[frozenset[str]] = frozenset(
    {"create-new-revision", "rename", "replace", "skip"}
)

#: Von der CLI unterstuetzte Ordnerstrategien (aus ``upload --help``).
KNOWN_FOLDER_STRATEGIES: Final[frozenset[str]] = frozenset({"merge", "rename", "replace", "skip"})

# ---------------------------------------------------------------------------
# Sicherheitsgrenzen
# ---------------------------------------------------------------------------

#: Erlaubte Kommandos als (Gruppe, Verb). Alles, was hier nicht steht, wird
#: vom Adapter abgelehnt, bevor ein Prozess startet. Eine Positivliste ist
#: der Negativliste vorzuziehen: neu hinzukommende CLI-Verben sind damit
#: automatisch gesperrt, statt versehentlich erlaubt zu sein.
ALLOWED_COMMANDS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("filesystem", "list"),
        ("filesystem", "info"),
        ("filesystem", "create-folder"),
        ("filesystem", "upload"),
        ("filesystem", "download"),
    }
)

#: Zweite Verteidigungslinie. Diese Verben veraendern oder loeschen entfernte
#: Daten und duerfen niemals in einer Argumentliste auftauchen -- auch dann
#: nicht, wenn jemand spaeter :data:`ALLOWED_COMMANDS` erweitert.
FORBIDDEN_VERBS: Final[frozenset[str]] = frozenset(
    {
        "trash",
        "delete",
        "empty-trash",
        "rename",
        "move",
        "restore",
        "logout",
        "leave",
        "remove",
        "remove-url",
        "remove-photo",
    }
)

#: Kommandogruppen, die diese Anwendung nie verwendet.
FORBIDDEN_GROUPS: Final[frozenset[str]] = frozenset({"sharing", "album", "invitation", "photo"})


def assert_command_allowed(argv: Sequence[str]) -> None:
    """Prueft eine fertige Argumentliste gegen die Sicherheitsgrenzen.

    Wird vom Adapter unmittelbar vor jedem Prozessstart aufgerufen. Bei einem
    Verstoss fliegt :class:`ForbiddenCommandError`, und es wird kein Prozess
    gestartet.

    Erwartet die Liste *ohne* den Programmnamen, also z. B.
    ``["filesystem", "upload", ...]``.
    """
    args = list(argv)
    if not args:
        raise ForbiddenCommandError("Leere Argumentliste ist nicht zulaessig.")

    # Reine Options-Aufrufe wie --version sind unkritisch.
    if all(arg.startswith("-") for arg in args):
        return

    positional = [arg for arg in args if not arg.startswith("-")]
    group = args[0]

    if group in FORBIDDEN_GROUPS:
        raise ForbiddenCommandError(
            f"Die Kommandogruppe '{group}' ist in ProtonSyncUI gesperrt.",
            argv=tuple(args),
        )

    if len(positional) < 2:
        raise ForbiddenCommandError(
            f"Unvollstaendiges Kommando: {' '.join(args[:2])}", argv=tuple(args)
        )

    verb = positional[1]

    if verb in FORBIDDEN_VERBS:
        raise ForbiddenCommandError(
            f"Das Kommando '{group} {verb}' veraendert oder loescht entfernte Daten "
            "und ist in ProtonSyncUI dauerhaft gesperrt.",
            argv=tuple(args),
        )

    if (group, verb) not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(f"{grp} {vrb}" for grp, vrb in ALLOWED_COMMANDS))
        raise ForbiddenCommandError(
            f"Das Kommando '{group} {verb}' ist nicht freigegeben. Erlaubt sind: {allowed}.",
            argv=tuple(args),
        )

    # Verbotene Konfliktstrategien -- unabhaengig davon, ueber welches Flag
    # sie hereinkaemen.
    for index, arg in enumerate(args):
        if arg in ("-f", "--file-conflict-strategy", "-d", "--folder-conflict-strategy"):
            value = args[index + 1] if index + 1 < len(args) else ""
            if value in FORBIDDEN_STRATEGIES:
                raise ForbiddenCommandError(
                    f"Die Konfliktstrategie '{value}' wuerde entfernte Daten in den "
                    "Papierkorb verschieben und ist gesperrt.",
                    argv=tuple(args),
                )


def _check_remote_path(path: str) -> str:
    """Stellt sicher, dass ein entfernter Pfad an die CLI uebergeben werden darf."""
    if not path.startswith("/"):
        raise ValueError(f"Entfernte Pfade muessen absolut sein: {path!r}")
    if "\0" in path:
        raise ValueError("Entfernte Pfade duerfen keine Nullbytes enthalten.")
    return path


def _check_local_path(path: Path) -> str:
    """Stellt sicher, dass ein lokaler Pfad sicher uebergeben werden kann.

    Nur absolute Pfade sind zulaessig. Das ist nicht nur sauber, sondern
    verhindert zugleich, dass ein Dateiname mit fuehrendem Bindestrich als
    Option missverstanden wird -- ein ``--``-Trenner ist in der CLI nicht
    dokumentiert.
    """
    if not path.is_absolute():
        raise ValueError(f"Lokale Pfade muessen absolut sein: {path!r}")
    text = str(path)
    if "\0" in text:
        raise ValueError("Lokale Pfade duerfen keine Nullbytes enthalten.")
    return text


# ---------------------------------------------------------------------------
# Kommando-Erzeugung
# ---------------------------------------------------------------------------


def version_args() -> list[str]:
    """``proton-drive --version``."""
    return ["--version"]


def auth_probe_args() -> list[str]:
    """Lesender Aufruf zur Ermittlung des Anmeldezustands.

    Die CLI hat kein ``auth status``. ``filesystem list /`` listet lediglich
    die statischen Bereichsnamen, ist damit billig und gibt keine privaten
    Inhalte preis. Beendigungscode 0 bedeutet angemeldet.
    """
    return ["filesystem", "list", "/", "-j"]


def list_args(
    remote_path: str, *, as_json: bool = True, type_filter: str | None = None
) -> list[str]:
    """``filesystem list [-t TYPE] path [-j]``.

    ``-j`` muss hinter dem Unterkommando stehen (geprueft, siehe Kopf).
    """
    args = ["filesystem", "list"]
    if type_filter is not None:
        if type_filter not in ("file", "folder", "album", "photo"):
            raise ValueError(f"Unbekannter Typfilter: {type_filter!r}")
        args += ["-t", type_filter]
    args.append(_check_remote_path(remote_path))
    if as_json:
        args.append("-j")
    return args


def info_args(remote_path: str, *, as_json: bool = True) -> list[str]:
    """``filesystem info path [-j]``."""
    args = ["filesystem", "info", _check_remote_path(remote_path)]
    if as_json:
        args.append("-j")
    return args


def create_folder_args(parent_path: str, name: str) -> list[str]:
    """``filesystem create-folder parentPath name``."""
    if not name or "/" in name or name in (".", ".."):
        raise ValueError(f"Ungueltiger Ordnername: {name!r}")
    return ["filesystem", "create-folder", _check_remote_path(parent_path), name]


def upload_args(
    local_paths: Sequence[Path],
    remote_parent: str,
    *,
    file_strategy: str = FILE_CONFLICT_STRATEGY,
    folder_strategy: str = FOLDER_CONFLICT_STRATEGY,
    skip_thumbnails: bool = False,
) -> list[str]:
    """``filesystem upload [-f STRATEGY] [-d STRATEGY] [-t] localPath... parentPath``.

    Die Konfliktstrategien sind vorbelegt und duerfen nie ``replace`` sein.
    Der Zielparameter ist der *Elternordner*; den entfernten Dateinamen
    bestimmt die CLI aus dem lokalen Dateinamen.
    """
    if not local_paths:
        raise ValueError("Es wurde keine hochzuladende Datei angegeben.")
    if file_strategy in FORBIDDEN_STRATEGIES or folder_strategy in FORBIDDEN_STRATEGIES:
        raise ForbiddenCommandError(
            f"Die Konfliktstrategie '{file_strategy}/{folder_strategy}' ist gesperrt, "
            "weil sie entfernte Daten in den Papierkorb verschieben wuerde."
        )
    if file_strategy not in KNOWN_FILE_STRATEGIES:
        raise ValueError(f"Unbekannte Dateistrategie: {file_strategy!r}")
    if folder_strategy not in KNOWN_FOLDER_STRATEGIES:
        raise ValueError(f"Unbekannte Ordnerstrategie: {folder_strategy!r}")

    args = [
        "filesystem",
        "upload",
        "-f",
        file_strategy,
        "-d",
        folder_strategy,
    ]
    if skip_thumbnails:
        args.append("-t")
    args += [_check_local_path(path) for path in local_paths]
    args.append(_check_remote_path(remote_parent))
    return args


def download_args(
    remote_paths: Sequence[str],
    local_folder: Path,
    *,
    file_strategy: str = "skip",
    folder_strategy: str = "merge",
) -> list[str]:
    """``filesystem download [-f STRATEGY] [-d STRATEGY] path... localFolder``."""
    if not remote_paths:
        raise ValueError("Es wurde kein entfernter Pfad fuer den Download angegeben.")
    args = [
        "filesystem",
        "download",
        "-f",
        file_strategy,
        "-d",
        folder_strategy,
    ]
    args += [_check_remote_path(p) for p in remote_paths]
    args.append(_check_local_path(local_folder))
    return args


def remote_join(parent: str, *parts: str) -> str:
    """Setzt einen entfernten Pfad aus Bestandteilen zusammen."""
    cleaned = [part.strip("/") for part in parts if part.strip("/")]
    if not cleaned:
        return parent
    return parent.rstrip("/") + "/" + "/".join(cleaned)


def remote_parent_and_name(remote_path: str) -> tuple[str, str]:
    """Zerlegt einen entfernten Pfad in Elternordner und Namen."""
    pure = PurePosixPath(remote_path)
    return str(pure.parent), pure.name


__all__ = [
    "ALLOWED_COMMANDS",
    "DEFAULT_BINARY",
    "FILE_CONFLICT_STRATEGY",
    "FOLDER_CONFLICT_STRATEGY",
    "FORBIDDEN_GROUPS",
    "FORBIDDEN_STRATEGIES",
    "FORBIDDEN_VERBS",
    "KNOWN_FILE_STRATEGIES",
    "KNOWN_FOLDER_STRATEGIES",
    "assert_command_allowed",
    "auth_probe_args",
    "create_folder_args",
    "download_args",
    "info_args",
    "list_args",
    "remote_join",
    "remote_parent_and_name",
    "upload_args",
    "version_args",
]
