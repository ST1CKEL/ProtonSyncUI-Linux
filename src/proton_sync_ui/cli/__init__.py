"""Kommandozeilen-Schnittstelle -- der Einstiegspunkt der systemd-Units.

Die Funktion ``main`` wird bewusst *nicht* hierher re-exportiert: sie wuerde
das gleichnamige Untermodul :mod:`proton_sync_ui.cli.main` im
Paket-Namensraum verdecken. Einstiegspunkt ist ``proton_sync_ui.cli.main:main``.
"""

from __future__ import annotations

from .main import EXIT_ERROR, EXIT_LOCKED, EXIT_OK, EXIT_USAGE, EXIT_WARNING

__all__ = [
    "EXIT_ERROR",
    "EXIT_LOCKED",
    "EXIT_OK",
    "EXIT_USAGE",
    "EXIT_WARNING",
]
