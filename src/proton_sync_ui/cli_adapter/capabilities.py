"""Ermittlung von Version und Anmeldezustand der Proton-Drive-CLI.

Wird beim Start der Oberflaeche und vor jedem Lauf ausgefuehrt, damit
Fehlermeldungen konkret ausfallen statt erst mitten im Upload aufzutauchen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..i18n import tr
from ..logging_setup import get_logger
from .adapter import ProtonDriveAdapter
from .errors import ProtonCliError, ProtonCliNotFoundError

log = get_logger("cli_adapter.capabilities")

# "Proton Drive CLI cli-drive@0.8.0+06e8c605"
_CLI_VERSION_RE: Final = re.compile(r"cli-drive@(?P<version>[0-9][^\s+]*)")
# "Proton Drive SDK js@0.21.0+06e8c605"
_SDK_VERSION_RE: Final = re.compile(r"js@(?P<version>[0-9][^\s+]*)")

# "A newer version is available: 0.9.0 (you have 0.8.0)."
_NEWER_CLI_RE: Final = re.compile(
    r"newer version is available:\s*(?P<version>[0-9][0-9A-Za-z.\-]*)"
)

#: Aelteste Fassung, gegen die dieser Adapter geprueft wurde.
VERIFIED_CLI_VERSION: Final = "0.9.0"

#: Alle Fassungen, mit denen der Adapter erprobt ist.
VERIFIED_CLI_VERSIONS: Final[frozenset[str]] = frozenset({"0.8.0", "0.9.0"})


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Was die vorgefundene CLI kann und ob sie benutzbar ist."""

    binary_path: str | None
    available: bool
    raw_version: str = ""
    cli_version: str = ""
    sdk_version: str = ""
    authenticated: bool = False
    problem: str = ""
    #: Neuere CLI-Fassung, auf die ``proton-drive --version`` selbst hinweist.
    newer_cli_version: str = ""
    #: Der Anmeldezustand liess sich nicht ermitteln (z. B. kein Netz). Das
    #: ist etwas anderes als "abgemeldet" und verlangt keine neue Anmeldung.
    auth_check_failed: bool = False

    @property
    def needs_login(self) -> bool:
        """Wahr, wenn die CLI vorhanden, aber sicher nicht angemeldet ist."""
        return self.available and not self.authenticated and not self.auth_check_failed

    @property
    def usable(self) -> bool:
        """Wahr, wenn sofort synchronisiert werden kann."""
        return self.available and self.authenticated

    def describe(self) -> str:
        """Kurzbeschreibung fuer Kommandozeile und Oberflaeche."""
        if not self.available:
            return tr("proton-drive nicht gefunden")
        version = self.cli_version or "unbekannt"
        state = tr("angemeldet") if self.authenticated else tr("nicht angemeldet")
        return f"proton-drive {version} ({state})"


def parse_version(raw: str) -> tuple[str, str]:
    """Liest CLI- und SDK-Version aus der Ausgabe von ``--version``."""
    cli_match = _CLI_VERSION_RE.search(raw)
    sdk_match = _SDK_VERSION_RE.search(raw)
    return (
        cli_match.group("version") if cli_match else "",
        sdk_match.group("version") if sdk_match else "",
    )


async def probe(
    adapter: ProtonDriveAdapter | None = None, *, check_auth: bool = True
) -> Capabilities:
    """Prueft Verfuegbarkeit, Version und Anmeldezustand der CLI.

    Wirft nicht, sondern beschreibt das Problem im Ergebnis -- die Oberflaeche
    soll auch dann starten, wenn die CLI fehlt.
    """
    cli = adapter if adapter is not None else ProtonDriveAdapter()

    try:
        binary = cli.resolve_binary()
    except ProtonCliNotFoundError as error:
        log.warning("Proton-Drive-CLI nicht gefunden.")
        return Capabilities(binary_path=None, available=False, problem=str(error))

    try:
        raw_version = await cli.version()
    except ProtonCliError as error:
        log.warning("Version der CLI konnte nicht ermittelt werden: %s", error)
        return Capabilities(
            binary_path=binary,
            available=True,
            problem=tr("Die CLI antwortet nicht wie erwartet: {0}").format(error),
        )

    cli_version, sdk_version = parse_version(raw_version)
    newer_match = _NEWER_CLI_RE.search(raw_version)
    newer_cli_version = newer_match.group("version").rstrip(".") if newer_match else ""
    if cli_version and cli_version not in VERIFIED_CLI_VERSIONS:
        log.info(
            "CLI-Version %s weicht von der geprueften Fassung %s ab. "
            "Bei Syntaxfehlern bitte proton_sync_ui/cli_adapter/commands.py pruefen.",
            cli_version,
            VERIFIED_CLI_VERSION,
        )

    if not check_auth:
        return Capabilities(
            binary_path=binary,
            available=True,
            raw_version=raw_version,
            cli_version=cli_version,
            sdk_version=sdk_version,
            newer_cli_version=newer_cli_version,
        )

    try:
        authenticated = await cli.check_authenticated()
    except ProtonCliNotFoundError as error:
        return Capabilities(binary_path=None, available=False, problem=str(error))
    except ProtonCliError as error:
        return Capabilities(
            binary_path=binary,
            available=True,
            raw_version=raw_version,
            cli_version=cli_version,
            sdk_version=sdk_version,
            newer_cli_version=newer_cli_version,
            problem=tr("Der Anmeldezustand konnte nicht geprueft werden: {0}").format(error),
            auth_check_failed=True,
        )

    problem = (
        ""
        if authenticated
        else (
            tr(
                "Die Proton-Drive-CLI ist nicht angemeldet.\n\n"
                "Bitte in ProtonSyncUI unter Einstellungen auf 'Anmelden' klicken "
                "oder im Terminal ausfuehren:\n\n"
                "    proton-drive auth login\n\n"
                "Die Anmeldung oeffnet einen Browser. ProtonSyncUI verarbeitet dabei "
                "keinerlei Zugangsdaten."
            )
        )
    )

    return Capabilities(
        binary_path=binary,
        available=True,
        raw_version=raw_version,
        cli_version=cli_version,
        sdk_version=sdk_version,
        newer_cli_version=newer_cli_version,
        authenticated=authenticated,
        problem=problem,
    )


__all__ = [
    "VERIFIED_CLI_VERSION",
    "VERIFIED_CLI_VERSIONS",
    "Capabilities",
    "parse_version",
    "probe",
]
