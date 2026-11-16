"""Aktivitaets-Historie fuer Laeufe, Uebertragungen und Ereignisse."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

from ...i18n import tr

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
            tooltip_text=tr("Aktivitaeten aktualisieren"),
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

        filter_label = Gtk.Label(label=tr("Filter:"), css_classes=["dim-label"])
        filter_bar.append(filter_label)

        self._filter_combo = Gtk.DropDown.new_from_strings(
            [tr("Alle"), tr("Erfolgreich"), tr("Fehler"), "Dry-Run"]
        )
        self._filter_combo.connect("notify::selected", self._on_filter_changed)
        filter_bar.append(self._filter_combo)
        self.append(filter_bar)

        # Stack
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)

        empty_page = Adw.StatusPage(
            icon_name="document-open-recent-symbolic",
            title=tr("Keine Aktivitaeten vorhanden"),
            description=tr(
                "Sobald Synchronisationslaeufe stattfinden, werden sie hier aufgefuehrt."
            ),
        )
        self._stack.add_named(empty_page, "empty")

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        self._group = Adw.PreferencesGroup(title=tr("Chronologischer Verlauf"))
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
        ts = (
            run.finished_at.astimezone().strftime("%d.%m.%Y %H:%M:%S")
            if run.finished_at
            else tr("Laeuft")
        )
        title = tr("Lauf vom {0}").format(ts)
        if run.dry_run:
            title += tr(" (Dry-Run Vorschau)")

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
            title=tr("Uebertragene Daten"),
            subtitle=(
                tr("Dateien: {0} uebertragen / {1} geplant · Upload: {2} · Download: {3}").format(
                    run.transferred_files,
                    run.planned_files,
                    format_size(run.uploaded_bytes),
                    format_size(run.downloaded_bytes),
                )
            ),
        )
        stat_row.add_css_class("property")
        row.add_row(stat_row)

        if run.duration_seconds is not None:
            dur_row = Adw.ActionRow(
                title=tr("Dauer"), subtitle=tr("{0:.1f} Sekunden").format(run.duration_seconds)
            )
            dur_row.add_css_class("property")
            row.add_row(dur_row)

        copy_btn = Gtk.Button(label=tr("Zusammenfassung kopieren"), css_classes=["flat"])
        copy_btn.connect("clicked", lambda _: self._copy_run_details(run))

        btn_row = Adw.ActionRow()
        btn_row.set_child(copy_btn)
        row.add_row(btn_row)

        return row

    def _copy_run_details(self, run: RunRecord) -> None:
        text = tr(
            "ProtonSyncUI Lauf:\nStatus: {0}\nZeit: {1}\nMeldung: {2}\nDateien "
            "geplant: {3}, uebertragen: {4}\nUpload: {5} B, Download: {6} B"
        ).format(
            run.status.value,
            run.finished_at.astimezone() if run.finished_at else "laeuft",
            run.message,
            run.planned_files,
            run.transferred_files,
            run.uploaded_bytes,
            run.downloaded_bytes,
        )
        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            if clipboard:
                clipboard.set(text)
                self._window.toast(tr("Lauf-Informationen kopiert."))

    def _on_filter_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        idx = combo.get_selected()
        modes = ["all", "success", "error", "dry_run"]
        self._filter_mode = modes[idx] if idx < len(modes) else "all"
        self.refresh()


__all__ = ["ActivityView"]
