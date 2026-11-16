"""Autostart bei der Anmeldung (XDG-Autostart).

Der Eintrag liegt unter ``~/.config/autostart/`` und wird von KDE Plasma,
GNOME und allen anderen XDG-konformen Arbeitsflaechen ausgewertet -- auf
aktuellen Fedora-Versionen ueber ``systemd-xdg-autostart-generator``.

``Exec`` enthaelt immer einen absoluten Pfad: Die Sitzung startet Autostart-
Programme ohne die PATH-Erweiterungen einer Login-Shell.
"""

from __future__ import annotations

from pathlib import Path

from . import APP_ID, APP_TITLE
from .paths import _xdg_dir, find_gui_executable


def autostart_file() -> Path:
    """Pfad des Autostart-Eintrags."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / "autostart" / f"{APP_ID}.desktop"


def is_enabled() -> bool:
    """Wahr, wenn ein (nicht versteckter) Autostart-Eintrag existiert."""
    try:
        content = autostart_file().read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "Hidden=true" not in content


def is_minimized() -> bool:
    """Wahr, wenn der Eintrag minimiert startet (Vorgabe ohne Eintrag: ja)."""
    try:
        content = autostart_file().read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    return "--minimized" in content or "--hidden" in content


def desktop_entry_text(*, minimized: bool, executable: str | None = None) -> str:
    """Inhalt des Autostart-Eintrags."""
    command = executable if executable is not None else find_gui_executable()
    if minimized:
        command += " --minimized"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.5\n"
        f"Name={APP_TITLE}\n"
        "Comment=Proton-Drive-Synchronisation im Hintergrund\n"
        f"Exec={command}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        # Das Symbol im Infobereich braucht die Kontrollleiste.
        "X-KDE-autostart-after=panel\n"
        "X-GNOME-Autostart-Delay=5\n"
    )


def enable(*, minimized: bool = True, executable: str | None = None) -> Path:
    """Schreibt den Autostart-Eintrag und liefert dessen Pfad."""
    target = autostart_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        desktop_entry_text(minimized=minimized, executable=executable), encoding="utf-8"
    )
    return target


def disable() -> bool:
    """Entfernt den Autostart-Eintrag. ``False``, wenn keiner vorhanden war."""
    target = autostart_file()
    if not target.exists():
        return False
    target.unlink()
    return True


def refresh() -> bool:
    """Schreibt einen bestehenden Eintrag neu (aktueller Programmpfad).

    Wird nach Installation und Update aufgerufen. Gibt ``False`` zurueck, wenn
    der Autostart nicht eingerichtet ist.
    """
    if not is_enabled():
        return False
    enable(minimized=is_minimized())
    return True


__all__ = [
    "autostart_file",
    "desktop_entry_text",
    "disable",
    "enable",
    "is_enabled",
    "is_minimized",
    "refresh",
]
