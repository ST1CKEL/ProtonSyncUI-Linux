"""Tests fuer Pfad- und Executable-Ermittlung."""

from __future__ import annotations

from pathlib import Path

from proton_sync_ui.paths import (
    config_dir,
    data_dir,
    find_cli_executable,
    find_gui_executable,
    format_size,
    format_timestamp,
    log_dir,
    log_file,
    state_dir,
    systemd_user_dir,
)


class TestExecutableResolution:
    """Aufloesung der CLI- und GUI-Binaerdateien fuer Autostart und systemd."""

    def test_find_gui_executable_uses_local_bin_if_present(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        fake_gui = local_bin / "proton-sync-ui-gui"
        fake_gui.touch()

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        resolved = find_gui_executable()
        assert resolved == str(fake_gui)

    def test_find_gui_executable_uses_which_if_local_bin_missing(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "custom_home_2"
        fake_home.mkdir(parents=True, exist_ok=True)
        fake_bin_dir = tmp_path / "bin"
        fake_bin_dir.mkdir(parents=True, exist_ok=True)
        fake_gui = fake_bin_dir / "proton-sync-ui-gui"
        fake_gui.touch()

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr(
            "shutil.which",
            lambda name: str(fake_gui) if name == "proton-sync-ui-gui" else None,
        )

        resolved = find_gui_executable()
        assert resolved == str(fake_gui)

    def test_find_gui_executable_fallback_to_module(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "custom_home_3"
        fake_home.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "empty_share"))

        resolved = find_gui_executable()
        # Entweder sys.executable/proton-sync-ui-gui (falls im venv vorhanden)
        # oder der python -m Fallback mit absolutem sys.executable.
        assert Path(resolved.split()[0]).is_absolute()

    def test_find_cli_executable_uses_local_bin_if_present(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        fake_cli = local_bin / "proton-sync-ui"
        fake_cli.touch()

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        resolved = find_cli_executable()
        assert resolved == str(fake_cli)


class TestFormatting:
    """Formatierung von Groessen und Zeitstempeln."""

    def test_format_size(self) -> None:
        assert format_size(100) == "100 B"
        assert format_size(2048) == "2.0 KiB"
        assert format_size(1024 * 1024) == "1.0 MiB"

    def test_format_timestamp(self) -> None:
        assert format_timestamp(None) == "nie"


class TestXdgDirs:
    """XDG-Pfade reagieren auf Umgebungsvariablen."""

    def test_respects_custom_xdg_vars(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "dat"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "ste"))

        assert config_dir() == tmp_path / "cfg" / "proton-sync-ui"
        assert data_dir() == tmp_path / "dat" / "proton-sync-ui"
        assert state_dir() == tmp_path / "ste" / "proton-sync-ui"
        assert log_dir() == tmp_path / "ste" / "proton-sync-ui" / "logs"
        assert log_file() == tmp_path / "ste" / "proton-sync-ui" / "logs" / "proton-sync-ui.log"
        assert systemd_user_dir() == tmp_path / "cfg" / "systemd" / "user"
