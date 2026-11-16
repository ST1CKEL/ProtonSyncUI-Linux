"""Update-Suche und -Installation fuer ProtonSyncUI.

Quelle ist das oeffentliche GitHub-Repository. Gesucht wird zuerst nach einer
veroeffentlichten Release; gibt es keine, zaehlt die Versionsnummer des
Hauptzweigs. Uebertragen wird dabei nichts ausser der Anfrage selbst -- keine
Kennungen, keine Nutzungsdaten.

Die Installation laedt das Quellarchiv, entpackt es in ein temporaeres
Verzeichnis und ruft das darin enthaltene ``install.sh --yes --no-deps`` auf.
Konfiguration, Datenbank und Sync-Zustand bleiben unberuehrt.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import __version__
from .logging_setup import get_logger

log = get_logger("update")

#: ``Besitzer/Repository`` bei GitHub.
REPOSITORY: Final = "ST1CKEL/ProtonSyncUI-Linux"
BRANCH: Final = "main"

RELEASE_API_URL: Final = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
BRANCH_VERSION_URL: Final = (
    f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/src/proton_sync_ui/__init__.py"
)
BRANCH_ARCHIVE_URL: Final = f"https://github.com/{REPOSITORY}/archive/refs/heads/{BRANCH}.tar.gz"
PROJECT_URL: Final = f"https://github.com/{REPOSITORY}"

#: Download-Seite der offiziellen Proton-Drive-CLI.
PROTON_CLI_DOWNLOAD_URL: Final = "https://proton.me/download/drive/cli/index.html"

_USER_AGENT: Final = "ProtonSyncUI-Updater"
_VERSION_RE: Final = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")
_MAX_ARCHIVE_BYTES: Final = 50 * 1024 * 1024

ProgressCallback = Callable[[str], None]


class UpdateError(Exception):
    """Update-Suche oder -Installation ist fehlgeschlagen (Meldung anzeigbar)."""


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """Ergebnis einer Update-Suche."""

    current_version: str
    latest_version: str
    archive_url: str
    #: ``release`` oder ``branch``.
    source: str = "branch"
    notes: str = ""

    @property
    def available(self) -> bool:
        """Wahr, wenn die gefundene Version neuer ist als die installierte."""
        return is_newer(self.latest_version, self.current_version)


def parse_version(text: str) -> tuple[int, ...]:
    """Zerlegt ``v1.2.3`` in ``(1, 2, 3)``; Zusaetze wie ``-beta`` werden ignoriert."""
    numbers = re.findall(r"\d+", text.strip().lstrip("vV").split("+", 1)[0].split("-", 1)[0])
    return tuple(int(number) for number in numbers)


def is_newer(candidate: str, current: str) -> bool:
    """Wahr, wenn ``candidate`` eine hoehere Version als ``current`` ist."""
    left, right = parse_version(candidate), parse_version(current)
    if not left:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def _fetch(url: str, *, timeout: float, limit: int = 2 * 1024 * 1024) -> bytes:
    """Laedt eine HTTPS-Ressource mit Groessenbegrenzung."""
    if not url.startswith("https://"):
        raise UpdateError(f"Unsichere Adresse abgelehnt: {url}")
    request = urllib.request.Request(  # noqa: S310 -- Schema oben geprueft
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data: bytes = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Die Antwort des Servers ist unerwartet gross.")
    return data


def check_for_update(*, timeout: float = 15.0, fetch: Any = None) -> UpdateInfo:
    """Sucht nach einer neueren Version. Blockiert; nicht im GTK-Hauptthread aufrufen."""
    fetcher = fetch if fetch is not None else _fetch

    try:
        payload = json.loads(fetcher(RELEASE_API_URL, timeout=timeout))
        tag = str(payload.get("tag_name") or "")
        if tag and parse_version(tag):
            archive = f"https://github.com/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz"
            return UpdateInfo(
                current_version=__version__,
                latest_version=tag.lstrip("vV"),
                archive_url=archive,
                source="release",
                notes=str(payload.get("body") or "").strip(),
            )
    except urllib.error.HTTPError as error:
        if error.code != 404:  # 404 = es gibt (noch) keine Release
            log.debug("Release-Abfrage fehlgeschlagen: %s", error)
        error.close()
    except (OSError, ValueError, UpdateError) as error:
        log.debug("Release-Abfrage fehlgeschlagen: %s", error)

    try:
        text = fetcher(BRANCH_VERSION_URL, timeout=timeout).decode("utf-8", errors="replace")
    except (OSError, UpdateError) as error:
        raise UpdateError(f"Die Update-Suche ist fehlgeschlagen: {error}") from error
    match = _VERSION_RE.search(text)
    if match is None:
        raise UpdateError("Die Versionsnummer im Repository konnte nicht gelesen werden.")
    return UpdateInfo(
        current_version=__version__,
        latest_version=match.group(1),
        archive_url=BRANCH_ARCHIVE_URL,
        source="branch",
    )


def _find_installer(root: Path) -> Path:
    """Sucht ``install.sh`` im entpackten Archiv (liegt in genau einem Unterordner)."""
    candidates = [root / "install.sh", *sorted(root.glob("*/install.sh"))]
    for candidate in candidates:
        if candidate.is_file() and (candidate.parent / "src" / "proton_sync_ui").is_dir():
            return candidate
    raise UpdateError("Das heruntergeladene Archiv enthaelt kein gueltiges install.sh.")


def install_update(
    info: UpdateInfo,
    *,
    progress: ProgressCallback | None = None,
    timeout: float = 120.0,
) -> str:
    """Laedt und installiert die Version aus ``info``. Gibt die Installer-Ausgabe zurueck.

    Blockiert. Wirft :class:`UpdateError` mit einer anzeigbaren Meldung.
    """

    def note(message: str) -> None:
        log.info(message)
        if progress is not None:
            progress(message)

    bash = shutil.which("bash")
    if bash is None:
        raise UpdateError("'bash' wurde nicht gefunden; das Update kann nicht installiert werden.")

    with tempfile.TemporaryDirectory(prefix="proton-sync-ui-update-") as workdir:
        work = Path(workdir)
        note(f"Lade Version {info.latest_version} herunter …")
        try:
            archive_bytes = _fetch(info.archive_url, timeout=timeout, limit=_MAX_ARCHIVE_BYTES)
        except (OSError, UpdateError) as error:
            raise UpdateError(f"Der Download ist fehlgeschlagen: {error}") from error
        archive = work / "source.tar.gz"
        archive.write_bytes(archive_bytes)

        note("Entpacke Archiv …")
        target = work / "source"
        target.mkdir()
        try:
            with tarfile.open(archive, "r:gz") as tar:
                # filter="data" verweigert absolute Pfade, "..", Geraetedateien
                # und Links, die aus dem Zielordner herausfuehren.
                tar.extractall(target, filter="data")
        except (tarfile.TarError, OSError) as error:
            raise UpdateError(f"Das Archiv konnte nicht entpackt werden: {error}") from error

        installer = _find_installer(target)
        note("Installiere …")
        try:
            result = subprocess.run(  # noqa: S603 -- feste Argumentliste, keine Shell
                [bash, str(installer), "--yes", "--no-deps"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
                cwd=str(installer.parent),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpdateError(f"Die Installation ist fehlgeschlagen: {error}") from error

        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            tail = "\n".join(output.splitlines()[-12:])
            raise UpdateError(f"Die Installation endete mit Code {result.returncode}:\n{tail}")

    note(f"Version {info.latest_version} wurde installiert.")
    return output


__all__ = [
    "PROJECT_URL",
    "PROTON_CLI_DOWNLOAD_URL",
    "REPOSITORY",
    "UpdateError",
    "UpdateInfo",
    "check_for_update",
    "install_update",
    "is_newer",
    "parse_version",
]
