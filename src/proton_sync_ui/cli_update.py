"""Installation und Aktualisierung der offiziellen Proton-Drive-CLI.

Quelle ist ausschliesslich die Download-Seite von Proton
(``proton.me/download/drive/cli``). Sie nennt je Plattform die Adresse des
Programms und dessen SHA-512-Pruefsumme. Das heruntergeladene Programm wird

1. gegen diese Pruefsumme geprueft,
2. probeweise mit ``--version`` gestartet und
3. erst dann atomar an die Stelle der bisherigen Fassung gesetzt.

Die bisherige Fassung bleibt als ``proton-drive.bak`` daneben liegen. Die
Anmeldung bei Proton Drive ist davon nicht beruehrt -- sie liegt in der
Sitzungsablage der CLI, nicht im Programm.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import os
import platform
import re
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .i18n import tr
from .logging_setup import get_logger
from .update import is_newer

log = get_logger("cli_update")

INDEX_URL: Final = "https://proton.me/download/drive/cli/index.html"
#: Nur Adressen unterhalb dieses Pfads werden als Programmquelle akzeptiert.
TRUSTED_PREFIX: Final = "https://proton.me/download/drive/cli/"
BINARY_NAME: Final = "proton-drive"

_MAX_INDEX_BYTES: Final = 512 * 1024
_MAX_BINARY_BYTES: Final = 400 * 1024 * 1024
_USER_AGENT: Final = "ProtonSyncUI-Updater"

_TITLE_RE: Final = re.compile(r"Proton Drive CLI\s+(?P<version>[0-9][0-9A-Za-z.\-]*)")
_ROW_RE: Final = re.compile(
    r"<tr>\s*<td>(?P<platform>[^<]+)</td>\s*"
    r"<td>\s*<a href=\"(?P<url>[^\"]+)\"[^>]*>.*?</a>\s*</td>\s*"
    r"<td>\s*<code>(?P<sha512>[0-9a-fA-F]{128})</code>\s*</td>\s*</tr>",
    re.S,
)
_VERSION_RE: Final = re.compile(r"cli-drive@(?P<version>[0-9][^\s+]*)")

ProgressCallback = Callable[[str], None]
Fetcher = Callable[[str], bytes]


class CliUpdateError(Exception):
    """Die CLI konnte nicht ermittelt oder installiert werden (Meldung anzeigbar)."""


@dataclass(frozen=True, slots=True)
class CliRelease:
    """Eine bei Proton angebotene Fassung der CLI fuer diese Plattform."""

    version: str
    url: str
    sha512: str
    platform: str


def platform_key(machine: str | None = None, system: str | None = None) -> str:
    """Plattformname, wie ihn die Download-Seite fuehrt (z. B. ``linux/x64``)."""
    name = (system or platform.system()).lower()
    arch = (machine or platform.machine()).lower()
    os_part = {"linux": "linux", "darwin": "macos"}.get(name)
    arch_part = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(arch)
    if os_part is None or arch_part is None:
        raise CliUpdateError(
            tr("Fuer diese Plattform ({0}/{1}) bietet Proton keine CLI an.").format(name, arch)
        )
    return f"{os_part}/{arch_part}"


def _fetch(url: str, *, limit: int = _MAX_INDEX_BYTES, timeout: float = 30.0) -> bytes:
    if not url.startswith("https://proton.me/"):
        raise CliUpdateError(tr("Unsichere Adresse abgelehnt: {0}").format(url))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data: bytes = response.read(limit + 1)
    if len(data) > limit:
        raise CliUpdateError(tr("Die Antwort des Servers ist unerwartet gross."))
    return data


def parse_index(page: str, *, key: str | None = None) -> CliRelease:
    """Liest Version, Adresse und Pruefsumme fuer diese Plattform aus der Download-Seite."""
    wanted = key if key is not None else platform_key()
    title = _TITLE_RE.search(page)
    if title is None:
        raise CliUpdateError(tr("Die Download-Seite von Proton hat ein unerwartetes Format."))
    for row in _ROW_RE.finditer(page):
        if html.unescape(row.group("platform")).strip() != wanted:
            continue
        url = html.unescape(row.group("url")).strip()
        if not url.startswith(TRUSTED_PREFIX):
            raise CliUpdateError(tr("Unsichere Adresse abgelehnt: {0}").format(url))
        return CliRelease(
            version=title.group("version").rstrip("."),
            url=url,
            sha512=row.group("sha512").lower(),
            platform=wanted,
        )
    raise CliUpdateError(
        tr("Auf der Download-Seite von Proton fehlt ein Eintrag fuer {0}.").format(wanted)
    )


def fetch_release(*, fetch: Fetcher | None = None) -> CliRelease:
    """Ermittelt die aktuell angebotene Fassung. Blockiert."""
    fetcher = fetch if fetch is not None else _fetch
    try:
        page = fetcher(INDEX_URL).decode("utf-8", errors="replace")
    except OSError as error:
        raise CliUpdateError(
            tr("Die Download-Seite von Proton ist nicht erreichbar: {0}").format(error)
        ) from error
    return parse_index(page)


def installed_version(binary: str | Path) -> str:
    """Version eines CLI-Programms laut ``--version`` (leer, wenn nicht ermittelbar)."""
    try:
        result = subprocess.run(  # noqa: S603 -- feste Argumentliste, keine Shell
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = _VERSION_RE.search(result.stdout + result.stderr)
    return match.group("version") if match else ""


def target_path(current_binary: str | None = None) -> Path:
    """Wohin installiert wird: an die Stelle der bisherigen CLI, sonst ``~/.local/bin``.

    Liegt die bisherige CLI an einem Ort ohne Schreibrecht (z. B. ``/usr/bin``),
    wird ebenfalls ``~/.local/bin`` verwendet -- ProtonSyncUI sucht dort zuerst.
    """
    if current_binary:
        current = Path(current_binary).resolve()
        if current.is_file() and os.access(current.parent, os.W_OK):
            return current
    return Path.home() / ".local" / "bin" / BINARY_NAME


def is_update_available(release: CliRelease, current_version: str) -> bool:
    """Wahr, wenn ``release`` neuer ist als die installierte Fassung (oder keine da ist)."""
    return not current_version or is_newer(release.version, current_version)


def _download(url: str, destination: Path, *, progress: ProgressCallback | None) -> str:
    """Laedt das Programm nach ``destination`` und liefert dessen SHA-512."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    digest = hashlib.sha512()
    received = 0
    last_percent = -10
    with (
        urllib.request.urlopen(request, timeout=60) as response,  # noqa: S310
        destination.open("wb") as handle,
    ):
        total = int(response.headers.get("Content-Length") or 0)
        while chunk := response.read(1024 * 256):
            received += len(chunk)
            if received > _MAX_BINARY_BYTES:
                raise CliUpdateError(tr("Die Antwort des Servers ist unerwartet gross."))
            digest.update(chunk)
            handle.write(chunk)
            if progress is not None and total:
                percent = received * 100 // total
                if percent >= last_percent + 10:
                    last_percent = percent
                    progress(tr("Download: {0} %").format(percent))
    return digest.hexdigest()


