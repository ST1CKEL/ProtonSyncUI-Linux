"""Fehlerklassen des CLI-Adapters.

Die Unterscheidung zwischen :class:`TransientError` und
:class:`PermanentError` steuert, ob die Retry-Logik einen weiteren Versuch
unternimmt.
"""

from __future__ import annotations


class ProtonCliError(Exception):
    """Basisklasse aller Fehler rund um die Proton-Drive-CLI."""

    #: Ob ein erneuter Versuch sinnvoll ist.
    transient: bool = False

    def __init__(self, message: str, *, argv: tuple[str, ...] = (), stderr: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.argv = argv
        self.stderr = stderr

    def __str__(self) -> str:
        return self.message


class ProtonCliNotFoundError(ProtonCliError):
    """Das Programm ``proton-drive`` wurde nicht im PATH gefunden."""

    transient = False


class ForbiddenCommandError(ProtonCliError):
    """Ein Kommando wurde blockiert, bevor es ausgefuehrt werden konnte.

    Wird ausgeloest, wenn eine Argumentliste ein Verb enthaelt, das entfernte
    Daten veraendern oder loeschen koennte, oder eine verbotene
    Konfliktstrategie verwendet. Das ist eine Sicherheitszusage der
    Anwendung -- kein gewoehnlicher Laufzeitfehler.
    """

    transient = False


class NotAuthenticatedError(ProtonCliError):
    """Die CLI ist nicht angemeldet.

    Die Anmeldung erfolgt ausschliesslich ausserhalb dieser Anwendung mit
    ``proton-drive auth login``.
    """

    transient = False


class RemotePathNotFoundError(ProtonCliError):
    """Ein angefragter Proton-Drive-Pfad existiert nicht."""

    transient = False


class RemotePathExistsError(ProtonCliError):
    """Ein Ordner existiert bereits -- beim Anlegen unkritisch."""

    transient = False


class PermanentError(ProtonCliError):
    """Ein Fehler, den ein erneuter Versuch nicht behebt."""

    transient = False


class TransientError(ProtonCliError):
    """Ein voraussichtlich voruebergehender Fehler (Netz, Auslastung, Zeitlimit)."""

    transient = True


class CommandTimeoutError(TransientError):
    """Ein CLI-Aufruf hat das Zeitlimit ueberschritten und wurde beendet."""


__all__ = [
    "CommandTimeoutError",
    "ForbiddenCommandError",
    "NotAuthenticatedError",
    "PermanentError",
    "ProtonCliError",
    "ProtonCliNotFoundError",
    "RemotePathExistsError",
    "RemotePathNotFoundError",
    "TransientError",
]
