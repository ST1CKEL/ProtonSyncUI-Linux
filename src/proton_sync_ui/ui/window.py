"""Hauptfenster von ProtonSyncUI mit adaptiver NavigationSplitView."""

from __future__ import annotations

import asyncio

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, APP_TITLE, __version__  # noqa: E402
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
from ..storage.repository import Repository  # noqa: E402
from ..systemd.manager import SystemdManager, SystemdUnavailableError  # noqa: E402
from .log_window import LogWindow  # noqa: E402
from .pair_dialog import PairDialog  # noqa: E402
from .pair_row import PairRow  # noqa: E402
from .preflight import show_error_dialog  # noqa: E402
from .runner import AsyncRunner  # noqa: E402
from .views.activity_view import ActivityView  # noqa: E402
from .views.conflicts_view import ConflictsView  # noqa: E402
from .views.diag_view import DiagnosticsView  # noqa: E402
from .views.overview_view import OverviewView  # noqa: E402
from .views.pairs_view import SyncPairsView  # noqa: E402
from .views.settings_view import SettingsView  # noqa: E402

log = get_logger("ui.window")


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

        content_page = Adw.NavigationPage.new(self._content_stack, "Inhalt")
        self._split_view.set_content(content_page)

    def _on_nav_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row == self._row_overview:
            self._content_stack.set_visible_child_name("overview")
            self.view_overview.refresh()
        elif row == self._row_pairs:
            self._content_stack.set_visible_child_name("pairs")
            self.view_pairs.refresh()
        elif row == self._row_activity:
            self._content_stack.set_visible_child_name("activity")
            self.view_activity.refresh()
        elif row == self._row_conflicts:
            self._content_stack.set_visible_child_name("conflicts")
            self.view_conflicts.refresh()
        elif row == self._row_settings:
            self._content_stack.set_visible_child_name("settings")
        elif row == self._row_diag:
            self._content_stack.set_visible_child_name("diag")

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
        self.view_pairs.refresh()
        self.view_overview.refresh()
        current_name = self._content_stack.get_visible_child_name()
        if current_name == "activity":
            self.view_activity.refresh()
        elif current_name == "conflicts":
            self.view_conflicts.refresh()

        conflicts = self._conflict_service.list_conflicts()
        self.update_conflict_badge(len(conflicts))

        app = self.get_application()
        if app is not None and hasattr(app, "update_tray_status"):
            pairs = self._pair_repo.list_pairs()
            any_running = any(self._sync_service.is_running(p.uid) for p in pairs)
            if any_running:
                app.update_tray_status("Synchronisiert…", is_syncing=True)
            elif conflicts:
                app.update_tray_status(f"{len(conflicts)} Konflikt(e)", has_error=False)
            else:
                app.update_tray_status("Alles synchronisiert", is_syncing=False)

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
        elif record.status is RunStatus.ERROR and pair is not None:
            self._show_errors_dialog(pair, record)

        self.refresh()

    def _on_sync_error(self, error: BaseException) -> None:
        log.error("Sync-Fehler: %s", error)
        self.toast(f"Fehler: {error}")
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
        }
        for name, callback in entries.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)


__all__ = ["MainWindow"]
