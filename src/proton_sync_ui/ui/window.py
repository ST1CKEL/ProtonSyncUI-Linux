"""Hauptfenster von ProtonSyncUI mit adaptiver NavigationSplitView."""

from __future__ import annotations

import asyncio

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, APP_TITLE, __version__, launcher, settings, update  # noqa: E402
from ..cli_adapter.adapter import ProtonDriveAdapter  # noqa: E402
from ..cli_adapter.capabilities import Capabilities, probe  # noqa: E402
from ..logging_setup import get_logger  # noqa: E402
from ..models.plan import UploadPlan, action_label  # noqa: E402
from ..models.run import RunRecord, RunStatus  # noqa: E402
from ..models.sync_pair import SyncPair  # noqa: E402
from ..paths import format_size  # noqa: E402
from ..services.contracts import (  # noqa: E402
    ActivityRepository,
    ConflictService,
    SyncPairRepository,
    SyncProgress,
    SyncService,
)
from ..services.default_services import (  # noqa: E402
    DefaultActivityRepository,
    DefaultConflictService,
    DefaultPairRepository,
    DefaultSyncService,
)
from ..storage.locking import is_locked  # noqa: E402
from ..storage.repository import Repository  # noqa: E402
from ..systemd.manager import SystemdManager, SystemdUnavailableError  # noqa: E402
from .log_window import LogWindow  # noqa: E402
from .pair_dialog import PairDialog  # noqa: E402
from .pair_row import PairRow  # noqa: E402
from .preflight import show_error_dialog  # noqa: E402
from .runner import AsyncRunner  # noqa: E402
from .tray import TrayState  # noqa: E402
from .views.activity_view import ActivityView  # noqa: E402
from .views.conflicts_view import ConflictsView  # noqa: E402
from .views.diag_view import DiagnosticsView  # noqa: E402
from .views.overview_view import OverviewView  # noqa: E402
from .views.pairs_view import SyncPairsView  # noqa: E402
from .views.settings_view import SettingsView  # noqa: E402

log = get_logger("ui.window")

#: Abstand der Anmeldepruefung, waehrend das Anmelde-Terminal offen ist.
LOGIN_POLL_SECONDS = 5
#: So oft wird nach dem Oeffnen des Terminals hoechstens geprueft (10 Minuten).
LOGIN_POLL_ATTEMPTS = 120