def install_release(
    release: CliRelease,
    target: Path,
    *,
    progress: ProgressCallback | None = None,
    download: Callable[[str, Path], str] | None = None,
) -> str:
    """Laedt ``release``, prueft es und setzt es an ``target``. Gibt die Version zurueck.

    Blockiert. Bei jedem Fehler bleibt die bisherige CLI unveraendert.
    """

    def note(message: str) -> None:
        log.info(message)
        if progress is not None:
            progress(message)

    if not release.url.startswith(TRUSTED_PREFIX):
        raise CliUpdateError(tr("Unsichere Adresse abgelehnt: {0}").format(release.url))

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CliUpdateError(
            tr("Der Zielordner {0} kann nicht angelegt werden: {1}").format(target.parent, error)
        ) from error

    staging = target.with_name(f".{target.name}.new-{os.getpid()}")
    try:
        note(tr("Lade Proton-Drive-CLI {0} herunter …").format(release.version))
        try:
            if download is not None:
                actual = download(release.url, staging)
            else:
                actual = _download(release.url, staging, progress=progress)
        except OSError as error:
            raise CliUpdateError(
                tr("Der Download ist fehlgeschlagen: {0}").format(error)
            ) from error

        note(tr("Pruefe SHA-512-Pruefsumme …"))
        if actual.lower() != release.sha512.lower():
            raise CliUpdateError(
                tr(
                    "Die Pruefsumme des Downloads stimmt nicht mit der Angabe von Proton "
                    "ueberein. Es wurde nichts installiert."
                )
            )

        staging.chmod(0o755)
        version = installed_version(staging)
        if not version:
            raise CliUpdateError(
                tr(
                    "Die heruntergeladene CLI laesst sich nicht starten. "
                    "Es wurde nichts installiert."
                )
            )

        note(tr("Installiere nach {0} …").format(target))
        try:
            if target.exists():
                backup = target.with_name(f"{target.name}.bak")
                with contextlib.suppress(OSError):
                    backup.unlink()
                # Kopie statt Umbenennen: target bleibt bis zum Austausch benutzbar.
                backup.write_bytes(target.read_bytes())
                backup.chmod(0o755)
            staging.replace(target)
        except OSError as error:
            raise CliUpdateError(
                tr("Die CLI konnte nicht nach {0} geschrieben werden: {1}").format(target, error)
            ) from error
    finally:
        with contextlib.suppress(OSError):
            staging.unlink()

    note(tr("Proton-Drive-CLI {0} ist installiert.").format(version))
    return version


__all__ = [
    "BINARY_NAME",
    "INDEX_URL",
    "CliRelease",
    "CliUpdateError",
    "fetch_release",
    "install_release",
    "installed_version",
    "is_update_available",
    "parse_index",
    "platform_key",
    "target_path",
]
