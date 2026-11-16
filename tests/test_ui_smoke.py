"""Aufbau-Tests der GTK-Oberflaeche.

Diese Tests belegen, dass jede verwendete GTK4-/libadwaita-API tatsaechlich
existiert und die Widget-Hierarchien sich bauen lassen -- etwas, das die
uebrigen Tests nicht abdecken koennen, weil die Sync-Logik bewusst kein GTK
kennt.

Es wird nur *konstruiert*, nichts angezeigt (kein ``present()``): Ein
Testlauf soll keine Fenster auf dem Bildschirm aufblitzen lassen.

Ohne importierbares GTK oder ohne grafische Sitzung werden die Tests
uebersprungen -- die Kernlogik bleibt vollstaendig ohne Display pruefbar.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

from proton_sync_ui.models.plan import PlanAction, PlanItem, UploadPlan
from proton_sync_ui.models.run import FileError, RunRecord, RunStatus
from proton_sync_ui.models.sync_pair import SyncPair
from proton_sync_ui.storage.repository import Repository

MakeFile = Callable[..., Path]


def _gtk_available() -> bool:
    """Prueft, ob GTK4, libadwaita und eine grafische Sitzung vorhanden sind."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        return bool(Gtk.init_check()) and Adw is not None
    except (ImportError, ValueError):
        return False


pytestmark = [
    pytest.mark.gtk,
    pytest.mark.skipif(not _gtk_available(), reason="GTK4/libadwaita oder grafische Sitzung fehlt"),
]


