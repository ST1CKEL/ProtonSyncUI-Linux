"""Einstellungen-Ansicht fuer globale Optionen, Datenschutz und CLI-Verbindung."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ... import APP_ID, APP_TITLE  # noqa: E402
from ...cli_adapter.adapter import ProtonDriveAdapter  # noqa: E402
from ...cli_adapter.capabilities import probe  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class SettingsView(Gtk.Box):
    """Einstellungen und globale Konfiguration."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._adapter = ProtonDriveAdapter()

        # HeaderBar
        header = Adw.HeaderBar()
        self.append(header)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        page = Adw.PreferencesPage()

        # 1. Allgemein & Systemstart
        general_group = Adw.PreferencesGroup(
            title="Allgemein und Autostart",
            description="Systemintegration, Infobereich (Tray) und Hintergrundstart.",
        )
        notif_row = Adw.SwitchRow(
            title="Desktop-Benachrichtigungen",
            subtitle="Bei Fehlern und Konflikten benachrichtigen",
        )
        notif_row.set_active(True)
        general_group.add(notif_row)

        self._autostart_row = Adw.SwitchRow(
            title="Beim Anmelden automatisch starten",
            subtitle="Startet ProtonSyncUI bei der Benutzeranmeldung",
        )
        self._autostart_row.set_active(self._is_autostart_enabled())
        self._autostart_row.connect("notify::active", self._on_autostart_changed)
        general_group.add(self._autostart_row)

        self._minimized_row = Adw.SwitchRow(
            title="Minimiert im Infobereich starten",
            subtitle="Startet wie ein Hintergrund-Dienst, ohne das Hauptfenster zu oeffnen",
        )
        self._minimized_row.set_active(self._is_autostart_minimized())
        self._minimized_row.set_sensitive(self._autostart_row.get_active())
        self._minimized_row.connect("notify::active", self._on_autostart_changed)
        general_group.add(self._minimized_row)

        tray_note = Adw.ActionRow(
            title="Infobereich (System Tray)",
            subtitle="Die App laeuft beim Schliessen minimiert im Hintergrund weiter.",
        )
        tray_note.add_css_class("property")
        general_group.add(tray_note)

        page.add(general_group)

        # 2. Synchronisation
        sync_group = Adw.PreferencesGroup(
            title="Synchronisation",
            description="Verhalten bei Konflikten und automatischen Laeufen.",
        )
        conflict_strategy_row = Adw.ComboRow(
            title="Standard-Konfliktstrategie",
            model=Gtk.StringList.new(
                [
                    "Immer fragen",
                    "Beide behalten (umbenennen)",
                    "Lokale bevorzugen",
                    "Cloud bevorzugen",
                ]
            ),
        )
        sync_group.add(conflict_strategy_row)
        page.add(sync_group)

        # 3. Datenschutz & Protokollierung
        privacy_group = Adw.PreferencesGroup(
            title="Datenschutz und Protokolle",
            description="Lokale Speicherung und Logdateien.",
        )
        retention_row = Adw.ComboRow(
            title="Log-Aufbewahrung",
            model=Gtk.StringList.new(["30 Tage", "60 Tage", "90 Tage", "Unbegrenzt"]),
        )
        privacy_group.add(retention_row)

        privacy_notice = Adw.ActionRow(
            title="Datenschutzhinweis",
            subtitle="ProtonSyncUI arbeitet 100% lokal und sendet keinerlei Nutzungsdaten.",
        )
        privacy_notice.add_css_class("property")
        privacy_group.add(privacy_notice)
        page.add(privacy_group)

        # 4. Proton Drive CLI
        cli_group = Adw.PreferencesGroup(
            title="Proton Drive CLI",
            description="Status und Authentifizierung der Schnittstelle.",
        )
        self._cli_status_row = Adw.ActionRow(title="CLI-Status", subtitle="Wird geprueft…")
        self._cli_status_row.add_css_class("property")
        cli_group.add(self._cli_status_row)

        test_cli_btn = Gtk.Button(label="Verbindung pruefen", css_classes=["flat"])
        test_cli_btn.connect("clicked", lambda _: self.check_cli())
        btn_row = Adw.ActionRow()
        btn_row.set_child(test_cli_btn)
        cli_group.add(btn_row)
        page.add(cli_group)

        scroll.set_child(page)
        self.append(scroll)

        self.check_cli()

    def _is_autostart_enabled(self) -> bool:
        autostart_file = Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
        return autostart_file.is_file()

    def _is_autostart_minimized(self) -> bool:
        autostart_file = Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
        if not autostart_file.is_file():
            return True
        content = autostart_file.read_text(encoding="utf-8", errors="ignore")
        return "--minimized" in content or "--hidden" in content

    def _on_autostart_changed(self, _row: Adw.SwitchRow, _param: object) -> None:
        enabled = self._autostart_row.get_active()
        minimized = self._minimized_row.get_active()
        self._minimized_row.set_sensitive(enabled)

        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_file = autostart_dir / f"{APP_ID}.desktop"

        if not enabled:
            if autostart_file.exists():
                autostart_file.unlink(missing_ok=True)
                self._window.toast("Autostart deaktiviert.")
            return

        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_src = Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
        content = desktop_src.read_text(encoding="utf-8") if desktop_src.exists() else ""

        exec_cmd = "Exec=proton-sync-ui-gui --minimized" if minimized else "Exec=proton-sync-ui-gui"
        if content:
            lines = [
                exec_cmd if line.startswith("Exec=") else line for line in content.splitlines()
            ]
            autostart_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            fallback = (
                f"[Desktop Entry]\nType=Application\nName={APP_TITLE}\n"
                f"{exec_cmd}\nIcon={APP_ID}\nTerminal=false\n"
            )
            autostart_file.write_text(fallback, encoding="utf-8")

        mode = " (minimiert)" if minimized else ""
        self._window.toast(f"Autostart{mode} aktiviert.")

    def check_cli(self) -> None:
        async def _check() -> None:
            caps = await probe(self._adapter)
            if not caps.available:
                self._cli_status_row.set_subtitle(f"Nicht verfuegbar: {caps.problem}")
            elif not caps.authenticated:
                ver = caps.cli_version or "?"
                self._cli_status_row.set_subtitle(f"CLI v{ver} gefunden, aber NICHT angemeldet.")
            else:
                ver = caps.cli_version or "?"
                self._cli_status_row.set_subtitle(f"CLI v{ver} bereit und angemeldet.")

        self._window._runner.submit_coroutine(_check)


__all__ = ["SettingsView"]
