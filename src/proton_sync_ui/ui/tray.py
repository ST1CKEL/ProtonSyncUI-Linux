"""Symbol im Infobereich (StatusNotifierItem + DBusMenu) fuer KDE Plasma und GNOME.

KDE Plasma zeigt Eintraege an, die sich beim ``org.kde.StatusNotifierWatcher``
anmelden. Drei Dinge sind dabei fuer einen verlaesslichen Betrieb wichtig:

* **Reihenfolge beim Anmelden.** Per Autostart laeuft die Anwendung oft, bevor
  die Kontrollleiste bereit ist. Statt einmalig zu registrieren, wird der
  Watcher beobachtet und das Symbol jedes Mal angemeldet, wenn er erscheint --
  auch nach einem Neustart von ``plasmashell``.
* **Symbol ohne Abhaengigkeit vom Icon-Thema.** Zusaetzlich zum Namen wird das
  Symbol als Pixmap geliefert, je Zustand mit farbiger Marke.
* **Menue-Aktualisierung.** Aendert sich der Zustand, wird ``LayoutUpdated``
  gesendet, sonst zeigt Plasma ein veraltetes Menue.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .. import APP_ID, APP_TITLE  # noqa: E402
from ..logging_setup import get_logger  # noqa: E402

if TYPE_CHECKING:
    from .application import ProtonSyncUIApplication

log = get_logger("ui.tray")

WATCHER_NAME: Final = "org.kde.StatusNotifierWatcher"
WATCHER_PATH: Final = "/StatusNotifierWatcher"
ITEM_PATH: Final = "/StatusNotifierItem"
MENU_PATH: Final = "/StatusNotifierMenu"
ITEM_INTERFACE: Final = "org.kde.StatusNotifierItem"
MENU_INTERFACE: Final = "com.canonical.dbusmenu"

#: Kantenlaengen der gelieferten Pixmaps (Plasma waehlt die passende aus).
PIXMAP_SIZES: Final = (16, 22, 24, 32, 48, 64)

# Menue-Kennungen
MENU_STATUS: Final = 1
MENU_OPEN: Final = 3
MENU_SYNC: Final = 4
MENU_UPDATE: Final = 5
MENU_QUIT: Final = 7


class TrayState(StrEnum):
    """Zustand, den das Symbol anzeigt."""

    IDLE = "idle"
    SYNCING = "syncing"
    WARNING = "warning"
    ERROR = "error"


#: Farbe der Zustandsmarke (RGB) je Zustand; ``None`` = keine Marke.
_BADGE_COLORS: Final[dict[TrayState, tuple[float, float, float] | None]] = {
    TrayState.IDLE: None,
    TrayState.SYNCING: (0.20, 0.52, 0.89),
    TrayState.WARNING: (0.96, 0.62, 0.04),
    TrayState.ERROR: (0.88, 0.11, 0.14),
}

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewMenu"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in" />
      <arg name="recursionDepth" type="i" direction="in" />
      <arg name="propertyNames" type="as" direction="in" />
      <arg name="revision" type="u" direction="out" />
      <arg name="layout" type="(ia{sv}av)" direction="out" />
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in" />
      <arg name="propertyNames" type="as" direction="in" />
      <arg name="properties" type="a(ia{sv})" direction="out" />
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in" />
      <arg name="name" type="s" direction="in" />
      <arg name="value" type="v" direction="out" />
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in" />
      <arg name="eventId" type="s" direction="in" />
      <arg name="data" type="v" direction="in" />
      <arg name="timestamp" type="u" direction="in" />
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in" />
      <arg name="idErrors" type="ai" direction="out" />
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in" />
      <arg name="needUpdate" type="b" direction="out" />
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in" />
      <arg name="updatesNeeded" type="ai" direction="out" />
      <arg name="idErrors" type="ai" direction="out" />
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})" />
      <arg name="removedProps" type="a(ias)" />
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u" />
      <arg name="parent" type="i" />
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i" />
      <arg name="timestamp" type="u" />
    </signal>
  </interface>
</node>
"""


