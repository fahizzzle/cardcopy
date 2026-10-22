# PyInstaller recipe for CardCopy.app. Run through scripts/build_mac.sh, which makes AppIcon.icns first.
# -*- mode: python -*-
import os
import re

ROOT = os.path.dirname(os.path.abspath(SPECPATH))
with open(os.path.join(ROOT, "cardcopy", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
# CFBundleVersion grows with every build (the GitHub run number), so two builds of 1.20.0 are told apart
BUILD_NUMBER = os.environ.get("CARDCOPY_BUILD_NUMBER", "0")

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "cardcopy", "assets"), os.path.join("cardcopy", "assets"))],
    hiddenimports=["cardcopy.mac_window", "cardcopy.mac.devices", "cardcopy.mac.power", "cardcopy.mac.gdrive",
                   "cardcopy.mac.native"],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CardCopy", console=False,
          target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="CardCopy")
app = BUNDLE(
    coll,
    name="CardCopy.app",
    icon=os.path.join(SPECPATH, "AppIcon.icns"),
    bundle_identifier="com.framedhorizon.cardcopy",
    version=VERSION,
    info_plist={
        "CFBundleName": "CardCopy",
        "CFBundleDisplayName": "CardCopy",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": f"{VERSION}.{BUILD_NUMBER}",
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.photography",
        "NSHumanReadableCopyright": "© 2026 Framed Horizon LLC",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,            # follows light and dark mode
        # What macOS shows when it asks the user for each kind of access:
        "NSRemovableVolumesUsageDescription":
            "CardCopy reads the photos, videos and recordings on your camera cards. It never changes or deletes them.",
        "NSNetworkVolumesUsageDescription": "CardCopy can copy into project folders on a network drive.",
        "NSDesktopFolderUsageDescription": "CardCopy can copy into project folders on your Desktop.",
        "NSDocumentsFolderUsageDescription": "CardCopy can copy into project folders in Documents.",
        "NSDownloadsFolderUsageDescription": "CardCopy can copy into project folders in Downloads.",
        "NSFileProviderDomainUsageDescription":
            "CardCopy copies your cards into project folders in Google Drive.",
        "NSAppleEventsUsageDescription":
            "CardCopy asks System Events to shut your Mac down when an offload has finished, "
            "only when you switch Shut down Mac on.",
    },
)
