"""Durchlauf des lokalen Quellordners.

Der Scanner trifft keine Entscheidung ueber Uploads -- er stellt nur fest,
welche Dateien vorhanden sind und welche von vornherein ausscheiden.

Symlinks werden im MVP grundsaetzlich uebersprungen, sowohl als Datei als
auch als Verzeichnis. Damit ist ausgeschlossen, dass ein Link versehentlich
Daten ausserhalb des Quellordners uebertraegt oder eine Schleife erzeugt.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from ..i18n import tr
from ..logging_setup import get_logger
from ..models.plan import PlanAction
from ..models.sync_pair import name_is_supported
from .ignore import IgnoreMatcher

log = get_logger("sync.scanner")

#: Blockgroesse fuer die Pruefsummenbildung.
HASH_CHUNK_SIZE: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """Eine gefundene, grundsaetzlich uebertragbare Datei."""

    relative_path: PurePosixPath
    absolute_path: Path
    size_bytes: int
    mtime_ns: int

    @property
    def key(self) -> str:
        """Relativer Pfad als Zeichenkette -- Schluessel in der Zustandstabelle."""
        return self.relative_path.as_posix()


@dataclass(frozen=True, slots=True)
class ScanSkip:
    """Ein bewusst uebersprungener Eintrag samt Begruendung."""

    relative_path: PurePosixPath
    action: PlanAction
    reason: str
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Ergebnis eines vollstaendigen Durchlaufs."""

    files: tuple[ScannedFile, ...] = ()
    skips: tuple[ScanSkip, ...] = ()
    errors: tuple[str, ...] = field(default=())

    @property
    def total_bytes(self) -> int:
        """Summe der Groessen aller gefundenen Dateien."""
        return sum(item.size_bytes for item in self.files)

    def by_key(self) -> dict[str, ScannedFile]:
        """Gefundene Dateien nach relativem Pfad."""
        return {item.key: item for item in self.files}


def compute_sha256(path: Path, *, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Bildet die SHA-256-Pruefsumme einer Datei blockweise."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def scan_directory(
    root: Path,
    *,
    matcher: IgnoreMatcher | None = None,
    max_file_size_bytes: int | None = None,
) -> ScanResult:
    """Durchlaeuft einen Ordner und liefert Dateien, Ausschluesse und Fehler.

    Ausgeschlossene Verzeichnisse werden nicht betreten. Ein Lesefehler in
    einem Unterordner bricht den Durchlauf nicht ab, sondern wird gesammelt.
    """
    rules = matcher if matcher is not None else IgnoreMatcher()
    files: list[ScannedFile] = []
    skips: list[ScanSkip] = []
    errors: list[str] = []
    # Schutz gegen Schleifen durch Bind-Mounts.
    visited: set[tuple[int, int]] = set()

    for entry, relative in _walk(root, rules, skips, errors, visited):
        name = entry.name

        if not name_is_supported(name):
            skips.append(
                ScanSkip(
                    relative_path=relative,
                    action=PlanAction.SKIP_UNSUPPORTED_NAME,
                    reason=(
                        tr(
                            "Der Name enthaelt Zeichen, die die Proton-Drive-CLI nicht "
                            "eindeutig verarbeiten kann (z. B. Backslash)."
                        )
                    ),
                )
            )
            continue

        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError as error:
            errors.append(f"{relative}: {error.strerror or error}")
            skips.append(
                ScanSkip(
                    relative_path=relative,
                    action=PlanAction.SKIP_UNREADABLE,
                    reason=tr("Dateiinformationen nicht lesbar: {0}").format(
                        error.strerror or error
                    ),
                )
            )
            continue

        size = stat.st_size

        if max_file_size_bytes is not None and size > max_file_size_bytes:
            skips.append(
                ScanSkip(
                    relative_path=relative,
                    action=PlanAction.SKIP_TOO_LARGE,
                    reason=(
                        tr("{0} ueberschreitet das Limit von {1}.").format(
                            _format_size(size), _format_size(max_file_size_bytes)
                        )
                    ),
                    size_bytes=size,
                )
            )
            continue

        if not os.access(entry.path, os.R_OK):
            skips.append(
                ScanSkip(
                    relative_path=relative,
                    action=PlanAction.SKIP_UNREADABLE,
                    reason=tr("Keine Leseberechtigung."),
                    size_bytes=size,
                )
            )
            continue

        files.append(
            ScannedFile(
                relative_path=relative,
                absolute_path=Path(entry.path),
                size_bytes=size,
                mtime_ns=stat.st_mtime_ns,
            )
        )

    return ScanResult(files=tuple(files), skips=tuple(skips), errors=tuple(errors))


def _walk(
    root: Path,
    rules: IgnoreMatcher,
    skips: list[ScanSkip],
    errors: list[str],
    visited: set[tuple[int, int]],
) -> Iterator[tuple[os.DirEntry[str], PurePosixPath]]:
    """Iterativer Durchlauf, der nur regulaere Dateien ausliefert."""
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath())]

    while stack:
        directory, prefix = stack.pop()

        try:
            stat = directory.stat()
            marker = (stat.st_dev, stat.st_ino)
            if marker in visited:
                log.warning("Verzeichnisschleife erkannt, ueberspringe: %s", directory)
                continue
            visited.add(marker)
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            label = prefix.as_posix() or "."
            errors.append(f"{label}: {error.strerror or error}")
            continue

        for entry in entries:
            relative = prefix / entry.name

            try:
                is_symlink = entry.is_symlink()
            except OSError as error:
                errors.append(f"{relative}: {error.strerror or error}")
                continue

            if is_symlink:
                skips.append(
                    ScanSkip(
                        relative_path=relative,
                        action=PlanAction.SKIP_SYMLINK,
                        reason=tr("Symbolische Links werden nicht synchronisiert."),
                    )
                )
                continue

            try:
                is_directory = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as error:
                errors.append(f"{relative}: {error.strerror or error}")
                continue

            path_text = relative.as_posix()

            if is_directory:
                if rules.is_dir_ignored(path_text):
                    skips.append(
                        ScanSkip(
                            relative_path=relative,
                            action=PlanAction.SKIP_EXCLUDED,
                            reason=tr("Verzeichnis durch Ausschlussregel ausgenommen."),
                        )
                    )
                    continue
                stack.append((Path(entry.path), relative))
                continue

            if not is_file:
                # Geraetedateien, Sockets, FIFOs -- nicht sicherbar.
                skips.append(
                    ScanSkip(
                        relative_path=relative,
                        action=PlanAction.SKIP_UNSUPPORTED_NAME,
                        reason=tr("Keine regulaere Datei."),
                    )
                )
                continue

            if rules.is_ignored(path_text):
                skips.append(
                    ScanSkip(
                        relative_path=relative,
                        action=PlanAction.SKIP_EXCLUDED,
                        reason=tr("Durch Ausschlussregel ausgenommen."),
                    )
                )
                continue

            yield entry, relative


def _format_size(num_bytes: int) -> str:
    """Formatiert eine Byte-Anzahl kompakt."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"  # pragma: no cover -- durch Schleife abgedeckt


__all__ = [
    "HASH_CHUNK_SIZE",
    "ScanResult",
    "ScanSkip",
    "ScannedFile",
    "compute_sha256",
    "scan_directory",
]
