"""Ansicht fuer alle konfigurierten Sync-Paare mit Filterung und Aktionen."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...models.sync_pair import SyncPair  # noqa: E402
from ...services.contracts import (  # noqa: E402
    ActivityRepository,
    SyncPairRepository,
    SyncService,
)
from ..pair_row import PairRow  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class SyncPairsView(Gtk.Box):
    """Verwaltung aller Sync-Paare."""

    def __init__(
        self,
        window: MainWindow,
        pair_repo: SyncPairRepository,
        activity_repo: ActivityRepository,
        sync_service: SyncService,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._pair_repo = pair_repo
        self._activity_repo = activity_repo
        self._sync_service = sync_service
        self._rows: dict[str, PairRow] = {}
        self._filter_mode = "all"
        self._search_term = ""

        # HeaderBar
        header = Adw.HeaderBar()
        add_btn = Gtk.Button(
            label="Sync-Paar hinzufuegen",
            icon_name="list-add-symbolic",
            css_classes=["suggested-action"],
        )
        add_btn.connect("clicked", lambda _: self._window.show_add_pair_dialog())
        header.pack_end(add_btn)
        self.append(header)

        # Filter & Suche Leiste
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        filter_bar.set_margin_top(12)
        filter_bar.set_margin_bottom(12)
        filter_bar.set_margin_start(16)
        filter_bar.set_margin_end(16)

        self._search_entry = Gtk.SearchEntry(
            placeholder_text="Sync-Paare durchsuchen…", hexpand=True
        )
        self._search_entry.connect("search-changed", self._on_search_changed)
        filter_bar.append(self._search_entry)

        self._filter_combo = Gtk.DropDown.new_from_strings(
            ["Alle", "Aktiviert", "Laeuft", "Deaktiviert"]
        )
        self._filter_combo.connect("notify::selected", self._on_filter_changed)
        filter_bar.append(self._filter_combo)
        self.append(filter_bar)

        # Inhaltsbereich mit Stack (Liste oder Leerer Zustand)
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)

        # Empty State
        empty_page = Adw.StatusPage(
            icon_name="folder-remote-symbolic",
            title="Keine Sync-Paare gefunden",
            description="Lege ein neues Sync-Paar an, um Ordner mit Proton Drive abzugleichen.",
        )
        empty_btn = Gtk.Button(label="Sync-Paar anlegen", css_classes=["suggested-action", "pill"])
        empty_btn.set_halign(Gtk.Align.CENTER)
        empty_btn.connect("clicked", lambda _: self._window.show_add_pair_dialog())
        empty_page.set_child(empty_btn)
        self._stack.add_named(empty_page, "empty")

        # Listenansicht
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        self._group = Adw.PreferencesGroup(title="Konfigurierte Ordnerpaare")
        clamp.set_child(self._group)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        self.append(self._stack)

    def refresh(self) -> None:
        pairs = self._pair_repo.list_pairs()
        visible_pairs: list[SyncPair] = []

        for pair in pairs:
            # Filter
            if self._search_term and self._search_term.lower() not in pair.name.lower():
                continue
            is_running = self._sync_service.is_running(pair.uid)
            if self._filter_mode == "active" and not pair.enabled:
                continue
            if self._filter_mode == "inactive" and pair.enabled:
                continue
            if self._filter_mode == "running" and not is_running:
                continue

            visible_pairs.append(pair)

        # Liste sauber aufraeumen
        for row in list(self._rows.values()):
            self._group.remove(row)
        self._rows.clear()

        if not visible_pairs:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for pair in visible_pairs:
            row = PairRow(
                pair,
                on_sync=self._on_sync_pair,
                on_dry_run=self._on_dry_run_pair,
                on_edit=self._on_edit_pair,
                on_toggle_enabled=self._on_toggle_pair,
                on_show_log=self._on_show_log,
                on_cancel=self._on_cancel_pair,
                on_delete=self._on_delete_pair,
            )
            last_run = self._activity_repo.get_last_run(pair.uid)
            row.update_run(last_run, running=self._sync_service.is_running(pair.uid))
            self._rows[pair.uid] = row
            self._group.add(row)

    def get_row(self, pair_uid: str) -> PairRow | None:
        return self._rows.get(pair_uid)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_term = entry.get_text().strip()
        self.refresh()

    def _on_filter_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        idx = combo.get_selected()
        modes = ["all", "active", "running", "inactive"]
        self._filter_mode = modes[idx] if idx < len(modes) else "all"
        self.refresh()

    def _on_sync_pair(self, pair: SyncPair) -> None:
        self._sync_service.start_sync(pair, dry_run=False)
        self._window.toast(f"'{pair.name}': Synchronisierung gestartet.")
        if pair.uid in self._rows:
            self._rows[pair.uid].set_busy(True)

    def _on_dry_run_pair(self, pair: SyncPair) -> None:
        self._sync_service.start_sync(pair, dry_run=True)
        self._window.toast(f"'{pair.name}': Dry-Run gestartet.")
        if pair.uid in self._rows:
            self._rows[pair.uid].set_busy(True)

    def _on_cancel_pair(self, pair: SyncPair) -> None:
        self._sync_service.cancel_sync(pair.uid)
        self._window.toast(f"'{pair.name}': Abbruch angefordert.")

    def _on_edit_pair(self, pair: SyncPair) -> None:
        self._window.show_edit_pair_dialog(pair)

    def _on_toggle_pair(self, pair: SyncPair, active: bool) -> None:
        self._pair_repo.set_pair_enabled(pair.uid, enabled=active)
        self._window.toast(f"'{pair.name}' {'aktiviert' if active else 'deaktiviert'}.")
        self.refresh()

    def _on_show_log(self, pair: SyncPair) -> None:
        self._window.show_log(pair)

    def _on_delete_pair(self, pair: SyncPair) -> None:
        self._window.confirm_delete_pair(pair)


__all__ = ["SyncPairsView"]
