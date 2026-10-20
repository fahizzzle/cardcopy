"""Find the SD card volumes that are plugged in (Windows; a Mac uses mac/devices.py). No Qt in here."""
from __future__ import annotations

import ctypes
import json
import os
import re
import string
import subprocess
import sys
from dataclasses import dataclass, field

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_FOLDER = -1  # a plain folder added by hand

# A volume with one of these at its root is treated as a camera card even
# when Windows does not report it as removable (some readers show as fixed).
CARD_MARKERS = ("DCIM", "M4ROOT", os.path.join("PRIVATE", "M4ROOT"), os.path.join("PRIVATE", "AVCHD"))
# Not cards: the little utility drive a Sony body exposes next to its card slots over USB.
IGNORED_LABELS = {"PMHOME"}

_SEM_FAILCRITICALERRORS = 0x0001
_CREATE_NO_WINDOW = 0x08000000


@dataclass
class Volume:
    root: str            # "E:\\" or a folder path
    label: str = ""
    serial: str = ""     # volume serial number, hex
    total: int = 0
    free: int = 0
    drive_type: int = 0
    model: str = ""      # disk model from Windows ("Sony ILCE-7M4 USB Device")
    device_key: str = "" # same for every card slot of one USB device
    lun: int | None = None
    facts: dict = field(default_factory=dict)   # what else the system says about it (a Mac's diskutil details)

    @property
    def letter(self) -> str:
        """What the card is called in the window and the log: "E:" on Windows, the volume's name
        under /Volumes on a Mac ("Untitled 1"). Empty for a folder added by hand."""
        if self.drive_type == DRIVE_FOLDER:
            return ""
        if sys.platform == "darwin":
            return os.path.basename(self.root.rstrip("/")) or self.root
        return self.root[:2]

    @property
    def key(self) -> str:
        return f"{self.root}|{self.serial}"


def drive_mask() -> int:
    """Bitmask of the drive letters that exist; cheap, used to notice plug/unplug."""
    return ctypes.windll.kernel32.GetLogicalDrives()


def _volume_info(root: str) -> tuple[str, str] | None:
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), label, 261, ctypes.byref(serial), None, None, fs, 261)
    if not ok:
        return None  # empty reader slot, or not ready
    return label.value, f"{serial.value:08X}"


def list_volumes() -> list[Volume]:
    """Every mounted drive letter that has media in it."""
    kernel32 = ctypes.windll.kernel32
    kernel32.SetErrorMode(_SEM_FAILCRITICALERRORS)  # no "insert a disk" popups
    mask = kernel32.GetLogicalDrives()
    volumes = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        info = _volume_info(root)
        if info is None:
            continue
        total = free = 0
        free_b, total_b = ctypes.c_ulonglong(0), ctypes.c_ulonglong(0)
        if kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root), None,
                                        ctypes.byref(total_b), ctypes.byref(free_b)):
            total, free = total_b.value, free_b.value
        volumes.append(Volume(root=root, label=info[0], serial=info[1], total=total,
                              free=free, drive_type=kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))))
    return volumes


def is_card(volume: Volume) -> bool:
    system = os.environ.get("SystemDrive", "C:").upper()
    if volume.root.upper().startswith(system) or "google drive" in volume.label.lower():
        return False
    if volume.label.upper() in IGNORED_LABELS:
        return False
    if volume.drive_type == DRIVE_REMOVABLE:
        return True
    return any(os.path.isdir(os.path.join(volume.root, m)) for m in CARD_MARKERS)


def folder_volume(path: str) -> Volume:
    path = os.path.abspath(path)
    return Volume(root=path, label=os.path.basename(path.rstrip("\\/")) or path,
                  drive_type=DRIVE_FOLDER)


_DISK_QUERY = r"""
$o = foreach ($d in Get-CimInstance Win32_DiskDrive) {
  foreach ($p in Get-CimAssociatedInstance -InputObject $d -ResultClassName Win32_DiskPartition) {
    foreach ($l in Get-CimAssociatedInstance -InputObject $p -ResultClassName Win32_LogicalDisk) {
      [pscustomobject]@{Letter=$l.DeviceID; Model=$d.Model; Pnp=$d.PNPDeviceID; Lun=$d.SCSILogicalUnit; Bus=$d.InterfaceType}
    }
  }
}
ConvertTo-Json @($o) -Compress
"""


