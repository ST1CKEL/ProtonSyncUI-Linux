"""StatusNotifierItem (SNI) & DBusMenu Taskleisten-Dienst fuer Linux/GNOME/KDE."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cairo
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Rsvg", "2.0")
from gi.repository import Gio, GLib, Rsvg  # noqa: E402

from .. import APP_ID, APP_TITLE  # noqa: E402
from ..logging_setup import get_logger  # noqa: E402

if TYPE_CHECKING:
    from .application import ProtonSyncUIApplication

log = get_logger("ui.tray")

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


def _render_icon_pixmaps() -> list[tuple[int, int, bytes]]:
    """Rendert IconPixmap in Standard-Tray-Groessen fuer universelle SNI-Kompatibilitaet."""
    try:
        svg_path = (
            Path.home()
            / ".local"
            / "share"
            / "icons"
            / "hicolor"
            / "scalable"
            / "apps"
            / f"{APP_ID}.svg"
        )
        if not svg_path.exists():
            return []
        handle = Rsvg.Handle.new_from_file(str(svg_path))
        results: list[tuple[int, int, bytes]] = []
        for size in (22, 24, 32, 48):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            cr = cairo.Context(surface)
            cr.scale(size / 128.0, size / 128.0)
            handle.render_cairo(cr)
            bgra = bytearray(surface.get_data().tobytes())
            argb = bytearray(len(bgra))
            for i in range(0, len(bgra), 4):
                argb[i] = bgra[i + 3]  # Alpha
                argb[i + 1] = bgra[i + 2]  # Red
                argb[i + 2] = bgra[i + 1]  # Green
                argb[i + 3] = bgra[i]  # Blue
            results.append((size, size, bytes(argb)))
        return results
    except Exception as err:
        log.debug("IconPixmap konnte nicht gerendert werden: %s", err)
        return []


class TrayService:
    """Taskleisten- und Infobereich-Dienst (StatusNotifierItem & DBusMenu)."""

    def __init__(
        self,
        app: ProtonSyncUIApplication,
        *,
        on_show_window: Callable[[], None],
        on_sync_all: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._app = app
        self._on_show_window = on_show_window
        self._on_sync_all = on_sync_all
        self._on_quit = on_quit

        self._connection: Gio.DBusConnection | None = None
        self._sni_reg_id: int = 0
        self._menu_reg_id: int = 0
        self._bus_name_id: int = 0

        self._title = APP_TITLE
        self._status_text = "Alles synchronisiert"
        self._icon_name = APP_ID
        self._is_syncing = False
        self._has_error = False
        self._icon_pixmaps: list[tuple[int, int, bytes]] = []

        self._sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]

    def start(self) -> None:
        """Startet den Tray-Dienst auf dem Session-Bus."""
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as err:
            log.warning("DBus Session-Bus nicht verfuegbar fuer Tray: %s", err)
            return

        # 1. StatusNotifierItem registrieren
        self._sni_reg_id = self._connection.register_object(
            "/StatusNotifierItem",
            self._sni_info,
            self._handle_sni_method_call,
            self._handle_sni_get_property,
            None,
        )

        # 2. DBusMenu registrieren
        self._menu_reg_id = self._connection.register_object(
            "/StatusNotifierMenu",
            self._menu_info,
            self._handle_menu_method_call,
            self._handle_menu_get_property,
            None,
        )

        # 3. Eindeutigen Busnamen anfordern
        pid = os.getpid()
        bus_name = f"org.kde.StatusNotifierItem-{pid}-1"

        def on_name_acquired(
            conn: Gio.DBusConnection, name: str, _user_data: object = None
        ) -> None:
            self._register_with_watcher(conn, name)

        self._bus_name_id = Gio.bus_own_name_on_connection(
            self._connection,
            bus_name,
            Gio.BusNameOwnerFlags.NONE,
            on_name_acquired,
            None,
        )

    def stop(self) -> None:
        """Beendet den Tray-Dienst und raeumt DBus-Registrierungen auf."""
        if self._bus_name_id and self._connection:
            Gio.bus_unown_name(self._bus_name_id)
            self._bus_name_id = 0
        if self._sni_reg_id and self._connection:
            self._connection.unregister_object(self._sni_reg_id)
            self._sni_reg_id = 0
        if self._menu_reg_id and self._connection:
            self._connection.unregister_object(self._menu_reg_id)
            self._menu_reg_id = 0

    def update_status(
        self, status_text: str, *, is_syncing: bool = False, has_error: bool = False
    ) -> None:
        """Aktualisiert den Status, das Icon und den Tooltip im Tray."""
        self._status_text = status_text
        self._is_syncing = is_syncing
        self._has_error = has_error

        if is_syncing:
            self._icon_name = "emblem-synchronizing-symbolic"
        elif has_error:
            self._icon_name = "dialog-error-symbolic"
        else:
            self._icon_name = APP_ID

        if self._connection:
            self._connection.emit_signal(
                None,
                "/StatusNotifierItem",
                "org.kde.StatusNotifierItem",
                "NewIcon",
                None,
            )
            self._connection.emit_signal(
                None,
                "/StatusNotifierItem",
                "org.kde.StatusNotifierItem",
                "NewToolTip",
                None,
            )

    def _register_with_watcher(self, conn: Gio.DBusConnection, item_name: str) -> None:
        """Registriert das Item bei org.kde.StatusNotifierWatcher."""
        try:
            conn.call(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (item_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
                self._on_watcher_registered,
            )
        except Exception as err:
            log.debug("StatusNotifierWatcher Aufruf fehlgeschlagen: %s", err)

    def _on_watcher_registered(
        self, conn: Gio.DBusConnection, res: Gio.AsyncResult, _user_data: object = None
    ) -> None:
        try:
            conn.call_finish(res)
            log.info("ProtonSyncUI erfolgreich im System-Tray registriert.")
        except Exception as err:
            log.debug("Watcher Rueckmeldung: %s", err)

    # ------------------------------------------------------------------
    # SNI DBus Dispatcher
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
            GLib.idle_add(self._on_show_window)
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
        if property_name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if property_name == "Id":
            return GLib.Variant("s", "ProtonSyncUI")
        if property_name == "Title":
            return GLib.Variant("s", self._title)
        if property_name == "Status":
            return GLib.Variant("s", "Active")
        if property_name == "WindowId":
            return GLib.Variant("i", 0)
        if property_name == "IconThemePath":
            return GLib.Variant("s", str(Path.home() / ".local" / "share" / "icons"))
        if property_name == "IconName":
            return GLib.Variant("s", self._icon_name)
        if property_name in ("IconPixmap", "OverlayIconPixmap", "AttentionIconPixmap"):
            if not self._icon_pixmaps:
                self._icon_pixmaps = _render_icon_pixmaps()
            return GLib.Variant("a(iiay)", self._icon_pixmaps)
        if property_name in ("OverlayIconName", "AttentionIconName", "AttentionMovieName"):
            return GLib.Variant("s", "")
        if property_name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if property_name == "Menu":
            return GLib.Variant("o", "/StatusNotifierMenu")
        if property_name == "ToolTip":
            tooltip_sub = f"ProtonSyncUI: {self._status_text}"
            return GLib.Variant("(sa(iiay)ss)", (self._icon_name, [], self._title, tooltip_sub))
        return GLib.Variant("s", "")

    # ------------------------------------------------------------------
    # DBusMenu Dispatcher
    # ------------------------------------------------------------------

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
            layout = self._build_menu_layout()
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, layout)))
        elif method_name == "GetGroupProperties":
            invocation.return_value(GLib.Variant("(a(ia{sv}))", ([])))
        elif method_name == "GetProperty":
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", ""),)))
        elif method_name == "Event":
            item_id = parameters[0]
            event_id = parameters[1]
            if event_id == "clicked":
                self._handle_menu_click(item_id)
            invocation.return_value(None)
        elif method_name == "EventGroup":
            invocation.return_value(GLib.Variant("(ai)", ([])))
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
        if property_name == "Version":
            return GLib.Variant("u", 3)
        if property_name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if property_name == "Status":
            return GLib.Variant("s", "normal")
        if property_name == "IconThemePath":
            return GLib.Variant("as", [str(Path.home() / ".local" / "share" / "icons")])
        return GLib.Variant("s", "")

    def _build_menu_layout(self) -> tuple[int, dict[str, GLib.Variant], list[Any]]:
        """Erstellt die DBusMenu-Struktur (ia{sv}av)."""
        root_props: dict[str, GLib.Variant] = {"children-display": GLib.Variant("s", "submenu")}

        items: list[tuple[int, dict[str, GLib.Variant], list[Any]]] = [
            (
                1,
                {
                    "label": GLib.Variant("s", "ProtonSyncUI oeffnen"),
                    "enabled": GLib.Variant("b", True),
                    "visible": GLib.Variant("b", True),
                },
                [],
            ),
            (
                2,
                {
                    "type": GLib.Variant("s", "separator"),
                    "visible": GLib.Variant("b", True),
                },
                [],
            ),
            (
                3,
                {
                    "label": GLib.Variant("s", "Alle jetzt synchronisieren"),
                    "enabled": GLib.Variant("b", not self._is_syncing),
                    "visible": GLib.Variant("b", True),
                },
                [],
            ),
            (
                4,
                {
                    "type": GLib.Variant("s", "separator"),
                    "visible": GLib.Variant("b", True),
                },
                [],
            ),
            (
                5,
                {
                    "label": GLib.Variant("s", "Beenden"),
                    "enabled": GLib.Variant("b", True),
                    "visible": GLib.Variant("b", True),
                },
                [],
            ),
        ]

        return (0, root_props, [GLib.Variant("(ia{sv}av)", item) for item in items])

    def _handle_menu_click(self, item_id: int) -> None:
        """Fuehrt die Aktion eines Menue-Eintrags aus."""
        if item_id == 1:
            GLib.idle_add(self._on_show_window)
        elif item_id == 3:
            GLib.idle_add(self._on_sync_all)
        elif item_id == 5:
            GLib.idle_add(self._on_quit)


__all__ = ["TrayService"]
