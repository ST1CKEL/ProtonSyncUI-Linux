"""Logansicht mit Filtern fuer Info, Warnung und Fehler."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import gi

from ..i18n import tr

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import paths  # noqa: E402
from ..logging_setup import read_log_entries  # noqa: E402
from ..models.sync_pair import SyncPair  # noqa: E402

#: Anzeigename je Protokollstufe.
_LEVEL_LABELS: dict[str, str] = {
    "DEBUG": "Debug",
    "INFO": "Info",
    "WARNING": "Warnung",
    "ERROR": "Fehler",
    "CRITICAL": "Fehler",
}

_LEVEL_TAGS: dict[str, str] = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "CRITICAL": "error",
}

MAX_ENTRIES = 2000


class LogWindow(Adw.Window):
    """Fenster mit den letzten Protokolleintraegen."""

    __gtype_name__ = "ProtonSyncUILogWindow"

    def __init__(self, parent: Gtk.Window, *, pair: SyncPair | None = None) -> None:
        super().__init__(transient_for=parent, modal=False)
        self._pair = pair
        self.set_default_size(900, 620)
        self.set_title(tr("Protokoll – {0}").format(pair.name) if pair else tr("Protokoll"))

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        reload_button = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_button.set_tooltip_text(tr("Neu laden"))
        reload_button.connect("clicked", lambda _b: self.reload())
        header.pack_start(reload_button)

        copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_button.set_tooltip_text(tr("Sichtbare Eintraege in die Zwischenablage kopieren"))
        copy_button.connect("clicked", self._copy_visible)
        header.pack_end(copy_button)

        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._build_filter_bar())
        toolbar.set_content(self._build_text_view())
        toolbar.add_bottom_bar(self._build_status_bar())

        self.set_content(toolbar)
        self.reload()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_filter_bar(self) -> Gtk.Widget:
        """Leiste mit den Stufenfiltern."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        box.append(Gtk.Label(label=tr("Anzeigen:"), css_classes=["dim-label"]))

        self._info_toggle = Gtk.ToggleButton(label="Info", active=True)
        self._warning_toggle = Gtk.ToggleButton(label=tr("Warnung"), active=True)
        self._error_toggle = Gtk.ToggleButton(label=tr("Fehler"), active=True)
        self._debug_toggle = Gtk.ToggleButton(label="Debug", active=False)

        linked = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        linked.add_css_class("linked")
        for toggle in (
            self._info_toggle,
            self._warning_toggle,
            self._error_toggle,
            self._debug_toggle,
        ):
            toggle.connect("toggled", lambda _t: self.reload())
            linked.append(toggle)
        box.append(linked)

        if self._pair is not None:
            self._only_pair_toggle = Gtk.ToggleButton(label=tr("Nur dieses Paar"), active=True)
            self._only_pair_toggle.connect("toggled", lambda _t: self.reload())
            box.append(self._only_pair_toggle)
        else:
            self._only_pair_toggle = None

        spacer = Gtk.Box(hexpand=True)
        box.append(spacer)

        self._search_entry = Gtk.SearchEntry(placeholder_text=tr("Filtern…"))
        self._search_entry.set_size_request(220, -1)
        self._search_entry.connect("search-changed", lambda _e: self.reload())
        box.append(self._search_entry)

        return box

    def _build_text_view(self) -> Gtk.Widget:
        """Der eigentliche Textbereich."""
        self._text_view = Gtk.TextView(
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=8,
            bottom_margin=8,
            left_margin=8,
            right_margin=8,
        )
        buffer = self._text_view.get_buffer()
        buffer.create_tag("debug", foreground_rgba=_rgba("#9a9996"))
        buffer.create_tag("info", foreground_rgba=None)
        buffer.create_tag("warning", foreground_rgba=_rgba("#e5a50a"), weight=700)
        buffer.create_tag("error", foreground_rgba=_rgba("#e01b24"), weight=700)
        buffer.create_tag("timestamp", foreground_rgba=_rgba("#77767b"))

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.set_child(self._text_view)
        return scrolled

    def _build_status_bar(self) -> Gtk.Widget:
        """Fusszeile mit Pfad und Trefferzahl."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        self._count_label = Gtk.Label(xalign=0.0)
        self._count_label.add_css_class("dim-label")
        box.append(self._count_label)

        spacer = Gtk.Box(hexpand=True)
        box.append(spacer)

        path_label = Gtk.Label(label=str(paths.log_file()), xalign=1.0, selectable=True)
        path_label.add_css_class("dim-label")
        path_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        box.append(path_label)

        return box

    # ------------------------------------------------------------------
    # Inhalt
    # ------------------------------------------------------------------

    def _active_levels(self) -> frozenset[str]:
        """Die aktuell gewaehlten Protokollstufen."""
        levels: set[str] = set()
        if self._debug_toggle.get_active():
            levels.add("DEBUG")
        if self._info_toggle.get_active():
            levels.add("INFO")
        if self._warning_toggle.get_active():
            levels.add("WARNING")
        if self._error_toggle.get_active():
            levels.update({"ERROR", "CRITICAL"})
        return frozenset(levels)

    def reload(self) -> None:
        """Liest das Protokoll neu ein und wendet die Filter an."""
        pair_uid = None
        if self._pair is not None and self._only_pair_toggle is not None:
            pair_uid = self._pair.uid if self._only_pair_toggle.get_active() else None

        entries = read_log_entries(
            limit=MAX_ENTRIES,
            levels=self._active_levels(),
            pair_uid=pair_uid,
        )

        needle = self._search_entry.get_text().strip().lower()
        if needle:
            entries = [
                entry
                for entry in entries
                if needle in str(entry.get("message", "")).lower()
                or needle in str(entry.get("relative_path", "")).lower()
            ]

        buffer = self._text_view.get_buffer()
        buffer.set_text("")

        if not entries:
            buffer.insert(
                buffer.get_end_iter(),
                tr("Keine Eintraege fuer die gewaehlten Filter.\n"),
            )
            self._count_label.set_label(tr("0 Eintraege"))
            return

        for entry in entries:
            self._append_entry(buffer, entry)

        self._count_label.set_label(tr("{0} Eintraege").format(len(entries)))
        end_mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self._text_view.scroll_to_mark(end_mark, 0.0, False, 0.0, 1.0)

    def _append_entry(self, buffer: Gtk.TextBuffer, entry: dict[str, Any]) -> None:
        """Haengt einen Eintrag formatiert an."""
        level = str(entry.get("level", "INFO"))
        tag = _LEVEL_TAGS.get(level, "info")
        label = tr(_LEVEL_LABELS.get(level, level))

        buffer.insert_with_tags_by_name(
            buffer.get_end_iter(), f"{_format_ts(entry.get('ts'))}  ", "timestamp"
        )
        buffer.insert_with_tags_by_name(buffer.get_end_iter(), f"{label:<8}", tag)

        message = str(entry.get("message", ""))
        relative = entry.get("relative_path")
        if relative:
            message = f"{message}  [{relative}]"
        buffer.insert(buffer.get_end_iter(), f" {message}\n")

    def _copy_visible(self, _button: Gtk.Button) -> None:
        """Kopiert den sichtbaren Text in die Zwischenablage."""
        buffer = self._text_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)


def _format_ts(raw: object) -> str:
    """Formatiert einen ISO-Zeitstempel in lokaler Zeit."""
    if not isinstance(raw, str):
        return "?"
    try:
        return datetime.fromisoformat(raw).astimezone().strftime("%d.%m. %H:%M:%S")
    except ValueError:
        return raw[:19]


def _rgba(color: str) -> Gdk.RGBA | None:
    """Erzeugt eine RGBA-Farbe aus einer Hex-Angabe."""
    rgba = Gdk.RGBA()
    return rgba if rgba.parse(color) else None


__all__ = ["LogWindow"]
