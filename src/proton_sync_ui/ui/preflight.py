"""Verstaendliche Dialoge fuer Probleme mit der Proton-Drive-CLI."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..cli_adapter.capabilities import Capabilities  # noqa: E402

LOGIN_COMMAND = "proton-drive auth login"

_INSTALL_HINT = (
    "ProtonSyncUI steuert ausschliesslich die offizielle Proton-Drive-Kommandozeile "
    "und enthaelt selbst keinen Proton-Zugang.\n\n"
    "1. Offizielle Proton-Drive-CLI installieren\n"
    "2. Sicherstellen, dass 'proton-drive' im PATH liegt (haeufig ~/.local/bin)\n"
    "3. Einmalig anmelden:\n\n"
    f"    {LOGIN_COMMAND}\n\n"
    "Danach ProtonSyncUI erneut pruefen lassen."
)

_AUTH_HINT = (
    "Die Anmeldung erfolgt bewusst ausserhalb dieser Anwendung. ProtonSyncUI liest, "
    "speichert und verarbeitet keine Passwoerter, Sitzungsdaten, Tokens oder "
    "Schluessel.\n\n"
    "Bitte im Terminal ausfuehren:\n\n"
    f"    {LOGIN_COMMAND}\n\n"
    "Der Befehl oeffnet einen Browser zur Anmeldung."
)


def _copy_to_clipboard(text: str) -> None:
    """Legt Text in die Zwischenablage."""
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def show_cli_missing_dialog(parent: Gtk.Widget, message: str = "") -> Adw.AlertDialog:
    """Meldet, dass ``proton-drive`` nicht gefunden wurde."""
    dialog = Adw.AlertDialog(
        heading="Proton-Drive-CLI nicht gefunden",
        body=message or _INSTALL_HINT,
    )
    dialog.add_response("close", "Verstanden")
    dialog.add_response("copy", "Befehl kopieren")
    dialog.set_default_response("close")
    dialog.set_close_response("close")
    dialog.connect("response", _on_copy_response)
    dialog.present(parent)
    return dialog


def show_not_authenticated_dialog(parent: Gtk.Widget, message: str = "") -> Adw.AlertDialog:
    """Meldet, dass die CLI nicht angemeldet ist."""
    dialog = Adw.AlertDialog(
        heading="Proton-Drive-CLI nicht angemeldet",
        body=message or _AUTH_HINT,
    )
    dialog.add_response("close", "Verstanden")
    dialog.add_response("copy", "Befehl kopieren")
    dialog.set_default_response("copy")
    dialog.set_close_response("close")
    dialog.connect("response", _on_copy_response)
    dialog.present(parent)
    return dialog


def _on_copy_response(_dialog: Adw.AlertDialog, response: str) -> None:
    """Kopiert den Anmeldebefehl, wenn der Benutzer das moechte."""
    if response == "copy":
        _copy_to_clipboard(LOGIN_COMMAND)


def show_capability_problem(parent: Gtk.Widget, caps: Capabilities) -> Adw.AlertDialog | None:
    """Zeigt den passenden Dialog zu einem Befund der CLI-Pruefung."""
    if not caps.available:
        return show_cli_missing_dialog(parent, caps.problem)
    if not caps.authenticated:
        return show_not_authenticated_dialog(parent, caps.problem)
    if caps.problem:
        dialog = Adw.AlertDialog(heading="Hinweis zur Proton-Drive-CLI", body=caps.problem)
        dialog.add_response("close", "Verstanden")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present(parent)
        return dialog
    return None


def show_error_dialog(parent: Gtk.Widget, heading: str, body: str) -> Adw.AlertDialog:
    """Allgemeiner Fehlerdialog."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("close", "Schliessen")
    dialog.set_default_response("close")
    dialog.set_close_response("close")
    dialog.present(parent)
    return dialog


__all__ = [
    "LOGIN_COMMAND",
    "show_capability_problem",
    "show_cli_missing_dialog",
    "show_error_dialog",
    "show_not_authenticated_dialog",
]