def parse_disks(raw: str) -> dict[str, dict]:
    """{'E:': {'model', 'device_key', 'lun'}} from the PowerShell JSON."""
    try:
        rows = json.loads(raw) if raw.strip() else []
    except ValueError:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    disks = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("Letter"):
            continue
        pnp = row.get("Pnp") or ""
        # USBSTOR\DISK&VEN_SONY&PROD_X\<serial>&0 and ...&1 are the two slots
        # of one camera: drop the trailing LUN to get a per-device key.
        key = re.sub(r"&\d+$", "", pnp) if (row.get("Bus") or "").upper() == "USB" else ""
        model = re.sub(r"\s+USB Device$", "", (row.get("Model") or "").strip(), flags=re.I)
        disks[row["Letter"].upper()] = {"model": model, "device_key": key, "lun": row.get("Lun")}
    return disks


def query_disks(timeout: float = 25.0) -> dict[str, dict]:
    """Which physical USB device each drive letter sits on. Empty dict on failure."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _DISK_QUERY],
            capture_output=True, text=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_disks(out.stdout)


def find_cards() -> list[Volume]:
    cards = [v for v in list_volumes() if is_card(v)]
    if cards:
        disks = query_disks()
        for v in cards:
            d = disks.get(v.letter.upper())
            if d:
                v.model, v.device_key, v.lun = d["model"], d["device_key"], d["lun"]
    return cards


# ------------------------------------------------------------------- eject

_GENERIC_READ, _GENERIC_WRITE = 0x80000000, 0x40000000
_FSCTL_LOCK_VOLUME, _FSCTL_DISMOUNT_VOLUME = 0x00090018, 0x00090020
_IOCTL_STORAGE_MEDIA_REMOVAL, _IOCTL_STORAGE_EJECT_MEDIA = 0x002D4804, 0x002D4808


def eject_volume(root: str, tries: int = 10) -> tuple[bool, str]:
    """Safely remove one card: flush and dismount the volume, then eject the media, like Explorer's Eject.
    Nothing is written to the card. Returns (ok, message).

    Hard rule: only ever a REMOVABLE drive letter. A fixed disk, a network drive or a Google Drive volume is refused.
    """
    import time
    from ctypes import wintypes
    if os.name != "nt" or os.environ.get("CARDCOPY_NO_DEVICES"):
        return False, "ejecting is switched off"
    letter = root[:2].upper()
    if not re.fullmatch(r"[A-Z]:", letter):
        return False, "not a drive"
    k = ctypes.windll.kernel32
    if k.GetDriveTypeW(ctypes.c_wchar_p(letter + "\\")) != DRIVE_REMOVABLE:
        return False, "not a removable drive, left alone"
    k.CreateFileW.restype = wintypes.HANDLE
    handle = k.CreateFileW(ctypes.c_wchar_p("\\\\.\\" + letter), _GENERIC_READ | _GENERIC_WRITE, 0x3, None, 3, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return False, "Windows would not open the drive"
    returned = wintypes.DWORD(0)

    def control(code: int, data=None, size: int = 0) -> bool:
        return bool(k.DeviceIoControl(wintypes.HANDLE(handle), code, data, size, None, 0, ctypes.byref(returned), None))

    try:
        for _ in range(tries):                      # something may still be reading: give it a moment
            if control(_FSCTL_LOCK_VOLUME):
                break
            time.sleep(0.3)
        else:
            return False, "still in use by another program (close Explorer windows or players showing it)"
        control(_FSCTL_DISMOUNT_VOLUME)
        allow = ctypes.c_ubyte(0)                   # PREVENT_MEDIA_REMOVAL { PreventMediaRemoval = FALSE }
        control(_IOCTL_STORAGE_MEDIA_REMOVAL, ctypes.byref(allow), 1)
        if control(_IOCTL_STORAGE_EJECT_MEDIA):
            return True, "ejected, safe to remove"
        return True, "dismounted, safe to remove"    # some readers cannot eject media; flushed and offline is enough
    finally:
        k.CloseHandle(wintypes.HANDLE(handle))


if sys.platform == "darwin":                                 # the same calls, answered by diskutil and ioreg
    from .mac.devices import drive_mask, eject_volume, find_cards, is_card, list_volumes  # noqa: E402,F401,F811
