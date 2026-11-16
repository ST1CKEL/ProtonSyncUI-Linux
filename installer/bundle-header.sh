#!/bin/sh
# ProtonSyncUI setup -- self-extracting installer for Linux (KDE Plasma, GNOME, ...).
# Everything after the __PAYLOAD__ line is a tar.gz with the application and
# its graphical installer. Run with:  sh ProtonSyncUI-Setup-*.run
#
# Options:  --text       install in the terminal instead of the setup window
#           --autostart  (with --text) start ProtonSyncUI at login
set -eu
directory=$(mktemp -d "${TMPDIR:-/tmp}/proton-sync-ui-setup.XXXXXX")
trap 'rm -rf "$directory"' EXIT HUP INT TERM
start=$(awk '/^__PAYLOAD__$/ { print NR + 1; exit }' "$0")
tail -n +"$start" "$0" | tar -xz -C "$directory"
sh "$directory/installer/setup.sh" "$@"
exit $?
__PAYLOAD__
