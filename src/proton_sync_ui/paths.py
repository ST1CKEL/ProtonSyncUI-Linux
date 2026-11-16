"""XDG-konforme Pfade.

Alle Funktionen lesen die Umgebungsvariablen bei jedem Aufruf neu aus. Das ist
Absicht: Tests setzen ``XDG_*`` auf ein temporaeres Verzeichnis, und ein beim
Import zwischengespeicherter Pfad wuerde diese Isolation aushebeln.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import APP_NAME
from .i18n import tr


def _xdg_dir(env_var: str, default_relative: str) -> Path:
    """Liest ein XDG-Basisverzeichnis aus der Umgebung.

    Laut XDG-Spezifikation werden relative Pfade in den Variablen ignoriert;
    in dem Fall gilt der Standardwert.
    """
    raw = os.environ.get(env_var, "").strip()
    return Path(raw) if raw and raw.startswith("/") else Path.home() / default_relative


def config_dir() -> Path:
    """~/.config/proton-sync-ui/ -- Konfiguration."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_NAME


def data_dir() -> Path:
    """~/.local/share/proton-sync-ui/ -- Datenbank."""
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / APP_NAME


def state_dir() -> Path:
    """~/.local/state/proton-sync-ui/ -- Logs und Laufzeitzustand."""
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_NAME


def database_path() -> Path:
    """Pfad der SQLite-Datenbank."""
    return data_dir() / "sync.db"


def log_dir() -> Path:
    """Verzeichnis der rotierenden Logdateien."""
    return state_dir() / "logs"


def log_file() -> Path:
    """Aktuelle Logdatei."""
    return log_dir() / "proton-sync-ui.log"


def systemd_user_dir() -> Path:
    """~/.config/systemd/user/ -- Ablage der systemd-Units des Benutzers."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / "systemd" / "user"


def ensure_directories() -> None:
    """Legt alle benoetigten Verzeichnisse an.

    Konfiguration und Zustand koennen Dateipfade des Benutzers enthalten und
    werden daher nur fuer den Besitzer lesbar angelegt (0700).
    """
    for directory in (config_dir(), data_dir(), state_dir(), log_dir()):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def format_size(num_bytes: int) -> str:
    """Formatiert eine Byte-Anzahl kompakt."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def format_timestamp(value: datetime | None) -> str:
    """Formatiert einen Zeitstempel in lokaler Zeit."""
    if value is None:
        return tr("nie")
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def log_file_path() -> Path:
    """Alias fuer log_file()."""
    return log_file()


def find_gui_executable() -> str:
    """Ermittelt den absoluten Pfad der GUI-Kommandozeile (proton-sync-ui-gui).

    Fuer Desktop-Autostart und systemd muss zwingend ein absoluter Pfad verwendet
    werden, da systemd-xdg-autostart-generator und Login-Sessions ohne die
    PATH-Erweiterungen interaktiver Shells arbeiten.
    """
    local_bin = Path.home() / ".local" / "bin" / "proton-sync-ui-gui"
    if local_bin.is_file():
        return str(local_bin)

    found = shutil.which("proton-sync-ui-gui")
    if found and Path(found).is_absolute():
        return found

    candidate = Path(sys.executable).parent / "proton-sync-ui-gui"
    if candidate.is_file():
        return str(candidate)

    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    venv_candidate = data_home / "proton-sync-ui" / "venv" / "bin" / "proton-sync-ui-gui"
    if venv_candidate.is_file():
        return str(venv_candidate)

    return f"{sys.executable} -m proton_sync_ui.ui.application"


def find_cli_executable() -> str:
    """Ermittelt den absoluten Pfad der CLI-Kommandozeile (proton-sync-ui)."""
    local_bin = Path.home() / ".local" / "bin" / "proton-sync-ui"
    if local_bin.is_file():
        return str(local_bin)

    found = shutil.which("proton-sync-ui")
    if found and Path(found).is_absolute():
        return found

    candidate = Path(sys.executable).parent / "proton-sync-ui"
    if candidate.is_file():
        return str(candidate)

    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    venv_candidate = data_home / "proton-sync-ui" / "venv" / "bin" / "proton-sync-ui"
    if venv_candidate.is_file():
        return str(venv_candidate)

    return f"{sys.executable} -m proton_sync_ui"


__all__ = [
    "config_dir",
    "data_dir",
    "database_path",
    "ensure_directories",
    "find_cli_executable",
    "find_gui_executable",
    "format_size",
    "format_timestamp",
    "log_dir",
    "log_file",
    "log_file_path",
    "state_dir",
    "systemd_user_dir",
]
