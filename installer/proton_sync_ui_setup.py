"""Grafisches Setup fuer ProtonSyncUI (Deutsch / English).

Wird aus dem selbstentpackenden Setup gestartet (``installer/setup.sh``) und
fuehrt durch drei Schritte: Sprache, Optionen, Installation. Installiert wird
ausschliesslich in das Benutzerverzeichnis -- ohne Root-Rechte:

1. ``install.sh --yes --no-deps [--autostart]`` aus dem entpackten Archiv
2. gewaehlte Sprache in ``settings.json`` schreiben
3. auf Wunsch die offizielle Proton-Drive-CLI installieren bzw. aktualisieren
   (``proton-sync-ui cli-update``: Download von proton.me, SHA-512 geprueft)

Die Hilfsfunktionen im oberen Teil kommen ohne GTK aus und sind einzeln
getestet (``tests/test_setup.py``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "io.github.protonsyncui.ProtonSyncUI"
APP_TITLE = "ProtonSyncUI"
SETUP_ID = "io.github.protonsyncui.Setup"
LANGUAGES = {"de": "Deutsch", "en": "English"}

TEXTS: dict[str, dict[str, str]] = {
    "window_title": {"de": "ProtonSyncUI einrichten", "en": "Set up ProtonSyncUI"},
    "welcome": {"de": "Willkommen", "en": "Welcome"},
    "tagline": {
        "de": "2-Wege-Synchronisation und Backups mit Proton Drive",
        "en": "Two-way sync and backups with Proton Drive",
    },
    "choose_language": {"de": "Sprache waehlen", "en": "Choose your language"},
    "developed_by": {"de": "Entwickelt von", "en": "Developed by"},
    "options_title": {"de": "Installation", "en": "Installation"},
    "options_intro": {
        "de": (
            "ProtonSyncUI {version} wird in Ihr Benutzerverzeichnis installiert. "
            "Root-Rechte sind nicht noetig."
        ),
        "en": (
            "ProtonSyncUI {version} will be installed into your home directory. "
            "No root privileges are needed."
        ),
    },
    "update_intro": {
        "de": "Die installierte Version {installed} wird durch {version} ersetzt.",
        "en": "The installed version {installed} will be replaced by {version}.",
    },
    "autostart": {"de": "Beim Anmelden automatisch starten", "en": "Start automatically at login"},
    "autostart_sub": {
        "de": "Minimiert im Infobereich (KDE Plasma, GNOME)",
        "en": "Minimized in the system tray (KDE Plasma, GNOME)",
    },
    "cli": {"de": "Proton-Drive-CLI einrichten", "en": "Set up the Proton Drive CLI"},
    "cli_missing": {
        "de": "Nicht installiert -- wird von proton.me geladen und per SHA-512 geprueft",
        "en": "Not installed -- downloaded from proton.me and verified by SHA-512",
    },
    "cli_found": {
        "de": "Version {version} gefunden -- wird aktualisiert, falls Proton eine neuere anbietet",
        "en": "Version {version} found -- updated if Proton offers a newer one",
    },
    "launch": {"de": "Nach der Installation starten", "en": "Start after installing"},
    "where": {"de": "Speicherort", "en": "Location"},
    "back": {"de": "Zurueck", "en": "Back"},
    "install": {"de": "Installieren", "en": "Install"},
    "update": {"de": "Aktualisieren", "en": "Update"},
    "installing": {"de": "ProtonSyncUI wird installiert …", "en": "Installing ProtonSyncUI …"},
    "step_app": {"de": "Anwendung wird installiert …", "en": "Installing the application …"},
    "step_language": {"de": "Sprache wird gespeichert …", "en": "Saving the language …"},
    "step_cli": {
        "de": "Proton-Drive-CLI wird eingerichtet …",
        "en": "Setting up the Proton Drive CLI …",
    },
    "details": {"de": "Einzelheiten", "en": "Details"},
    "done_title": {"de": "ProtonSyncUI ist installiert", "en": "ProtonSyncUI is installed"},
    "done_body": {
        "de": (
            "Sie finden ProtonSyncUI im Startmenue. Beim ersten Start weist die Anwendung "
            "auf die Anmeldung bei Proton Drive hin."
        ),
        "en": (
            "You will find ProtonSyncUI in the application menu. On first start the "
            "application points you to signing in to Proton Drive."
        ),
    },
    "cli_warning": {
        "de": (
            "Die Proton-Drive-CLI konnte nicht eingerichtet werden. Das laesst sich in der "
            "Anwendung unter Einstellungen nachholen."
        ),
        "en": (
            "The Proton Drive CLI could not be set up. You can do that later in the "
            "application under Settings."
        ),
    },
    "failed_title": {"de": "Die Installation ist fehlgeschlagen", "en": "The installation failed"},
    "failed_body": {
        "de": (
            "Die Einzelheiten stehen unten. Am System wurde nichts ausserhalb Ihres "
            "Benutzerverzeichnisses veraendert."
        ),
        "en": "The details are below. Nothing outside your home directory was changed.",
    },
    "start": {"de": "ProtonSyncUI starten", "en": "Start ProtonSyncUI"},
    "close": {"de": "Schliessen", "en": "Close"},
    "retry": {"de": "Erneut versuchen", "en": "Try again"},
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen ohne GTK
# ---------------------------------------------------------------------------


def text(key: str, language: str, **values: object) -> str:
    """Text in der gewaehlten Sprache (Rueckfall: Englisch)."""
    entry = TEXTS[key]
    template = entry.get(language) or entry["en"]
    return template.format(**values) if values else template


def system_language(environ: dict[str, str] | None = None) -> str:
    """Deutsch fuer eine deutsche Sitzung, Englisch fuer alle anderen."""
    env = os.environ if environ is None else environ
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = env.get(variable, "")
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return "de" if value.lower().startswith("de") else "en"
    return "en"


def payload_root() -> Path:
    """Wurzel des entpackten Archivs bzw. des Quellbaums."""
    return Path(__file__).resolve().parent.parent


def bundled_version(root: Path | None = None) -> str:
    """Version der Anwendung, die dieses Setup installiert."""
    init = (root or payload_root()) / "src" / "proton_sync_ui" / "__init__.py"
    try:
        match = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return match.group(1) if match else ""


def config_home(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    raw = env.get("XDG_CONFIG_HOME", "").strip()
    return Path(raw) if raw.startswith("/") else Path.home() / ".config"


def data_home(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    raw = env.get("XDG_DATA_HOME", "").strip()
    return Path(raw) if raw.startswith("/") else Path.home() / ".local" / "share"


def installed_cli_command() -> Path:
    """Der Startbefehl, den install.sh anlegt."""
    return Path.home() / ".local" / "bin" / "proton-sync-ui"


def installed_gui_command() -> Path:
    return Path.home() / ".local" / "bin" / "proton-sync-ui-gui"


def installed_version() -> str:
    """Version einer bereits vorhandenen Installation (leer, wenn keine da ist)."""
    init = data_home() / "proton-sync-ui" / "app" / "proton_sync_ui" / "__init__.py"
    try:
        match = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return match.group(1) if match else ""


def find_proton_cli() -> str | None:
    """Sucht die Proton-Drive-CLI im PATH und in ``~/.local/bin``."""
    found = shutil.which("proton-drive")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "proton-drive"
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def proton_cli_version(binary: str | None) -> str:
    """Version der Proton-Drive-CLI (leer, wenn nicht ermittelbar)."""
    if not binary:
        return ""
    try:
        result = subprocess.run(  # noqa: S603 -- feste Argumentliste, keine Shell
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = re.search(r"cli-drive@([0-9][^\s+]*)", result.stdout + result.stderr)
    return match.group(1) if match else ""


def install_command(root: Path, *, autostart: bool) -> list[str]:
    """Argumentliste fuer die Installation der Anwendung."""
    argv = ["bash", str(root / "install.sh"), "--yes", "--no-deps"]
    if autostart:
        argv.append("--autostart")
    return argv


def cli_update_command() -> list[str]:
    """Argumentliste fuer Installation/Aktualisierung der Proton-Drive-CLI."""
    return [str(installed_cli_command()), "cli-update"]


def write_language(language: str, path: Path | None = None) -> Path:
    """Traegt die Sprache in ``settings.json`` ein, ohne andere Werte zu verlieren."""
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    target = path or config_home() / "proton-sync-ui" / "settings.json"
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current["language"] = language
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def strip_ansi(line: str) -> str:
    """Entfernt Farbsequenzen aus der Ausgabe von install.sh."""
    return re.sub(r"\x1b\[[0-9;]*m", "", line)


def asset(name: str) -> Path | None:
    """Sucht eine Bilddatei im Archiv."""
    root = payload_root()
    candidates = {
        "icon": [root / "data" / "icons" / f"{APP_ID}.svg"],
        "logo": [root / "src" / "proton_sync_ui" / "data" / "stickelbroeck-labs.png"],
    }[name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Oberflaeche
# ---------------------------------------------------------------------------

_CSS = """
.developer-card {
  background-color: #12161c;
  border-radius: 14px;
  padding: 14px 22px;
}
.developer-card .developer-caption { color: rgba(245, 247, 250, 0.72); }
.setup-log { font-family: monospace; font-size: 0.85em; }
"""


def run_gui(argv: list[str]) -> int:
    import gi  # noqa: PLC0415 -- GTK erst hier, die Hilfsfunktionen kommen ohne aus

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: PLC0415

    self_test: Path | None = None
    if "--self-test" in argv:
        self_test = Path(argv[argv.index("--self-test") + 1])
        self_test.mkdir(parents=True, exist_ok=True)

    class SetupWindow(Adw.ApplicationWindow):
        def __init__(self, application: Adw.Application) -> None:
            super().__init__(application=application)
            self.language = system_language()
            self.root = payload_root()
            self.version = bundled_version(self.root)
            self.previous = installed_version()
            self.cli_binary = find_proton_cli()
            self.cli_version = proton_cli_version(self.cli_binary)
            self.cli_failed = False
            self._steps: list[tuple[str, list[str], bool]] = []
            self._process: Gio.Subprocess | None = None

            self.set_default_size(620, 720)
            self.set_icon_name(APP_ID)

            provider = Gtk.CssProvider()
            provider.load_from_string(_CSS)
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

            self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
            toolbar = Adw.ToolbarView()
            self._header = Adw.HeaderBar()
            toolbar.add_top_bar(self._header)
            toolbar.set_content(self._stack)
            self.set_content(toolbar)

            self._show("language", self._language_page())
            if self_test is not None:
                GLib.timeout_add(1200, self._self_test_step, "language")

        # -- Selbsttest (tools/build-setup.sh --check) ------------------------

        def _snapshot(self, name: str) -> None:
            from gi.repository import Graphene  # noqa: PLC0415

            width, height = self.get_width(), self.get_height()
            snapshot = Gtk.Snapshot()
            Gtk.WidgetPaintable.new(self).snapshot(snapshot, width, height)
            node = snapshot.to_node()
            if node is None or self_test is None:
                return
            texture = (
                self.get_native()
                .get_renderer()
                .render_texture(node, Graphene.Rect().init(0, 0, width, height))
            )
            texture.save_to_png(str(self_test / f"setup-{self.language}-{name}.png"))

        def _self_test_step(self, page: str) -> bool:
            """Durchlaeuft das Setup ohne Eingaben und legt je Seite ein Bild ab."""
            self._snapshot(page)
            if page == "language":
                self.language = os.environ.get("PROTON_SYNC_UI_LANGUAGE", self.language)
                self._show("options", self._options_page())
                GLib.timeout_add(1200, self._self_test_step, "options")
            elif page == "options":
                self._launch.set_active(False)
                self._start()
            else:
                self.close()
            return GLib.SOURCE_REMOVE

        # -- Hilfen ---------------------------------------------------------

        def t(self, key: str, **values: object) -> str:
            return text(key, self.language, **values)

        def _show(self, name: str, page: Gtk.Widget) -> None:
            old = self._stack.get_child_by_name(name)
            if old is not None:
                self._stack.remove(old)
            self._stack.add_named(page, name)
            self._stack.set_visible_child_name(name)
            self.set_title(self.t("window_title"))

        @staticmethod
        def _clamped(child: Gtk.Widget) -> Gtk.Widget:
            clamp = Adw.Clamp(maximum_size=480)
            clamp.set_child(child)
            clamp.set_margin_top(18)
            clamp.set_margin_bottom(24)
            clamp.set_margin_start(18)
            clamp.set_margin_end(18)
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            scroll.set_child(clamp)
            return scroll

        def _head(self, title: str, subtitle: str, *, size: int = 96) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_halign(Gtk.Align.CENTER)
            icon_path = asset("icon")
            if icon_path is not None:
                icon = Gtk.Image.new_from_file(str(icon_path))
                icon.set_pixel_size(size)
                box.append(icon)
            box.append(Gtk.Label(label=title, css_classes=["title-1"]))
            label = Gtk.Label(
                label=subtitle,
                wrap=True,
                justify=Gtk.Justification.CENTER,
                css_classes=["dim-label"],
            )
            box.append(label)
            return box

        def _developer_card(self) -> Gtk.Widget:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("developer-card")
            card.append(
                Gtk.Label(
                    label=self.t("developed_by"), css_classes=["caption", "developer-caption"]
                )
            )
            logo = asset("logo")
            if logo is not None:
                picture = Gtk.Picture.new_for_filename(str(logo))
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_can_shrink(True)
                picture.set_size_request(-1, 110)
                card.append(picture)
            else:
                card.append(Gtk.Label(label="Stickelbroeck Labs", css_classes=["title-3"]))
            return card

        # -- Seite 1: Sprache -----------------------------------------------

        def _language_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
            box.append(self._head(APP_TITLE, f"{self.t('tagline')}\nVersion {self.version}"))

            group = Adw.PreferencesGroup(title="Sprache / Language")
            for code, name in LANGUAGES.items():
                row = Adw.ActionRow(title=name, activatable=True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.connect("activated", self._language_chosen, code)
                group.add(row)
            box.append(group)
            box.append(self._developer_card())
            return self._clamped(box)

        def _language_chosen(self, _row: Adw.ActionRow, code: str) -> None:
            self.language = code
            self._show("options", self._options_page())

        # -- Seite 2: Optionen ----------------------------------------------

        def _options_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
            updating = bool(self.previous) and self.previous != self.version
            intro = (
                self.t("update_intro", installed=self.previous, version=self.version)
                if updating
                else self.t("options_intro", version=self.version)
            )
            box.append(self._head(self.t("options_title"), intro, size=72))

            group = Adw.PreferencesGroup()
            self._autostart = Adw.SwitchRow(
                title=self.t("autostart"), subtitle=self.t("autostart_sub")
            )
            self._autostart.set_active(True)
            group.add(self._autostart)

            self._cli = Adw.SwitchRow(
                title=self.t("cli"),
                subtitle=(
                    self.t("cli_found", version=self.cli_version)
                    if self.cli_version
                    else self.t("cli_missing")
                ),
            )
            self._cli.set_active(True)
            group.add(self._cli)

            self._launch = Adw.SwitchRow(title=self.t("launch"))
            self._launch.set_active(True)
            group.add(self._launch)
            box.append(group)

            where = Adw.PreferencesGroup()
            location = Adw.ActionRow(
                title=self.t("where"),
                subtitle=GLib.markup_escape_text(str(data_home() / "proton-sync-ui")),
            )
            location.add_css_class("property")
            where.add(location)
            box.append(where)

            buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            back = Gtk.Button(label=self.t("back"), css_classes=["pill"])
            back.connect("clicked", lambda _b: self._show("language", self._language_page()))
            buttons.append(back)
            install = Gtk.Button(
                label=self.t("update") if updating else self.t("install"),
                css_classes=["pill", "suggested-action"],
            )
            install.connect("clicked", lambda _b: self._start())
            buttons.append(install)
            box.append(buttons)
            return self._clamped(box)

        # -- Seite 3: Fortschritt -------------------------------------------

        def _progress_page(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            box.append(self._head(self.t("installing"), "", size=72))

            self._step_label = Gtk.Label(label="", css_classes=["heading"])
            box.append(self._step_label)
            self._bar = Gtk.ProgressBar()
            box.append(self._bar)

            expander = Gtk.Expander(label=self.t("details"))
            self._log_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
            self._log_view.add_css_class("setup-log")
            self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            log_scroll = Gtk.ScrolledWindow(min_content_height=220)
            log_scroll.set_child(self._log_view)
            log_scroll.add_css_class("card")
            expander.set_child(log_scroll)
            box.append(expander)
            return self._clamped(box)

        def _log(self, line: str) -> None:
            buffer = self._log_view.get_buffer()
            buffer.insert(buffer.get_end_iter(), strip_ansi(line).rstrip() + "\n")
            self._log_view.scroll_to_mark(buffer.get_insert(), 0.0, False, 0.0, 1.0)

        def _log_text(self) -> str:
            buffer = self._log_view.get_buffer()
            return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

        def _start(self) -> None:
            self.cli_failed = False
            self._want_launch = self._launch.get_active()
            self._steps = [
                (
                    "step_app",
                    install_command(self.root, autostart=self._autostart.get_active()),
                    True,
                )
            ]
            if self._cli.get_active():
                self._steps.append(("step_cli", cli_update_command(), False))
            self._show("progress", self._progress_page())
            self._pulse_id = GLib.timeout_add(120, self._pulse)
            if self_test is None:
                self._quit_running_app()
            self._next_step()

        def _pulse(self) -> bool:
            self._bar.pulse()
            return GLib.SOURCE_CONTINUE

        def _quit_running_app(self) -> None:
            """Beendet eine laufende Instanz, damit danach die neue Version startet."""
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                bus.call_sync(
                    APP_ID,
                    "/" + APP_ID.replace(".", "/"),
                    "org.freedesktop.Application",
                    "ActivateAction",
                    GLib.Variant("(sava{sv})", ("quit", [], {})),
                    None,
                    Gio.DBusCallFlags.NO_AUTO_START,
                    3000,
                    None,
                )
            except GLib.Error:
                return  # es lief keine Instanz

        def _next_step(self) -> None:
            if not self._steps:
                self._finish(True)
                return
            key, command, fatal = self._steps.pop(0)
            self._step_label.set_label(self.t(key))
            self._log(f"$ {' '.join(command)}")
            if key == "step_cli":
                # Die Sprache muss vor dem ersten Start der Anwendung feststehen.
                try:
                    write_language(self.language)
                except OSError as error:
                    self._log(str(error))
            self._run(command, fatal)

        def _run(self, command: list[str], fatal: bool) -> None:
            launcher = Gio.SubprocessLauncher.new(
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
            )
            launcher.setenv("PROTON_SYNC_UI_LANGUAGE", self.language, True)
            launcher.set_cwd(str(self.root))
            try:
                process = launcher.spawnv(command)
            except GLib.Error as error:
                self._log(error.message)
                self._step_done(False, fatal)
                return
            self._process = process
            stream = Gio.DataInputStream.new(process.get_stdout_pipe())

            def read(source: Gio.DataInputStream, result: Gio.AsyncResult) -> None:
                try:
                    line, _length = source.read_line_finish_utf8(result)
                except GLib.Error:
                    line = None
                if line is None:
                    return
                self._log(line)
                source.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

            def finished(proc: Gio.Subprocess, result: Gio.AsyncResult) -> None:
                try:
                    proc.wait_finish(result)
                    success = proc.get_if_exited() and proc.get_exit_status() == 0
                except GLib.Error:
                    success = False
                self._step_done(success, fatal)

            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)
            process.wait_async(None, finished)

        def _step_done(self, success: bool, fatal: bool) -> None:
            if not success and fatal:
                self._finish(False)
                return
            if not success:
                self.cli_failed = True
            self._next_step()

        # -- Seite 4: Ergebnis ----------------------------------------------

        def _finish(self, success: bool) -> None:
            if getattr(self, "_pulse_id", 0):
                GLib.source_remove(self._pulse_id)
                self._pulse_id = 0
            if success:
                try:
                    write_language(self.language)
                except OSError as error:
                    self._log(str(error))
            log_text = self._log_text()

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
            if success:
                body = self.t("done_body")
                if self.cli_failed:
                    body += "\n\n" + self.t("cli_warning")
                box.append(self._head(self.t("done_title"), body))
            else:
                box.append(self._head(self.t("failed_title"), self.t("failed_body"), size=72))

            if not success or self.cli_failed:
                view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
                view.add_css_class("setup-log")
                view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
                view.get_buffer().set_text("\n".join(log_text.splitlines()[-40:]))
                scroll = Gtk.ScrolledWindow(min_content_height=200)
                scroll.add_css_class("card")
                scroll.set_child(view)
                box.append(scroll)

            buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            if success:
                start = Gtk.Button(label=self.t("start"), css_classes=["pill", "suggested-action"])
                start.connect("clicked", lambda _b: self._launch_and_close())
                buttons.append(start)
            else:
                retry = Gtk.Button(label=self.t("retry"), css_classes=["pill", "suggested-action"])
                retry.connect("clicked", lambda _b: self._show("options", self._options_page()))
                buttons.append(retry)
            close = Gtk.Button(label=self.t("close"), css_classes=["pill"])
            close.connect("clicked", lambda _b: self.close())
            buttons.append(close)
            box.append(buttons)
            if success:
                box.append(self._developer_card())

            self._show("result", self._clamped(box))
            if self_test is not None:
                (self_test / "result.txt").write_text(
                    f"success={success}\ncli_failed={self.cli_failed}\n\n{log_text}",
                    encoding="utf-8",
                )
                GLib.timeout_add(1200, self._self_test_step, "result")
            elif success and self._want_launch:
                self._launch_app()

        def _launch_app(self) -> None:
            command = installed_gui_command()
            if not command.is_file():
                return
            try:
                subprocess.Popen(  # noqa: S603 -- feste Argumentliste, keine Shell
                    [str(command)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(Path.home()),
                )
            except OSError as error:
                self._log(str(error))

        def _launch_and_close(self) -> None:
            self._launch_app()
            self.close()

    application = Adw.Application(application_id=SETUP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.connect("activate", lambda app: SetupWindow(app).present())
    return int(application.run(argv[:1]))


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    return run_gui(arguments)


if __name__ == "__main__":
    sys.exit(main())
