#!/bin/bash
# Build CardCopy for the Mac (Apple silicon), on a Mac. Run from anywhere; everything lands in dist/:
#
#   CardCopy.app          the app, ad-hoc signed
#   CardCopy-Installer.pkg  a regular installer that puts the app in Applications (what people download)
#   CardCopy-mac.dmg      drag-to-Applications disk image
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
# the commit this build comes from, shown beside the version (Settings, sidebar, diagnostic report)
git rev-parse --short HEAD > cardcopy/assets/build.txt 2>/dev/null || echo dev > cardcopy/assets/build.txt
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

echo "== installer package"
# A classic installer (Continue, Install, password): puts CardCopy.app into /Applications. Not relocatable,
# or Installer would "upgrade" a stray copy wherever it found one (Downloads, a mounted .dmg) instead.
version="$("$PYTHON" -c 'import cardcopy; print(cardcopy.__version__)')"
pkgroot=build/pkgroot
rm -rf "$pkgroot" dist/CardCopy-Installer.pkg && mkdir -p "$pkgroot/Applications"
ditto dist/CardCopy.app "$pkgroot/Applications/CardCopy.app"
pkgbuild --analyze --root "$pkgroot" build/component.plist >/dev/null
# Every bundle the analysis found (the app, and the Qt frameworks inside it): installed exactly where the
# package says, always replacing what is there. Relocatable, Installer "upgrades" any other copy it knows
# of (one left in Downloads, the opened .dmg) and leaves the one in Applications as it was.
"$PYTHON" - build/component.plist <<'PY'
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    bundles = plistlib.load(f)
for bundle in bundles:
    bundle.update(BundleIsRelocatable=False, BundleIsVersionChecked=False, BundleOverwriteAction="upgrade")
with open(sys.argv[1], "wb") as f:
    plistlib.dump(bundles, f)
print(f"{len(bundles)} bundle(s) pinned to their install location")
PY
pkgbuild --root "$pkgroot" --component-plist build/component.plist --identifier com.framedhorizon.cardcopy \
  --version "$version" --install-location / build/CardCopy-component.pkg >/dev/null
productbuild --package build/CardCopy-component.pkg --identifier com.framedhorizon.cardcopy.installer \
  --version "$version" dist/CardCopy-Installer.pkg >/dev/null

echo "== disk image and zip"
stage=build/dmg
rm -rf "$stage" dist/CardCopy-mac.dmg dist/CardCopy-mac.zip && mkdir -p "$stage"
cp -R dist/CardCopy.app "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create -volname CardCopy -srcfolder "$stage" -ov -format UDZO dist/CardCopy-mac.dmg >/dev/null
ditto -c -k --keepParent dist/CardCopy.app dist/CardCopy-mac.zip
shasum -a 256 dist/CardCopy-Installer.pkg dist/CardCopy-mac.dmg dist/CardCopy-mac.zip
du -sh dist/CardCopy.app dist/CardCopy-Installer.pkg dist/CardCopy-mac.dmg