@pytest.fixture(autouse=True)
def no_real_proton_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sorgt dafuer, dass kein Test die echte Proton-Drive-CLI aufruft.

    Das Hauptfenster prueft beim Aufbau im Hintergrund den Anmeldezustand.
    Ohne diese Absicherung wuerde dabei das echte ``proton-drive`` mit dem
    Konto des Benutzers kontaktiert -- in einem Testlauf inakzeptabel. Mit
    leerem PATH meldet die Pruefung sauber "nicht gefunden".
    """
    empty_bin = tmp_path / "leeres-bin"
    empty_bin.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_bin))


@pytest.fixture(scope="session")
def adw_app():
    """Eine registrierte Adw.Application als Elternobjekt der Fenster.

    ``register()`` loest das startup-Signal aus; ohne das beschwert sich GTK
    zu Recht, dass Fenster vor dem Start hinzugefuegt werden.

    ``NON_UNIQUE`` verhindert, dass die Anwendung einen eindeutigen Namen auf
    dem Sitzungsbus beansprucht -- sonst scheitert die Registrierung, sobald
    mehr als ein Test eine Anwendung erzeugt. Aus demselben Grund ist die
    Vorrichtung sitzungsweit.
    """
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio

    Adw.init()
    app = Adw.Application(
        application_id="io.github.protonsyncui.Test",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture
def runner():
    """Ein gestarteter Arbeitsthread, der am Ende sauber beendet wird."""
    from proton_sync_ui.ui.runner import AsyncRunner

    active = AsyncRunner()
    active.start()
    yield active
    active.stop()


@pytest.fixture
def main_window(adw_app, runner, repository: Repository, stored_pair: SyncPair):
    """Das Hauptfenster mit einem gespeicherten Sync-Paar."""
    from proton_sync_ui.ui.window import MainWindow

    return MainWindow(adw_app, repository=repository, runner=runner)


class TestMainWindow:
    """Aufbau der Uebersicht."""

    def test_window_builds(self, main_window) -> None:
        assert main_window.get_title() == "ProtonSyncUI"

    def test_pair_row_is_created(self, main_window, stored_pair: SyncPair) -> None:
        assert stored_pair.uid in main_window._rows

    def test_refresh_is_idempotent(self, main_window) -> None:
        before = len(main_window._rows)
        main_window.refresh()
        main_window.refresh()
        assert len(main_window._rows) == before

    def test_removed_pair_disappears(
        self,
        main_window,
        repository: Repository,
        stored_pair: SyncPair,
    ) -> None:
        repository.delete_pair(stored_pair.uid)
        main_window.refresh()
        assert main_window._rows == {}

    def test_toast_can_be_shown(self, main_window) -> None:
        main_window.toast("Testmeldung")


class TestPairRow:
    """Die Zeile eines Sync-Paars."""

    def test_row_reflects_the_pair(self, main_window, stored_pair: SyncPair) -> None:
        row = main_window._rows[stored_pair.uid]
        assert stored_pair.name in row.get_title()

    def test_busy_state_toggles(self, main_window, stored_pair: SyncPair) -> None:
        row = main_window._rows[stored_pair.uid]
        row.set_busy(True)
        assert row._cancel_button.get_visible() is True
        row.set_busy(False)
        assert row._cancel_button.get_visible() is False

    def test_progress_updates(self, main_window, stored_pair: SyncPair) -> None:
        from proton_sync_ui.sync.engine import SyncPhase, SyncProgress

        row = main_window._rows[stored_pair.uid]
        row.update_progress(
            SyncProgress(
                pair_uid=stored_pair.uid,
                phase=SyncPhase.UPLOADING,
                current=1,
                total=4,
                relative_path="ordner/datei.txt",
            )
        )
        assert row._progress_bar.get_fraction() == pytest.approx(0.25)

    def test_markup_characters_in_names_are_escaped(
        self,
        main_window,
        repository: Repository,
        source_dir: Path,
    ) -> None:
        # Ein "&" im Namen wuerde Pango-Markup sonst zerlegen.
        pair = SyncPair.create(
            name="Fotos & <Videos>",
            local_path=source_dir,
            remote_path="/my-files/Backup/Medien",
        )
        repository.save_pair(pair)
        main_window.refresh()

        row = main_window._rows[pair.uid]
        assert "&amp;" in row.get_title()
        assert "&lt;" in row.get_title()

    def test_status_is_shown_after_a_run(
        self,
        main_window,
        stored_pair: SyncPair,
    ) -> None:
        row = main_window._rows[stored_pair.uid]
        record = RunRecord(pair_uid=stored_pair.uid, run_id=1, uploaded_files=2, planned_files=2)
        record.finish()
        row.update_run(record)
        assert row._status_label.get_label() == "Erfolgreich"


class TestDialogs:
    """Dialoge lassen sich aufbauen."""

    def test_add_dialog(self, main_window) -> None:
        from proton_sync_ui.ui.pair_dialog import PairDialog

        dialog = PairDialog(main_window, pair=None, on_save=lambda _p: None)
        assert dialog.get_title() == "Sync-Paar hinzufuegen"

    def test_edit_dialog_is_prefilled(self, main_window, stored_pair: SyncPair) -> None:
        from proton_sync_ui.ui.pair_dialog import PairDialog

        dialog = PairDialog(main_window, pair=stored_pair, on_save=lambda _p: None)
        assert dialog._name_row.get_text() == stored_pair.name
        assert dialog._remote_row.get_text() == stored_pair.remote_path

    def test_log_window(self, main_window) -> None:
        from proton_sync_ui.ui.log_window import LogWindow

        window = LogWindow(main_window)
        assert window.get_title() == "Protokoll"

    def test_log_window_for_one_pair(self, main_window, stored_pair: SyncPair) -> None:
        from proton_sync_ui.ui.log_window import LogWindow

        window = LogWindow(main_window, pair=stored_pair)
        assert stored_pair.name in window.get_title()

    def test_preflight_dialogs(self, main_window) -> None:
        from proton_sync_ui.ui.preflight import (
            show_cli_missing_dialog,
            show_not_authenticated_dialog,
        )

        missing = show_cli_missing_dialog(main_window)
        auth = show_not_authenticated_dialog(main_window)
        assert "nicht gefunden" in missing.get_heading()
        assert "auth login" in auth.get_body()

    def test_plan_dialog_with_all_sections(
        self,
        main_window,
        stored_pair: SyncPair,
    ) -> None:
        plan = UploadPlan.from_items(
            stored_pair.uid,
            [
                PlanItem(PurePosixPath("neu.txt"), PlanAction.UPLOAD_NEW, 1234, 1),
                PlanItem(PurePosixPath("a/b & c.txt"), PlanAction.UPLOAD_CHANGED, 99, 2),
                PlanItem(PurePosixPath("gleich.txt"), PlanAction.SKIP_UNCHANGED, 10, 3),
                PlanItem(PurePosixPath("weg.txt"), PlanAction.LOCAL_DELETED, 20, 0),
            ],
            scan_errors=("gesperrt/: Zugriff verweigert",),
        )
        record = RunRecord(pair_uid=stored_pair.uid, run_id=1, dry_run=True)
        record.finish()

        main_window._show_plan_dialog(stored_pair, plan, record)

    def test_error_dialog(self, main_window, stored_pair: SyncPair) -> None:
        record = RunRecord(pair_uid=stored_pair.uid, run_id=2, uploaded_files=3, failed_files=2)
        record.errors = [
            FileError("a/gross.bin", "Kontingent erschoepft", attempts=1, permanent=True),
            FileError("b/wackelig.txt", "Netzwerkfehler", attempts=3, permanent=False),
        ]
        record.finish()
        assert record.status is RunStatus.WARNING

        main_window._show_errors_dialog(stored_pair, record)

    def test_about_dialog_states_the_security_model(self, main_window) -> None:
        from proton_sync_ui.ui.about_dialog import AboutDialog, developer_logo_path

        main_window.show_about()
        # Das Entwickler-Logo wird mit dem Paket ausgeliefert.
        assert developer_logo_path() is not None
        assert AboutDialog(main_window).get_title() == "Ueber ProtonSyncUI"

    def test_delete_confirmation_mentions_remote_stays(
        self,
        main_window,
        stored_pair: SyncPair,
    ) -> None:
        main_window.confirm_delete(stored_pair)


class TestApplication:
    """Die Anwendungsklasse selbst."""

    def test_application_can_be_created(self) -> None:
        from proton_sync_ui.ui.application import ProtonSyncUIApplication

        app = ProtonSyncUIApplication()
        assert app.get_application_id() == "io.github.protonsyncui.ProtonSyncUI"
