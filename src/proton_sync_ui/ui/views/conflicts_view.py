"""Konflikt-Center zur Uebersicht und Loesung von Dateikonflikten."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...services.contracts import ConflictItem, ConflictService  # noqa: E402
from ..components.conflict_card import ConflictCard  # noqa: E402

if TYPE_CHECKING:
    from ..window import MainWindow


class ConflictsView(Gtk.Box):
    """Dedizierte Ansicht zur Konfliktloesung."""

    def __init__(self, window: MainWindow, conflict_service: ConflictService) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._conflict_service = conflict_service
        self._cards: list[Gtk.Widget] = []

        # HeaderBar
        header = Adw.HeaderBar()
        self._resolve_all_btn = Gtk.Button(
            label="Alle: Beide behalten",
            icon_name="emblem-ok-symbolic",
            css_classes=["flat"],
        )
        self._resolve_all_btn.connect("clicked", self._on_resolve_all_clicked)
        header.pack_end(self._resolve_all_btn)
        self.append(header)

        # Inhaltsbereich Stack
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)

        # 1. Empty State
        empty_page = Adw.StatusPage(
            icon_name="emblem-ok-symbolic",
            title="Keine Konflikte vorhanden",
            description="Alle Dateien wurden erfolgreich synchronisiert.",
        )
        self._stack.add_named(empty_page, "empty")

        # 2. Konfliktliste
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        self._group = Adw.PreferencesGroup(
            title="Offene Dateikonflikte",
            description="Waehle fuer jede Datei, welche Version beibehalten werden soll.",
        )
        clamp.set_child(self._group)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        self.append(self._stack)

    def refresh(self) -> None:
        conflicts = self._conflict_service.list_conflicts()
        self._window.update_conflict_badge(len(conflicts))
        self._resolve_all_btn.set_visible(bool(conflicts))

        for card in self._cards:
            self._group.remove(card)
        self._cards.clear()

        if not conflicts:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for conflict in conflicts:
            card = ConflictCard(conflict, on_resolve=self._on_resolve_conflict)
            self._group.add(card)
            self._cards.append(card)

    def _on_resolve_conflict(self, conflict: ConflictItem, resolution: str) -> None:
        self._conflict_service.resolve_conflict(conflict, resolution)
        self._window.toast(f"Konflikt '{conflict.relative_path}' geloest.")
        self.refresh()

    def _on_resolve_all_clicked(self, _btn: Gtk.Button) -> None:
        conflicts = self._conflict_service.list_conflicts()
        for conflict in conflicts:
            self._conflict_service.resolve_conflict(conflict, "keep_both")
        self._window.toast(f"{len(conflicts)} Konflikte geloest (Beide Versionen behalten).")
        self.refresh()


__all__ = ["ConflictsView"]
