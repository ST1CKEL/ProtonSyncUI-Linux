"""systemd-Integration fuer zeitgesteuerte Laeufe (``systemd --user``)."""

from __future__ import annotations

from .manager import SystemctlResult, SystemdManager, SystemdUnavailableError, TimerStatus
from .units import (
    SERVICE_TEMPLATE_NAME,
    UnitError,
    service_template_text,
    service_unit_name,
    timer_unit_name,
    timer_unit_text,
)

__all__ = [
    "SERVICE_TEMPLATE_NAME",
    "SystemctlResult",
    "SystemdManager",
    "SystemdUnavailableError",
    "TimerStatus",
    "UnitError",
    "service_template_text",
    "service_unit_name",
    "timer_unit_name",
    "timer_unit_text",
]
