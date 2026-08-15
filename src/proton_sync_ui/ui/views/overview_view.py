"""Uebersichtsansicht mit Hero-Statuskarte und Schnellaktivitaeten."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...models.run import RunStatus  # noqa: E402
from ...paths import format_size  # noqa: E402
from ...services.contracts import (  # noqa: E402
    ActivityRepository,
    ConflictService,
    SyncPairRepository,
    SyncService,
)

if TYPE_CHECKING:
    from ..window import MainWindow


class OverviewView(Gtk.Box):
    """Zentrale Uebersichtsseite."""

    def __init__(
        self,
        window: MainWindow,
        pair_repo: SyncPairRepository,
        activity_repo: ActivityRepository,
        conflict_service: ConflictService,
        sync_service: SyncService,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._pair_repo = pair_repo
        self._activity_repo = activity_repo
        self._conflict_service = conflict_service
        self._sync_service = sync_service

        # HeaderBar
        header = Adw.HeaderBar()
        self._sync_all_btn = Gtk.Button(
            label="Alle synchronisieren",
            icon_name="emblem-synchronizing-symbolic",
            css_classes=["suggested-action"],
        )
        self._sync_all_btn.connect("clicked", self._on_sync_all_clicked)
        header.pack_end(self._sync_all_btn)
        self.append(header)

        # Geklammerter Scrollbereich
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)

        # 1. Hero-Statuskarte
        self._status_card = self._build_status_card()
        content_box.append(self._status_card)

        # 2. Letzte Aktivitaeten
        self._activity_group = Adw.PreferencesGroup(
            title="Letzte Aktivitaeten",
            description="Die neuesten Uebertragungen und Ereignisse.",
        )
        show_all_btn = Gtk.Button(label="Alle Aktivitaeten anzeigen", css_classes=["flat"])
        show_all_btn.connect("clicked", lambda _: self._window.navigate_to("activity"))
        self._activity_group.set_header_suffix(show_all_btn)
        content_box.append(self._activity_group)

        clamp.set_child(content_box)
        scroll.set_child(clamp)
        self.append(scroll)

    def _build_status_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("card")
        card.set_margin_start(4)
        card.set_margin_end(4)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        self._status_icon = Gtk.Image(icon_name="emblem-ok-symbolic", pixel_size=48)
        self._status_icon.add_css_class("success")

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._title_label = Gtk.Label(
            label="Alles synchronisiert", xalign=0, css_classes=["title-2"]
        )
        self._subtitle_label = Gtk.Label(
            label="Alle konfigurierten Ordner sind auf dem aktuellen Stand.",
            xalign=0,
            css_classes=["body", "dim-label"],
            wrap=True,
        )
        self._meta_label = Gtk.Label(
            label="Letzter Lauf: soeben",
            xalign=0,
            css_classes=["caption", "dim-label"],
        )

        text_box.append(self._title_label)
        text_box.append(self._subtitle_label)
        text_box.append(self._meta_label)

        inner.append(self._status_icon)
        inner.append(text_box)
        card.append(inner)
        return card

    def refresh(self) -> None:
        pairs = self._pair_repo.list_pairs()
        recent_runs = self._activity_repo.list_recent_runs(limit=5)
        conflicts = self._conflict_service.list_conflicts()
        self._window.update_conflict_badge(len(conflicts))

        # Statuskarte auswerten
        any_running = any(self._sync_service.is_running(p.uid) for p in pairs)
        any_error = (
            any(r.status is RunStatus.ERROR for r in recent_runs[: len(pairs)]) if pairs else False
        )

        self._status_icon.remove_css_class("success")
        self._status_icon.remove_css_class("accent")
        self._status_icon.remove_css_class("warning")
        self._status_icon.remove_css_class("error")

        if any_running:
            self._status_icon.set_from_icon_name("emblem-synchronizing-symbolic")
            self._status_icon.add_css_class("accent")
            self._title_label.set_label("Synchronisierung laeuft")
            self._subtitle_label.set_label("Dateien werden uebertragen und abgeglichen.")
        elif conflicts:
            self._status_icon.set_from_icon_name("emblem-important-symbolic")
            self._status_icon.add_css_class("warning")
            self._title_label.set_label(f"{len(conflicts)} Konflikt(e) erfordert Aufmerksamkeit")
            self._subtitle_label.set_label(
                "Waehle in der Konfliktansicht, welche Fassungen beibehalten werden sollen."
            )
        elif any_error:
            self._status_icon.set_from_icon_name("dialog-error-symbolic")
            self._status_icon.add_css_class("error")
            self._title_label.set_label("Synchronisierungsfehler aufgetreten")
            self._subtitle_label.set_label(
                "Ein oder mehrere Durchgaenge konnten nicht abgeschlossen werden."
            )
        elif not pairs:
            self._status_icon.set_from_icon_name("folder-remote-symbolic")
            self._status_icon.add_css_class("dim-label")
            self._title_label.set_label("Noch kein Sync-Paar eingerichtet")
            self._subtitle_label.set_label(
                "Füge dein erstes Sync-Paar hinzu, um die Synchronisation zu starten."
            )
        else:
            self._status_icon.set_from_icon_name("emblem-ok-symbolic")
            self._status_icon.add_css_class("success")
            self._title_label.set_label("Alles synchronisiert")
            self._subtitle_label.set_label(
                f"Alle {len(pairs)} Sync-Paare sind auf dem aktuellen Stand."
            )

        # Letzter Lauf Meta
        if recent_runs:
            last = recent_runs[0]
            ts = last.finished_at.strftime("%d.%m.%Y %H:%M") if last.finished_at else "kürzlich"
            self._meta_label.set_label(f"Letzter Lauf: {ts} · {last.summary_line()}")
        else:
            self._meta_label.set_label("Noch kein Durchgang ausgefuehrt")

        # Letzte Aktivitaeten befuellen
        if not hasattr(self, "_activity_rows"):
            self._activity_rows: list[Gtk.Widget] = []

        for row in self._activity_rows:
            self._activity_group.remove(row)
        self._activity_rows.clear()

        if not recent_runs:
            empty_row = Adw.ActionRow(title="Noch keine Aktivitaeten vorhanden")
            empty_row.add_css_class("dim-label")
            self._activity_group.add(empty_row)
            self._activity_rows.append(empty_row)
        else:
            for run in recent_runs:
                pair = self._pair_repo.get_pair(run.pair_uid)
                pair_name = pair.name if pair else "Unbekannt"
                ts = run.finished_at.strftime("%H:%M") if run.finished_at else "Laeuft"
                icon_name = (
                    "emblem-ok-symbolic"
                    if run.status is RunStatus.SUCCESS
                    else "dialog-error-symbolic"
                )

                act_row = Adw.ActionRow(
                    title=GLib.markup_escape_text(f"{pair_name} ({ts})"),
                    subtitle=GLib.markup_escape_text(run.message or run.summary_line()),
                )
                act_row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
                total_bytes = run.uploaded_bytes + run.downloaded_bytes
                if total_bytes > 0:
                    act_row.add_suffix(
                        Gtk.Label(label=format_size(total_bytes), css_classes=["dim-label"])
                    )
                self._activity_group.add(act_row)
                self._activity_rows.append(act_row)

    def _on_sync_all_clicked(self, _button: Gtk.Button) -> None:
        count = 0
        for pair in self._pair_repo.list_pairs():
            if pair.enabled and not self._sync_service.is_running(pair.uid):
                self._sync_service.start_sync(pair)
                count += 1
        if count > 0:
            self._window.toast(f"{count} Sync-Paar(e) gestartet.")
        else:
            self._window.toast("Keine aktiven Sync-Paare zum Starten.")


__all__ = ["OverviewView"]