class MainWindow(Adw.ApplicationWindow):
    """Hauptfenster mit NavigationSplitView, Statuskarte und Detailansichten."""

    __gtype_name__ = "ProtonSyncUIMainWindow"

    def __init__(
        self,
        application: Adw.Application,
        *,
        repository: Repository,
        runner: AsyncRunner,
    ) -> None:
        super().__init__(application=application)
        self._repository = repository
        self._runner = runner
        self.settings = settings.load()
        self._adapter = ProtonDriveAdapter()
        self._caps: Capabilities | None = None
        self._update_info: update.UpdateInfo | None = None
        self._update_busy = False
        self._conflict_count = 0
        self._last_snapshot: tuple[object, ...] | None = None
        self._last_error_text: dict[str, str] = {}
        self._login_poll_id = 0
        self._login_poll_left = 0

        # Services initialisieren
        self._pair_repo: SyncPairRepository = DefaultPairRepository(repository)
        self._activity_repo: ActivityRepository = DefaultActivityRepository(repository)
        self._conflict_service: ConflictService = DefaultConflictService(
            DefaultPairRepository(repository), repository
        )
        self._sync_service: SyncService = DefaultSyncService(
            runner,
            on_progress=self._on_sync_progress,
            on_done=self._on_sync_done,
            on_error=self._on_sync_error,
        )

        self.set_title(APP_TITLE)
        self.set_icon_name(APP_ID)
        self.set_default_size(1020, 720)
        self.set_size_request(840, 560)

        # Toast Overlay
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # NavigationSplitView
        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_min_sidebar_width(220)
        self._split_view.set_max_sidebar_width(280)
        self._toast_overlay.set_child(self._split_view)

        # Aufbau der Komponenten
        self._build_sidebar()
        self._build_content_views()
        self._install_actions()

        self.connect("close-request", self._on_close_request)

        # Initiale Auswahl & Laden
        self._sidebar_list.select_row(self._row_overview)
        self.refresh()
        self.check_cli()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        """Minimiert das Fenster in den Hintergrund / Infobereich statt die App zu beenden."""
        self.set_visible(False)
        return True

    # ------------------------------------------------------------------
    # Seitenleiste
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> None:
        sidebar_page = Adw.NavigationPage.new(Gtk.Box(), "Navigation")
        sidebar_page.set_title(APP_TITLE)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_title(True)
        toolbar.add_top_bar(header)

        # Hinzufuegen-Button im Sidebar-Header
        add_btn = Gtk.Button(
            icon_name="list-add-symbolic",
            tooltip_text="Sync-Paar hinzufuegen",
        )
        add_btn.connect("clicked", lambda _: self.show_add_pair_dialog())
        header.pack_start(add_btn)

        # App-Menue
        menu = Gio.Menu()
        menu.append("Protokoll anzeigen", "win.show-log")
        menu.append("Zeitplaene aktualisieren", "win.sync-systemd")
        menu.append("Nach Updates suchen", "win.check-update")
        menu.append("Ueber ProtonSyncUI", "win.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_btn)

        # Sidebar ListBox
        self._sidebar_list = Gtk.ListBox()
        self._sidebar_list.add_css_class("navigation-sidebar")
        self._sidebar_list.connect("row-selected", self._on_nav_selected)

        self._row_overview = self._create_nav_row("view-dashboard-symbolic", "Uebersicht")
        self._row_pairs = self._create_nav_row("folder-remote-symbolic", "Sync-Paare")
        self._row_activity = self._create_nav_row("document-open-recent-symbolic", "Aktivitaet")
        self._row_conflicts, self._conflicts_badge = self._create_nav_row_with_badge(
            "dialog-warning-symbolic", "Konflikte"
        )
        self._row_settings = self._create_nav_row("preferences-system-symbolic", "Einstellungen")
        self._row_diag = self._create_nav_row("system-help-symbolic", "Diagnose & Hilfe")

        self._sidebar_list.append(self._row_overview)
        self._sidebar_list.append(self._row_pairs)
        self._sidebar_list.append(self._row_activity)
        self._sidebar_list.append(self._row_conflicts)
        self._sidebar_list.append(self._row_settings)
        self._sidebar_list.append(self._row_diag)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self._sidebar_list)
        toolbar.set_content(scroll)

        sidebar_page.set_child(toolbar)
        self._split_view.set_sidebar(sidebar_page)

    def _create_nav_row(self, icon_name: str, label_text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        label = Gtk.Label(label=label_text, xalign=0, hexpand=True)

        box.append(icon)
        box.append(label)
        row.set_child(box)
        return row

    def _create_nav_row_with_badge(
        self, icon_name: str, label_text: str
    ) -> tuple[Gtk.ListBoxRow, Gtk.Label]:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        label = Gtk.Label(label=label_text, xalign=0, hexpand=True)
        badge = Gtk.Label(label="0")
        badge.add_css_class("badge")
        badge.set_visible(False)

        box.append(icon)
        box.append(label)
        box.append(badge)
        row.set_child(box)
        return row, badge

    # ------------------------------------------------------------------
    # Inhaltsbereich
    # ------------------------------------------------------------------

    def _build_content_views(self) -> None:
        self._content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

        self.view_overview = OverviewView(
            self,
            self._pair_repo,
            self._activity_repo,
            self._conflict_service,
            self._sync_service,
        )
        self.view_pairs = SyncPairsView(
            self,
            self._pair_repo,
            self._activity_repo,
            self._sync_service,
        )
        self.view_activity = ActivityView(self, self._activity_repo)
        self.view_conflicts = ConflictsView(self, self._conflict_service)
        self.view_settings = SettingsView(self)
        self.view_diag = DiagnosticsView(self)

        self._content_stack.add_named(self.view_overview, "overview")
        self._content_stack.add_named(self.view_pairs, "pairs")
        self._content_stack.add_named(self.view_activity, "activity")
        self._content_stack.add_named(self.view_conflicts, "conflicts")
        self._content_stack.add_named(self.view_settings, "settings")
        self._content_stack.add_named(self.view_diag, "diag")

        # Hinweisleisten ueber allen Ansichten: fehlende Anmeldung und Updates.
        self._login_banner = Adw.Banner(title="", button_label="Anmelden")
        self._login_banner.connect("button-clicked", lambda _b: self.start_login())
        self._update_banner = Adw.Banner(title="", button_label="Jetzt installieren")
        self._update_banner.connect("button-clicked", lambda _b: self.install_update())

        # Die Leisten sitzen unter der Kopfzeile der jeweils sichtbaren Ansicht
        # und wandern beim Wechsel mit (siehe _show_view).
        self._banner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._banner_box.append(self._login_banner)
        self._banner_box.append(self._update_banner)

        self._content_page = Adw.NavigationPage.new(self._content_stack, "Uebersicht")
        self._split_view.set_content(self._content_page)

    def _show_view(self, name: str, title: str) -> None:
        """Zeigt eine Ansicht und haengt die Hinweisleisten unter deren Kopfzeile."""
        view = self._content_stack.get_child_by_name(name)
        if isinstance(view, Gtk.Box):
            parent = self._banner_box.get_parent()
            if parent is not view:
                if isinstance(parent, Gtk.Box):
                    parent.remove(self._banner_box)
                view.insert_child_after(self._banner_box, view.get_first_child())
        self._content_stack.set_visible_child_name(name)
        self._content_page.set_title(title)

    def _on_nav_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row == self._row_overview:
            self._show_view("overview", "Uebersicht")
            self.view_overview.refresh()
        elif row == self._row_pairs:
            self._show_view("pairs", "Sync-Paare")
            self.view_pairs.refresh()
        elif row == self._row_activity:
            self._show_view("activity", "Aktivitaet")
            self.view_activity.refresh()
        elif row == self._row_conflicts:
            self._show_view("conflicts", "Konflikte")
            self.view_conflicts.refresh()
        elif row == self._row_settings:
            self._show_view("settings", "Einstellungen")
        elif row == self._row_diag:
            self._show_view("diag", "Diagnose & Hilfe")

    def navigate_to(self, view_name: str) -> None:
        """Navigiert programmgesteuert zu einer bestimmten Ansicht."""
        views = {
            "overview": self._row_overview,
            "pairs": self._row_pairs,
            "activity": self._row_activity,
            "conflicts": self._row_conflicts,
            "settings": self._row_settings,
            "diag": self._row_diag,
        }
        target_row = views.get(view_name)
        if target_row:
            self._sidebar_list.select_row(target_row)

    def update_conflict_badge(self, count: int) -> None:
        if count > 0:
            self._conflicts_badge.set_label(str(count))
            self._conflicts_badge.set_visible(True)
        else:
            self._conflicts_badge.set_visible(False)

    @property
    def _rows(self) -> dict[str, PairRow]:
        """Zugriff auf die Zeilen der Sync-Paare (fuer Tests und Rueckmeldungen)."""
        return self.view_pairs._rows

    def confirm_delete(self, pair: SyncPair) -> None:
        """Alias fuer confirm_delete_pair."""
        self.confirm_delete_pair(pair)

    def _show_plan_dialog(self, pair: SyncPair, plan: UploadPlan, record: RunRecord) -> None:
        """Alias fuer Dry-Run-Vorschau."""
        self._show_dry_run_preview(pair, record, plan)

    def toast(self, message: str, *, timeout: int = 3) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        self._toast_overlay.add_toast(toast)

    def refresh(self) -> None:
        """Aktualisiert die aktive Ansicht und den globalen Status."""
        # Die Konfliktsuche durchlaeuft die Sync-Ordner: nur einmal je Auffrischung.
        try:
            self._conflict_count = len(self._conflict_service.list_conflicts())
        except OSError as error:
            # Ordner waehrend der Suche verschwunden oder nicht lesbar.
            log.warning("Konfliktsuche fehlgeschlagen: %s", error)
        self.update_conflict_badge(self._conflict_count)

        self.view_pairs.refresh()
        self.view_overview.refresh()
        current_name = self._content_stack.get_visible_child_name()
        if current_name == "activity":
            self.view_activity.refresh()
        elif current_name == "conflicts":
            self.view_conflicts.refresh()
        self.update_tray()

    @property
    def conflict_count(self) -> int:
        """Anzahl offener Konflikte laut letzter Auffrischung."""
        return self._conflict_count

    # ------------------------------------------------------------------
    # Gesamtzustand, Infobereich und Hintergrundlaeufe
    # ------------------------------------------------------------------

    def pair_is_busy(self, pair_uid: str) -> bool:
        """Wahr, wenn das Paar hier oder in einem anderen Prozess (Timer) laeuft."""
        if self._sync_service.is_running(pair_uid):
            return True
        try:
            return is_locked(self._repository.connection, pair_uid)
        except Exception:
            return False

    def overall_state(self) -> tuple[TrayState, str]:
        """Zustand ueber alle Sync-Paare: fuer Infobereich und Uebersicht."""
        pairs = self._pair_repo.list_pairs()
        running = [pair.name for pair in pairs if self.pair_is_busy(pair.uid)]
        if running:
            return TrayState.SYNCING, f"Synchronisiert: {', '.join(running)}"

        caps = self._caps
        if caps is not None and not caps.available:
            return TrayState.ERROR, "Proton-Drive-CLI nicht gefunden"
        if caps is not None and caps.needs_login:
            return TrayState.ERROR, "Proton Drive ist nicht angemeldet"

        last_runs = self._repository.last_runs(include_dry_runs=False)
        warnings = 0
        for pair in pairs:
            run = last_runs.get(pair.uid)
            if not pair.enabled or run is None:
                continue
            if run.status is RunStatus.ERROR:
                detail = (run.message or "Lauf fehlgeschlagen").splitlines()[0]
                return TrayState.ERROR, f"Fehler bei '{pair.name}': {detail[:120]}"
            if run.status is RunStatus.WARNING:
                warnings += 1

        if warnings:
            return TrayState.WARNING, "Letzter Lauf mit einzelnen Dateifehlern"
        if self._conflict_count:
            return TrayState.WARNING, f"{self._conflict_count} Konflikt(e) zu klaeren"
        if not pairs:
            return TrayState.IDLE, "Noch kein Sync-Paar eingerichtet"
        return TrayState.IDLE, "Alles synchronisiert"

    def update_tray(self) -> None:
        """Uebertraegt den Gesamtzustand in den Infobereich."""
        app = self.get_application()
        if app is not None and hasattr(app, "set_tray_state"):
            state, text = self.overall_state()
            app.set_tray_state(state, text)

    def poll_background(self) -> None:
        """Erkennt Laeufe anderer Prozesse (systemd-Timer) und reagiert darauf.

        Bewusst billig: nur zwei kleine Datenbankabfragen. Die teurere
        Auffrischung der Ansichten folgt nur, wenn sich etwas geaendert hat.
        """
        pairs = self._pair_repo.list_pairs()
        last_runs = self._repository.last_runs(include_dry_runs=False)
        snapshot: tuple[object, ...] = tuple(
            (
                pair.uid,
                self.pair_is_busy(pair.uid),
                getattr(last_runs.get(pair.uid), "run_id", None),
                getattr(last_runs.get(pair.uid), "status", None),
            )
            for pair in pairs
        )
        if snapshot == self._last_snapshot:
            return
        first_poll = self._last_snapshot is None
        self._last_snapshot = snapshot

        for pair in pairs:
            run = last_runs.get(pair.uid)
            if run is None or self.pair_is_busy(pair.uid):
                continue
            if run.status is RunStatus.ERROR:
                text = (run.message or "Lauf fehlgeschlagen").splitlines()[0]
                # Jede Ursache nur einmal melden -- ein stuendlicher Timer soll
                # nicht stuendlich dieselbe Benachrichtigung ausloesen.
                if self._last_error_text.get(pair.uid) != text:
                    self._last_error_text[pair.uid] = text
                    self.notify(f"'{pair.name}': Synchronisierung fehlgeschlagen", text)
            else:
                self._last_error_text.pop(pair.uid, None)

        if not first_poll and any(
            getattr(run, "status", None) is RunStatus.ERROR for run in last_runs.values()
        ):
            self.check_cli()
        if self.get_visible():
            self.refresh()
        else:
            self.update_tray()

    def notify(self, title: str, body: str) -> None:
        """Sendet eine Desktop-Benachrichtigung, sofern eingeschaltet."""
        if not self.settings.notifications:
            return
        app = self.get_application()
        if app is None:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_default_action("app.show")
        try:
            app.send_notification(None, notification)
        except GLib.Error as error:
            log.debug("Benachrichtigung konnte nicht gesendet werden: %s", error)

    # ------------------------------------------------------------------
    # Proton-Drive-CLI: Zustand und Anmeldung
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> Capabilities | None:
        """Ergebnis der letzten CLI-Pruefung."""
        return self._caps

    def check_cli(self) -> None:
        """Prueft die CLI im Hintergrund und verteilt das Ergebnis im Hauptthread."""
        self._runner.submit_coroutine(
            lambda: probe(self._adapter),
            on_done=self._on_cli_checked,
            on_error=lambda error: log.warning("CLI-Pruefung fehlgeschlagen: %s", error),
        )

    def _on_cli_checked(self, caps: Capabilities) -> None:
        previous = self._caps
        self._caps = caps

        if not caps.available:
            self._login_banner.set_title("Die Proton-Drive-CLI wurde nicht gefunden.")
            self._login_banner.set_button_label("Download-Seite")
            self._login_banner.set_revealed(True)
        elif caps.needs_login:
            self._login_banner.set_title(
                "Proton Drive ist nicht angemeldet – es wird nichts synchronisiert."
            )
            self._login_banner.set_button_label("Anmelden")
            self._login_banner.set_revealed(True)
        else:
            self._login_banner.set_revealed(False)

        self.view_settings.show_capabilities(caps)
        self.update_tray()

        became_ready = caps.usable and previous is not None and not previous.usable
        if became_ready:
            self._stop_login_poll()
            self.toast("Proton Drive ist angemeldet. Die Synchronisation startet.", timeout=5)
            self.view_overview.sync_all(quiet=True)

    def start_login(self) -> None:
        """Oeffnet die Anmeldung (bzw. die Download-Seite, wenn die CLI fehlt)."""
        caps = self._caps
        if caps is not None and not caps.available:
            self.open_uri(update.PROTON_CLI_DOWNLOAD_URL)
            return

        try:
            binary = self._adapter.resolve_binary()
        except Exception as error:
            show_error_dialog(self, "Proton-Drive-CLI nicht gefunden", str(error))
            return

        if not launcher.open_login_terminal(binary):
            show_error_dialog(
                self,
                "Kein Terminalprogramm gefunden",
                "Bitte in einem Terminal ausfuehren:\n\n    proton-drive auth login",
            )
            return

        self.toast("Anmeldung im Terminal gestartet – bitte im Browser abschliessen.", timeout=8)
        self._login_poll_left = LOGIN_POLL_ATTEMPTS
        if not self._login_poll_id:
            self._login_poll_id = GLib.timeout_add_seconds(LOGIN_POLL_SECONDS, self._login_poll)

    def _login_poll(self) -> bool:
        self._login_poll_left -= 1
        if self._login_poll_left <= 0 or (self._caps is not None and self._caps.usable):
            self._login_poll_id = 0
            return GLib.SOURCE_REMOVE
        self.check_cli()
        return GLib.SOURCE_CONTINUE

    def _stop_login_poll(self) -> None:
        if self._login_poll_id:
            GLib.source_remove(self._login_poll_id)
            self._login_poll_id = 0

    def open_uri(self, uri: str) -> None:
        """Oeffnet eine Adresse im Standardprogramm."""
        Gtk.UriLauncher.new(uri).launch(self, None, None, None)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    @property
    def update_info(self) -> update.UpdateInfo | None:
        """Ergebnis der letzten Update-Suche."""
        return self._update_info

    def check_for_updates(self, *, manual: bool = True) -> None:
        """Sucht im Hintergrund nach einer neuen Version."""
        if self._update_busy:
            return
        self._update_busy = True
        self.view_settings.show_update_state("Suche nach Updates …", busy=True)

        def done(info: object) -> None:
            self._update_busy = False
            if not isinstance(info, update.UpdateInfo):
                return
            self._update_info = info
            if info.available:
                self._update_banner.set_title(
                    f"ProtonSyncUI {info.latest_version} ist verfuegbar "
                    f"(installiert: {info.current_version})."
                )
                self._update_banner.set_revealed(True)
                self.view_settings.show_update_state(
                    f"Version {info.latest_version} ist verfuegbar.", available=True
                )
                if manual:
                    self.toast(f"Update auf Version {info.latest_version} verfuegbar.")
                else:
                    self.notify(
                        "Update fuer ProtonSyncUI verfuegbar",
                        f"Version {info.latest_version} kann in den Einstellungen "
                        "installiert werden.",
                    )
            else:
                self._update_banner.set_revealed(False)
                self.view_settings.show_update_state(
                    f"ProtonSyncUI ist aktuell (Version {info.current_version})."
                )
                if manual:
                    self.toast("ProtonSyncUI ist aktuell.")

        def failed(error: BaseException) -> None:
            self._update_busy = False
            log.warning("Update-Suche fehlgeschlagen: %s", error)
            self.view_settings.show_update_state(f"Update-Suche fehlgeschlagen: {error}")
            if manual:
                self.toast("Die Update-Suche ist fehlgeschlagen (keine Verbindung?).")

        self._runner.submit_coroutine(
            lambda: asyncio.to_thread(update.check_for_update), on_done=done, on_error=failed
        )

    def install_update(self) -> None:
        """Installiert das gefundene Update und bietet den Neustart an."""
        info = self._update_info
        if info is None or not info.available or self._update_busy:
            return
        if any(self._sync_service.is_running(p.uid) for p in self._pair_repo.list_pairs()):
            self.toast("Bitte zuerst die laufende Synchronisierung abwarten.")
            return

        self._update_busy = True
        self._update_banner.set_revealed(False)
        self.view_settings.show_update_state(
            f"Version {info.latest_version} wird installiert …", busy=True
        )
        self.toast(f"Version {info.latest_version} wird installiert …")

        def done(_output: object) -> None:
            self._update_busy = False
            self._update_info = None
            self.view_settings.show_update_state(
                f"Version {info.latest_version} ist installiert – Neustart erforderlich."
            )
            dialog = Adw.AlertDialog(
                heading="Update installiert",
                body=(
                    f"ProtonSyncUI {info.latest_version} wurde installiert. "
                    "Die neue Version wird nach einem Neustart der Anwendung aktiv."
                ),
            )
            dialog.add_response("later", "Spaeter")
            dialog.add_response("restart", "Jetzt neu starten")
            dialog.set_response_appearance("restart", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("restart")
            dialog.set_close_response("later")

            def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
                app = self.get_application()
                if response == "restart" and app is not None and launcher.restart_gui():
                    app.quit()

            dialog.connect("response", on_response)
            self.set_visible(True)
            self.present()
            dialog.present(self)

        def failed(error: BaseException) -> None:
            self._update_busy = False
            log.error("Update fehlgeschlagen: %s", error)
            self._update_banner.set_revealed(True)
            self.view_settings.show_update_state(
                "Die Installation ist fehlgeschlagen.", available=True
            )
            show_error_dialog(self, "Update fehlgeschlagen", str(error))

        self._runner.submit_coroutine(
            lambda: asyncio.to_thread(update.install_update, info), on_done=done, on_error=failed
        )

    # ------------------------------------------------------------------
    # Synchronisations-Rueckmeldungen
    # ------------------------------------------------------------------

    def _on_sync_progress(self, progress: SyncProgress) -> None:
        row = self.view_pairs.get_row(progress.pair_uid)
        if row is not None:
            row.update_progress(progress)

    def _on_sync_done(self, record: RunRecord, plan: UploadPlan) -> None:
        pair = self._pair_repo.get_pair(record.pair_uid)
        if pair is not None:
            row = self.view_pairs.get_row(pair.uid)
            if row is not None:
                row.update_run(record, running=False)

        if record.dry_run and pair is not None:
            self._show_dry_run_preview(pair, record, plan)
        elif record.status is RunStatus.SUCCESS:
            name = pair.name if pair else "Sync-Paar"
            self.toast(f"'{name}': Synchronisierung erfolgreich abgeschlossen.")
        elif record.status is RunStatus.WARNING and pair is not None:
            self.toast(
                f"'{pair.name}': abgeschlossen, {record.failed_files} Datei(en) fehlgeschlagen.",
                timeout=6,
            )
        elif record.status is RunStatus.ERROR and pair is not None:
            if self.get_visible():
                self._show_errors_dialog(pair, record)
            # Im Hintergrund meldet poll_background() den Fehler per Benachrichtigung.
            self.check_cli()

        self.refresh()

    def _on_sync_error(self, error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            self.toast("Der Lauf wurde abgebrochen.")
        else:
            log.error("Sync-Fehler: %s", error)
            self.toast(f"Fehler: {error}", timeout=6)
        self.refresh()

    # ------------------------------------------------------------------
    # Dialoge & Aktionen
    # ------------------------------------------------------------------

    def show_add_pair_dialog(self) -> None:
        PairDialog(self, pair=None, on_save=self._save_pair).present(self)

    def show_edit_pair_dialog(self, pair: SyncPair) -> None:
        PairDialog(self, pair=pair, on_save=self._save_pair).present(self)

    def _save_pair(self, pair: SyncPair) -> None:
        self._pair_repo.save_pair(pair)
        self.refresh()
        self.toast(f"'{pair.name}' gespeichert.")
        self.sync_systemd_units(quiet=True)

    def confirm_delete_pair(self, pair: SyncPair) -> None:
        dialog = Adw.AlertDialog(
            heading=f"'{pair.name}' entfernen?",
            body=(
                "Entfernt werden nur die Konfiguration und der lokale Sync-Status.\n\n"
                "Ihre Dateien bei Proton Drive und auf der Festplatte bleiben "
                "vollstaendig erhalten."
            ),
        )
        dialog.add_response("keep", "Behalten")
        dialog.add_response("delete", "Entfernen")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "delete":
                try:
                    manager = SystemdManager()
                    if manager.timer_exists(pair.uid):
                        manager.remove_timer(pair.uid)
                except (SystemdUnavailableError, OSError) as err:
                    log.warning("Timer konnte nicht entfernt werden: %s", err)
                self._pair_repo.delete_pair(pair.uid)
                self.refresh()
                self.toast(f"Sync-Paar '{pair.name}' entfernt.")

        dialog.connect("response", on_response)
        dialog.present(self)

    def _show_dry_run_preview(self, pair: SyncPair, record: RunRecord, plan: UploadPlan) -> None:
        dialog = Adw.Dialog(title=f"Dry-Run – {pair.name}")
        dialog.set_content_width(700)
        dialog.set_content_height(580)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()

        summary = Adw.PreferencesGroup(
            title="Vorschau der Aktionen",
            description=record.message or plan.describe(),
        )
        stat_row = Adw.ActionRow(
            title="Geplante Datenmengen",
            subtitle=(
                f"Downloads: {plan.download_count} ({format_size(plan.total_download_bytes)}) · "
                f"Uploads: {plan.upload_count} ({format_size(plan.total_upload_bytes)}) · "
                f"Uebersprungen: {plan.skip_count}"
            ),
        )
        stat_row.add_css_class("property")
        summary.add(stat_row)
        page.add(summary)

        # Downloads Gruppe
        if plan.downloads:
            dl_group = Adw.PreferencesGroup(title=f"Downloads ({len(plan.downloads)})")
            for item in plan.downloads[:100]:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(str(item.relative_path)),
                    subtitle=GLib.markup_escape_text(
                        f"{action_label(item.action)} · {format_size(item.size_bytes)}"
                    ),
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
                dl_group.add(row)
            page.add(dl_group)

        # Uploads Gruppe
        if plan.uploads:
            up_group = Adw.PreferencesGroup(title=f"Uploads ({len(plan.uploads)})")
            for item in plan.uploads[:100]:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(str(item.relative_path)),
                    subtitle=GLib.markup_escape_text(
                        f"{action_label(item.action)} · {format_size(item.size_bytes)}"
                    ),
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("document-send-symbolic"))
                up_group.add(row)
            page.add(up_group)

        # Uebersprungene Dateien
        if plan.skipped:
            skip_group = Adw.PreferencesGroup(
                title=f"Uebersprungen ({len(plan.skipped)})",
                description="Unveraenderte oder ausgenommene Dateien.",
            )
            for item in plan.skipped[:50]:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(str(item.relative_path)),
                    subtitle=GLib.markup_escape_text(action_label(item.action)),
                )
                skip_group.add(row)
            page.add(skip_group)

        # Lokale Loeschungen
        if plan.local_deletions:
            del_group = Adw.PreferencesGroup(
                title=f"Lokal geloescht ({len(plan.local_deletions)})",
                description=(
                    "Diese Dateien wurden lokal entfernt. Bei Proton Drive bleiben sie erhalten."
                ),
            )
            for item in plan.local_deletions[:50]:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(str(item.relative_path)),
                    subtitle=GLib.markup_escape_text(action_label(item.action)),
                )
                del_group.add(row)
            page.add(del_group)

        # Scan-Warnungen
        if plan.scan_errors:
            err_group = Adw.PreferencesGroup(title="Hinweise beim Einlesen")
            for warning in plan.scan_errors[:50]:
                err_group.add(Adw.ActionRow(title=GLib.markup_escape_text(str(warning))))
            page.add(err_group)

        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scrolled.set_child(page)
        toolbar.set_content(scrolled)

        if plan.uploads or plan.downloads:
            start_btn = Gtk.Button(label="Jetzt synchronisieren", css_classes=["suggested-action"])

            def _on_start_clicked(_btn: Gtk.Button) -> None:
                dialog.close()
                self._sync_service.start_sync(pair, dry_run=False)

            start_btn.connect("clicked", _on_start_clicked)
            header.pack_end(start_btn)

        dialog.set_child(toolbar)
        dialog.present(self)

    def _show_errors_dialog(self, pair: SyncPair, record: RunRecord) -> None:
        if not record.errors and record.message:
            show_error_dialog(self, f"Lauf fuer '{pair.name}'", record.message)
            return
        if not record.errors:
            return

        dialog = Adw.Dialog(title=f"Fehler – {pair.name}")
        dialog.set_content_width(700)
        dialog.set_content_height(560)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=f"{len(record.errors)} Datei(en) fehlgeschlagen",
            description="Der Lauf wurde fortgesetzt. Uebrige Dateien wurden uebertragen.",
        )
        for error in record.errors[:200]:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(error.relative_path),
                subtitle=GLib.markup_escape_text(f"{error.attempts} Versuch(e): {error.message}"),
            )
            group.add(row)
        page.add(group)

        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scrolled.set_child(page)
        toolbar.set_content(scrolled)
        dialog.set_child(toolbar)
        dialog.present(self)

    def show_log(self, pair: SyncPair | None = None) -> None:
        LogWindow(self, pair=pair).present()

    def sync_systemd_units(self, *, quiet: bool = False) -> None:
        pairs = self._pair_repo.list_pairs()
        manager = SystemdManager()

        if not manager.available:
            if not quiet:
                show_error_dialog(
                    self,
                    "systemd nicht verfuegbar",
                    (
                        "'systemctl' wurde nicht gefunden. "
                        "Hintergrund-Timer stehen nicht zur Verfuegung."
                    ),
                )
            return

        def work() -> object:
            return asyncio.to_thread(manager.sync_pairs, pairs)

        def done(actions: object) -> None:
            if quiet:
                return
            count = len(actions) if isinstance(actions, dict) else 0
            self.toast(
                f"Zeitplaene aktualisiert ({count} Aenderung(en))."
                if count
                else "Zeitplaene sind aktuell."
            )

        def failed(error: BaseException) -> None:
            log.error("systemd-Abgleich fehlgeschlagen: %s", error)
            if not quiet:
                show_error_dialog(self, "Zeitplan konnte nicht geschrieben werden", str(error))

        self._runner.submit_coroutine(work, on_done=done, on_error=failed)

    def show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name=APP_TITLE,
            version=__version__,
            developer_name="ProtonSyncUI Contributors",
            application_icon=APP_ID,
            website=update.PROJECT_URL,
            issue_url=f"{update.PROJECT_URL}/issues",
            license_type=Gtk.License.MIT_X11,
            comments=(
                "Fedora-native 2-Wege-Synchronisation und Backups mit Proton Drive.\n\n"
                "ProtonSyncUI steuert ausschliesslich die offizielle proton-drive-CLI. "
                "Bei Proton Drive wird niemals etwas geloescht."
            ),
        )
        about.present(self)

    def _install_actions(self) -> None:
        entries = {
            "show-log": lambda: self.show_log(None),
            "sync-systemd": lambda: self.sync_systemd_units(quiet=False),
            "about": self.show_about,
            "check-update": lambda: self.check_for_updates(manual=True),
        }
        for name, callback in entries.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)


__all__ = ["MainWindow"]
