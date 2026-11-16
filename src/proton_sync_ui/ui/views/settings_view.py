"""Einstellungen: Autostart, Benachrichtigungen, Updates und CLI-Verbindung."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import gi

from ...i18n import tr

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ... import __version__, autostart, i18n, settings, update  # noqa: E402
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
            title=tr("Allgemein und Autostart"),
            description=tr("Systemintegration, Infobereich und Hintergrundstart."),
        )

        self._language_row = Adw.ComboRow(
            title=tr("Sprache"),
            subtitle=tr("Gilt fuer Fenster, Infobereich und Benachrichtigungen"),
            model=Gtk.StringList.new(
                [tr("Automatisch (Sprache des Systems)"), *i18n.LANGUAGES.values()]
            ),
        )
        codes = ("", *i18n.LANGUAGES)
        stored = self._window.settings.language
        self._language_row.set_selected(codes.index(stored) if stored in codes else 0)
        self._language_row.connect("notify::selected", self._on_language_changed)
        group.add(self._language_row)

        self._autostart_row = Adw.SwitchRow(
            title=tr("Beim Anmelden automatisch starten"),
            subtitle=tr("Startet ProtonSyncUI mit der Arbeitsflaeche (KDE Plasma, GNOME)"),
        )
        self._autostart_row.set_active(autostart.is_enabled())
        self._autostart_row.connect("notify::active", self._on_autostart_changed)
        group.add(self._autostart_row)

        self._minimized_row = Adw.SwitchRow(
            title=tr("Minimiert im Infobereich starten"),
            subtitle=tr("Beim Autostart nur das Symbol in der Kontrollleiste zeigen"),
        )
        self._minimized_row.set_active(autostart.is_minimized())
        self._minimized_row.set_sensitive(self._autostart_row.get_active())
        self._minimized_row.connect("notify::active", self._on_autostart_changed)
        group.add(self._minimized_row)

        self._notif_row = Adw.SwitchRow(
            title=tr("Desktop-Benachrichtigungen"),
            subtitle=tr("Bei fehlgeschlagenen Laeufen und verfuegbaren Updates benachrichtigen"),
        )
        self._notif_row.set_active(self._window.settings.notifications)
        self._notif_row.connect("notify::active", self._on_setting_changed)
        group.add(self._notif_row)

        tray_note = Adw.ActionRow(
            title=tr("Infobereich"),
            subtitle=(
                tr(
                    "Beim Schliessen des Fensters laeuft ProtonSyncUI im Infobereich weiter. "
                    "Beenden ueber das Symbol-Menue oder Strg+Q."
                )
            ),
        )
        tray_note.add_css_class("property")
        group.add(tray_note)
        return group

    def _build_update_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Updates",
            description=tr("Neue Versionen von ProtonSyncUI suchen und installieren."),
        )

        self._update_row = Adw.ActionRow(
            title=tr("Installierte Version: {0}").format(__version__),
            subtitle=tr("Noch nicht nach Updates gesucht."),
        )
        self._update_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self._update_spinner.set_visible(False)
        self._update_row.add_suffix(self._update_spinner)

        self._install_btn = Gtk.Button(
            label=tr("Installieren"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
        )
        self._install_btn.set_visible(False)
        self._install_btn.connect("clicked", lambda _b: self._window.install_update())
        self._update_row.add_suffix(self._install_btn)

        self._check_btn = Gtk.Button(label=tr("Nach Updates suchen"), valign=Gtk.Align.CENTER)
        self._check_btn.connect("clicked", lambda _b: self._window.check_for_updates(manual=True))
        self._update_row.add_suffix(self._check_btn)
        group.add(self._update_row)

        self._auto_update_row = Adw.SwitchRow(
            title=tr("Automatisch nach Updates suchen"),
            subtitle=tr("Hoechstens einmal taeglich; installiert wird erst nach Bestaetigung"),
        )
        self._auto_update_row.set_active(self._window.settings.auto_update_check)
        self._auto_update_row.connect("notify::active", self._on_setting_changed)
        group.add(self._auto_update_row)
        return group

    def _build_cli_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Proton Drive",
            description=tr("Anmeldung und Zustand der offiziellen Proton-Drive-CLI."),
        )

        self._cli_status_row = Adw.ActionRow(title=tr("Verbindung"), subtitle=tr("Wird geprueft …"))
        self._cli_status_icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
        self._cli_status_row.add_prefix(self._cli_status_icon)

        self._login_btn = Gtk.Button(
            label=tr("Anmelden"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
        )
        self._login_btn.set_visible(False)
        self._login_btn.connect("clicked", lambda _b: self._window.start_login())
        self._cli_status_row.add_suffix(self._login_btn)

        check_btn = Gtk.Button(label=tr("Erneut pruefen"), valign=Gtk.Align.CENTER)
        check_btn.connect("clicked", lambda _b: self.check_cli())
        self._cli_status_row.add_suffix(check_btn)
        group.add(self._cli_status_row)

        self._cli_update_row = Adw.ActionRow(title=tr("Neue CLI-Version verfuegbar"))
        self._cli_update_row.add_prefix(
            Gtk.Image.new_from_icon_name("software-update-available-symbolic")
        )
        self._cli_update_btn = Gtk.Button(
            label=tr("Aktualisieren"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"]
        )
        self._cli_update_btn.connect("clicked", lambda _b: self._window.update_cli())
        self._cli_update_row.add_suffix(self._cli_update_btn)
        self._cli_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        self._cli_spinner.set_visible(False)
        self._cli_update_row.add_suffix(self._cli_spinner)
        download_btn = Gtk.Button(label=tr("Download-Seite"), valign=Gtk.Align.CENTER)
        download_btn.connect(
            "clicked", lambda _b: self._window.open_uri(update.PROTON_CLI_DOWNLOAD_URL)
        )
        self._cli_update_row.add_suffix(download_btn)
        self._cli_update_row.set_visible(False)
        group.add(self._cli_update_row)
        return group

    def _build_privacy_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=tr("Datenschutz"))
        notice = Adw.ActionRow(
            title=tr("Keine Nutzungsdaten"),
            subtitle=(
                tr(
                    "ProtonSyncUI arbeitet lokal und sendet keine Nutzungsdaten. Die Update-Suche "
                    "ruft lediglich die aktuelle Versionsnummer bei GitHub ab; die Anmeldung "
                    "geschieht ausschliesslich in der Proton-Drive-CLI."
                )
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
        self._cli_status_row.set_subtitle(tr("Wird geprueft …"))
        self._window.check_cli()

    def show_capabilities(self, caps: Capabilities) -> None:
        """Zeigt das Ergebnis der CLI-Pruefung (im Hauptthread aufzurufen)."""
        version = caps.cli_version or "?"
        if not caps.available:
            icon, text = "dialog-error-symbolic", tr("Die Proton-Drive-CLI wurde nicht gefunden.")
        elif caps.authenticated:
            icon, text = "emblem-ok-symbolic", tr("Angemeldet (CLI {0}).").format(version)
        elif caps.auth_check_failed:
            icon = "dialog-warning-symbolic"
            text = tr(
                "CLI {0} gefunden; Anmeldezustand nicht pruefbar (keine Verbindung?)."
            ).format(version)
        else:
            icon, text = "dialog-error-symbolic", tr("Nicht angemeldet (CLI {0}).").format(version)

        self._cli_status_icon.set_from_icon_name(icon)
        self._cli_status_row.set_subtitle(GLib.markup_escape_text(text))
        self._login_btn.set_visible(caps.needs_login)

        # Die Zeile bietet die Installation (CLI fehlt) oder die Aktualisierung an.
        self._cli_spinner.set_visible(False)
        self._cli_update_btn.set_sensitive(True)
        if not caps.available:
            self._cli_update_row.set_visible(True)
            self._cli_update_row.set_title(tr("Proton-Drive-CLI installieren"))
            self._cli_update_btn.set_label(tr("Installieren"))
            self._cli_update_row.set_subtitle(
                GLib.markup_escape_text(
                    tr("Laedt die aktuelle CLI von proton.me und prueft ihre SHA-512-Pruefsumme.")
                )
            )
        elif caps.newer_cli_version:
            self._cli_update_row.set_visible(True)
            self._cli_update_row.set_title(tr("Neue CLI-Version verfuegbar"))
            self._cli_update_btn.set_label(tr("Aktualisieren"))
            self._cli_update_row.set_subtitle(
                GLib.markup_escape_text(
                    tr(
                        "Version {0} (installiert: {1}). Der Download von proton.me wird "
                        "per SHA-512 geprueft; die Anmeldung bleibt erhalten."
                    ).format(caps.newer_cli_version, version)
                )
            )
        else:
            self._cli_update_row.set_visible(False)

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

    def show_cli_update_state(self, text: str, *, busy: bool = False) -> None:
        """Zeigt den Stand einer CLI-Installation bzw. -Aktualisierung."""
        self._cli_update_row.set_visible(True)
        self._cli_update_row.set_subtitle(GLib.markup_escape_text(text))
        self._cli_spinner.set_visible(busy)
        self._cli_spinner.set_spinning(busy)
        self._cli_update_btn.set_sensitive(not busy)

    def _on_language_changed(self, row: Adw.ComboRow, _param: object) -> None:
        if self._loading:
            return
        code = ("", *i18n.LANGUAGES)[row.get_selected()]
        current = self._window.settings
        if current.language == code:
            return
        current.language = code
        settings.save(current)
        self._window.offer_restart(
            tr("Sprache geaendert"),
            tr("Die neue Sprache wird nach einem Neustart der Anwendung verwendet."),
        )

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
                mode = tr(" (minimiert)") if minimized else ""
                self._window.toast(tr("Autostart{0} aktiviert.").format(mode))
            elif autostart.disable():
                self._window.toast(tr("Autostart deaktiviert."))
        except OSError as error:
            self._window.toast(tr("Autostart konnte nicht geaendert werden: {0}").format(error))
            return

        # systemd erzeugt die Autostart-Units aus dem Verzeichnis neu.
        with contextlib.suppress(Exception):
            SystemdManager().daemon_reload()


__all__ = ["SettingsView"]
