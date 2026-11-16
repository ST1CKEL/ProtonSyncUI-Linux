#!/usr/bin/env bash
#
# Installiert ProtonSyncUI als Desktop-Anwendung im Benutzerkontext.
#
# Installiert bei Bedarf fehlende System-Abhaengigkeiten (GTK4, libadwaita,
# PyGObject) ueber den jeweiligen Paketmanager (dnf, apt, pacman, zypper)
# und richtet die Anwendung isoliert unter ~/.local ein.
#
# Optionen:
#   -y, --yes          Nicht-interaktive Installation (Bestaetigt Prompts automatisch)
#   --no-deps          Keine Systempakete via sudo installieren
#   --dev              Entwicklermodus: Startbefehle verweisen direkt auf diesen Quellbaum
#   --autostart        Start bei der Anmeldung einrichten (minimiert im Infobereich)
#
# Die Anwendung benoetigt ausschliesslich die Python-Standardbibliothek und
# die PyGObject-Systempakete. Sie wird deshalb OHNE virtuelle Umgebung
# installiert: Eine venv ist fest an die Python-Version gebunden und war nach
# jedem Fedora-Versionssprung (Python 3.14 -> 3.15 -> ...) unbrauchbar --
# Autostart und Timer liefen dann ins Leere.
#
# Rueckgaengig machen: ./uninstall.sh

set -euo pipefail

APP_ID="io.github.protonsyncui.ProtonSyncUI"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/proton-sync-ui/app"
LEGACY_VENV_DIR="$DATA_HOME/proton-sync-ui/venv"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

MIN_PY_MINOR=13

AUTO_YES=0
NO_DEPS=0
DEV_MODE=0
AUTOSTART=0

for arg in "$@"; do
    case "$arg" in
        -y|--yes) AUTO_YES=1 ;;
        --no-deps) NO_DEPS=1 ;;
        --dev) DEV_MODE=1 ;;
        --autostart) AUTOSTART=1 ;;
        -h|--help)
            cat <<EOF
Verwendung: ./install.sh [OPTIONEN]

Optionen:
  -y, --yes          Automatische Bestaetigung aller Abfragen
  --no-deps          Ueberspringt die Pruefung/Installation von Systempaketen
  --dev              Entwicklermodus: Startbefehle nutzen direkt diesen Quellbaum
  --autostart        Start bei der Anmeldung einrichten (minimiert im Infobereich)
  -h, --help         Diese Hilfe anzeigen
EOF
            exit 0
            ;;
    esac
done

info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
ok()    { printf '   \033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '   \033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Systemabhaengigkeiten pruefen & installieren
# ---------------------------------------------------------------------------
# Der Systeminterpreter, nicht ein zufaellig aktives venv/pyenv: nur er kennt
# die PyGObject-Systempakete und bleibt ueber Distributions-Upgrades gueltig.
if [[ -x /usr/bin/python3 ]]; then
    PYTHON=/usr/bin/python3
else
    PYTHON="$(command -v python3 || true)"
fi
[[ -n "$PYTHON" ]] || die "python3 wurde nicht gefunden."

check_python_gi() {
    "$PYTHON" - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
PY
}

install_system_deps() {
    info "System-Abhaengigkeiten pruefen (GTK4, libadwaita, PyGObject)"

    if check_python_gi; then
        ok "PyGObject, GTK4 und libadwaita bereits vorhanden"
        return 0
    fi

    if [[ "$NO_DEPS" -eq 1 ]]; then
        die "GTK4 / libadwaita fehlt und --no-deps wurde angegeben."
    fi

    warn "Benoetigte Systembibliotheken (GTK4, libadwaita, PyGObject) fehlen."

    # Paketmanager ermitteln
    local pkg_manager=""
    local install_cmd=""

    if command -v dnf >/dev/null 2>&1; then
        pkg_manager="dnf"
        install_cmd="sudo dnf install -y python3-gobject gtk4 libadwaita python3-pip desktop-file-utils"
    elif command -v apt-get >/dev/null 2>&1; then
        pkg_manager="apt"
        install_cmd="sudo apt-get update && sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 python3-pip python3-venv desktop-file-utils"
    elif command -v pacman >/dev/null 2>&1; then
        pkg_manager="pacman"
        install_cmd="sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita python-pip desktop-file-utils"
    elif command -v zypper >/dev/null 2>&1; then
        pkg_manager="zypper"
        install_cmd="sudo zypper install -y python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 libadwaita-1-0 python3-pip desktop-file-utils"
    else
        die "Kein unterstuetzter Paketmanager gefunden (dnf, apt, pacman, zypper). Bitte installiere GTK4, libadwaita und python3-gobject manuell."
    fi

    if [[ "$AUTO_YES" -eq 0 ]]; then
        printf '\033[1;33m?\033[0m Fehlende Systempakete via %s installieren? [J/n] ' "$pkg_manager"
        read -r answer
        case "$answer" in
            [nN][oO]|[nN]) die "Installation ohne Systempakete abgebrochen." ;;
        esac
    fi

    info "Installiere Systempakete mit: $install_cmd"
    eval "$install_cmd"

    if ! check_python_gi; then
        die "Trotz Paketinstallation konnten GTK4 / libadwaita nicht in Python importiert werden."
    fi
    ok "System-Abhaengigkeiten erfolgreich eingerichtet"
}

