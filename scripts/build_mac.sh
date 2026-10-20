#!/bin/bash
# Build CardCopy for the Mac (Apple silicon), on a Mac. Run from anywhere; everything lands in dist/:
#
#   CardCopy.app          the app, ad-hoc signed
#   CardCopy-mac.dmg      drag-to-Applications disk image (what people download)
#   CardCopy-mac.zip      the app zipped with ditto (keeps the bundle's links and permissions)
#   screenshots/          the packaged app's own window, opened once to prove it starts, plus the
#                         window on made-up cards in light and dark (scripts/screenshot.py)
#
# GitHub Actions runs this on every push (.github/workflows/build.yml). Not notarized: without an Apple
# Developer ID, the first open needs System Settings > Privacy & Security > Open Anyway.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

"$PYTHON" -m pip install --quiet -r mac/requirements-build.txt

echo "== icon"
rm -rf build/AppIcon.iconset && mkdir -p build/AppIcon.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" mac/AppIcon.png --out "build/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" mac/AppIcon.png --out "build/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/AppIcon.iconset -o mac/AppIcon.icns

echo "== app"
rm -rf dist/CardCopy.app dist/CardCopy
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller mac/CardCopy.spec
codesign --force --deep --sign - dist/CardCopy.app
codesign --verify --deep --strict dist/CardCopy.app

echo "== does it start?"
shots="$PWD/dist/screenshots"
rm -rf "$shots" && mkdir -p "$shots"
home="$(mktemp -d)"
CARDCOPY_HOME="$home" CARDCOPY_NO_UPDATE_CHECK=1 CARDCOPY_NO_SHUTDOWN=1 CARDCOPY_SELFTEST="$shots" \
  dist/CardCopy.app/Contents/MacOS/CardCopy &
app=$!
( sleep 90; kill "$app" 2>/dev/null ) &
watchdog=$!
wait "$app" || true
kill "$watchdog" 2>/dev/null || true
if [ ! -f "$shots/app-window.png" ]; then
  echo "CardCopy.app did not start (no self-test picture)" >&2
  exit 1
fi

echo "== screenshots on made-up cards"
"$PYTHON" scripts/screenshot.py "$shots" --appearance both || echo "(screenshots failed; the app itself started)"

echo "== disk image and zip"
stage=build/dmg
rm -rf "$stage" dist/CardCopy-mac.dmg dist/CardCopy-mac.zip && mkdir -p "$stage"
cp -R dist/CardCopy.app "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create -volname CardCopy -srcfolder "$stage" -ov -format UDZO dist/CardCopy-mac.dmg >/dev/null
ditto -c -k --keepParent dist/CardCopy.app dist/CardCopy-mac.zip
shasum -a 256 dist/CardCopy-mac.dmg dist/CardCopy-mac.zip
du -sh dist/CardCopy.app dist/CardCopy-mac.dmg
