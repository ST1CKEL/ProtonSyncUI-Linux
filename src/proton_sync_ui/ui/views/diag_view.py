"""Diagnose-, Hilfe- und Systemuebersicht."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ... import APP_TITLE, __version__  # noqa: E402
from ...paths import log_file_path  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class DiagnosticsView(Gtk.Box):
    """Diagnose-, Log- und Hilfe-Ansicht."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window

        # HeaderBar
        header = Adw.HeaderBar()
        self.append(header)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        page = Adw.PreferencesPage()

        # 1. System & Diagnose
        diag_group = Adw.PreferencesGroup(
            title="Systemdiagnose",
            description="Ueberpruefe Hintergrunddienste und Systemd-Timer.",
        )

        sync_systemd_row = Adw.ActionRow(
            title="Systemd-Timer abgleichen",
            subtitle="Richtet Hintergrund-Timer fuer alle konfigurierten Intervalle ein.",
        )
        sync_systemd_btn = Gtk.Button(label="Timer aktualisieren", css_classes=["flat"])
        sync_systemd_btn.connect("clicked", lambda _: self._window.sync_systemd_units())
        sync_systemd_row.add_suffix(sync_systemd_btn)
        diag_group.add(sync_systemd_row)

        copy_report_row = Adw.ActionRow(
            title="Diagnosebericht erstellen",
            subtitle="Kopiert System-, Versions- und Statusinformationen fuer Support.",
        )
        copy_report_btn = Gtk.Button(label="Bericht kopieren", css_classes=["flat"])
        copy_report_btn.connect("clicked", lambda _: self._copy_diagnostics())
        copy_report_row.add_suffix(copy_report_btn)
        diag_group.add(copy_report_row)
        page.add(diag_group)

        # 2. Protokolle
        log_group = Adw.PreferencesGroup(
            title="Protokolle und Logs",
            description="Detailprotokolle der Hintergrundprozesse.",
        )
        log_row = Adw.ActionRow(
            title="Logdatei oeffnen",
            subtitle=str(log_file_path()),
        )
        view_log_btn = Gtk.Button(label="Log anzeigen", css_classes=["flat"])
        view_log_btn.connect("clicked", lambda _: self._window.show_log())
        log_row.add_suffix(view_log_btn)
        log_group.add(log_row)
        page.add(log_group)

        # 3. Ueber die App
        about_group = Adw.PreferencesGroup(title="Ueber ProtonSyncUI")
        about_row = Adw.ActionRow(
            title=f"{APP_TITLE} {__version__}",
            subtitle="2-Wege-Synchronisation mit Proton Drive · entwickelt von Stickelbroeck Labs",
        )
        about_btn = Gtk.Button(label="Info & Lizenz", css_classes=["flat"])
        about_btn.connect("clicked", lambda _: self._window.show_about())
        about_row.add_suffix(about_btn)
        about_group.add(about_row)
        page.add(about_group)

        scroll.set_child(page)
        self.append(scroll)

    def _copy_diagnostics(self) -> None:
        report = (
            f"ProtonSyncUI Diagnostics Report\n"
            f"Version: {__version__}\n"
            f"Log File: {log_file_path()}\n"
            f"OS: Linux Fedora\n"
        )
        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            if clipboard:
                clipboard.set(report)
                self._window.toast("Diagnosebericht in Zwischenablage kopiert.")


__all__ = ["DiagnosticsView"]
