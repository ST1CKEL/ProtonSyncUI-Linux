"""Gemeinsame Fixtures.

Jeder Test laeuft in einer eigenen XDG-Umgebung unterhalb von ``tmp_path``.
Damit beruehrt die Testausfuehrung niemals die echte Konfiguration, Datenbank
oder Protokolle des Benutzers.

Die Proton-Drive-CLI wird vollstaendig ersetzt -- kein Test kontaktiert
Proton, und keiner ruft das echte ``proton-drive`` auf.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from proton_sync_ui.models.sync_pair import ScheduleKind, SyncPair
from proton_sync_ui.storage.database import connect
from proton_sync_ui.storage.repository import Repository


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Legt XDG-Verzeichnisse in tmp_path an -- fuer jeden Test automatisch."""
    base = tmp_path / "xdg"
    for name, sub in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        target = base / sub
        target.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(target))

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    # Die Tests pruefen deutsche Texte -- unabhaengig von der Sitzungssprache.
    from proton_sync_ui import i18n

    monkeypatch.setenv(i18n.ENVIRONMENT_VARIABLE, "de")
    i18n.set_language("de")
    return base


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Pfad einer frischen Testdatenbank."""
    return tmp_path / "test-sync.db"


@pytest.fixture
def repository(db_path: Path) -> Iterator[Repository]:
    """Ein offenes Repository auf einer frischen Datenbank."""
    repo = Repository(connect(db_path))
    try:
        yield repo
    finally:
        repo.close()


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Ein leerer lokaler Quellordner."""
    path = tmp_path / "quelle"
    path.mkdir()
    return path


MakeFile = Callable[..., Path]


@pytest.fixture
def make_file(source_dir: Path) -> MakeFile:
    """Erzeugt eine Datei im Quellordner.

    Beispiel::

        make_file("unterordner/datei.txt", "Inhalt", mtime_ns=1_000_000_000)
    """

    def factory(
        relative: str,
        content: str | bytes = "Inhalt",
        *,
        mtime_ns: int | None = None,
    ) -> Path:
        target = source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        if mtime_ns is not None:
            os.utime(target, ns=(mtime_ns, mtime_ns))
        return target

    return factory


@pytest.fixture
def sample_pair(source_dir: Path) -> SyncPair:
    """Ein einfaches, gueltiges Sync-Paar auf dem Quellordner."""
    return SyncPair.create(
        name="Testpaar",
        local_path=source_dir,
        remote_path="/my-files/Backup",
    )


@pytest.fixture
def scheduled_pair(source_dir: Path) -> SyncPair:
    """Ein Sync-Paar mit Intervall-Zeitplan."""
    return SyncPair.create(
        name="Stuendlich",
        local_path=source_dir,
        remote_path="/my-files/Backup/Stuendlich",
        schedule_kind=ScheduleKind.INTERVAL,
        interval_minutes=60,
    )


@pytest.fixture
def stored_pair(repository: Repository, sample_pair: SyncPair) -> SyncPair:
    """Ein bereits gespeichertes Sync-Paar."""
    repository.save_pair(sample_pair)
    return sample_pair
