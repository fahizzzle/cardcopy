# CardCopy — notes for Claude Code sessions

Copies camera SD cards into `Raw Photo|Video|Audio\<Project>\Cam N` folders. Python 3.11 + PySide6 6.11.2, for Windows and macOS (Apple silicon). Framed Horizon LLC. Public repo: fahizzzle/cardcopy (users download from its Releases; the app's update check reads `latest.json` / `latest-mac.json` from the latest release, so publishing a release reaches every user).

## Hard rules
- Never delete or overwrite anything, on a card or at the destination. Cards are only read. Finished copies are renamed into place with `copier.rename_new` (POSIX `rename` silently replaces, so a Mac uses `renamex_np(RENAME_EXCL)`). `tests/test_copier.py` guards this.
- Eject only removable media; shutdown is always ordinary (never forced), after a 60 s countdown.

## Layout
- Qt-free logic: `copier`, `identify`, `cameras`, `structure`, `missing`, `receipt`, `progress`, `updates`, `settings`.
- System calls: `devices`, `power`, `gdrive` hold the Windows code and, at the bottom, import the same names from `cardcopy/mac/` on a Mac (diskutil/ioreg, caffeinate/osascript/nettop, ~/Library/CloudStorage).
- Look: `theme.py` picks `glass.py` (Windows dark glass, frameless) or `aqua.py` (Mac: native frame, vibrancy sidebar via `mac/native.py`, light/dark, coral accent). Both export the same names. `ui.MainWindow._make_widgets` builds every control once; `_arrange` (Windows) or `mac_window.arrange` (Mac: toolbar, menus, Settings window) places them. Keep behaviour in `ui.py` only.
- `CARDCOPY_THEME=mac` previews the Mac look on Windows; `CARDCOPY_APPEARANCE=light|dark` pins it.

## Environment (Windows dev PC)
- No system Python: venv `%USERPROFILE%\.venvs\cardcopy` made with `uv` (`UV_NATIVE_TLS=1`, Avast intercepts HTTPS). Tests: `%USERPROFILE%\.venvs\cardcopy\Scripts\python.exe -m pytest`. Run Python with the sandbox disabled.
- Screenshots of the window on made-up cards: `scripts/screenshot.py OUT [--appearance both]` (offscreen needs `QT_QPA_FONTDIR=C:/Windows/Fonts`).
- Git identity in this repo is the GitHub no-reply address (public history).

## Builds
- Mac: `.github/workflows/build.yml` runs the tests on Windows and macOS, then `scripts/build_mac.sh` on macos-15: PyInstaller (`mac/CardCopy.spec`, Info.plist usage strings there) -> ad-hoc signed `CardCopy.app`, opened once with `CARDCOPY_SELFTEST` to prove it starts, then `CardCopy-Installer.pkg` (installs into /Applications), `CardCopy-mac.dmg` / `.zip` and screenshots. Pushes to `mac` replace the `mac-preview` pre-release (never "latest"). Not notarized (no Developer ID yet).
- Windows: the release zip = embedded Python 3.11.9 + PySide6 + `cardcopy/` + `windows/` scripts. The original build/release scripts were not recovered; recreate them before the next Windows release. No PyInstaller/exe on Windows (Avast).
- App icon: `mac/AppIcon.png` from `scripts/make_icon.py`; the build makes the .icns.
