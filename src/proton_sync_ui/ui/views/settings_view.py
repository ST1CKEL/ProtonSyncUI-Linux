"""Einstellungen: Autostart, Benachrichtigungen, Updates und CLI-Verbindung."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ... import __version__, autostart, settings, update  # noqa: E402
from ...cli_adapter.capabilities import Capabilities  # noqa: E402
from ...systemd.manager import SystemdManager  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class SettingsView(Gtk.Box):
    """Einstellungen und globale Konfiguration."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._loading = True

        self.append(Adw.HeaderBar())

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        page = Adw.PreferencesPage()
        page.add(self._build_general_group())
        page.add(self._build_update_group())
        page.add(self._build_cli_group())
        page.add(self._build_privacy_group())
        scroll.set_child(page)
        self.append(scroll)

        self._loading = False

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_general_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Allgemein und Autostart",
            description="Systemintegration, Infobereich und Hintergrundstart.",
        )

        self._autostart_row = Adw.SwitchRow(
            title="Beim Anmelden automatisch starten",
            subtitle="Startet ProtonSyncUI mit der Arbeitsflaeche (KDE Plasma, GNOME)",
        )
        self._autostart_row.set_active(autostart.is_enabled())
        self._autostart_row.connect("notify::active", self._on_autostart_changed)
        group.add(self._autostart_row)

        self._minimized_row = Adw.SwitchRow(
            title="Minimiert im Infobereich starten",
            subtitle="Beim Autostart nur das Symbol in der Kontrollleiste zeigen",
        )
        self._minimized_row.set_active(autostart.is_minimized())
        self._minimized_row.set_sensitive(self._autostart_row.get_active())
        self._minimized_row.connect("notify::active", self._on_autostart_changed)
        group.add(self._minimized_row)

        self._notif_row = Adw.SwitchRow(
            title="Desktop-Benachrichtigungen",
            subtitle="Bei fehlgeschlagenen Laeufen und verfuegbaren Updates benachrichtigen",
        )
        self._notif_row.set_active(self._window.settings.notifications)
        self._notif_row.connect("notify::active", self._on_setting_changed)
        group.add(self._notif_row)

        tray_note = Adw.ActionRow(
            title="Infobereich",
            subtitle=(
                "Beim Schliessen des Fensters laeuft ProtonSyncUI im Infobereich weiter. "
                "Beenden ueber das Symbol-Menue oder Strg+Q."
            ),
        )
        tray_note.add_css_class("property")
        group.add(tray_note)
        return group

    def _build_update_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Updates",
            description="Neue Versionen von ProtonSyncUI suchen und installieren.",
        )

        self._update_row = Adw.ActionRow(
            title=f"Installierte Version: {__version__}",
            subtitle="Noch nicht nach Updates gesucht.",
        )
        self._update_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self._update_spinner.set_visible(False)
        self._update_row.add_suffix(self._update_spinner)

        self._install_btn = Gtk.Button(
            label="Installieren", valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
        )
        self._install_btn.set_visible(False)
        self._install_btn.connect("clicked", lambda _b: self._window.install_update())
        self._update_row.add_suffix(self._install_btn)

        self._check_btn = Gtk.Button(label="Nach Updates suchen", valign=Gtk.Align.CENTER)
        self._check_btn.connect("clicked", lambda _b: self._window.check_for_updates(manual=True))
        self._update_row.add_suffix(self._check_btn)
        group.add(self._update_row)

        self._auto_update_row = Adw.SwitchRow(
            title="Automatisch nach Updates suchen",
            subtitle="Hoechstens einmal taeglich; installiert wird erst nach Bestaetigung",
        )
        self._auto_update_row.set_active(self._window.settings.auto_update_check)
        self._auto_update_row.connect("notify::active", self._on_setting_changed)
        group.add(self._auto_update_row)
        return group

    def _build_cli_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Proton Drive",
            description="Anmeldung und Zustand der offiziellen Proton-Drive-CLI.",
        )

        self._cli_status_row = Adw.ActionRow(title="Verbindung", subtitle="Wird geprueft …")
        self._cli_status_icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
        self._cli_status_row.add_prefix(self._cli_status_icon)

        self._login_btn = Gtk.Button(
            label="Anmelden", valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
        )
        self._login_btn.set_visible(False)
        self._login_btn.connect("clicked", lambda _b: self._window.start_login())
        self._cli_status_row.add_suffix(self._login_btn)

        check_btn = Gtk.Button(label="Erneut pruefen", valign=Gtk.Align.CENTER)
        check_btn.connect("clicked", lambda _b: self.check_cli())
        self._cli_status_row.add_suffix(check_btn)
        group.add(self._cli_status_row)

        self._cli_update_row = Adw.ActionRow(title="Neue CLI-Version verfuegbar")
        self._cli_update_row.add_prefix(
            Gtk.Image.new_from_icon_name("software-update-available-symbolic")
        )
        download_btn = Gtk.Button(label="Download-Seite", valign=Gtk.Align.CENTER)
        download_btn.connect(
            "clicked", lambda _b: self._window.open_uri(update.PROTON_CLI_DOWNLOAD_URL)
        )
        self._cli_update_row.add_suffix(download_btn)
        self._cli_update_row.set_visible(False)
        group.add(self._cli_update_row)
        return group

    def _build_privacy_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Datenschutz")
        notice = Adw.ActionRow(
            title="Keine Nutzungsdaten",
            subtitle=(
                "ProtonSyncUI arbeitet lokal und sendet keine Nutzungsdaten. Die Update-Suche "
                "ruft lediglich die aktuelle Versionsnummer bei GitHub ab; die Anmeldung "
                "geschieht ausschliesslich in der Proton-Drive-CLI."
            ),
        )
        notice.add_css_class("property")
        group.add(notice)
        return group

    # ------------------------------------------------------------------
    # Rueckmeldungen aus dem Fenster
    # ------------------------------------------------------------------

    def check_cli(self) -> None:
        """Stoesst eine neue Pruefung der CLI an."""
        self._cli_status_row.set_subtitle("Wird geprueft …")
        self._window.check_cli()

    def show_capabilities(self, caps: Capabilities) -> None:
        """Zeigt das Ergebnis der CLI-Pruefung (im Hauptthread aufzurufen)."""
        version = caps.cli_version or "?"
        if not caps.available:
            icon, text = "dialog-error-symbolic", "Die Proton-Drive-CLI wurde nicht gefunden."
        elif caps.authenticated:
            icon, text = "emblem-ok-symbolic", f"Angemeldet (CLI {version})."
        elif caps.auth_check_failed:
            icon = "dialog-warning-symbolic"
            text = f"CLI {version} gefunden; Anmeldezustand nicht pruefbar (keine Verbindung?)."
        else:
            icon, text = "dialog-error-symbolic", f"Nicht angemeldet (CLI {version})."

        self._cli_status_icon.set_from_icon_name(icon)
        self._cli_status_row.set_subtitle(GLib.markup_escape_text(text))
        self._login_btn.set_visible(caps.needs_login)

        self._cli_update_row.set_visible(bool(caps.newer_cli_version))
        if caps.newer_cli_version:
            self._cli_update_row.set_subtitle(
                GLib.markup_escape_text(
                    f"Version {caps.newer_cli_version} (installiert: {version}). "
                    "Die CLI wird von Proton bereitgestellt und manuell aktualisiert."
                )
            )

    def show_update_state(self, text: str, *, busy: bool = False, available: bool = False) -> None:
        """Zeigt den Stand der Update-Suche bzw. -Installation."""
        self._update_row.set_subtitle(GLib.markup_escape_text(text))
        self._update_spinner.set_visible(busy)
        self._update_spinner.set_spinning(busy)
        self._check_btn.set_sensitive(not busy)
        self._install_btn.set_visible(available and not busy)

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------

    def _on_setting_changed(self, _row: Adw.SwitchRow, _param: object) -> None:
        if self._loading:
            return
        current = self._window.settings
        current.notifications = self._notif_row.get_active()
        current.auto_update_check = self._auto_update_row.get_active()
        settings.save(current)

    def _on_autostart_changed(self, _row: Adw.SwitchRow, _param: object) -> None:
        if self._loading:
            return
        enabled = self._autostart_row.get_active()
        minimized = self._minimized_row.get_active()
        self._minimized_row.set_sensitive(enabled)

        try:
            if enabled:
                autostart.enable(minimized=minimized)
                mode = " (minimiert)" if minimized else ""
                self._window.toast(f"Autostart{mode} aktiviert.")
            elif autostart.disable():
                self._window.toast("Autostart deaktiviert.")
        except OSError as error:
            self._window.toast(f"Autostart konnte nicht geaendert werden: {error}")
            return

        # systemd erzeugt die Autostart-Units aus dem Verzeichnis neu.
        with contextlib.suppress(Exception):
            SystemdManager().daemon_reload()


__all__ = ["SettingsView"]