install_system_deps

# ---------------------------------------------------------------------------
# 2. Python & CLI pruefen
# ---------------------------------------------------------------------------
info "Laufzeit-Voraussetzungen pruefen"

PY_MAJOR="$("$PYTHON" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')"
if [[ "$PY_MAJOR" -lt 3 || "$PY_MINOR" -lt "$MIN_PY_MINOR" ]]; then
    die "Python 3.${MIN_PY_MINOR} oder neuer noetig, gefunden $("$PYTHON" --version)."
fi
ok "$("$PYTHON" --version) ($PYTHON)"

if command -v proton-drive >/dev/null; then
    ok "proton-drive gefunden: $(command -v proton-drive)"
else
    warn "proton-drive CLI ist aktuell nicht im PATH installiert."
    warn "ProtonSyncUI startet trotzdem. Die CLI gibt es bei Proton:"
    warn "  https://proton.me/download/drive/cli/index.html"
fi

# ---------------------------------------------------------------------------
# 3. Anwendung kopieren
# ---------------------------------------------------------------------------
if [[ "$DEV_MODE" -eq 1 ]]; then
    info "Entwicklermodus: Quellbaum wird direkt verwendet"
    PACKAGE_PARENT="$PROJECT_DIR/src"
    ok "$PACKAGE_PARENT"
else
    info "ProtonSyncUI installieren: $APP_DIR"
    PACKAGE_PARENT="$APP_DIR"
    STAGING="$APP_DIR.new.$$"
    rm -rf "$STAGING"
    mkdir -p "$STAGING"
    cp -r "$PROJECT_DIR/src/proton_sync_ui" "$STAGING/proton_sync_ui"
    find "$STAGING" -name '__pycache__' -type d -prune -exec rm -rf {} +
    mkdir -p "$STAGING/proton_sync_ui/data"
    install -m 644 "$PROJECT_DIR/data/icons/$APP_ID.svg" "$STAGING/proton_sync_ui/data/$APP_ID.svg"
    # Erst vollstaendig kopieren, dann austauschen: Ein laufender Timer-Lauf
    # sieht nie einen halb geschriebenen Stand.
    rm -rf "$APP_DIR.old"
    [[ -d "$APP_DIR" ]] && mv "$APP_DIR" "$APP_DIR.old"
    mv "$STAGING" "$APP_DIR"
    rm -rf "$APP_DIR.old"
fi

if [[ -d "$LEGACY_VENV_DIR" ]]; then
    rm -rf "$LEGACY_VENV_DIR"
    ok "Alte virtuelle Umgebung entfernt (nicht mehr noetig)"
fi

# ---------------------------------------------------------------------------
# 4. Startbefehle im Benutzer-Pfad anlegen
# ---------------------------------------------------------------------------
info "Startbefehle einrichten: $BIN_DIR"

mkdir -p "$BIN_DIR"
write_launcher() {
    local name="$1" module="$2"
    local target="$BIN_DIR/$name"
    # Fruehere Versionen legten hier Symlinks in die venv an -- erst entfernen,
    # sonst wuerde durch den Link hindurch geschrieben.
    rm -f "$target"
    cat > "$target" <<LAUNCHER
#!$PYTHON -P
# Startbefehl von ProtonSyncUI -- erzeugt von install.sh. Nicht bearbeiten.
import sys

sys.path.insert(0, r"""$PACKAGE_PARENT""")
from $module import main

if __name__ == "__main__":
    sys.exit(main())
LAUNCHER
    chmod 755 "$target"
    ok "$target"
}
write_launcher proton-sync-ui proton_sync_ui.cli.main
write_launcher proton-sync-ui-gui proton_sync_ui.ui.application

INSTALLED_VERSION="$("$BIN_DIR/proton-sync-ui" --version | awk '{print $NF}')" \
    || die "Die installierte Anwendung laesst sich nicht starten."
ok "Version $INSTALLED_VERSION installiert"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR liegt nicht im PATH. Ergaenze in ~/.bashrc oder ~/.zshrc:"
       warn '    export PATH="$HOME/.local/bin:$PATH"' ;;
esac

# ---------------------------------------------------------------------------
# 5. Desktop-Eintrag & Symbole in allen Aufloesungen installieren
# ---------------------------------------------------------------------------
info "Symbol und Startmenue-Eintrag installieren"