def find_icon_file() -> Path | None:
    """Sucht die SVG-Datei des Anwendungssymbols."""
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    candidates = [
        data_home / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
        Path("/usr/share/icons/hicolor/scalable/apps") / f"{APP_ID}.svg",
        Path("/usr/local/share/icons/hicolor/scalable/apps") / f"{APP_ID}.svg",
        # Mitgeliefert im Paket (install.sh) bzw. im Quellbaum.
        Path(__file__).resolve().parent.parent / "data" / f"{APP_ID}.svg",
        Path(__file__).resolve().parents[3] / "data" / "icons" / f"{APP_ID}.svg",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def render_icon_pixmaps(state: TrayState = TrayState.IDLE) -> list[tuple[int, int, bytes]]:
    """Rendert das Symbol samt Zustandsmarke als ARGB32-Pixmaps (Netzwerk-Bytefolge).

    Fehlen cairo oder librsvg, kommt eine leere Liste zurueck; dann greift
    allein der Symbolname.
    """
    try:
        import cairo  # noqa: PLC0415 -- optional

        gi.require_version("Rsvg", "2.0")
        from gi.repository import Rsvg  # noqa: PLC0415

        svg_path = find_icon_file()
        if svg_path is None:
            return []
        handle = Rsvg.Handle.new_from_file(str(svg_path))
        badge = _BADGE_COLORS.get(state)
        results: list[tuple[int, int, bytes]] = []
        for size in PIXMAP_SIZES:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            context = cairo.Context(surface)
            viewport = Rsvg.Rectangle()
            viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, size, size
            handle.render_document(context, viewport)

            if badge is not None:
                radius = size * 0.24
                center = size - radius - size * 0.02
                context.arc(center, center, radius + size * 0.05, 0, 6.2832)
                context.set_source_rgb(1, 1, 1)
                context.fill()
                context.arc(center, center, radius, 0, 6.2832)
                context.set_source_rgb(*badge)
                context.fill()

            surface.flush()
            results.append((size, size, _cairo_to_argb(bytes(surface.get_data()))))
        return results
    except Exception as error:
        log.debug("Symbol-Pixmap konnte nicht gerendert werden: %s", error)
        return []


def _cairo_to_argb(data: bytes) -> bytes:
    """Wandelt cairo-ARGB32 (vormultipliziert, native Bytefolge) in ARGB (Big Endian)."""
    import sys  # noqa: PLC0415

    source = bytearray(data)
    if sys.byteorder == "little":
        blue, green, red, alpha = source[0::4], source[1::4], source[2::4], source[3::4]
    else:  # pragma: no cover -- Big-Endian-Rechner
        alpha, red, green, blue = source[0::4], source[1::4], source[2::4], source[3::4]

    # Vormultiplikation rueckgaengig machen (nur an halbtransparenten Kanten noetig).
    for index, value in enumerate(alpha):
        if 0 < value < 255:
            red[index] = min(255, red[index] * 255 // value)
            green[index] = min(255, green[index] * 255 // value)
            blue[index] = min(255, blue[index] * 255 // value)

    result = bytearray(len(source))
    result[0::4], result[1::4], result[2::4], result[3::4] = alpha, red, green, blue
    return bytes(result)


class TrayService:
    """Symbol im Infobereich samt Kontextmenue."""

    def __init__(
        self,
        app: ProtonSyncUIApplication | None,
        *,
        on_show_window: Callable[[], None],
        on_sync_all: Callable[[], None],
        on_quit: Callable[[], None],
        on_check_update: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._on_show_window = on_show_window
        self._on_sync_all = on_sync_all
        self._on_quit = on_quit
        self._on_check_update = on_check_update

        self._connection: Gio.DBusConnection | None = None
        self._sni_reg_id = 0
        self._menu_reg_id = 0
        self._bus_name_id = 0
        self._watch_id = 0
        self._bus_name = ""
        self._name_acquired = False
        self._watcher_present = False
        self._registered = False

        self._title = APP_TITLE
        self._status_text = "Bereit"
        self._state = TrayState.IDLE
        self._menu_revision = 1
        self._pixmap_cache: dict[TrayState, list[tuple[int, int, bytes]]] = {}

        self._sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------

    @property
    def registered(self) -> bool:
        """Wahr, wenn eine Arbeitsflaeche das Symbol aktuell anzeigt."""
        return self._registered

    @property
    def state(self) -> TrayState:
        """Aktuell angezeigter Zustand."""
        return self._state

    def start(self) -> None:
        """Meldet das Symbol am Sitzungsbus an und beobachtet den Watcher."""
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as error:
            log.warning("Sitzungsbus nicht verfuegbar, kein Symbol im Infobereich: %s", error)
            return

        try:
            self._sni_reg_id = self._connection.register_object(
                ITEM_PATH,
                self._sni_info,
                self._handle_sni_method_call,
                self._handle_sni_get_property,
                None,
            )
            self._menu_reg_id = self._connection.register_object(
                MENU_PATH,
                self._menu_info,
                self._handle_menu_method_call,
                self._handle_menu_get_property,
                None,
            )
        except GLib.Error as error:
            log.warning("Symbol im Infobereich konnte nicht angelegt werden: %s", error)
            return

        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._bus_name_id = Gio.bus_own_name_on_connection(
            self._connection,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired,
            self._on_name_lost,
        )
        # Der Watcher gehoert zur Kontrollleiste und kann spaeter erscheinen,
        # verschwinden und wiederkommen (Anmeldung, plasmashell-Neustart).
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )

    def stop(self) -> None:
        """Meldet das Symbol ab und raeumt alle Registrierungen auf."""
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._bus_name_id:
            Gio.bus_unown_name(self._bus_name_id)
            self._bus_name_id = 0
        if self._connection is not None:
            if self._sni_reg_id:
                self._connection.unregister_object(self._sni_reg_id)
                self._sni_reg_id = 0
            if self._menu_reg_id:
                self._connection.unregister_object(self._menu_reg_id)
                self._menu_reg_id = 0
        self._registered = False
        self._name_acquired = False

    def _on_name_acquired(self, *_args: object) -> None:
        self._name_acquired = True
        self._try_register()

    def _on_name_lost(self, *_args: object) -> None:
        self._name_acquired = False
        self._registered = False

    def _on_watcher_appeared(self, *_args: object) -> None:
        self._watcher_present = True
        self._registered = False
        self._try_register()

    def _on_watcher_vanished(self, *_args: object) -> None:
        if self._registered:
            log.info("Infobereich ist verschwunden; das Symbol wird bei Rueckkehr neu angemeldet.")
        self._watcher_present = False
        self._registered = False

    def _try_register(self) -> None:
        """Meldet das Symbol an, sobald Busname und Watcher vorhanden sind."""
        if self._connection is None or self._registered:
            return
        if not (self._name_acquired and self._watcher_present):
            return
        self._connection.call(
            WATCHER_NAME,
            WATCHER_PATH,
            WATCHER_NAME,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._bus_name,)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            self._on_watcher_registered,
        )

    def _on_watcher_registered(
        self, connection: Gio.DBusConnection, result: Gio.AsyncResult, _user_data: object = None
    ) -> None:
        try:
            connection.call_finish(result)
        except GLib.Error as error:
            log.warning("Anmeldung im Infobereich fehlgeschlagen: %s", error.message)
            return
        self._registered = True
        log.info("ProtonSyncUI erfolgreich im System-Tray registriert.")

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------

    def set_state(self, state: TrayState, status_text: str) -> None:
        """Setzt Zustand und Statuszeile und benachrichtigt die Arbeitsflaeche."""
        if state is self._state and status_text == self._status_text:
            return
        state_changed = state is not self._state
        self._state = state
        self._status_text = status_text
        self._menu_revision += 1

        self._emit(ITEM_INTERFACE, ITEM_PATH, "NewToolTip")
        if state_changed:
            self._emit(ITEM_INTERFACE, ITEM_PATH, "NewIcon")
            self._emit(ITEM_INTERFACE, ITEM_PATH, "NewAttentionIcon")
            self._emit(
                ITEM_INTERFACE, ITEM_PATH, "NewStatus", GLib.Variant("(s)", (self._sni_status(),))
            )
        self._emit(
            MENU_INTERFACE,
            MENU_PATH,
            "LayoutUpdated",
            GLib.Variant("(ui)", (self._menu_revision, 0)),
        )

    def update_status(
        self, status_text: str, *, is_syncing: bool = False, has_error: bool = False
    ) -> None:
        """Bequeme Variante von :meth:`set_state` (aeltere Schnittstelle)."""
        if is_syncing:
            state = TrayState.SYNCING
        elif has_error:
            state = TrayState.ERROR
        else:
            state = TrayState.IDLE
        self.set_state(state, status_text)

    def _emit(
        self, interface: str, path: str, signal: str, parameters: GLib.Variant | None = None
    ) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(None, path, interface, signal, parameters)
        except GLib.Error as error:
            log.debug("Signal %s konnte nicht gesendet werden: %s", signal, error)

    def _sni_status(self) -> str:
        """SNI-Status: ``NeedsAttention`` laesst Plasma das Symbol einblenden."""
        return "NeedsAttention" if self._state is TrayState.ERROR else "Active"

    def _pixmaps(self, state: TrayState) -> list[tuple[int, int, bytes]]:
        if state not in self._pixmap_cache:
            self._pixmap_cache[state] = render_icon_pixmaps(state)
        return self._pixmap_cache[state]

    def _icon_name(self) -> str:
        """Symbolname. Ausser im Ruhezustand leer, damit die Pixmap mit Marke gilt."""
        if self._state is TrayState.IDLE or not self._pixmaps(self._state):
            return APP_ID
        return ""

    # ------------------------------------------------------------------
    # StatusNotifierItem
    # ------------------------------------------------------------------

    def _handle_sni_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self._call, self._on_show_window)
            invocation.return_value(None)
        elif method_name in ("ContextMenu", "Scroll"):
            invocation.return_value(None)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                f"Unknown method {method_name}",
            )

    def _handle_sni_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        property_name: str,
    ) -> GLib.Variant:
        match property_name:
            case "Category":
                return GLib.Variant("s", "ApplicationStatus")
            case "Id":
                return GLib.Variant("s", APP_ID)
            case "Title":
                return GLib.Variant("s", self._title)
            case "Status":
                return GLib.Variant("s", self._sni_status())
            case "WindowId":
                return GLib.Variant("i", 0)
            case "IconThemePath":
                return GLib.Variant("s", "")
            case "IconName":
                return GLib.Variant("s", self._icon_name())
            case "IconPixmap":
                return GLib.Variant("a(iiay)", self._pixmaps(self._state))
            case "AttentionIconName":
                return GLib.Variant("s", "")
            case "AttentionIconPixmap":
                return GLib.Variant("a(iiay)", self._pixmaps(TrayState.ERROR))
            case "OverlayIconPixmap":
                return GLib.Variant("a(iiay)", [])
            case "OverlayIconName" | "AttentionMovieName":
                return GLib.Variant("s", "")
            case "ItemIsMenu":
                return GLib.Variant("b", False)
            case "Menu":
                return GLib.Variant("o", MENU_PATH)
            case "ToolTip":
                return GLib.Variant("(sa(iiay)ss)", (APP_ID, [], self._title, self._status_text))
        return GLib.Variant("s", "")

    # ------------------------------------------------------------------
    # DBusMenu
    # ------------------------------------------------------------------

    def _menu_items(self) -> list[tuple[int, dict[str, GLib.Variant]]]:
        """Eintraege des Kontextmenues als (Kennung, Eigenschaften)."""

        def entry(label: str, *, enabled: bool = True, icon: str = "") -> dict[str, GLib.Variant]:
            props = {
                "label": GLib.Variant("s", label),
                "enabled": GLib.Variant("b", enabled),
                "visible": GLib.Variant("b", True),
            }
            if icon:
                props["icon-name"] = GLib.Variant("s", icon)
            return props

        separator = {"type": GLib.Variant("s", "separator"), "visible": GLib.Variant("b", True)}
        items = [
            (MENU_STATUS, entry(self._status_text, enabled=False)),
            (2, separator),
            (MENU_OPEN, entry(f"{APP_TITLE} oeffnen", icon="window-new")),
            (
                MENU_SYNC,
                entry(
                    "Alle jetzt synchronisieren",
                    enabled=self._state is not TrayState.SYNCING,
                    icon="view-refresh",
                ),
            ),
        ]
        if self._on_check_update is not None:
            items.append((MENU_UPDATE, entry("Nach Updates suchen", icon="system-software-update")))
        items += [(6, separator), (MENU_QUIT, entry("Beenden", icon="application-exit"))]
        return items

    def _build_menu_layout(self) -> tuple[int, dict[str, GLib.Variant], list[Any]]:
        """Erstellt die DBusMenu-Struktur ``(ia{sv}av)``."""
        root_props = {"children-display": GLib.Variant("s", "submenu")}
        children = [
            GLib.Variant("(ia{sv}av)", (item_id, props, []))
            for item_id, props in self._menu_items()
        ]
        return (0, root_props, children)

    def _handle_menu_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "GetLayout":
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (self._menu_revision, self._build_menu_layout()))
            )
        elif method_name == "GetGroupProperties":
            wanted = set(parameters[0])
            properties = [
                (item_id, props)
                for item_id, props in self._menu_items()
                if not wanted or item_id in wanted
            ]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (properties,)))
        elif method_name == "GetProperty":
            item_id, name = parameters[0], parameters[1]
            props = dict(self._menu_items()).get(item_id, {})
            value = props.get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method_name == "Event":
            if parameters[1] == "clicked":
                self._handle_menu_click(parameters[0])
            invocation.return_value(None)
        elif method_name == "EventGroup":
            for event in parameters[0]:
                if event[1] == "clicked":
                    self._handle_menu_click(event[0])
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method_name == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                f"Unknown method {method_name}",
            )

    def _handle_menu_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        property_name: str,
    ) -> GLib.Variant:
        match property_name:
            case "Version":
                return GLib.Variant("u", 3)
            case "TextDirection":
                return GLib.Variant("s", "ltr")
            case "Status":
                return GLib.Variant("s", "normal")
            case "IconThemePath":
                return GLib.Variant("as", [])
        return GLib.Variant("s", "")

    def _handle_menu_click(self, item_id: int) -> None:
        """Fuehrt die Aktion eines Menue-Eintrags im Hauptthread aus."""
        callbacks = {
            MENU_OPEN: self._on_show_window,
            MENU_SYNC: self._on_sync_all,
            MENU_UPDATE: self._on_check_update,
            MENU_QUIT: self._on_quit,
        }
        callback = callbacks.get(item_id)
        if callback is not None:
            GLib.idle_add(self._call, callback)

    @staticmethod
    def _call(callback: Callable[[], None]) -> bool:
        try:
            callback()
        except Exception:
            log.exception("Aktion aus dem Infobereich fehlgeschlagen")
        return GLib.SOURCE_REMOVE


__all__ = ["TrayService", "TrayState", "find_icon_file", "render_icon_pixmaps"]
