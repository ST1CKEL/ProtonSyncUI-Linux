"""Verwaltung der systemd-Units unter ``~/.config/systemd/user/``.

Alle ``systemctl``-Aufrufe erfolgen mit Argumentlisten ueber
:func:`subprocess.run`; ``shell=True`` kommt nicht vor.

Es werden ausschliesslich Units verwaltet, deren Name mit
``proton-sync-ui@`` beginnt. Fremde Units werden nie angefasst.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .. import paths
from ..logging_setup import get_logger
from ..models.sync_pair import SyncPair
from .units import (
    SERVICE_TEMPLATE_NAME,
    UnitError,
    service_template_text,
    service_unit_name,
    timer_unit_name,
    timer_unit_text,
    validate_instance,
)

log = get_logger("systemd.manager")

#: Zeitlimit fuer systemctl-Aufrufe.
SYSTEMCTL_TIMEOUT: Final = 30.0

#: Praefix, das eine Unit als von dieser Anwendung verwaltet ausweist.
UNIT_PREFIX: Final = "proton-sync-ui@"


@dataclass(frozen=True, slots=True)
class SystemctlResult:
    """Ergebnis eines ``systemctl``-Aufrufs."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Wahr bei Beendigungscode 0."""
        return self.returncode == 0


@dataclass(frozen=True, slots=True)
class TimerStatus:
    """Zustand des Timers eines Sync-Paars."""

    uid: str
    unit: str
    exists: bool
    enabled: bool
    active: bool

    def describe(self) -> str:
        """Kurzbeschreibung fuer die Anzeige."""
        if not self.exists:
            return "kein Timer"
        state = "aktiviert" if self.enabled else "nicht aktiviert"
        running = "laeuft" if self.active else "gestoppt"
        return f"{state}, {running}"


class SystemdUnavailableError(RuntimeError):
    """``systemctl`` steht nicht zur Verfuegung (z. B. im Container)."""