mkdir -p "$ICON_DIR" "$APPS_DIR" "$DATA_HOME/pixmaps" "$DATA_HOME/icons"
install -m 644 "$PROJECT_DIR/data/icons/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"
install -m 644 "$PROJECT_DIR/data/icons/$APP_ID.svg" "$DATA_HOME/pixmaps/$APP_ID.svg"
install -m 644 "$PROJECT_DIR/data/icons/$APP_ID.svg" "$DATA_HOME/icons/$APP_ID.svg"
ok "$ICON_DIR/$APP_ID.svg"

# Falls hicolor/index.theme im Benutzerprofil fehlt, aus System kopieren
if [[ ! -f "$DATA_HOME/icons/hicolor/index.theme" && -f /usr/share/icons/hicolor/index.theme ]]; then
    cp /usr/share/icons/hicolor/index.theme "$DATA_HOME/icons/hicolor/index.theme"
fi

# Raster-PNGs in Standardgroessen (16, 22, 24, 32, 48, 64, 128, 256, 512) rendern
"$PYTHON" - "$PROJECT_DIR/data/icons/$APP_ID.svg" "$DATA_HOME" "$APP_ID" <<'PY' 2>/dev/null || true
import sys
from pathlib import Path
try:
    import cairo
    import gi
    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg
    svg_path = sys.argv[1]
    data_home = Path(sys.argv[2])
    app_id = sys.argv[3]
    handle = Rsvg.Handle.new_from_file(svg_path)
    for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
        out_dir = data_home / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{app_id}.png"
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)
        cr.scale(size / 128.0, size / 128.0)
        handle.render_cairo(cr)
        surface.write_to_png(str(out_file))
        if size == 48:
            pixmap_file = data_home / "pixmaps" / f"{app_id}.png"
            surface.write_to_png(str(pixmap_file))
except Exception:
    pass
PY
ok "Symbole in 16px, 22px, 24px, 32px, 48px, 64px, 128px, 256px und 512px eingerichtet"

install -m 644 "$PROJECT_DIR/data/$APP_ID.desktop" "$APPS_DIR/$APP_ID.desktop"
sed -i "s|^Exec=proton-sync-ui-gui|Exec=$BIN_DIR/proton-sync-ui-gui|" "$APPS_DIR/$APP_ID.desktop"

ok "$APPS_DIR/$APP_ID.desktop"

# Autostart: neu einrichten (--autostart) oder bestehenden Eintrag auf den
# aktuellen Programmpfad bringen.
if [[ "$AUTOSTART" -eq 1 ]]; then
    "$BIN_DIR/proton-sync-ui" autostart on >/dev/null && ok "Autostart bei der Anmeldung eingerichtet"
else
    "$BIN_DIR/proton-sync-ui" autostart refresh >/dev/null 2>&1 || true
fi

# systemd-Units bestehender Zeitplaene auf den aktuellen Stand bringen.
if command -v systemctl >/dev/null 2>&1; then
    "$BIN_DIR/proton-sync-ui" systemd sync >/dev/null 2>&1 && ok "Zeitplaene (systemd-Timer) aktualisiert" || true
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
    if desktop-file-validate "$APPS_DIR/$APP_ID.desktop"; then
        ok "Startmenue-Eintrag ist gueltig"
    else
        warn "desktop-file-validate meldet Beanstandungen."
    fi
fi

# ---------------------------------------------------------------------------
# 6. Zwischenspeicher der Desktop-Umgebung auffrischen
# ---------------------------------------------------------------------------
info "Zwischenspeicher der Arbeitsflaeche auffrischen"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null && ok "update-desktop-database"
command -v gtk-update-icon-cache  >/dev/null 2>&1 && gtk-update-icon-cache -qtf "$DATA_HOME/icons/hicolor" 2>/dev/null && ok "gtk-update-icon-cache"

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 && ok "kbuildsycoca6 (KDE-Menue)"
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 && ok "kbuildsycoca5 (KDE-Menue)"
fi

command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload 2>/dev/null && ok "systemctl --user daemon-reload"

# ---------------------------------------------------------------------------
# 7. Abschlussmeldung
# ---------------------------------------------------------------------------
printf '\n\033[1;32mFertig.\033[0m ProtonSyncUI ist erfolgreich installiert.\n\n'
cat <<'EOF'
Starten:
  - Startmenue / Anwendungsuebersicht: nach "ProtonSyncUI" suchen
  - Terminal (GUI):                    proton-sync-ui-gui
  - Terminal (Status/CLI):             proton-sync-ui status

Einmalige Anmeldung bei Proton Drive (falls noch nicht erfolgt):
  in der Anwendung auf "Anmelden" klicken -- oder: proton-drive auth login

Start bei der Anmeldung (KDE Plasma, GNOME):
  proton-sync-ui autostart on        (oder in den Einstellungen der Anwendung)

Updates:
  proton-sync-ui update              (oder in den Einstellungen der Anwendung)

Deinstallation:
  ./uninstall.sh
EOF
