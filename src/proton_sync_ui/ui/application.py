"""Adw.Application und Einstiegspunkt der grafischen Oberflaeche."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from .. import APP_ID, APP_TITLE, __version__, paths, settings  # noqa: E402
from ..logging_setup import configure_logging, get_logger  # noqa: E402
from ..storage.database import connect  # noqa: E402
from ..storage.repository import Repository  # noqa: E402
from .runner import AsyncRunner  # noqa: E402
from .tray import TrayService, TrayState  # noqa: E402
from .window import MainWindow  # noqa: E402

log = get_logger("ui.application")

#: Abstand, in dem Laeufe anderer Prozesse (systemd-Timer) erkannt werden.
POLL_SECONDS = 15
#: Abstand der regelmaessigen CLI-Pruefung (Anmeldezustand).
CLI_CHECK_SECONDS = 15 * 60
#: Wartezeit nach dem Start bis zur automatischen Update-Suche.
UPDATE_CHECK_DELAY_SECONDS = 60
#: Mindestabstand zwischen automatischen Update-Suchen.
UPDATE_CHECK_INTERVAL = timedelta(hours=24)


class ProtonSyncUIApplication(Adw.Application):
    """Die Anwendung. Haelt Datenbank, Tray-Dienst und Arbeitsthread ueber die Laufzeit."""

    __gtype_name__ = "ProtonSyncUIApplication"

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._repository: Repository | None = None
        self._runner = AsyncRunner()
        self._window: MainWindow | None = None
        self._tray: TrayService | None = None
        self._start_hidden = False
        self._timer_ids: list[int] = []
        self._update_timer_id = 0

        self.set_option_context_summary(
            "Synchronisation und Backups mit Proton Drive ueber die offizielle CLI."
        )
        self.add_main_option(
            "minimized",
            ord("m"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Minimiert im Infobereich/Hintergrund starten",
            None,
        )
        self.add_main_option(
            "hidden",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Im Hintergrund starten",
            None,
        )

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Wertet CLI-Optionen aus."""
        options = command_line.get_options_dict()
        if options.contains("minimized") or options.contains("hidden"):
            self._start_hidden = True
        self.activate()
        return 0

    def do_startup(self) -> None:
        """Richtet Protokoll, Datenbank, Tray-Dienst und Arbeitsthread ein."""
        Adw.Application.do_startup(self)

        paths.ensure_directories()
        configure_logging(console=False)
        log.info("%s %s startet.", APP_TITLE, __version__)

        self._repository = Repository(connect())
        self._runner.start()

        # Taskleisten- / Infobereich-Dienst starten
        self._tray = TrayService(
            self,
            on_show_window=self._show_window,
            on_sync_all=self._sync_all,
            on_quit=self.quit,
            on_check_update=self._check_update_from_tray,
        )
        self._tray.start()

        self._install_actions()

        self._timer_ids = [
            GLib.timeout_add_seconds(POLL_SECONDS, self._poll),
            GLib.timeout_add_seconds(CLI_CHECK_SECONDS, self._periodic_cli_check),
        ]
        self._update_timer_id = GLib.timeout_add_seconds(
            UPDATE_CHECK_DELAY_SECONDS, self._auto_update_check
        )

    def do_activate(self) -> None:
        """Zeigt das Hauptfenster oder belaesst es minimiert."""
        if self._window is None:
            if self._repository is None:  # pragma: no cover
                raise RuntimeError("Die Datenbank wurde nicht geoeffnet.")
            self._window = MainWindow(self, repository=self._repository, runner=self._runner)

        if not self._start_hidden:
            self._window.set_visible(True)
            self._window.present()
        else:
            self._window.set_visible(False)
            self._start_hidden = False
        self._window.poll_background()

    def do_shutdown(self) -> None:
        """Beendet Arbeitsthread, Tray und Datenbank sauber."""
        log.info("%s wird beendet.", APP_TITLE)
        for timer_id in (*self._timer_ids, self._update_timer_id):
            if timer_id:
                GLib.source_remove(timer_id)
        self._timer_ids = []
        self._update_timer_id = 0
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self._runner.stop()
        if self._repository is not None:
            self._repository.close()
            self._repository = None
        Adw.Application.do_shutdown(self)

    # ------------------------------------------------------------------
    # Aktionen & Steuerung
    # ------------------------------------------------------------------

    def update_tray_status(
        self, status_text: str, *, is_syncing: bool = False, has_error: bool = False
    ) -> None:
        """Aktualisiert den Tray-Status."""
        if self._tray is not None:
            self._tray.update_status(status_text, is_syncing=is_syncing, has_error=has_error)

    def set_tray_state(self, state: TrayState, status_text: str) -> None:
        """Setzt Zustand und Statuszeile des Symbols im Infobereich."""
        if self._tray is not None:
            self._tray.set_state(state, status_text)

    # ------------------------------------------------------------------
    # Wiederkehrende Aufgaben
    # ------------------------------------------------------------------

    def _poll(self) -> bool:
        if self._window is not None:
            try:
                self._window.poll_background()
            except Exception:
                log.exception("Statusabfrage fehlgeschlagen")
        return GLib.SOURCE_CONTINUE

    def _periodic_cli_check(self) -> bool:
        if self._window is not None:
            self._window.check_cli()
        return GLib.SOURCE_CONTINUE

    def _auto_update_check(self) -> bool:
        """Sucht hoechstens einmal taeglich selbsttaetig nach einer neuen Version."""
        self._update_timer_id = 0
        if self._window is None:
            return GLib.SOURCE_REMOVE
        current = self._window.settings
        if current.auto_update_check:
            now = datetime.now(tz=UTC)
            try:
                last = datetime.fromisoformat(current.last_update_check)
            except ValueError:
                last = None
            if last is None or now - last >= UPDATE_CHECK_INTERVAL:
                current.last_update_check = now.isoformat()
                settings.save(current)
                self._window.check_for_updates(manual=False)
        # Laeuft die Anwendung tagelang durch, wird stuendlich neu bewertet.
        self._update_timer_id = GLib.timeout_add_seconds(3600, self._auto_update_check)
        return GLib.SOURCE_REMOVE

    def _check_update_from_tray(self) -> None:
        self._show_window()
        if self._window is not None:
            self._window.navigate_to("settings")
            self._window.check_for_updates(manual=True)

    def _show_window(self) -> None:
        """Oeffnet das Hauptfenster (z. B. bei Klick im Tray)."""
        if self._window is None:
            if self._repository is None:
                return
            self._window = MainWindow(self, repository=self._repository, runner=self._runner)
        # Im Hintergrund wird die Ansicht nicht mitgefuehrt: vor dem Zeigen auffrischen.
        self._window.refresh()
        self._window.set_visible(True)
        self._window.present()

    def _sync_all(self) -> None:
        """Startet Synchronisation fuer alle Paare."""
        if self._window is not None:
            self._window.view_overview.sync_all()

    def _install_actions(self) -> None:
        """Registriert die Anwendungsaktionen und Tastenkuerzel."""
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda _a, _p: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        show_action = Gio.SimpleAction.new("show", None)
        show_action.connect("activate", lambda _a, _p: self._show_window())
        self.add_action(show_action)

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda _a, _p: self._refresh_window())
        self.add_action(refresh_action)
        self.set_accels_for_action("app.refresh", ["<Primary>r", "F5"])

        self.set_accels_for_action("win.show-log", ["<Primary>l"])

    def _refresh_window(self) -> None:
        """Aktualisiert die Ansicht, falls das Fenster offen ist."""
        if self._window is not None:
            self._window.refresh()


def main(argv: Sequence[str] | None = None) -> int:
    """Startet die grafische Oberflaeche."""
    arguments = list(sys.argv) if argv is None else ["proton-sync-ui-gui", *argv]

    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_TITLE)

    try:
        application = ProtonSyncUIApplication()
    except GLib.Error as error:  # pragma: no cover
        print(f"Die Anwendung konnte nicht gestartet werden: {error}", file=sys.stderr)
        return 1

    try:
        return application.run(arguments)
    except KeyboardInterrupt:  # pragma: no cover
        return 0
    except Exception as error:
        logging.getLogger("proton_sync_ui").exception("Unerwarteter Fehler in der Oberflaeche")
        print(f"Unerwarteter Fehler: {error}", file=sys.stderr)
        print(f"Einzelheiten stehen im Protokoll: {paths.log_file()}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
