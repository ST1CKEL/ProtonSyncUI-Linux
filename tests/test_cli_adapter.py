"""Tests des CLI-Adapters: Argumentlisten, Prozessstart, Fehlereinordnung.

Kein Test in dieser Datei ruft die echte Proton-Drive-CLI auf. Wo ein echter
Prozess noetig ist, wird das Skript aus :mod:`tests.fake_proton_drive`
verwendet.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import pytest

from proton_sync_ui.cli_adapter import commands
from proton_sync_ui.cli_adapter.adapter import (
    ProtonDriveAdapter,
    _parse_nodes,
    classify_error,
)
from proton_sync_ui.cli_adapter.capabilities import parse_version, probe
from proton_sync_ui.cli_adapter.errors import (
    CommandTimeoutError,
    NotAuthenticatedError,
    PermanentError,
    ProtonCliNotFoundError,
    RemotePathExistsError,
    RemotePathNotFoundError,
    TransientError,
)
from proton_sync_ui.logging_setup import redact

from .fake_proton_drive import (
    FakeAdapter,
    fake_cli_env,
    read_recorded_calls,
    write_fake_cli,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "proton_sync_ui"


class TestArgumentLists:
    """Die Argumentlisten entsprechen der gemessenen CLI-Syntax."""

    def test_upload_matches_documented_syntax(self) -> None:
        argv = commands.upload_args([Path("/home/nutzer/a.txt")], "/my-files/Backup")

        assert argv == [
            "filesystem",
            "upload",
            "-f",
            "create-new-revision",
            "-d",
            "merge",
            "/home/nutzer/a.txt",
            "/my-files/Backup",
        ]

    def test_upload_puts_parent_path_last(self) -> None:
        # Laut 'filesystem upload --help' ist das letzte Argument der
        # Elternordner, nicht der Zieldateiname.
        argv = commands.upload_args([Path("/a.txt"), Path("/b.txt")], "/my-files/Ziel")
        assert argv[-1] == "/my-files/Ziel"

    def test_upload_with_skip_thumbnails(self) -> None:
        argv = commands.upload_args([Path("/a.jpg")], "/my-files/Bilder", skip_thumbnails=True)
        assert "-t" in argv

    def test_list_places_json_flag_after_subcommand(self) -> None:
        # Gemessen: '-j' vor dem Unterkommando zeigt nur die Hilfe.
        argv = commands.list_args("/my-files")
        assert argv.index("-j") > argv.index("list")

    def test_list_with_type_filter(self) -> None:
        argv = commands.list_args("/my-files", type_filter="folder")
        assert argv[:4] == ["filesystem", "list", "-t", "folder"]

    def test_list_rejects_unknown_type_filter(self) -> None:
        with pytest.raises(ValueError, match="Typfilter"):
            commands.list_args("/my-files", type_filter="verzeichnis")

    def test_auth_probe_is_a_cheap_read(self) -> None:
        assert commands.auth_probe_args() == ["filesystem", "list", "/", "-j"]

    def test_create_folder_takes_parent_and_name(self) -> None:
        assert commands.create_folder_args("/my-files", "Backup") == [
            "filesystem",
            "create-folder",
            "/my-files",
            "Backup",
        ]

    def test_create_folder_rejects_slash_in_name(self) -> None:
        with pytest.raises(ValueError, match="Ordnername"):
            commands.create_folder_args("/my-files", "a/b")


class TestArgumentSafety:
    """Argumentlisten statt Shell -- Sonderzeichen bleiben Daten."""

    def test_local_paths_must_be_absolute(self) -> None:
        # Absolute Pfade schliessen aus, dass ein Dateiname mit fuehrendem
        # Bindestrich als Option gelesen wird.
        with pytest.raises(ValueError, match="absolut"):
            commands.upload_args([Path("relativ.txt")], "/my-files/Backup")

    def test_remote_paths_must_be_absolute(self) -> None:
        with pytest.raises(ValueError, match="absolut"):
            commands.upload_args([Path("/a.txt")], "my-files/Backup")

    def test_null_byte_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Nullbyte"):
            commands.list_args("/my-files/\0boese")

    @pytest.mark.parametrize(
        "filename",
        [
            "datei; rm -rf ~.txt",
            "datei && echo hallo.txt",
            "datei$(whoami).txt",
            "datei`id`.txt",
            "datei|pipe.txt",
            "datei>umleitung.txt",
            "datei mit leerzeichen.txt",
            "datei'mit'anfuehrung.txt",
            'datei"doppelt".txt',
            "datei\nmit\numbruch.txt",
            "-fuehrender-bindestrich.txt",
            "datei*stern?.txt",
        ],
    )
    def test_special_characters_stay_one_argument(self, filename: str) -> None:
        argv = commands.upload_args([Path("/tmp") / filename], "/my-files/Backup")

        # Der Dateiname bleibt genau ein Listenelement -- unverandert.
        assert f"/tmp/{filename}" in argv
        assert len(argv) == 8

    def test_argv_is_a_list_of_strings(self) -> None:
        argv = commands.upload_args([Path("/a.txt")], "/my-files/Backup")
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)


class TestNoShellInSource:
    """Belegt fuer den gesamten Quellcode, dass keine Shell benutzt wird.

    Geprueft wird der Syntaxbaum, nicht der Rohtext: Erwaehnungen in
    Kommentaren und Docstrings -- etwa die Zusage "shell=True kommt nicht
    vor" -- sollen keinen Fehlalarm ausloesen, echter Code dagegen sehr wohl.
    """

    def _python_sources(self) -> list[Path]:
        return sorted(SRC_ROOT.rglob("*.py"))

    def _trees(self) -> list[tuple[Path, ast.Module]]:
        return [
            (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            for path in self._python_sources()
        ]

    @staticmethod
    def _dotted_name(node: ast.expr) -> str:
        """Baut 'os.system' aus einem Attributzugriff."""
        parts: list[str] = []
        current: ast.expr | None = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def test_source_files_were_found(self) -> None:
        assert len(self._python_sources()) > 20

    def test_no_call_passes_shell_true(self) -> None:
        offenders: list[str] = []
        for path, tree in self._trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == [], f"shell=True im Code gefunden: {offenders}"

    def test_no_shell_spawning_functions_are_called(self) -> None:
        forbidden = {
            "os.system",
            "os.popen",
            "subprocess.getoutput",
            "subprocess.getstatusoutput",
            "commands.getoutput",
            "asyncio.create_subprocess_shell",
        }
        offenders: list[str] = []
        for path, tree in self._trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = self._dotted_name(node.func)
                    if name in forbidden:
                        offenders.append(f"{path.name}:{node.lineno} -> {name}")
        assert offenders == [], f"Shell-startende Aufrufe gefunden: {offenders}"

    def test_only_exec_variants_of_subprocess_are_used(self) -> None:
        # create_subprocess_exec statt _shell, subprocess.run statt Shell-Hilfen.
        used: set[str] = set()
        for _path, tree in self._trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = self._dotted_name(node.func)
                    if "subprocess" in name:
                        used.add(name)
        assert used <= {
            "asyncio.create_subprocess_exec",
            "asyncio.subprocess.DEVNULL",
            "subprocess.run",
            "subprocess.Popen",
        }, f"Unerwartete subprocess-Aufrufe: {used}"

    def test_subprocess_is_only_imported_where_expected(self) -> None:
        users = {
            path.relative_to(SRC_ROOT).as_posix()
            for path in self._python_sources()
            if re.search(r"^\s*(import|from)\s+subprocess", path.read_text("utf-8"), re.M)
        }
        assert users <= {
            "cli_adapter/adapter.py",
            "systemd/manager.py",
            "update.py",
            "launcher.py",
            "cli_update.py",
        }, f"Unerwartete Nutzung von subprocess: {users}"


class TestRealProcessExecution:
    """Echter Prozessstart gegen das Fake-Skript."""

    def test_arguments_arrive_unmodified(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        record = tmp_path / "aufrufe.jsonl"

        # Ein Dateiname, der als Shell-Kommando verheerend waere. Der Name
        # enthaelt bewusst keinen Schraegstrich -- er muss ein einzelner
        # Dateiname bleiben. Laege irgendwo eine Shell dazwischen, entstuende
        # im Arbeitsverzeichnis die Datei "beweis".
        marker = tmp_path / "beweis"
        tricky = tmp_path / "datei; touch beweis; echo x"
        tricky.write_text("Inhalt")

        adapter = ProtonDriveAdapter(binary=str(binary), env=fake_cli_env(record))
        argv = commands.upload_args([tricky], "/my-files/Backup")
        result = asyncio.run(adapter.run(argv, cwd=tmp_path))

        assert result.ok
        calls = read_recorded_calls(record)
        # Der gefaehrlich aussehende Name kam als genau ein Argument an.
        assert calls[0] == argv
        assert str(tricky) in calls[0]
        # Und wurde nirgends ausgefuehrt.
        assert not marker.exists()

    def test_semicolons_and_pipes_are_not_interpreted(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        record = tmp_path / "aufrufe.jsonl"
        marker = tmp_path / "sollte-nicht-entstehen"

        adapter = ProtonDriveAdapter(binary=str(binary), env=fake_cli_env(record))
        # Der Zielpfad enthaelt Shell-Metazeichen.
        argv = commands.list_args(f"/my-files/a && touch {marker}")
        asyncio.run(adapter.run(argv))

        assert not marker.exists()
        assert read_recorded_calls(record)[0] == argv

    def test_version_is_parsed(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        record = tmp_path / "aufrufe.jsonl"

        adapter = ProtonDriveAdapter(binary=str(binary), env=fake_cli_env(record))
        raw = asyncio.run(adapter.version())

        assert "cli-drive@0.8.0" in raw

    def test_nonzero_exit_is_reported_not_raised(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        record = tmp_path / "aufrufe.jsonl"
        env = fake_cli_env(record, FAKE_CLI_EXIT="1", FAKE_CLI_STDERR="Node not found: x")

        adapter = ProtonDriveAdapter(binary=str(binary), env=env)
        result = asyncio.run(adapter.run(commands.list_args("/my-files/x")))

        assert result.returncode == 1
        assert not result.ok
        assert "Node not found" in result.combined_output

    def test_run_checked_raises_on_failure(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        env = fake_cli_env(
            tmp_path / "aufrufe.jsonl", FAKE_CLI_EXIT="1", FAKE_CLI_STDERR="Node not found: x"
        )

        adapter = ProtonDriveAdapter(binary=str(binary), env=env)

        with pytest.raises(RemotePathNotFoundError):
            asyncio.run(adapter.run_checked(commands.list_args("/my-files/x")))

    def test_stdin_is_closed_so_prompts_cannot_block(self, tmp_path: Path) -> None:
        # Ein Skript, das auf Eingabe wartet, muss sofort zurueckkehren,
        # weil stdin auf DEVNULL liegt.
        script = tmp_path / "bin" / "proton-drive"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "data = sys.stdin.read()\n"
            "print('gelesen:', len(data))\n"
        )
        script.chmod(0o755)

        adapter = ProtonDriveAdapter(binary=str(script))
        result = asyncio.run(adapter.run(commands.list_args("/my-files"), timeout=10))

        assert result.ok
        assert "gelesen: 0" in result.stdout

    def test_timeout_terminates_the_process(self, tmp_path: Path) -> None:
        script = tmp_path / "bin" / "proton-drive"
        script.parent.mkdir(parents=True)
        script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
        script.chmod(0o755)

        adapter = ProtonDriveAdapter(binary=str(script))

        with pytest.raises(CommandTimeoutError):
            asyncio.run(adapter.run(commands.list_args("/my-files"), timeout=1.0))

    def test_missing_binary_gives_helpful_message(self, tmp_path: Path) -> None:
        adapter = ProtonDriveAdapter(binary=str(tmp_path / "fehlt"))

        with pytest.raises(ProtonCliNotFoundError) as error:
            adapter.resolve_binary()

        assert "nicht gefunden" in str(error.value)

    def test_missing_binary_in_path_mentions_login(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))
        adapter = ProtonDriveAdapter()

        with pytest.raises(ProtonCliNotFoundError) as error:
            adapter.resolve_binary()

        assert "proton-drive auth login" in str(error.value)
        assert adapter.binary_available is False


class TestErrorClassification:
    """Zuordnung von Fehlertexten zu Fehlerklassen."""

    @pytest.mark.parametrize(
        "text",
        ["not logged in", "Unauthorized", "session expired", "please log in first"],
    )
    def test_auth_errors(self, text: str) -> None:
        error = classify_error(returncode=1, output=text, argv=["filesystem", "list"])
        assert isinstance(error, NotAuthenticatedError)
        assert error.transient is False

    def test_auth_error_mentions_the_login_command(self) -> None:
        error = classify_error(returncode=1, output="not logged in", argv=[])
        assert "proton-drive auth login" in str(error)

    @pytest.mark.parametrize("text", ["Node not found: x", "no such file", "ENOENT"])
    def test_not_found_errors(self, text: str) -> None:
        error = classify_error(returncode=1, output=text, argv=[])
        assert isinstance(error, RemotePathNotFoundError)

    @pytest.mark.parametrize("text", ["already exists", "name is already taken"])
    def test_exists_errors(self, text: str) -> None:
        assert isinstance(classify_error(returncode=1, output=text, argv=[]), RemotePathExistsError)

    @pytest.mark.parametrize(
        "text",
        ["network unreachable", "ETIMEDOUT", "503 Service Unavailable", "rate limit exceeded"],
    )
    def test_transient_errors_are_retryable(self, text: str) -> None:
        error = classify_error(returncode=1, output=text, argv=[])
        assert isinstance(error, TransientError)
        assert error.transient is True

    @pytest.mark.parametrize("text", ["quota exceeded", "permission denied", "403 Forbidden"])
    def test_permanent_errors_are_not_retryable(self, text: str) -> None:
        error = classify_error(returncode=1, output=text, argv=[])
        assert isinstance(error, PermanentError)
        assert error.transient is False

    def test_unknown_errors_are_treated_as_transient(self) -> None:
        # Ein zusaetzlicher Versuch ist billig und unschaedlich.
        error = classify_error(returncode=1, output="voellig unbekannter Fehler", argv=[])
        assert error.transient is True

    def test_empty_output_still_yields_a_message(self) -> None:
        error = classify_error(returncode=7, output="", argv=[])
        assert "7" in str(error)


class TestOutputRedaction:
    """Ausgaben werden vor dem Protokollieren bereinigt."""

    @pytest.mark.parametrize(
        "text",
        [
            "password=geheim123",
            "token: abcdef123456",
            "api_key = XYZ",
            "Authorization: Bearer abc.def.ghi",
            "refresh_token=xyz",
        ],
    )
    def test_secrets_are_redacted(self, text: str) -> None:
        assert "redigiert" in redact(text)

    def test_jwt_is_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"
        assert jwt not in redact(f"Antwort: {jwt}")

    def test_long_hex_blob_is_redacted(self) -> None:
        blob = "a" * 64
        assert blob not in redact(f"key {blob}")

    def test_file_paths_are_preserved(self) -> None:
        # Pfade duerfen im Protokoll stehen -- im README dokumentiert.
        text = "Uebertragen: /home/nutzer/Dokumente/bericht.pdf"
        assert redact(text) == text

    def test_very_long_output_is_truncated(self) -> None:
        assert len(redact("x" * 10_000)) < 3000

    def test_adapter_redacts_process_output(self, tmp_path: Path) -> None:
        binary = write_fake_cli(tmp_path / "bin")
        env = fake_cli_env(tmp_path / "rec.jsonl", FAKE_CLI_STDOUT="token=supergeheim")

        adapter = ProtonDriveAdapter(binary=str(binary), env=env)
        result = asyncio.run(adapter.run(commands.list_args("/my-files")))

        assert "supergeheim" not in result.stdout
        assert "redigiert" in result.stdout


class TestNodeParsing:
    """Auswertung der JSON-Ausgabe von 'filesystem list'."""

    def test_parses_json_array(self) -> None:
        nodes = _parse_nodes('[\n{"path":"/my-files"},\n{"path":"/devices"}\n]')
        assert [node.path for node in nodes] == ["/my-files", "/devices"]

    def test_falls_back_to_plain_lines(self) -> None:
        nodes = _parse_nodes("/my-files\n/devices\n")
        assert [node.path for node in nodes] == ["/my-files", "/devices"]

    def test_empty_output(self) -> None:
        assert _parse_nodes("") == []

    def test_unknown_fields_are_preserved(self) -> None:
        nodes = _parse_nodes('[{"path":"/my-files/a","type":"file","size":42}]')
        assert nodes[0].node_type == "file"
        assert nodes[0].raw["size"] == 42


class TestCapabilityProbe:
    """Ermittlung von Version und Anmeldezustand."""

    def test_version_parsing(self) -> None:
        raw = "Proton Drive CLI cli-drive@0.8.0+06e8c605\nProton Drive SDK js@0.21.0+06e8c605"
        assert parse_version(raw) == ("0.8.0", "0.21.0")

    def test_version_parsing_tolerates_unknown_format(self) -> None:
        assert parse_version("etwas ganz anderes") == ("", "")

    def test_probe_reports_missing_binary(self) -> None:
        caps = asyncio.run(probe(FakeAdapter(available=False)))
        assert caps.available is False
        assert caps.usable is False
        assert "nicht gefunden" in caps.problem

    def test_probe_reports_missing_authentication(self) -> None:
        caps = asyncio.run(probe(FakeAdapter(authenticated=False)))
        assert caps.available is True
        assert caps.authenticated is False
        assert caps.usable is False
        assert "auth login" in caps.problem

    def test_probe_reports_ready_state(self) -> None:
        caps = asyncio.run(probe(FakeAdapter()))
        assert caps.usable is True
        assert caps.cli_version == "0.8.0"
        assert caps.problem == ""

    def test_probe_can_skip_auth_check(self) -> None:
        caps = asyncio.run(probe(FakeAdapter(authenticated=False), check_auth=False))
        assert caps.available is True
        assert caps.authenticated is False
