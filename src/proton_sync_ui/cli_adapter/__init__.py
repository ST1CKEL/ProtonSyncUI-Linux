"""Kapselung der offiziellen Proton-Drive-Kommandozeile.

Die gesamte CLI-Syntax steht in :mod:`~.commands`. Wird die Kommandozeile
von Proton geaendert, ist ausschliesslich dieses Modul anzupassen.
"""

from __future__ import annotations

from .adapter import CommandResult, ProtonDriveAdapter, RemoteNode, classify_error
from .capabilities import Capabilities, probe
from .errors import (
    CommandTimeoutError,
    ForbiddenCommandError,
    NotAuthenticatedError,
    PermanentError,
    ProtonCliError,
    ProtonCliNotFoundError,
    RemotePathExistsError,
    RemotePathNotFoundError,
    TransientError,
)

__all__ = [
    "Capabilities",
    "CommandResult",
    "CommandTimeoutError",
    "ForbiddenCommandError",
    "NotAuthenticatedError",
    "PermanentError",
    "ProtonCliError",
    "ProtonCliNotFoundError",
    "ProtonDriveAdapter",
    "RemoteNode",
    "RemotePathExistsError",
    "RemotePathNotFoundError",
    "TransientError",
    "classify_error",
    "probe",
]
