"""Erzeugung der systemd-Unit-Dateien.

Aufbau: ein *statischer* Template-Service ``proton-sync-ui@.service``, in dem
``%i`` die UUID des Sync-Paars ist, und je Paar ein *generierter* Timer. Nur
der Timer muss paarspezifisch sein, weil das Intervall variiert -- der
Service ist fuer alle Paare identisch.

Die Funktionen hier erzeugen ausschliesslich Text und beruehren weder
Dateisystem noch ``systemctl``. Damit sind sie ohne laufendes systemd
testbar.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Final

from ..models.sync_pair import SyncPair

#: Name des Template-Service. Instanzen heissen proton-sync-ui@<uuid>.service.
SERVICE_TEMPLATE_NAME: Final = "proton-sync-ui@.service"

#: Ziel der Documentation-Zeile. Bewusst eine URL und keine Manpage:
#: ``systemd-analyze verify`` beanstandet einen man:-Verweis, zu dem keine
#: Handbuchseite installiert ist.
DOCUMENTATION_URL: Final = "https://github.com/protonsyncui/proton-sync-ui#systemd-timer"

#: UUIDs bestehen nur aus Hexziffern und Bindestrichen und sind damit ohne
#: Maskierung als systemd-Instanzname verwendbar. Alles andere wird abgelehnt.
_INSTANCE_RE: Final = re.compile(r"^[0-9a-fA-F-]{8,64}$")


class UnitError(ValueError):
    """Eine Unit konnte nicht erzeugt werden."""


def validate_instance(uid: str) -> str:
    """Stellt sicher, dass eine UUID sicher als Instanzname taugt."""
    if not _INSTANCE_RE.match(uid):
        raise UnitError(
            f"'{uid}' ist keine gueltige Sync-Paar-Kennung und kann nicht als "
            "systemd-Instanzname verwendet werden."
        )
    return uid


def service_unit_name(uid: str) -> str:
    """Name der Service-Instanz eines Paars."""
    return f"proton-sync-ui@{validate_instance(uid)}.service"


def timer_unit_name(uid: str) -> str:
    """Name der Timer-Instanz eines Paars."""
    return f"proton-sync-ui@{validate_instance(uid)}.timer"


def find_executable() -> str:
    """Ermittelt den absoluten Pfad der installierten Kommandozeile.

    systemd fuehrt Units ohne die PATH-Erweiterungen einer Login-Shell aus,
    deshalb wird der Pfad fest in die Unit geschrieben. Bei einer Installation
    in einer virtuellen Umgebung ist das ohnehin der einzige verlaessliche Weg.
    """
    found = shutil.which("proton-sync-ui")
    if found:
        return found

    # Fallback: neben dem laufenden Interpreter (venv-Installation).
    candidate = Path(sys.executable).parent / "proton-sync-ui"
    if candidate.is_file():
        return str(candidate)

    # Letzter Ausweg: als Modul starten.
    return f"{sys.executable} -m proton_sync_ui"


def service_template_text(*, executable: str | None = None) -> str:
    """Inhalt des Template-Service.

    Bewusst zurueckhaltend abgeschottet: Die Proton-Drive-CLI braucht Zugriff
    auf das Benutzerverzeichnis und den Sitzungsbus fuer ihre eigene
    Anmeldeverwaltung. Ein strenges Sandboxing (``PrivateHome``,
    ``ProtectHome``) wuerde die Anmeldung unbrauchbar machen.
    """
    binary = executable if executable is not None else find_executable()
    return f"""\
[Unit]
Description=ProtonSyncUI -- Backup-Lauf fuer Sync-Paar %i
Documentation={DOCUMENTATION_URL}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={binary} sync %i

# Backups sollen die interaktive Arbeit nicht ausbremsen.
Nice=10
IOSchedulingClass=idle
CPUSchedulingPolicy=idle

# Ein Lauf darf lange dauern (grosse Dateien, langsame Leitung).
TimeoutStartSec=infinity

NoNewPrivileges=yes

# Erfolgreiche und teilweise erfolgreiche Laeufe (Code 1) gelten als
# abgeschlossen; nur echte Fehler sollen die Unit als "failed" markieren.
SuccessExitStatus=0 1
"""


def timer_unit_text(pair: SyncPair) -> str:
    """Inhalt der Timer-Unit eines Paars.

    ``OnUnitInactiveSec`` misst ab dem *Ende* des letzten Laufs. Damit kann
    sich ein langer Lauf nicht mit dem naechsten ueberschneiden -- die
    Datenbanksperre faengt das zwar ohnehin ab, aber gar nicht erst zu starten
    ist sauberer.
    """
    if pair.schedule_kind.value != "interval" or pair.interval_minutes is None:
        raise UnitError(
            f"Fuer das Sync-Paar '{pair.name}' ist kein Intervall konfiguriert; "
            "es wird kein Timer erzeugt."
        )
    validate_instance(pair.uid)
    interval = pair.interval_minutes

    return f"""\
[Unit]
Description=ProtonSyncUI -- Zeitplan fuer "{_escape_description(pair.name)}"
Documentation={DOCUMENTATION_URL}

[Timer]
Unit={service_unit_name(pair.uid)}
# Erster Lauf kurz nach dem Anmelden bzw. Systemstart.
OnStartupSec=5min
# Danach {interval} Minuten nach dem Ende des vorherigen Laufs.
OnUnitInactiveSec={interval}min
AccuracySec=1min
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
"""


def _escape_description(text: str) -> str:
    """Entschaerft Zeilenumbrueche in Beschreibungen."""
    return " ".join(text.split())


__all__ = [
    "SERVICE_TEMPLATE_NAME",
    "UnitError",
    "find_executable",
    "service_template_text",
    "service_unit_name",
    "timer_unit_name",
    "timer_unit_text",
    "validate_instance",
]
