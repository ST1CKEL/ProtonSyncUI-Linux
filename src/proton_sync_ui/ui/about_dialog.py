"""Dialog "Info & Lizenz" mit dem Logo des Entwicklers.

``Adw.AboutDialog`` kann ausser dem Anwendungssymbol kein Bild zeigen. Damit
das Logo von Stickelbroeck Labs als Entwickler erscheint, ist der Dialog hier
selbst aufgebaut -- im selben Stil (Symbol, Name, Version, Verweise, Lizenz).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import gi

from ..i18n import tr

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import APP_ID, APP_TITLE, __version__, update  # noqa: E402

DEVELOPER_NAME: Final = "Stickelbroeck Labs"
DEVELOPER_URL: Final = "https://stickelbroeck.com"

#: Das Logo hat helle Schrift und steht deshalb immer auf einer dunklen Karte --
#: unabhaengig davon, ob die Arbeitsflaeche hell oder dunkel eingestellt ist.
_CSS: Final = """
.developer-card {
  background-color: #12161c;
  border-radius: 14px;
  padding: 18px 24px;
}
.developer-card .developer-caption {
  color: rgba(245, 247, 250, 0.72);
}
"""

_MIT_NOTICE: Final = (
    "Copyright © 2026 ProtonSyncUI Contributors\n\n"
    "Hiermit wird jeder Person, die eine Kopie dieser Software und der zugehoerigen "
    "Dokumentation erhaelt, kostenlos die Erlaubnis erteilt, uneingeschraenkt mit der "
    "Software zu handeln -- einschliesslich der Rechte, sie zu nutzen, zu kopieren, zu "
    "aendern, zusammenzufuehren, zu veroeffentlichen, zu verbreiten, zu unterlizenzieren "
    "und zu verkaufen --, sofern der Urheberrechtsvermerk und dieser Erlaubnishinweis in "
    "allen Kopien enthalten sind.\n\n"
    "DIE SOFTWARE WIRD OHNE JEDE GEWAEHRLEISTUNG BEREITGESTELLT. Massgeblich ist der "
    "englische Originaltext der MIT-Lizenz in der Datei LICENSE."
)

_css_installed = False


def developer_logo_path() -> Path | None:
    """Pfad des mitgelieferten Logos, sofern vorhanden."""
    candidate = Path(__file__).resolve().parent.parent / "data" / "stickelbroeck-labs.png"
    return candidate if candidate.is_file() else None


def _install_css() -> None:
    global _css_installed  # noqa: PLW0603 -- einmalig je Prozess
    display = Gdk.Display.get_default()
    if _css_installed or display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _css_installed = True


class AboutDialog(Adw.Dialog):
    """Info & Lizenz."""

    __gtype_name__ = "ProtonSyncUIAboutDialog"

    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(title=tr("Ueber {0}").format(APP_TITLE))
        self._parent = parent
        self.set_content_width(460)
        self.set_content_height(680)
        _install_css()

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(6)
        box.set_margin_bottom(24)
        box.set_margin_start(18)
        box.set_margin_end(18)

        box.append(self._build_head())
        box.append(self._build_developer_card())
        box.append(self._build_links())
        box.append(self._build_license())

        clamp = Adw.Clamp(maximum_size=420)
        clamp.set_child(box)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(clamp)
        toolbar.set_content(scroll)
        self.set_child(toolbar)

    # ------------------------------------------------------------------

    def _build_head(self) -> Gtk.Widget:
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name(APP_ID)
        icon.set_pixel_size(96)
        head.append(icon)

        head.append(Gtk.Label(label=APP_TITLE, css_classes=["title-1"]))

        version = Gtk.Label(label=f"Version {__version__}", css_classes=["dim-label"])
        head.append(version)

        comments = Gtk.Label(
            label=(
                tr(
                    "2-Wege-Synchronisation und Backups mit Proton Drive.\n"
                    "ProtonSyncUI steuert ausschliesslich die offizielle proton-drive-CLI. "
                    "Bei Proton Drive wird niemals etwas geloescht."
                )
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        comments.set_margin_top(6)
        head.append(comments)
        return head

    def _build_developer_card(self) -> Gtk.Widget:
        """Dunkle Karte mit dem Logo von Stickelbroeck Labs."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("developer-card")

        caption = Gtk.Label(
            label=tr("Entwickelt von"), css_classes=["caption", "developer-caption"]
        )
        card.append(caption)

        logo = developer_logo_path()
        if logo is not None:
            picture = Gtk.Picture.new_for_filename(str(logo))
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_can_shrink(True)
            picture.set_size_request(-1, 130)
            picture.set_alternative_text(DEVELOPER_NAME)
            card.append(picture)
        else:
            card.append(Gtk.Label(label=DEVELOPER_NAME, css_classes=["title-2"]))

        link = Gtk.LinkButton.new_with_label(DEVELOPER_URL, "stickelbroeck.com")
        link.set_halign(Gtk.Align.CENTER)
        card.append(link)
        return card

    def _build_links(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup()
        for title, subtitle, uri in (
            (tr("Entwickler"), DEVELOPER_NAME, DEVELOPER_URL),
            (tr("Projektseite"), tr("Quelltext und Dokumentation bei GitHub"), update.PROJECT_URL),
            (
                tr("Fehler melden"),
                tr("Problem oder Wunsch einreichen"),
                f"{update.PROJECT_URL}/issues",
            ),
        ):
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))
            row.connect("activated", self._open, uri)
            group.add(row)
        return group

    def _build_license(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=tr("Lizenz"), subtitle=tr("MIT-Lizenz -- freie Software"))
        text = Gtk.Label(label=tr(_MIT_NOTICE), wrap=True, xalign=0, selectable=True)
        text.add_css_class("caption")
        text.set_margin_top(12)
        text.set_margin_bottom(12)
        text.set_margin_start(12)
        text.set_margin_end(12)
        expander.add_row(text)
        group.add(expander)
        return group

    def _open(self, _row: Adw.ActionRow, uri: str) -> None:
        Gtk.UriLauncher.new(uri).launch(self._parent, None, None, None)


__all__ = ["DEVELOPER_NAME", "DEVELOPER_URL", "AboutDialog", "developer_logo_path"]
