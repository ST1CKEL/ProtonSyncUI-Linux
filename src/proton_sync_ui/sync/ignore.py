"""Ausschlussregeln im Stil von ``.gitignore``.

Eigene Umsetzung ohne Fremdbibliothek -- die Anwendung soll ausser PyGObject
keine Laufzeitabhaengigkeiten haben.

Unterstuetzt werden:

* ``#`` Kommentare und Leerzeilen
* ``!`` zum Wiedereinschliessen
* ``/`` am Zeilenende: nur Verzeichnisse
* ``/`` am Anfang oder in der Mitte: Regel ist an die Wurzel gebunden
* ohne ``/``: Regel greift auf jeder Ebene
* ``*`` (nicht ueber ``/`` hinweg), ``?``, ``[abc]``, ``[!abc]``
* ``**`` fuer beliebig tiefe Verzeichnisse
* ``\\`` als Maskierung fuer Sonderzeichen

Wie bei Git gilt: Die *letzte* zutreffende Regel entscheidet. Liegt ein
Verzeichnis ausserhalb, koennen seine Inhalte nicht per ``!`` wieder
hereingeholt werden -- der Scanner betritt das Verzeichnis gar nicht erst.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

#: Regeln, die unabhaengig von der Konfiguration immer gelten. Sie halten
#: Muell aus dem Backup, der ohnehin nie gewollt ist.
#: Praefix der versteckten Staging-Verzeichnisse fuer Downloads (siehe
#: ``SyncEngine._download_one``). Reste nach einem Absturz werden nie
#: synchronisiert.
DOWNLOAD_STAGING_PREFIX: Final = ".proton-sync-ui-dl-"

#: Gesicherte lokale Fassungen aus Konflikten: ``name.conflict-<unix-zeit>.ext``.
#: Sie bleiben lokal, bis der Konflikt im Konflikt-Center geloest ist.
CONFLICT_COPY_PATTERN: Final = "*.conflict-" + "[0-9]" * 10 + "*"

DEFAULT_PATTERNS: Final[tuple[str, ...]] = (
    f"{DOWNLOAD_STAGING_PREFIX}*/",
    CONFLICT_COPY_PATTERN,
    ".git/",
    ".svn/",
    ".hg/",
    "__pycache__/",
    "*.pyc",
    ".Trash-*/",
    "lost+found/",
    ".directory",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*~",
    ".#*",
)


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    """Eine uebersetzte Ausschlussregel."""

    source: str
    regex: re.Pattern[str]
    negated: bool
    directory_only: bool

    def matches(self, relative_path: str) -> bool:
        """Prueft den Pfad gegen die Regel."""
        return self.regex.match(relative_path) is not None


def _translate_body(pattern: str) -> str:
    """Uebersetzt den Glob-Teil einer Regel in einen regulaeren Ausdruck."""
    out: list[str] = []
    index = 0
    length = len(pattern)

    while index < length:
        char = pattern[index]

        if char == "*":
            if pattern[index : index + 2] == "**":
                after = index + 2
                if after < length and pattern[after] == "/":
                    # "**/" -- null oder mehr Verzeichnisebenen
                    out.append("(?:[^/]+/)*")
                    index = after + 1
                    continue
                if after >= length:
                    # "**" am Ende -- alles Weitere
                    out.append(".*")
                    index = after
                    continue
                out.append(".*")
                index = after
                continue
            out.append("[^/]*")
            index += 1
            continue

        if char == "?":
            out.append("[^/]")
            index += 1
            continue

        if char == "[":
            end = index + 1
            if end < length and pattern[end] in "!^":
                end += 1
            if end < length and pattern[end] == "]":
                end += 1
            while end < length and pattern[end] != "]":
                end += 1
            if end >= length:
                out.append(re.escape("["))
                index += 1
                continue
            inner = pattern[index + 1 : end]
            if inner.startswith("!"):
                inner = "^" + inner[1:]
            out.append(f"[{inner}]")
            index = end + 1
            continue

        if char == "\\" and index + 1 < length:
            out.append(re.escape(pattern[index + 1]))
            index += 2
            continue

        out.append(re.escape(char))
        index += 1

    return "".join(out)


def compile_rule(raw: str) -> IgnoreRule | None:
    """Uebersetzt eine Zeile in eine Regel. Gibt ``None`` fuer Leer-/Kommentarzeilen."""
    line = raw.rstrip("\n")

    # Nicht maskierte Leerzeichen am Zeilenende sind bedeutungslos.
    line = re.sub(r"(?<!\\)\s+$", "", line)

    if not line:
        return None
    if line.startswith("#"):
        return None
    if line.startswith("\\#"):
        line = line[1:]

    negated = line.startswith("!")
    if negated or line.startswith("\\!"):
        line = line[1:]

    if not line:
        return None

    directory_only = line.endswith("/")
    if directory_only:
        line = line[:-1]
    if not line:
        return None

    # Ein "/" irgendwo ausser am Ende bindet die Regel an die Wurzel.
    anchored = "/" in line
    if line.startswith("/"):
        line = line[1:]

    body = _translate_body(line)
    prefix = "" if anchored else "(?:.*/)?"
    # Ein Treffer auf ein Verzeichnis schliesst dessen Inhalt mit ein.
    regex = re.compile(f"^{prefix}{body}(?:/.*)?$")

    return IgnoreRule(
        source=raw.strip(),
        regex=regex,
        negated=negated,
        directory_only=directory_only,
    )


class IgnoreMatcher:
    """Wertet eine Liste von Ausschlussregeln aus."""

    def __init__(
        self,
        patterns: Sequence[str] = (),
        *,
        use_defaults: bool = True,
    ) -> None:
        sources: list[str] = []
        if use_defaults:
            sources.extend(DEFAULT_PATTERNS)
        sources.extend(patterns)

        self._rules: list[IgnoreRule] = []
        self._invalid: list[str] = []
        for source in sources:
            try:
                rule = compile_rule(source)
            except re.error:
                self._invalid.append(source)
                continue
            if rule is not None:
                self._rules.append(rule)

    @property
    def rules(self) -> tuple[IgnoreRule, ...]:
        """Alle uebersetzten Regeln in Auswertungsreihenfolge."""
        return tuple(self._rules)

    @property
    def invalid_patterns(self) -> tuple[str, ...]:
        """Regeln, die sich nicht uebersetzen liessen."""
        return tuple(self._invalid)

    def is_ignored(self, relative_path: str, *, is_dir: bool = False) -> bool:
        """Entscheidet, ob ein relativer Pfad ausgeschlossen ist.

        Der Pfad wird ohne fuehrenden Schraegstrich erwartet, z. B.
        ``"unterordner/datei.txt"``.
        """
        path = relative_path.strip("/")
        if not path:
            return False

        ignored = False
        for rule in self._rules:
            if rule.directory_only and not is_dir and not self._matches_parent_dir(rule, path):
                continue
            if rule.matches(path):
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _matches_parent_dir(rule: IgnoreRule, path: str) -> bool:
        """Prueft, ob eine Nur-Verzeichnis-Regel ein Elternverzeichnis trifft.

        Damit schliesst ``build/`` auch ``build/out/app.bin`` aus.
        """
        segments = path.split("/")
        return any(rule.matches("/".join(segments[:depth])) for depth in range(1, len(segments)))

    def is_dir_ignored(self, relative_path: str) -> bool:
        """Kurzform fuer Verzeichnisse -- steuert das Abschneiden beim Durchlauf."""
        return self.is_ignored(relative_path, is_dir=True)


__all__ = [
    "CONFLICT_COPY_PATTERN",
    "DEFAULT_PATTERNS",
    "DOWNLOAD_STAGING_PREFIX",
    "IgnoreMatcher",
    "IgnoreRule",
    "compile_rule",
]
