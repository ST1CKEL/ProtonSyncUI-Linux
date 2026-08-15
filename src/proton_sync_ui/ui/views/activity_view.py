"""Aktivitaets-Historie fuer Laeufe, Uebertragungen und Ereignisse."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ...models.run import RunRecord, RunStatus  # noqa: E402
from ...paths import format_size  # noqa: E402
from ...services.contracts import ActivityRepository  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class ActivityView(Gtk.Box):
    """Chronologische Verlaufsuersicht aller Synchronisationslaeufe."""

    def __init__(self, window: MainWindow, activity_repo: ActivityRepository) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._activity_repo = activity_repo
        self._filter_mode = "all"
        self._rows: list[Gtk.Widget] = []

        # HeaderBar
        header = Adw.HeaderBar()
        refresh_btn = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Aktivitaeten aktualisieren",
            css_classes=["flat"],
        )
        refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(refresh_btn)
        self.append(header)

        # Filterleiste
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        filter_bar.set_margin_top(12)
        filter_bar.set_margin_bottom(12)
        filter_bar.set_margin_start(16)
        filter_bar.set_margin_end(16)

        filter_label = Gtk.Label(label="Filter:", css_classes=["dim-label"])
        filter_bar.append(filter_label)

        self._filter_combo = Gtk.DropDown.new_from_strings(
            ["Alle", "Erfolgreich", "Fehler", "Dry-Run"]
        )
        self._filter_combo.connect("notify::selected", self._on_filter_changed)
        filter_bar.append(self._filter_combo)
        self.append(filter_bar)

        # Stack
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)

        empty_page = Adw.StatusPage(
            icon_name="document-open-recent-symbolic",
            title="Keine Aktivitaeten vorhanden",
            description="Sobald Synchronisationslaeufe stattfinden, werden sie hier aufgefuehrt.",
        )
        self._stack.add_named(empty_page, "empty")

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        self._group = Adw.PreferencesGroup(title="Chronologischer Verlauf")
        clamp.set_child(self._group)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        self.append(self._stack)

    def refresh(self) -> None:
        runs = self._activity_repo.list_recent_runs(limit=100)
        filtered_runs: list[RunRecord] = []

        for run in runs:
            if self._filter_mode == "success" and run.status is not RunStatus.SUCCESS:
                continue
            if self._filter_mode == "error" and run.status is not RunStatus.ERROR:
                continue
            if self._filter_mode == "dry_run" and not run.dry_run:
                continue
            filtered_runs.append(run)

        for row in self._rows:
            self._group.remove(row)
        self._rows.clear()

        if not filtered_runs:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for run in filtered_runs:
            row = self._create_run_row(run)
            self._group.add(row)
            self._rows.append(row)

    def _create_run_row(self, run: RunRecord) -> Adw.ExpanderRow:
        ts = run.finished_at.strftime("%d.%m.%Y %H:%M:%S") if run.finished_at else "Laeuft"
        title = f"Lauf vom {ts}"
        if run.dry_run:
            title += " (Dry-Run Vorschau)"

        row = Adw.ExpanderRow(
            title=GLib.markup_escape_text(title),
            subtitle=GLib.markup_escape_text(run.message or run.summary_line()),
        )

        icon_name = (
            "emblem-ok-symbolic"
            if run.status is RunStatus.SUCCESS
            else (
                "dialog-warning-symbolic"
                if run.status is RunStatus.WARNING
                else "dialog-error-symbolic"
            )
        )
        row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))

        # Details
        stat_row = Adw.ActionRow(
            title="Uebertragene Daten",
            subtitle=(
                f"Dateien: {run.transferred_files} uebertragen / {run.planned_files} geplant · "
                f"Upload: {format_size(run.uploaded_bytes)} · "
                f"Download: {format_size(run.downloaded_bytes)}"
            ),
        )
        stat_row.add_css_class("property")
        row.add_row(stat_row)

        if run.duration_seconds is not None:
            dur_row = Adw.ActionRow(title="Dauer", subtitle=f"{run.duration_seconds:.1f} Sekunden")
            dur_row.add_css_class("property")
            row.add_row(dur_row)

        copy_btn = Gtk.Button(label="Zusammenfassung kopieren", css_classes=["flat"])
        copy_btn.connect("clicked", lambda _: self._copy_run_details(run))

        btn_row = Adw.ActionRow()
        btn_row.set_child(copy_btn)
        row.add_row(btn_row)

        return row

    def _copy_run_details(self, run: RunRecord) -> None:
        text = (
            f"ProtonSyncUI Lauf:\n"
            f"Status: {run.status.value}\n"
            f"Zeit: {run.finished_at}\n"
            f"Meldung: {run.message}\n"
            f"Dateien geplant: {run.planned_files}, uebertragen: {run.transferred_files}\n"
            f"Upload: {run.uploaded_bytes} B, Download: {run.downloaded_bytes} B"
        )
        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            if clipboard:
                clipboard.set(text)
                self._window.toast("Lauf-Informationen kopiert.")

    def _on_filter_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        idx = combo.get_selected()
        modes = ["all", "success", "error", "dry_run"]
        self._filter_mode = modes[idx] if idx < len(modes) else "all"
        self.refresh()


__all__ = ["ActivityView"]
