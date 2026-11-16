"""Hilfsfunktionen des grafischen Setups (ohne GTK)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "proton_sync_ui_setup", ROOT / "installer" / "proton_sync_ui_setup.py"
)
assert _SPEC is not None and _SPEC.loader is not None
setup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(setup)


class TestTexts:
    def test_every_text_exists_in_both_languages(self) -> None:
        incomplete = [key for key, entry in setup.TEXTS.items() if set(entry) != {"de", "en"}]
        assert incomplete == []

    def test_placeholders_match(self) -> None:
        import re

        pattern = re.compile(r"\{[a-z_]+\}")
        broken = [
            key
            for key, entry in setup.TEXTS.items()
            if sorted(pattern.findall(entry["de"])) != sorted(pattern.findall(entry["en"]))
        ]
        assert broken == []

    @pytest.mark.parametrize(
        ("environ", "expected"),
        [({"LANG": "de_DE.UTF-8"}, "de"), ({"LANG": "en_GB.UTF-8"}, "en"), ({}, "en")],
    )
    def test_system_language(self, environ: dict[str, str], expected: str) -> None:
        assert setup.system_language(environ) == expected


class TestHelpers:
    def test_bundled_version_matches_the_package(self) -> None:
        from proton_sync_ui import __version__

        assert setup.bundled_version() == __version__

    def test_install_command(self, tmp_path: Path) -> None:
        assert setup.install_command(tmp_path, autostart=True) == [
            "bash",
            str(tmp_path / "install.sh"),
            "--yes",
            "--no-deps",
            "--autostart",
        ]
        assert "--autostart" not in setup.install_command(tmp_path, autostart=False)

    def test_language_is_merged_into_existing_settings(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({"notifications": False}), encoding="utf-8")

        setup.write_language("en", target)

        assert json.loads(target.read_text()) == {"language": "en", "notifications": False}

    def test_language_survives_a_broken_file(self, tmp_path: Path) -> None:
        target = tmp_path / "conf" / "settings.json"
        target.parent.mkdir()
        target.write_text("{kaputt", encoding="utf-8")
        setup.write_language("de", target)
        assert json.loads(target.read_text()) == {"language": "de"}

    def test_unknown_language_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            setup.write_language("fr", tmp_path / "settings.json")

    def test_ansi_colours_are_removed(self) -> None:
        assert setup.strip_ansi("\x1b[1;32m✓\x1b[0m fertig") == "✓ fertig"

    def test_assets_are_shipped(self) -> None:
        assert setup.asset("icon") is not None
        assert setup.asset("logo") is not None


class TestScripts:
    @pytest.mark.parametrize(
        "script", ["installer/bundle-header.sh", "installer/setup.sh", "tools/build-setup.sh"]
    )
    def test_shell_syntax(self, script: str) -> None:
        shell = "bash" if script.startswith("tools/") else "sh"
        result = subprocess.run(
            [shell, "-n", str(ROOT / script)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
