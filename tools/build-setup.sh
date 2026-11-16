#!/usr/bin/env bash
#
# Baut das Setup: eine einzelne, selbstentpackende Datei fuer Endanwender.
#
#   tools/build-setup.sh            ->  dist/ProtonSyncUI-Setup-<Version>.run
#
# Enthalten sind die Anwendung (src/), Symbol und Startmenue-Eintrag (data/),
# install.sh/uninstall.sh und das grafische Setup (installer/). Der Bau ist
# reproduzierbar: sortierte Eintraege, feste Zeitstempel und Besitzer.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/src/proton_sync_ui/__init__.py")"
[[ -n "$VERSION" ]] || { echo "Version nicht gefunden." >&2; exit 1; }

OUT="$ROOT/dist/ProtonSyncUI-Setup-$VERSION.run"
STAGE="$ROOT/build/setup"
EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}"

rm -rf "$STAGE"
mkdir -p "$STAGE" "$ROOT/dist"
cp -r "$ROOT/src" "$ROOT/data" "$ROOT/installer" "$STAGE/"
cp "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/LICENSE" "$ROOT/README.md" "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$STAGE/installer/bundle-header.sh"
chmod 755 "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/installer/setup.sh"

sh -n "$ROOT/installer/bundle-header.sh"
sh -n "$ROOT/installer/setup.sh"

{
    cat "$ROOT/installer/bundle-header.sh"
    tar -C "$STAGE" --sort=name --format=gnu --owner=0 --group=0 --numeric-owner \
        --mtime="@$EPOCH" -cf - . | gzip -n
} > "$OUT.tmp"
chmod 755 "$OUT.tmp"
mv -f "$OUT.tmp" "$OUT"

( cd "$ROOT/dist" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "Setup: $OUT ($(du -h "$OUT" | cut -f1))"
cat "$OUT.sha256"
