"""Status-Badge / Pill-Widget fuer den visuellen Zustand."""

from __future__ import annotations

from enum import StrEnum

import gi

from ...i18n import tr

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from ...models.run import RunStatus  # noqa: E402


class BadgeState(StrEnum):
    """Visuelle Statuszustaende."""

    SUCCESS = "success"
    RUNNING = "running"
    PAUSED = "paused"
    WARNING = "warning"
    ERROR = "error"
    CONFLICT = "conflict"
    OFFLINE = "offline"
    NEUTRAL = "neutral"


class StatusBadge(Gtk.Label):
    """Abgerundete Pill-Statusanzeige nach libadwaita-Stil."""

    def __init__(self, label: str = "Aktuell", state: BadgeState = BadgeState.SUCCESS) -> None:
        super().__init__(label=label)
        self.add_css_class("pill")
        self.add_css_class("heading")
        self.set_valign(Gtk.Align.CENTER)
        self.set_state(label, state)

    def set_state(self, label: str, state: BadgeState) -> None:
        self.set_label(label)
        for cls in ("success", "accent", "warning", "error", "dim-label"):
            self.remove_css_class(cls)

        match state:
            case BadgeState.SUCCESS:
                self.add_css_class("success")
            case BadgeState.RUNNING:
                self.add_css_class("accent")
            case BadgeState.WARNING | BadgeState.CONFLICT:
                self.add_css_class("warning")
            case BadgeState.ERROR:
                self.add_css_class("error")
            case BadgeState.PAUSED | BadgeState.NEUTRAL | BadgeState.OFFLINE:
                self.add_css_class("dim-label")

    @classmethod
    def from_run_status(
        cls, status: RunStatus | None, *, is_running: bool = False, enabled: bool = True
    ) -> StatusBadge:
        if is_running:
            return cls(tr("Synchronisiert…"), BadgeState.RUNNING)
        if not enabled:
            return cls(tr("Deaktiviert"), BadgeState.PAUSED)
        if status is None:
            return cls(tr("Bereit"), BadgeState.NEUTRAL)

        match status:
            case RunStatus.SUCCESS:
                return cls(tr("Aktuell"), BadgeState.SUCCESS)
            case RunStatus.WARNING:
                return cls(tr("Warnung"), BadgeState.WARNING)
            case RunStatus.ERROR:
                return cls(tr("Fehler"), BadgeState.ERROR)
            case RunStatus.CANCELLED:
                return cls(tr("Abgebrochen"), BadgeState.PAUSED)
            case _:
                return cls(status.value, BadgeState.NEUTRAL)


__all__ = ["BadgeState", "StatusBadge"]
