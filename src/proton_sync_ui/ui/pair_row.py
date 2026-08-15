"""Darstellung eines Sync-Paars in der Hauptliste."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402 -- muss nach require_version stehen

from ..models.run import (  # noqa: E402
    PairStatus,
    RunRecord,
    pair_status_from_run,
    pair_status_label,
)
from ..models.sync_pair import ScheduleKind, SyncMode, SyncPair, sync_mode_label  # noqa: E402
from ..sync.engine import SyncProgress  # noqa: E402

#: Zuordnung Status -> CSS-Klasse von libadwaita.
_STATUS_CSS: dict[PairStatus, str] = {
    PairStatus.IDLE: "dim-label",
    PairStatus.WAITING: "dim-label",
    PairStatus.RUNNING: "accent",
    PairStatus.SUCCESS: "success",
    PairStatus.WARNING: "warning",
    PairStatus.ERROR: "error",
    PairStatus.DISABLED: "dim-label",
}

_ALL_STATUS_CSS = frozenset(_STATUS_CSS.values())


def format_size(num_bytes: int) -> str:
    """Formatiert eine Byte-Anzahl kompakt."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def format_timestamp(value: datetime | None) -> str:
    """Formatiert einen Zeitstempel in lokaler Zeit."""
    if value is None:
        return "nie"
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


