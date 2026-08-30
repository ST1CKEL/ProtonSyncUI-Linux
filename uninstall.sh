#!/usr/bin/env bash
#
# Entfernt ProtonSyncUI wieder vollstaendig aus dem Benutzerkontext.
#
# Konfiguration, Datenbank und Protokolle bleiben standardmaessig erhalten.
# Mit --purge werden auch diese geloescht.
#
# In keinem Fall werden Dateien bei Proton Drive angetastet.

set -euo pipefail

APP_ID="io.github.protonsyncui.ProtonSyncUI"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"

VENV_DIR="$DATA_HOME/proton-sync-ui/venv"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

info() { printf '\033[1;34m::\033[0m %s\n' "$*"; }
ok()   { printf '   \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[1;33m!\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------------------
info "Zeitgesteuerte Laeufe abschalten"
# ---------------------------------------------------------------------------

if [[ -x "$VENV_DIR/bin/proton-sync-ui" ]]; then
    "$VENV_DIR/bin/proton-sync-ui" systemd remove >/dev/null 2>&1 && ok "systemd-Units entfernt" \
        || warn "systemd-Units konnten nicht ueber die Anwendung entfernt werden."
fi

# Sicherheitsnetz, falls die Anwendung nicht mehr lauffaehig war.
shopt -s nullglob
for unit in "$CONFIG_HOME/systemd/user/proton-sync-ui@"*; do
    systemctl --user disable --now "$(basename "$unit")" >/dev/null 2>&1 || true
    rm -f "$unit"
    ok "entfernt: $(basename "$unit")"
done
shopt -u nullglob
command -v systemctl >/dev/null && systemctl --user daemon-reload >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
info "Anwendung entfernen"
# ---------------------------------------------------------------------------

for cmd in proton-sync-ui proton-sync-ui-gui; do
    if [[ -L "$BIN_DIR/$cmd" || -e "$BIN_DIR/$cmd" ]]; then
        rm -f "$BIN_DIR/$cmd"
        ok "$BIN_DIR/$cmd"
    fi
done

if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
    rmdir "$(dirname "$VENV_DIR")" 2>/dev/null || true
    ok "Laufzeitumgebung geloescht"
fi

for path in "$APPS_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.svg" "$CONFIG_HOME/autostart/$APP_ID.desktop"; do
    if [[ -e "$path" ]]; then
        rm -f "$path"
        ok "$path"
    fi
done

# ---------------------------------------------------------------------------
info "Zwischenspeicher der Arbeitsflaeche auffrischen"
# ---------------------------------------------------------------------------

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache  >/dev/null && gtk-update-icon-cache -qtf "$DATA_HOME/icons/hicolor" 2>/dev/null || true
if command -v kbuildsycoca6 >/dev/null; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi
ok "erledigt"

# ---------------------------------------------------------------------------
if [[ "$PURGE" -eq 1 ]]; then
    info "Benutzerdaten loeschen (--purge)"
    for path in "$CONFIG_HOME/proton-sync-ui" "$DATA_HOME/proton-sync-ui" "$STATE_HOME/proton-sync-ui"; do
        if [[ -d "$path" ]]; then
            rm -rf "$path"
            ok "$path"
        fi
    done
    printf '\n\033[1;32mVollstaendig entfernt.\033[0m\n'
else
    printf '\n\033[1;32mEntfernt.\033[0m Konfiguration, Datenbank und Protokolle blieben erhalten:\n'
    printf '  %s\n  %s\n  %s\n' \
        "$CONFIG_HOME/proton-sync-ui" "$DATA_HOME/proton-sync-ui" "$STATE_HOME/proton-sync-ui"
    printf '\nAuch diese loeschen:  ./uninstall.sh --purge\n'
fi

printf '\nDie zu Proton Drive uebertragenen Dateien bleiben unveraendert bestehen.\n'
