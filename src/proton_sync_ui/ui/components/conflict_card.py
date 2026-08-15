"""Konflikt-Karte fuer einen erkannten Dateikonflikt."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...paths import format_size  # noqa: E402
from ...services.contracts import ConflictItem  # noqa: E402


class ConflictCard(Adw.ExpanderRow):
    """Dedizierte Konfliktkarte fuer eine kollidierende Datei."""

    def __init__(
        self, conflict: ConflictItem, *, on_resolve: Callable[[ConflictItem, str], None]
    ) -> None:
        super().__init__()
        self.conflict = conflict
        self._on_resolve = on_resolve

        self.set_title(conflict.relative_path)
        self.set_subtitle("Datei wurde sowohl lokal als auch bei Proton Drive geaendert.")
        self.add_prefix(Gtk.Image.new_from_icon_name("emblem-important-symbolic"))
        self.set_expanded(True)

        # 2-Spalten Vergleich
        compare_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, homogeneous=True)
        compare_box.set_margin_top(12)
        compare_box.set_margin_bottom(12)
        compare_box.set_margin_start(16)
        compare_box.set_margin_end(16)

        # Lokale Spalte
        local_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        local_col.append(Gtk.Label(label="Lokale Fassung", css_classes=["heading"], xalign=0))
        local_col.append(
            Gtk.Label(
                label=f"Groesse: {format_size(conflict.local_size)}",
                css_classes=["caption", "dim-label"],
                xalign=0,
            )
        )
        compare_box.append(local_col)

        # Cloud Spalte
        remote_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        remote_col.append(
            Gtk.Label(label="Proton-Drive-Fassung", css_classes=["heading"], xalign=0)
        )
        remote_col.append(
            Gtk.Label(
                label=f"Groesse: {format_size(conflict.remote_size)}",
                css_classes=["caption", "dim-label"],
                xalign=0,
            )
        )
        compare_box.append(remote_col)

        # Aktionsbuttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_bottom(12)
        btn_box.set_margin_start(16)
        btn_box.set_margin_end(16)

        keep_both_btn = Gtk.Button(
            label="Beide behalten (umbenennen)", css_classes=["suggested-action"]
        )
        keep_both_btn.connect("clicked", lambda _: self._on_resolve(self.conflict, "keep_both"))

        keep_local_btn = Gtk.Button(label="Lokale Fassung behalten")
        keep_local_btn.connect("clicked", lambda _: self._on_resolve(self.conflict, "keep_local"))

        keep_remote_btn = Gtk.Button(label="Cloud-Fassung behalten")
        keep_remote_btn.connect("clicked", lambda _: self._on_resolve(self.conflict, "keep_remote"))

        btn_box.append(keep_both_btn)
        btn_box.append(keep_local_btn)
        btn_box.append(keep_remote_btn)

        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrapper.append(compare_box)
        wrapper.append(btn_box)

        content_row = Adw.ActionRow()
        content_row.set_child(wrapper)
        self.add_row(content_row)


__all__ = ["ConflictCard"]