class SystemdManager:
    """Schreibt, aktiviert und entfernt die Units der Sync-Paare."""

    def __init__(self, unit_dir: Path | None = None, *, systemctl: str | None = None) -> None:
        self._unit_dir = unit_dir if unit_dir is not None else paths.systemd_user_dir()
        self._systemctl = systemctl

    @property
    def unit_dir(self) -> Path:
        """Verzeichnis der Benutzer-Units."""
        return self._unit_dir

    # ------------------------------------------------------------------
    # systemctl
    # ------------------------------------------------------------------

    def systemctl_path(self) -> str:
        """Pfad zu ``systemctl`` oder Fehler, wenn nicht vorhanden."""
        if self._systemctl is not None:
            return self._systemctl
        found = shutil.which("systemctl")
        if found is None:
            raise SystemdUnavailableError(
                "'systemctl' wurde nicht gefunden. Die Zeitplanung ueber systemd "
                "steht auf diesem System nicht zur Verfuegung."
            )
        self._systemctl = found
        return found

    @property
    def available(self) -> bool:
        """Wahr, wenn systemd nutzbar ist."""
        try:
            self.systemctl_path()
        except SystemdUnavailableError:
            return False
        return True

    def _run(self, args: Sequence[str], *, check: bool = False) -> SystemctlResult:
        """Fuehrt ``systemctl --user ...`` aus."""
        argv = [self.systemctl_path(), "--user", *args]
        log.debug("systemctl: %s", " ".join(args))
        completed = subprocess.run(  # noqa: S603 -- feste Argumentliste, keine Shell
            argv,
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT,
            check=False,
        )
        result = SystemctlResult(
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        if check and not result.ok:
            raise UnitError(
                f"systemctl {' '.join(args)} ist fehlgeschlagen: "
                f"{result.stderr or result.stdout or f'Code {result.returncode}'}"
            )
        return result

    def daemon_reload(self) -> SystemctlResult:
        """``systemctl --user daemon-reload``."""
        return self._run(["daemon-reload"])

    # ------------------------------------------------------------------
    # Unit-Dateien
    # ------------------------------------------------------------------

    def install_service_template(self, *, executable: str | None = None) -> Path:
        """Schreibt den Template-Service, falls noetig."""
        self._unit_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_dir / SERVICE_TEMPLATE_NAME
        content = service_template_text(executable=executable)
        if target.exists() and target.read_text(encoding="utf-8") == content:
            return target
        target.write_text(content, encoding="utf-8")
        log.info("Template-Service geschrieben: %s", target)
        return target

    def write_timer(self, pair: SyncPair) -> Path:
        """Schreibt die Timer-Unit eines Paars."""
        self._unit_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_dir / timer_unit_name(pair.uid)
        content = timer_unit_text(pair)
        if target.exists() and target.read_text(encoding="utf-8") == content:
            return target
        target.write_text(content, encoding="utf-8")
        log.info("Timer geschrieben: %s", target, extra={"pair_uid": pair.uid})
        return target

    def remove_timer(self, uid: str) -> bool:
        """Entfernt die Timer-Unit eines Paars, nachdem sie gestoppt wurde."""
        unit = timer_unit_name(uid)
        target = self._unit_dir / unit
        if not target.exists():
            return False
        self.disable_timer(uid)
        target.unlink()
        log.info("Timer entfernt: %s", unit, extra={"pair_uid": uid})
        return True

    def timer_exists(self, uid: str) -> bool:
        """Wahr, wenn eine Timer-Datei fuer das Paar existiert."""
        return (self._unit_dir / timer_unit_name(uid)).exists()

    # ------------------------------------------------------------------
    # Aktivierung
    # ------------------------------------------------------------------

    def enable_timer(self, uid: str) -> SystemctlResult:
        """Aktiviert und startet den Timer eines Paars."""
        return self._run(["enable", "--now", timer_unit_name(uid)])

    def disable_timer(self, uid: str) -> SystemctlResult:
        """Stoppt und deaktiviert den Timer eines Paars."""
        return self._run(["disable", "--now", timer_unit_name(uid)])

    def start_now(self, uid: str) -> SystemctlResult:
        """Startet einen Lauf sofort ueber systemd (statt im Vordergrund)."""
        return self._run(["start", service_unit_name(uid)])

    def timer_status(self, uid: str) -> TimerStatus:
        """Ermittelt den Zustand des Timers eines Paars."""
        validate_instance(uid)
        unit = timer_unit_name(uid)
        exists = self.timer_exists(uid)
        if not exists or not self.available:
            return TimerStatus(uid=uid, unit=unit, exists=exists, enabled=False, active=False)

        enabled = self._run(["is-enabled", unit]).stdout.strip() == "enabled"
        active = self._run(["is-active", unit]).stdout.strip() == "active"
        return TimerStatus(uid=uid, unit=unit, exists=True, enabled=enabled, active=active)

    # ------------------------------------------------------------------
    # Abgleich
    # ------------------------------------------------------------------

    def sync_pairs(self, pairs: Sequence[SyncPair]) -> dict[str, str]:
        """Bringt die Units in Einklang mit der Konfiguration.

        Ein Timer entsteht nur fuer Paare, die *aktiviert* sind **und** einen
        Intervall-Zeitplan haben. Alle anderen verlieren ihren Timer.

        Gibt je Paar-UUID eine kurze Beschreibung der Aenderung zurueck.
        """
        self.install_service_template()
        actions: dict[str, str] = {}
        wanted: set[str] = set()

        for pair in pairs:
            if pair.is_scheduled:
                wanted.add(pair.uid)
                self.write_timer(pair)
                actions[pair.uid] = "Timer geschrieben"
            elif self.timer_exists(pair.uid):
                self.remove_timer(pair.uid)
                actions[pair.uid] = "Timer entfernt"

        # Verwaiste Timer entfernen (Paar geloescht).
        known = {pair.uid for pair in pairs}
        for orphan in self.list_managed_timers():
            if orphan not in known:
                self.remove_timer(orphan)
                actions[orphan] = "verwaister Timer entfernt"

        if self.available:
            self.daemon_reload()
            for uid in wanted:
                self.enable_timer(uid)

        return actions

    def list_managed_timers(self) -> list[str]:
        """UUIDs aller von dieser Anwendung geschriebenen Timer."""
        if not self._unit_dir.is_dir():
            return []
        result: list[str] = []
        for entry in sorted(self._unit_dir.glob(f"{UNIT_PREFIX}*.timer")):
            uid = entry.name[len(UNIT_PREFIX) : -len(".timer")]
            result.append(uid)
        return result

    def remove_all(self) -> list[str]:
        """Entfernt alle Timer und den Template-Service (fuer die Deinstallation)."""
        removed: list[str] = []
        for uid in self.list_managed_timers():
            if self.remove_timer(uid):
                removed.append(timer_unit_name(uid))

        template = self._unit_dir / SERVICE_TEMPLATE_NAME
        if template.exists():
            template.unlink()
            removed.append(SERVICE_TEMPLATE_NAME)

        if self.available:
            self.daemon_reload()
        return removed


__all__ = [
    "SYSTEMCTL_TIMEOUT",
    "UNIT_PREFIX",
    "SystemctlResult",
    "SystemdManager",
    "SystemdUnavailableError",
    "TimerStatus",
]
