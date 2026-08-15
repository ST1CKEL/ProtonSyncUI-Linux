"""Tests der zentralen Sicherheitszusage: niemals entfernte Daten loeschen.

Diese Datei prueft die Zusage auf drei Ebenen:

1. Die Argumentlisten-Ebene -- gesperrte Verben und Strategien.
2. Die Ausfuehrungsebene -- der Adapter startet gesperrte Kommandos nicht.
3. Die Ablaufebene -- ein vollstaendiger Lauf mit lokal geloeschten Dateien
   erzeugt keinen einzigen veraendernden Aufruf.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

from proton_sync_ui.cli_adapter import commands
from proton_sync_ui.cli_adapter.adapter import ProtonDriveAdapter
from proton_sync_ui.cli_adapter.errors import ForbiddenCommandError
from proton_sync_ui.models.plan import UPLOAD_ACTIONS, PlanAction
from proton_sync_ui.models.sync_pair import SyncPair
from proton_sync_ui.storage.repository import Repository
from proton_sync_ui.sync.engine import SyncEngine

from .fake_proton_drive import FakeAdapter

MakeFile = Callable[..., Path]

#: Verben, die entfernte Daten veraendern oder loeschen wuerden.
DESTRUCTIVE_VERBS = [
    "trash",
    "delete",
    "empty-trash",
    "rename",
    "move",
    "restore",
    "remove",
    "remove-url",
    "remove-photo",
    "leave",
]


class TestForbiddenVerbs:
    """Die Sperrliste auf Ebene der Argumentlisten."""

    @pytest.mark.parametrize("verb", DESTRUCTIVE_VERBS)
    def test_destructive_verb_is_rejected(self, verb: str) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(["filesystem", verb, "/my-files/datei.txt"])

    def test_empty_trash_is_rejected(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(["filesystem", "empty-trash"])

    def test_logout_is_rejected(self) -> None:
        # ProtonSyncUI fasst die Anmeldung grundsaetzlich nicht an.
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(["auth", "logout"])

    def test_download_is_allowed(self) -> None:
        # Download fuer 2-Wege-Sync freigegeben.
        commands.assert_command_allowed(["filesystem", "download", "/my-files/a", "/tmp"])

    @pytest.mark.parametrize("group", ["sharing", "album", "invitation", "photo"])
    def test_forbidden_groups_are_rejected(self, group: str) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed([group, "list", "/my-files"])


class TestAllowList:
    """Nur ausdruecklich freigegebene Kommandos sind erlaubt."""

    def test_allow_list_is_minimal(self) -> None:
        assert (
            frozenset(
                {
                    ("filesystem", "list"),
                    ("filesystem", "info"),
                    ("filesystem", "create-folder"),
                    ("filesystem", "upload"),
                    ("filesystem", "download"),
                }
            )
            == commands.ALLOWED_COMMANDS
        )

    def test_allowed_commands_pass(self) -> None:
        commands.assert_command_allowed(commands.list_args("/my-files"))
        commands.assert_command_allowed(commands.info_args("/my-files/a"))
        commands.assert_command_allowed(commands.create_folder_args("/my-files", "Backup"))
        commands.assert_command_allowed(
            commands.upload_args([Path("/tmp/a.txt")], "/my-files/Backup")
        )

    def test_unknown_command_is_rejected(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(["filesystem", "erfundenes-verb", "/my-files"])

    def test_version_flag_is_allowed(self) -> None:
        commands.assert_command_allowed(commands.version_args())

    def test_empty_argv_is_rejected(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed([])


class TestConflictStrategies:
    """Die Strategie 'replace' wuerde entfernte Daten in den Papierkorb legen."""

    def test_default_file_strategy_preserves_history(self) -> None:
        assert commands.FILE_CONFLICT_STRATEGY == "create-new-revision"

    def test_default_folder_strategy_merges(self) -> None:
        assert commands.FOLDER_CONFLICT_STRATEGY == "merge"

    def test_replace_is_in_the_forbidden_set(self) -> None:
        assert "replace" in commands.FORBIDDEN_STRATEGIES

    def test_upload_args_reject_replace_for_files(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.upload_args([Path("/tmp/a.txt")], "/my-files/Backup", file_strategy="replace")

    def test_upload_args_reject_replace_for_folders(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.upload_args(
                [Path("/tmp/a.txt")], "/my-files/Backup", folder_strategy="replace"
            )

    def test_guard_catches_replace_in_a_handcrafted_argv(self) -> None:
        # Zweite Verteidigungslinie: selbst eine von Hand gebaute Liste wird
        # unmittelbar vor dem Prozessstart abgefangen.
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(
                [
                    "filesystem",
                    "upload",
                    "-f",
                    "replace",
                    "/tmp/a.txt",
                    "/my-files/Backup",
                ]
            )

    def test_guard_catches_long_form_replace(self) -> None:
        with pytest.raises(ForbiddenCommandError):
            commands.assert_command_allowed(
                [
                    "filesystem",
                    "upload",
                    "--folder-conflict-strategy",
                    "replace",
                    "/tmp/a.txt",
                    "/my-files/Backup",
                ]
            )

    def test_generated_upload_never_contains_replace(self) -> None:
        argv = commands.upload_args([Path("/tmp/a.txt")], "/my-files/Backup")
        assert "replace" not in argv


class TestAdapterRefusesToStartForbiddenCommands:
    """Der Adapter startet gesperrte Kommandos gar nicht erst."""

    def test_run_raises_before_starting_a_process(self, tmp_path: Path) -> None:
        # Ein Programmpfad, der nicht existiert: Wuerde der Adapter starten
        # wollen, gaebe es einen anderen Fehler als ForbiddenCommandError.
        adapter = ProtonDriveAdapter(binary=str(tmp_path / "gibt-es-nicht"))

        with pytest.raises(ForbiddenCommandError):
            asyncio.run(adapter.run(["filesystem", "trash", "/my-files/a"]))

    def test_adapter_has_no_delete_methods(self) -> None:
        method_names = {
            name for name, _ in inspect.getmembers(ProtonDriveAdapter, inspect.isfunction)
        }
        for forbidden in ("trash", "delete", "remove", "rename", "move", "empty_trash"):
            assert not any(forbidden in name for name in method_names), (
                f"Der Adapter darf keine Methode mit '{forbidden}' im Namen haben."
            )


class TestPlanNeverDeletesRemotely:
    """Auf Ebene des Plans gibt es keine loeschende Aktion."""

    def test_no_plan_action_deletes_remotely(self) -> None:
        for action in PlanAction:
            assert "remote_delete" not in action.value
            assert action.value != "delete"

    def test_local_deleted_is_not_an_upload_action(self) -> None:
        assert PlanAction.LOCAL_DELETED not in UPLOAD_ACTIONS


class TestFullRunNeverDeletes:
    """Ein vollstaendiger Lauf mit geloeschten Dateien bleibt folgenlos."""

    def test_locally_deleted_file_triggers_no_remote_call(
        self,
        repository: Repository,
        source_dir: Path,
        make_file: MakeFile,
    ) -> None:
        pair = SyncPair.create(
            name="Loeschtest", local_path=source_dir, remote_path="/my-files/Backup"
        )
        repository.save_pair(pair)

        # Erster Lauf: zwei Dateien uebertragen.
        make_file("bleibt.txt", "A")
        make_file("verschwindet.txt", "B")
        adapter = FakeAdapter()
        engine = SyncEngine(repository, adapter)
        asyncio.run(engine.sync(pair))
        assert sorted(adapter.uploaded_names) == ["bleibt.txt", "verschwindet.txt"]

        # Eine Datei lokal loeschen und erneut laufen.
        (source_dir / "verschwindet.txt").unlink()
        adapter_two = FakeAdapter(existing_folders={"/my-files/Backup"})
        engine_two = SyncEngine(repository, adapter_two)
        record, plan = asyncio.run(engine_two.sync(pair))

        assert len(plan.local_deletions) == 1
        assert plan.local_deletions[0].posix_path == "verschwindet.txt"
        # Entscheidend: kein einziger veraendernder Aufruf.
        assert adapter_two.forbidden_calls() == []
        assert adapter_two.uploaded_names == []
        assert record.local_deletions == 1

    def test_deletion_only_removes_local_bookkeeping(
        self,
        repository: Repository,
        source_dir: Path,
        make_file: MakeFile,
    ) -> None:
        pair = SyncPair.create(
            name="Buchfuehrung", local_path=source_dir, remote_path="/my-files/Backup"
        )
        repository.save_pair(pair)

        make_file("datei.txt", "A")
        asyncio.run(SyncEngine(repository, FakeAdapter()).sync(pair))
        assert "datei.txt" in repository.load_file_states(pair.uid)

        (source_dir / "datei.txt").unlink()
        asyncio.run(SyncEngine(repository, FakeAdapter()).sync(pair))

        # Der lokale Zustandseintrag verschwindet, mehr passiert nicht.
        assert "datei.txt" not in repository.load_file_states(pair.uid)

    def test_every_call_of_a_run_is_on_the_allow_list(
        self,
        repository: Repository,
        source_dir: Path,
        make_file: MakeFile,
    ) -> None:
        pair = SyncPair.create(
            name="Vollstaendig", local_path=source_dir, remote_path="/my-files/Backup/Tief"
        )
        repository.save_pair(pair)
        make_file("a.txt")
        make_file("unter/b.txt")
        make_file("unter/noch/tiefer/c.txt")

        adapter = FakeAdapter()
        asyncio.run(SyncEngine(repository, adapter).sync(pair))

        assert adapter.argv_log, "Es sollten Aufrufe stattgefunden haben."
        for argv in adapter.argv_log:
            group, verb = argv[0], argv[1]
            assert (group, verb) in commands.ALLOWED_COMMANDS, f"Unerlaubter Aufruf im Lauf: {argv}"

    def test_dry_run_transfers_nothing(
        self,
        repository: Repository,
        source_dir: Path,
        make_file: MakeFile,
    ) -> None:
        pair = SyncPair.create(
            name="Nur Plan", local_path=source_dir, remote_path="/my-files/Backup"
        )
        repository.save_pair(pair)
        make_file("a.txt")
        make_file("b.txt")

        adapter = FakeAdapter()
        record, plan = asyncio.run(SyncEngine(repository, adapter).dry_run(pair))

        assert len(plan.uploads) == 2
        assert adapter.uploads == []
        assert adapter.created_folders == []
        assert record.uploaded_files == 0
        assert record.dry_run is True
        # Nach einem Dry-Run darf nichts als uebertragen vermerkt sein.
        assert repository.load_file_states(pair.uid) == {}
