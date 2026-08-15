"""Dialog zum Anlegen und Bearbeiten eines Sync-Paars."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..logging_setup import get_logger  # noqa: E402
from ..models.sync_pair import (  # noqa: E402
    DEFAULT_REMOTE_ROOT,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    ScheduleKind,
    SyncMode,
    SyncPair,
    ValidationError,
    parse_exclude_patterns,
    validate_local_path,
    validate_remote_path,
)

log = get_logger("ui.pair_dialog")

_MIB = 1024 * 1024

_EXCLUDE_HELP = (
    "Eine Regel pro Zeile, im Stil von .gitignore. Beispiele:\n"
    "*.tmp — alle temporaeren Dateien\n"
    "cache/ — den Ordner cache auf jeder Ebene\n"
    "/nur-oben.txt — nur im Wurzelverzeichnis\n"
    "!wichtig.tmp — Ausnahme von einer vorherigen Regel"
)


class PairDialog(Adw.Dialog):
    """Formular fuer ein Sync-Paar mit sofortiger Validierung."""

    __gtype_name__ = "ProtonSyncUIPairDialog"

    def __init__(
        self,
        parent: Gtk.Window,
        *,
        pair: SyncPair | None = None,
        on_save: Callable[[SyncPair], None],
    ) -> None:
        super().__init__()
        self._parent = parent
        self._pair = pair
        self._on_save = on_save
        self._local_path: Path | None = pair.local_path if pair else None

        self.set_title("Sync-Paar bearbeiten" if pair else "Sync-Paar hinzufuegen")
        self.set_content_width(620)
        self.set_content_height(720)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)

        cancel_button = Gtk.Button(label="Abbrechen")
        cancel_button.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel_button)

        self._save_button = Gtk.Button(label="Speichern")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", self._on_save_clicked)
        header.pack_end(self._save_button)

        toolbar.add_top_bar(header)

        self._banner = Adw.Banner(revealed=False)
        self._banner.add_css_class("error")
        toolbar.add_top_bar(self._banner)

        toolbar.set_content(self._build_content())
        self.set_child(toolbar)

        if pair is not None:
            self._load(pair)
        self._update_schedule_visibility()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_content(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        page = Adw.PreferencesPage()

        # --- Allgemein -------------------------------------------------
        general = Adw.PreferencesGroup(title="Allgemein")

        self._name_row = Adw.EntryRow(title="Anzeigename")
        self._name_row.connect("changed", lambda _r: self._clear_error())
        general.add(self._name_row)

        self._mode_row = Adw.ComboRow(
            title="Synchronisationsmodus",
            model=Gtk.StringList.new(
                [
                    "2-Wege-Synchronisation (Cloud ⇄ Lokal)",
                    "Nur Upload (Lokal ➔ Cloud)",
                    "Nur Download (Cloud ➔ Lokal)",
                ]
            ),
        )
        general.add(self._mode_row)

        self._enabled_row = Adw.SwitchRow(
            title="Aktiviert",
            subtitle="Deaktivierte Paare laufen weder manuell noch per Zeitplan.",
            active=True,
        )
        general.add(self._enabled_row)
        page.add(general)

        # --- Ordner-Pfade ----------------------------------------------
        location = Adw.PreferencesGroup(
            title="Ordner-Pfade",
            description=(
                "Lokaler Ordner und zugehoeriger Ordner bei Proton Drive. "
                "Dateien bei Proton Drive werden niemals geloescht."
            ),
        )

        self._local_row = Adw.ActionRow(
            title="Lokaler Ordner",
            subtitle="Noch nichts ausgewaehlt",
        )
        choose_button = Gtk.Button(label="Auswaehlen…", valign=Gtk.Align.CENTER)
        choose_button.connect("clicked", self._choose_folder)
        self._local_row.add_suffix(choose_button)
        self._local_row.set_activatable_widget(choose_button)
        location.add(self._local_row)

        self._remote_row = Adw.EntryRow(title="Proton-Drive-Pfad")
        self._remote_row.set_text(f"{DEFAULT_REMOTE_ROOT}/")
        self._remote_row.connect("changed", self._on_remote_changed)
        location.add(self._remote_row)

        hint = Adw.ActionRow(
            title="Hinweis zum Proton-Drive-Pfad",
            subtitle=(
                f"Absoluter Pfad, z. B. {DEFAULT_REMOTE_ROOT}/Dokumente. "
                "Fehlende Ordner werden automatisch angelegt."
            ),
        )
        hint.add_css_class("property")
        location.add(hint)
        page.add(location)

        # --- Zeitplan ---------------------------------------------------
        schedule = Adw.PreferencesGroup(
            title="Zeitplan",
            description=(
                "Bei einem Intervall wird ein systemd-Timer im Benutzerkontext eingerichtet."
            ),
        )

        self._schedule_row = Adw.ComboRow(
            title="Ausloesung",
            model=Gtk.StringList.new(["Manuell", "Alle X Minuten"]),
        )
        self._schedule_row.connect("notify::selected", self._on_schedule_changed)
        schedule.add(self._schedule_row)

        self._interval_row = Adw.SpinRow.new_with_range(
            MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES, 5
        )
        self._interval_row.set_title("Intervall in Minuten")
        self._interval_row.set_value(60)
        schedule.add(self._interval_row)
        page.add(schedule)

        # --- Filter ------------------------------------------------------
        filters = Adw.PreferencesGroup(title="Filter")

        self._size_limit_row = Adw.SwitchRow(
            title="Groessenlimit pro Datei",
            subtitle="Groessere Dateien werden uebersprungen und protokolliert.",
            active=False,
        )
        self._size_limit_row.connect("notify::active", self._on_size_limit_toggled)
        filters.add(self._size_limit_row)

        self._size_row = Adw.SpinRow.new_with_range(1, 1024 * 100, 1)
        self._size_row.set_title("Limit in MiB")
        self._size_row.set_value(512)
        self._size_row.set_sensitive(False)
        filters.add(self._size_row)
        page.add(filters)

        # --- Ausschlussregeln --------------------------------------------
        excludes = Adw.PreferencesGroup(
            title="Ausschlussregeln",
            description=_EXCLUDE_HELP,
        )
        self._exclude_view = Gtk.TextView(
            monospace=True,
            top_margin=8,
            bottom_margin=8,
            left_margin=8,
            right_margin=8,
        )
        exclude_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            min_content_height=140,
            vexpand=False,
        )
        exclude_scroll.set_child(self._exclude_view)
        exclude_scroll.add_css_class("card")
        excludes.add(exclude_scroll)
        page.add(excludes)

        scrolled.set_child(page)
        return scrolled

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------

    def _choose_folder(self, _button: Gtk.Button) -> None:
        """Oeffnet die GTK-Ordnerauswahl."""
        dialog = Gtk.FileDialog(title="Lokalen Quellordner waehlen", modal=True)
        if self._local_path is not None and self._local_path.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(self._local_path)))
        else:
            dialog.set_initial_folder(Gio.File.new_for_path(str(Path.home())))
        dialog.select_folder(self._parent, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        """Uebernimmt den gewaehlten Ordner."""
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:  # pragma: no cover -- Benutzerabbruch der Auswahl
            return
        if folder is None:
            return
        path = folder.get_path()
        if path is None:
            self._show_error("Der gewaehlte Ort liegt nicht im lokalen Dateisystem.")
            return
        try:
            self._local_path = validate_local_path(path)
        except ValidationError as error:
            self._show_error(str(error))
            return
        self._local_row.set_subtitle(str(self._local_path))
        self._clear_error()
        if not self._name_row.get_text().strip():
            self._name_row.set_text(self._local_path.name)

    def _on_schedule_changed(self, _row: Adw.ComboRow, _param: object) -> None:
        self._update_schedule_visibility()

    def _update_schedule_visibility(self) -> None:
        """Blendet das Intervallfeld nur bei Bedarf ein."""
        self._interval_row.set_sensitive(self._schedule_row.get_selected() == 1)

    def _on_size_limit_toggled(self, _row: Adw.SwitchRow, _param: object) -> None:
        self._size_row.set_sensitive(self._size_limit_row.get_active())

    def _on_remote_changed(self, _row: Adw.EntryRow) -> None:
        """Prueft den Zielpfad waehrend der Eingabe."""
        text = self._remote_row.get_text().strip()
        if not text or text == f"{DEFAULT_REMOTE_ROOT}/":
            self._remote_row.remove_css_class("error")
            self._clear_error()
            return
        try:
            validate_remote_path(text)
        except ValidationError:
            self._remote_row.add_css_class("error")
        else:
            self._remote_row.remove_css_class("error")
            self._clear_error()

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        """Validiert die Eingaben und meldet das fertige Paar."""
        if self._local_path is None:
            self._show_error("Bitte einen lokalen Quellordner auswaehlen.")
            return

        buffer = self._exclude_view.get_buffer()
        exclude_text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

        interval_selected = self._schedule_row.get_selected() == 1
        schedule_kind = ScheduleKind.INTERVAL if interval_selected else ScheduleKind.MANUAL
        interval = int(self._interval_row.get_value()) if interval_selected else None

        mode_idx = self._mode_row.get_selected()
        if mode_idx == 1:
            sync_mode = SyncMode.UPLOAD_ONLY
        elif mode_idx == 2:
            sync_mode = SyncMode.DOWNLOAD_ONLY
        else:
            sync_mode = SyncMode.BIDIRECTIONAL

        max_size = (
            int(self._size_row.get_value()) * _MIB if self._size_limit_row.get_active() else None
        )

        try:
            pair = SyncPair.create(
                name=self._name_row.get_text(),
                local_path=self._local_path,
                remote_path=self._remote_row.get_text(),
                enabled=self._enabled_row.get_active(),
                sync_mode=sync_mode,
                schedule_kind=schedule_kind,
                interval_minutes=interval,
                exclude_patterns=parse_exclude_patterns(exclude_text),
                max_file_size_bytes=max_size,
                uid=self._pair.uid if self._pair else None,
            )
        except ValidationError as error:
            self._show_error(str(error))
            return

        if self._pair is not None:
            pair = pair.with_changes(created_at=self._pair.created_at)

        self._on_save(pair)
        self.close()

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------

    def _load(self, pair: SyncPair) -> None:
        """Fuellt das Formular mit einem bestehenden Paar."""
        self._name_row.set_text(pair.name)
        self._local_row.set_subtitle(str(pair.local_path))
        self._remote_row.set_text(pair.remote_path)
        self._enabled_row.set_active(pair.enabled)

        if pair.sync_mode is SyncMode.UPLOAD_ONLY:
            self._mode_row.set_selected(1)
        elif pair.sync_mode is SyncMode.DOWNLOAD_ONLY:
            self._mode_row.set_selected(2)
        else:
            self._mode_row.set_selected(0)

        if pair.schedule_kind is ScheduleKind.INTERVAL:
            self._schedule_row.set_selected(1)
            if pair.interval_minutes:
                self._interval_row.set_value(pair.interval_minutes)
        else:
            self._schedule_row.set_selected(0)

        if pair.max_file_size_bytes:
            self._size_limit_row.set_active(True)
            self._size_row.set_sensitive(True)
            self._size_row.set_value(max(1, pair.max_file_size_bytes // _MIB))

        self._exclude_view.get_buffer().set_text("\n".join(pair.exclude_patterns))

    def _show_error(self, message: str) -> None:
        """Zeigt eine Fehlermeldung im Kopfbereich."""
        self._banner.set_title(message.replace("\n", " "))
        self._banner.set_revealed(True)

    def _clear_error(self) -> None:
        """Blendet eine Fehlermeldung wieder aus."""
        self._banner.set_revealed(False)


__all__ = ["PairDialog"]