class PairRow(Adw.ExpanderRow):
    """Eine aufklappbare Zeile mit Status, Kennzahlen und Aktionen."""

    __gtype_name__ = "ProtonSyncUIPairRow"

    def __init__(
        self,
        pair: SyncPair,
        *,
        on_sync: Callable[[SyncPair], None],
        on_dry_run: Callable[[SyncPair], None],
        on_edit: Callable[[SyncPair], None],
        on_toggle_enabled: Callable[[SyncPair, bool], None],
        on_show_log: Callable[[SyncPair], None],
        on_cancel: Callable[[SyncPair], None],
        on_delete: Callable[[SyncPair], None],
    ) -> None:
        super().__init__()
        self.pair = pair
        self._on_sync = on_sync
        self._on_dry_run = on_dry_run
        self._on_edit = on_edit
        self._on_toggle_enabled = on_toggle_enabled
        self._on_show_log = on_show_log
        self._on_cancel = on_cancel
        self._on_delete = on_delete
        self._busy = False

        self._status_label = Gtk.Label(xalign=1.0)
        self._status_label.add_css_class("dim-label")
        self.add_suffix(self._status_label)

        self._build_detail_rows()
        self._build_progress_row()
        self._build_action_row()

        self.update_pair(pair)

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_detail_rows(self) -> None:
        """Zeilen mit Pfaden, Zeitplan und Kennzahlen."""
        self._mode_row = Adw.ActionRow(title="Modus")
        self._mode_row.add_css_class("property")
        self.add_row(self._mode_row)

        self._source_row = Adw.ActionRow(title="Lokaler Ordner")
        self._source_row.add_css_class("property")
        self.add_row(self._source_row)

        self._target_row = Adw.ActionRow(title="Proton-Drive-Ordner")
        self._target_row.add_css_class("property")
        self.add_row(self._target_row)

        self._schedule_row = Adw.ActionRow(title="Zeitplan")
        self._schedule_row.add_css_class("property")
        self.add_row(self._schedule_row)

        self._last_run_row = Adw.ActionRow(title="Letzter Lauf")
        self._last_run_row.add_css_class("property")
        self.add_row(self._last_run_row)

        self._counts_row = Adw.ActionRow(title="Dateien")
        self._counts_row.add_css_class("property")
        self.add_row(self._counts_row)

    def _build_progress_row(self) -> None:
        """Fortschrittsbalken, nur waehrend eines Laufs sichtbar."""
        self._progress_bar = Gtk.ProgressBar(show_text=True, hexpand=True)
        self._progress_bar.set_margin_top(6)
        self._progress_bar.set_margin_bottom(6)
        self._progress_bar.set_margin_start(12)
        self._progress_bar.set_margin_end(12)

        self._progress_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        self._progress_row.set_child(self._progress_bar)
        self._progress_row.set_visible(False)
        self.add_row(self._progress_row)

    def _build_action_row(self) -> None:
        """Schaltflaechen der Zeile."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_halign(Gtk.Align.START)

        self._sync_button = Gtk.Button(label="Jetzt starten")
        self._sync_button.add_css_class("suggested-action")
        self._sync_button.connect("clicked", lambda _b: self._on_sync(self.pair))
        box.append(self._sync_button)

        self._dry_run_button = Gtk.Button(label="Dry-Run")
        self._dry_run_button.set_tooltip_text(
            "Zeigt, was uebertragen wuerde, ohne etwas zu uebertragen."
        )
        self._dry_run_button.connect("clicked", lambda _b: self._on_dry_run(self.pair))
        box.append(self._dry_run_button)

        self._cancel_button = Gtk.Button(label="Abbrechen")
        self._cancel_button.add_css_class("destructive-action")
        self._cancel_button.set_visible(False)
        self._cancel_button.connect("clicked", lambda _b: self._on_cancel(self.pair))
        box.append(self._cancel_button)

        self._edit_button = Gtk.Button(label="Bearbeiten")
        self._edit_button.connect("clicked", lambda _b: self._on_edit(self.pair))
        box.append(self._edit_button)

        self._enable_button = Gtk.Button()
        self._enable_button.connect("clicked", self._toggle_enabled)
        box.append(self._enable_button)

        log_button = Gtk.Button(label="Log anzeigen")
        log_button.connect("clicked", lambda _b: self._on_show_log(self.pair))
        box.append(log_button)

        delete_button = Gtk.Button(icon_name="user-trash-symbolic")
        delete_button.set_tooltip_text(
            "Sync-Paar entfernen. Dateien bei Proton Drive bleiben erhalten."
        )
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", lambda _b: self._on_delete(self.pair))
        box.append(delete_button)

        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.set_child(box)
        self.add_row(row)

    # ------------------------------------------------------------------
    # Aktualisierung
    # ------------------------------------------------------------------

    def update_pair(self, pair: SyncPair) -> None:
        """Uebernimmt geaenderte Stammdaten."""
        self.pair = pair
        # Adw-Zeilen interpretieren Pango-Markup: ein "&" im Dateinamen wuerde
        # die Darstellung sonst zerlegen.
        self.set_title(GLib.markup_escape_text(pair.name))
        if pair.sync_mode is SyncMode.BIDIRECTIONAL:
            arrow = "⇄"
        elif pair.sync_mode is SyncMode.UPLOAD_ONLY:
            arrow = "→"
        else:
            arrow = "←"
        self.set_subtitle(
            GLib.markup_escape_text(f"{pair.local_path}  {arrow}  {pair.remote_path}")
        )

        self._mode_row.set_subtitle(sync_mode_label(pair.sync_mode))
        self._source_row.set_subtitle(GLib.markup_escape_text(str(pair.local_path)))
        self._target_row.set_subtitle(GLib.markup_escape_text(pair.remote_path))

        if pair.schedule_kind is ScheduleKind.INTERVAL and pair.interval_minutes:
            schedule = f"alle {pair.interval_minutes} Minuten (systemd-Timer)"
        else:
            schedule = "manuell"
        if not pair.enabled:
            schedule += " -- deaktiviert"
        self._schedule_row.set_subtitle(schedule)

        self._enable_button.set_label("Deaktivieren" if pair.enabled else "Aktivieren")
        self._sync_button.set_sensitive(pair.enabled and not self._busy)
        self._dry_run_button.set_sensitive(not self._busy)

    def update_run(self, record: RunRecord | None, *, running: bool = False) -> None:
        """Uebernimmt das Ergebnis des letzten Laufs."""
        if running:
            self._set_status(PairStatus.RUNNING)
        else:
            status = pair_status_from_run(
                record.status if record else None, enabled=self.pair.enabled
            )
            self._set_status(status)

        if record is None:
            self._last_run_row.set_subtitle("nie")
            self._counts_row.set_subtitle("--")
            return

        kind = "Dry-Run" if record.dry_run else "Lauf"
        duration = record.duration_seconds
        suffix = f", {duration:.1f}s" if duration is not None else ""
        self._last_run_row.set_subtitle(f"{format_timestamp(record.started_at)} ({kind}{suffix})")

        parts = [f"geplant {record.planned_files}"]
        if record.downloaded_files > 0:
            parts.append(f"heruntergeladen {record.downloaded_files}")
        if record.uploaded_files > 0 or record.downloaded_files == 0:
            parts.append(f"hochgeladen {record.uploaded_files}")
        parts.append(f"fehlgeschlagen {record.failed_files}")
        parts.append(f"uebersprungen {record.skipped_files}")
        total_bytes = record.uploaded_bytes + record.downloaded_bytes
        if total_bytes:
            parts.append(format_size(total_bytes))
        if record.local_deletions:
            parts.append(f"{record.local_deletions} lokal geloescht (Proton Drive unveraendert)")
        self._counts_row.set_subtitle(" · ".join(parts))

    def update_progress(self, progress: SyncProgress) -> None:
        """Aktualisiert den Fortschrittsbalken waehrend eines Laufs."""
        self._progress_row.set_visible(True)
        self._progress_bar.set_fraction(progress.fraction)
        if progress.relative_path:
            text = f"{progress.current + 1}/{progress.total}: {progress.relative_path}"
        elif progress.message:
            text = progress.message
        else:
            text = "…"
        self._progress_bar.set_text(_ellipsize(text, 70))

    def set_busy(self, busy: bool) -> None:
        """Schaltet die Zeile zwischen Ruhe- und Laufzustand um."""
        self._busy = busy
        self._sync_button.set_sensitive(self.pair.enabled and not busy)
        self._dry_run_button.set_sensitive(not busy)
        self._edit_button.set_sensitive(not busy)
        self._enable_button.set_sensitive(not busy)
        self._cancel_button.set_visible(busy)
        if busy:
            self._progress_row.set_visible(True)
            self._progress_bar.set_fraction(0.0)
            self._progress_bar.set_text("Vorbereitung…")
            self._set_status(PairStatus.RUNNING)
        else:
            self._progress_row.set_visible(False)

    def _set_status(self, status: PairStatus) -> None:
        """Setzt Text und Farbe des Statuszeichens."""
        self._status_label.set_label(pair_status_label(status))
        for css in _ALL_STATUS_CSS:
            self._status_label.remove_css_class(css)
        self._status_label.add_css_class(_STATUS_CSS.get(status, "dim-label"))

    def _toggle_enabled(self, _button: Gtk.Button) -> None:
        self._on_toggle_enabled(self.pair, not self.pair.enabled)


def _ellipsize(text: str, limit: int) -> str:
    """Kuerzt zu langen Text in der Mitte."""
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return f"{text[:head]}…{text[-tail:]}"


__all__ = ["PairRow", "format_size", "format_timestamp"]
