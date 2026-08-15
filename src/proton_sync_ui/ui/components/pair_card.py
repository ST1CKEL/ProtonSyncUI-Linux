"""Moderne, lesbare Kartenzeile fuer ein Sync-Paar."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ...models.run import RunRecord  # noqa: E402
from ...models.sync_pair import ScheduleKind, SyncMode, SyncPair  # noqa: E402
from ...sync.engine import SyncProgress  # noqa: E402
from .status_badge import BadgeState, StatusBadge  # noqa: E402


class PairCardRow(Adw.ExpanderRow):
    """Moderne Sync-Paar-Zeile mit Status-Badge, Direktaktionen und Detailausklapper."""

    def __init__(
        self,
        pair: SyncPair,
        *,
        on_sync: Callable[[SyncPair], None],
        on_dry_run: Callable[[SyncPair], None],
        on_edit: Callable[[SyncPair], None],
        on_toggle: Callable[[SyncPair, bool], None],
        on_delete: Callable[[SyncPair], None],
        on_open_folder: Callable[[SyncPair], None],
    ) -> None:
        super().__init__()
        self.pair = pair
        self._on_sync = on_sync
        self._on_dry_run = on_dry_run
        self._on_edit = on_edit
        self._on_toggle = on_toggle
        self._on_delete = on_delete
        self._on_open_folder = on_open_folder
        self._busy = False

        self._setup_header()
        self._setup_details()

    def _setup_header(self) -> None:
        self.set_title(GLib.markup_escape_text(self.pair.name))
        arrow = (
            "⇄"
            if self.pair.sync_mode is SyncMode.BIDIRECTIONAL
            else ("→" if self.pair.sync_mode is SyncMode.UPLOAD_ONLY else "←")
        )
        self.set_subtitle(
            GLib.markup_escape_text(f"{self.pair.local_path}  {arrow}  {self.pair.remote_path}")
        )

        # Status Badge
        self._badge = StatusBadge.from_run_status(None, enabled=self.pair.enabled)
        self.add_prefix(self._badge)

        # Switch fuer Aktivierung
        self._switch = Gtk.Switch(active=self.pair.enabled, valign=Gtk.Align.CENTER)
        self._switch.connect("state-set", self._on_switch_toggled)
        self.add_suffix(self._switch)

        # Sync Button
        self._sync_btn = Gtk.Button(
            icon_name="emblem-synchronizing-symbolic",
            tooltip_text="Jetzt synchronisieren",
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        self._sync_btn.connect("clicked", lambda _: self._on_sync(self.pair))
        self.add_suffix(self._sync_btn)

        # Menue-Button
        self._menu_btn = Gtk.MenuButton(
            icon_name="view-more-symbolic",
            tooltip_text="Weitere Aktionen",
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        self._menu_btn.set_menu_model(self._build_menu())
        self.add_suffix(self._menu_btn)

    def _setup_details(self) -> None:
        # Fortschrittsbalken (waehrend Lauf)
        self._progress_bar = Gtk.ProgressBar(show_text=True, hexpand=True)
        self._progress_bar.set_margin_start(16)
        self._progress_bar.set_margin_end(16)
        self._progress_bar.set_margin_top(8)
        self._progress_bar.set_margin_bottom(8)
        self._progress_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        self._progress_row.set_child(self._progress_bar)
        self._progress_row.set_visible(False)
        self.add_row(self._progress_row)

        # Modus
        self._mode_row = Adw.ActionRow(title="Modus")
        self._mode_row.add_css_class("property")
        self.add_row(self._mode_row)

        # Lokaler Ordner
        self._local_row = Adw.ActionRow(title="Lokaler Ordner")
        self._local_row.add_css_class("property")
        open_folder_btn = Gtk.Button(
            icon_name="folder-open-symbolic",
            tooltip_text="Im Dateimanager oeffnen",
            valign=Gtk.Align.CENTER,
            css_classes=["flat"],
        )
        open_folder_btn.connect("clicked", lambda _: self._on_open_folder(self.pair))
        self._local_row.add_suffix(open_folder_btn)
        self.add_row(self._local_row)

        # Proton Drive Pfad
        self._remote_row = Adw.ActionRow(title="Proton-Drive-Ordner")
        self._remote_row.add_css_class("property")
        self.add_row(self._remote_row)

        # Zeitplan
        self._schedule_row = Adw.ActionRow(title="Zeitplan")
        self._schedule_row.add_css_class("property")
        self.add_row(self._schedule_row)

        # Letzter Lauf
        self._last_run_row = Adw.ActionRow(title="Letzter Lauf")
        self._last_run_row.add_css_class("property")
        self.add_row(self._last_run_row)

        # Detail-Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(12)
        btn_box.set_margin_bottom(12)
        btn_box.set_margin_start(16)
        btn_box.set_margin_end(16)

        dry_run_btn = Gtk.Button(label="Dry-Run (Vorschau)")
        dry_run_btn.connect("clicked", lambda _: self._on_dry_run(self.pair))
        btn_box.append(dry_run_btn)

        edit_btn = Gtk.Button(label="Bearbeiten")
        edit_btn.connect("clicked", lambda _: self._on_edit(self.pair))
        btn_box.append(edit_btn)

        delete_btn = Gtk.Button(label="Entfernen", css_classes=["destructive-action"])
        delete_btn.connect("clicked", lambda _: self._on_delete(self.pair))
        btn_box.append(delete_btn)

        action_row = Adw.ActionRow()
        action_row.set_child(btn_box)
        self.add_row(action_row)

        self.update_pair(self.pair)

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Dry-Run (Vorschau)", f"pair.dry-run::{self.pair.uid}")
        menu.append("Im Dateimanager oeffnen", f"pair.open-folder::{self.pair.uid}")
        menu.append("Bearbeiten", f"pair.edit::{self.pair.uid}")
        menu.append("Entfernen", f"pair.delete::{self.pair.uid}")
        return menu

    def _on_switch_toggled(self, _switch: Gtk.Switch, state: bool) -> bool:
        self._on_toggle(self.pair, state)
        self._badge.set_state(
            "Aktuell" if state else "Deaktiviert",
            BadgeState.SUCCESS if state else BadgeState.PAUSED,
        )
        return False

    def update_pair(self, pair: SyncPair) -> None:
        self.pair = pair
        self.set_title(GLib.markup_escape_text(pair.name))
        arrow = (
            "⇄"
            if pair.sync_mode is SyncMode.BIDIRECTIONAL
            else ("→" if pair.sync_mode is SyncMode.UPLOAD_ONLY else "←")
        )
        self.set_subtitle(
            GLib.markup_escape_text(f"{pair.local_path}  {arrow}  {pair.remote_path}")
        )

        self._mode_row.set_subtitle(pair.sync_mode.value.capitalize())
        self._local_row.set_subtitle(str(pair.local_path))
        self._remote_row.set_subtitle(pair.remote_path)

        if pair.schedule_kind is ScheduleKind.INTERVAL and pair.interval_minutes:
            schedule = f"alle {pair.interval_minutes} Minuten (systemd-Timer)"
        else:
            schedule = "manuell"
        if not pair.enabled:
            schedule += " -- deaktiviert"
        self._schedule_row.set_subtitle(schedule)

    def update_status(self, last_run: RunRecord | None, *, is_running: bool = False) -> None:
        self._busy = is_running
        self._sync_btn.set_sensitive(not is_running and self.pair.enabled)
        self._progress_row.set_visible(is_running)

        if is_running:
            self._badge.set_state("Synchronisiert…", BadgeState.RUNNING)
            self.set_expanded(True)
            return

        if not self.pair.enabled:
            self._badge.set_state("Deaktiviert", BadgeState.PAUSED)
            return

        if last_run is None:
            self._badge.set_state("Bereit", BadgeState.NEUTRAL)
            self._last_run_row.set_subtitle("Noch kein Durchgang erfolgt")
            return

        self._badge = StatusBadge.from_run_status(
            last_run.status, is_running=False, enabled=self.pair.enabled
        )
        ts = (
            last_run.finished_at.strftime("%d.%m.%Y %H:%M") if last_run.finished_at else "unbekannt"
        )
        kind = " (Dry-Run)" if last_run.dry_run else ""
        self._last_run_row.set_subtitle(
            f"{ts}{kind} -- {last_run.message or last_run.status.value}"
        )

    def update_progress(self, progress: SyncProgress) -> None:
        self._progress_row.set_visible(True)
        self._progress_bar.set_fraction(progress.fraction)
        self._progress_bar.set_text(progress.message)


__all__ = ["PairCardRow"]
