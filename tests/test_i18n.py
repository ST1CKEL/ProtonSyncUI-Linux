"""Sprachumschaltung und Vollstaendigkeit des englischen Katalogs."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from proton_sync_ui import i18n
from proton_sync_ui.i18n_en import ENGLISH, SAME_IN_BOTH

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "proton_sync_ui"
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _module_strings(tree: ast.Module) -> dict[str, list[str]]:
    """Modulweite Zeichenketten und Woerterbuchwerte nach Namen."""
    found: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found[target.id] = [value.value]
        elif isinstance(value, ast.Dict):
            found[target.id] = [
                item.value
                for item in value.values
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
    return found


def collect_keys() -> dict[str, str]:
    """Alle Texte, die im Code an tr() gehen (direkt oder ueber eine Modulkonstante)."""
    keys: dict[str, str] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_strings(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
            ):
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.setdefault(argument.value, path.name)
            elif isinstance(argument, ast.Name):
                for value in constants.get(argument.id, []):
                    keys.setdefault(value, path.name)
            elif (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Attribute)
                and argument.func.attr == "get"
                and isinstance(argument.func.value, ast.Name)
            ):
                for value in constants.get(argument.func.value.id, []):
                    keys.setdefault(value, path.name)
    return keys


class TestCatalogue:
    def test_every_text_has_an_english_translation(self) -> None:
        missing = {
            key: where
            for key, where in collect_keys().items()
            if key not in ENGLISH and key not in SAME_IN_BOTH
        }
        assert missing == {}, f"Ohne englische Uebersetzung: {missing}"

    def test_placeholders_survive_translation(self) -> None:
        broken = [
            key
            for key, value in ENGLISH.items()
            if sorted(_PLACEHOLDER.findall(key)) != sorted(_PLACEHOLDER.findall(value))
        ]
        assert broken == []

    def test_catalogue_has_no_stale_entries(self) -> None:
        used = collect_keys()
        assert [key for key in ENGLISH if key not in used] == []


class TestLanguageChoice:
    def test_environment_overrides_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(i18n.ENVIRONMENT_VARIABLE, "en")
        monkeypatch.setenv("LANG", "de_DE.UTF-8")
        assert i18n.resolve() == "en"

    def test_stored_choice_beats_the_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(i18n.ENVIRONMENT_VARIABLE)
        monkeypatch.setenv("LANG", "de_DE.UTF-8")
        path = i18n.settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        assert i18n.resolve() == "en"

    @pytest.mark.parametrize(
        ("lang", "expected"),
        [("de_DE.UTF-8", "de"), ("de_AT", "de"), ("en_US.UTF-8", "en"), ("fr_FR.UTF-8", "en")],
    )
    def test_session_language(
        self, monkeypatch: pytest.MonkeyPatch, lang: str, expected: str
    ) -> None:
        monkeypatch.delenv(i18n.ENVIRONMENT_VARIABLE)
        for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("LANG", lang)
        assert i18n.resolve() == expected

    def test_translation_and_fallback(self) -> None:
        i18n.set_language("en")
        try:
            assert i18n.tr("Einstellungen") == "Settings"
            assert i18n.tr("Fehler: {0}").format("x") == "Error: x"
            assert i18n.tr("Nicht im Katalog") == "Nicht im Katalog"
        finally:
            i18n.set_language("de")
        assert i18n.tr("Einstellungen") == "Einstellungen"

    def test_models_follow_the_language(self) -> None:
        from proton_sync_ui.models.plan import PlanAction, action_label
        from proton_sync_ui.models.run import RunRecord, RunStatus

        record = RunRecord(pair_uid="x", status=RunStatus.SUCCESS)
        i18n.set_language("en")
        try:
            assert action_label(PlanAction.UPLOAD_NEW) == "Upload (new)"
            assert record.summary_line().startswith("Run Successful | planned: 0")
        finally:
            i18n.set_language("de")
        assert action_label(PlanAction.UPLOAD_NEW) == "Upload (neu)"
