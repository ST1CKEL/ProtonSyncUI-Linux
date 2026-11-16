"""Start losgeloester Hilfsprozesse: Anmelde-Terminal und Neustart der Oberflaeche.

Alle Aufrufe verwenden Argumentlisten; eine Shell ist nie beteiligt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Final

from .logging_setup import get_logger
from .paths import find_gui_executable

log = get_logger("launcher")

#: Bekannte Terminals und das Argument, hinter dem das Kommando folgt.
#: Reihenfolge = Vorrang; das Terminal der laufenden Arbeitsflaeche zuerst.
_TERMINALS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("konsole", ("--hold", "-e")),
    ("ptyxis", ("--",)),
    ("gnome-terminal", ("--",)),
    ("kgx", ("-e",)),
    ("xfce4-terminal", ("--hold", "-x")),
    ("alacritty", ("--hold", "-e")),
    ("kitty", ("--hold",)),
    ("foot", ("--hold",)),
    ("xterm", ("-hold", "-e")),
)


def find_terminal() -> tuple[str, tuple[str, ...]] | None:
    """Sucht ein installiertes Terminalprogramm."""
    for name, separator in _TERMINALS:
        path = shutil.which(name)
        if path is not None:
            return path, separator
    return None


def terminal_command(command: list[str]) -> list[str] | None:
    """Argumentliste, die ``command`` in einem Terminalfenster ausfuehrt."""
    terminal = find_terminal()
    if terminal is None:
        return None
    path, separator = terminal
    return [path, *separator, *command]


def open_login_terminal(binary: str) -> bool:
    """Oeffnet ein Terminal mit ``proton-drive auth login``.

    Die Anmeldung selbst geschieht im Browser, den die CLI oeffnet;
    ProtonSyncUI sieht dabei weder Passwort noch Sitzungsdaten. Gibt ``False``
    zurueck, wenn kein Terminalprogramm gefunden wurde.
    """
    argv = terminal_command([binary, "auth", "login"])
    if argv is None:
        return False
    try:
        subprocess.Popen(  # noqa: S603 -- feste Argumentliste, keine Shell
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        log.warning("Terminal konnte nicht gestartet werden: %s", error)
        return False
    return True


def restart_gui(*, delay_seconds: float = 1.5) -> bool:
    """Startet die Oberflaeche neu, nachdem sich die laufende Instanz beendet hat.

    Die Verzoegerung ist noetig, weil die Anwendung nur einmal laufen kann:
    Ein sofort gestarteter Prozess wuerde lediglich die alte Instanz nach vorn
    holen und sich beenden.
    """
    command = find_gui_executable().split()
    helper = (
        "import os, sys, time\n"
        "time.sleep(float(sys.argv[1]))\n"
        "os.execvp(sys.argv[2], sys.argv[2:])\n"
    )
    try:
        subprocess.Popen(  # noqa: S603 -- feste Argumentliste, keine Shell
            [sys.executable, "-c", helper, str(delay_seconds), *command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=os.path.expanduser("~"),  # noqa: PTH111
        )
    except OSError as error:
        log.warning("Neustart konnte nicht eingeleitet werden: %s", error)
        return False
    return True


__all__ = ["find_terminal", "open_login_terminal", "restart_gui", "terminal_command"]
