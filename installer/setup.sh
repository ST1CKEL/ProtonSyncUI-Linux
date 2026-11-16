#!/bin/sh
# Starts the graphical ProtonSyncUI setup. Without a graphical session, without
# GTK 4/libadwaita, or with --text, the terminal installer (install.sh) runs
# instead -- it can also install the missing system packages.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(dirname -- "$here")

say() {
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
        de*) printf '%s\n' "$1" ;;
        *) printf '%s\n' "$2" ;;
    esac
}

text_mode=0
passthrough=""
for argument in "$@"; do
    case "$argument" in
        --text) text_mode=1 ;;
        *) passthrough="$passthrough $argument" ;;
    esac
done

python=/usr/bin/python3
[ -x "$python" ] || python=$(command -v python3 || true)

has_toolkit() {
    [ -n "$python" ] && "$python" - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
PY
}

if [ "$text_mode" -eq 0 ] && [ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    say "Keine grafische Sitzung gefunden -- Installation im Terminal." \
        "No graphical session found -- installing in the terminal."
    text_mode=1
fi

if [ "$text_mode" -eq 0 ] && ! has_toolkit; then
    say "GTK 4 und libadwaita fehlen noch -- die Installation laeuft im Terminal und richtet sie ein." \
        "GTK 4 and libadwaita are still missing -- the terminal installer will set them up."
    text_mode=1
fi

if [ "$text_mode" -eq 1 ]; then
    # shellcheck disable=SC2086
    exec bash "$root/install.sh" $passthrough
fi

# shellcheck disable=SC2086
exec "$python" "$here/proton_sync_ui_setup.py" $passthrough
