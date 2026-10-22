"""Find the SD card volumes that are mounted (macOS). No Qt in here.

Everything comes from two read-only queries: `diskutil info -plist` says what a volume is (removable,
a disk image, the Mac's own disk ...), and `ioreg` says which USB device it sits on, so the two card
slots of one camera can be grouped the way the Windows side does it with the disk's PNP id.
Ejecting goes through `diskutil eject`, which is what Finder's Eject does.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess

from ..devices import (CARD_MARKERS, DRIVE_FIXED, DRIVE_REMOVABLE, IGNORED_LABELS, Volume)

VOLUMES = "/Volumes"


def drive_mask() -> tuple[str, ...]:
    """What is mounted under /Volumes; cheap, used to notice plug/unplug."""
    try:
        return tuple(sorted(os.listdir(VOLUMES)))
    except OSError:
        return ()


def _run(args: list[str], timeout: float) -> bytes:
    try:
        out = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return b""
    return out.stdout if out.returncode == 0 else b""


def _plist(raw: bytes):
    try:
        return plistlib.loads(raw) if raw.strip() else None
    except Exception:            # plistlib raises several unrelated types on bad input
        return None


def disk_info(target: str, timeout: float = 15.0) -> dict:
    """`diskutil info -plist` for a mount point or a disk ("disk4s1"); {} when it knows nothing about it
    (a network share, a volume that has just gone)."""
    data = _plist(_run(["diskutil", "info", "-plist", target], timeout))
    return data if isinstance(data, dict) else {}


def mount_points() -> list[str]:
    """The volumes under /Volumes. The Mac's own disk shows up there as a link to / and is left out."""
    found = []
    for name in drive_mask():
        path = os.path.join(VOLUMES, name)
        if name.startswith(".") or os.path.islink(path):
            continue
        if os.path.ismount(path):
            found.append(path)
    return found


def _model(info: dict) -> str:
    """'Sony ILCE-7M4 Media' -> 'Sony ILCE-7M4'; a plain card reader says what it is ('SD Card Reader')."""
    name = str(info.get("MediaName") or info.get("IORegistryEntryName") or "").strip()
    return re.sub(r"\s+Media$", "", name, flags=re.I)


def on_boot_disk(root: str) -> bool:
    """Is this folder on the Mac's own disk (the system volume, or the Data volume beside it)?"""
    try:
        here = os.stat(root).st_dev
    except OSError:
        return False
    for system in ("/", "/System/Volumes/Data"):
        try:
            if os.stat(system).st_dev == here:
                return True
        except OSError:
            continue
    return False


def volume_from_info(root: str, info: dict) -> Volume:
    total = free = 0
    try:
        usage = shutil.disk_usage(root)
        total, free = usage.total, usage.free
    except OSError:
        pass
    boot = on_boot_disk(root)
    removable = bool(info.get("RemovableMedia") or info.get("Removable"))
    return Volume(
        root=root, label=str(info.get("VolumeName") or os.path.basename(root)),
        serial=str(info.get("VolumeUUID") or info.get("DiskUUID") or ""),
        total=total, free=free, drive_type=DRIVE_REMOVABLE if removable else DRIVE_FIXED,
        model=_model(info),
        facts={"bsd": str(info.get("DeviceIdentifier") or ""),
               "whole": str(info.get("ParentWholeDisk") or ""),
               "internal": bool(info.get("Internal")),
               "ejectable": bool(info.get("Ejectable")),
               "virtual": str(info.get("VirtualOrPhysical") or "").lower() == "virtual",
               "protocol": str(info.get("BusProtocol") or ""),
               "boot": boot})


def list_volumes() -> list[Volume]:
    """Every mounted volume diskutil can describe. Network shares (which it cannot) are left out."""
    volumes = []
    for root in mount_points():
        info = disk_info(root)
        if info:
            volumes.append(volume_from_info(root, info))
    return volumes


def is_card(volume: Volume) -> bool:
    facts = volume.facts
    if facts.get("boot") or facts.get("virtual"):        # this Mac's disk, a mounted .dmg
        return False
    label = volume.label.lower()
    if "google drive" in label or label.startswith("googledrive"):
        return False
    if volume.label.upper() in IGNORED_LABELS:
        return False
    if volume.drive_type == DRIVE_REMOVABLE:
        return True
    return any(os.path.isdir(os.path.join(volume.root, m)) for m in CARD_MARKERS)


# ------------------------------------------------------------- USB devices

_LUN_KEY = "SCSI Logical Unit Number"


def parse_usb(data) -> dict[str, dict]:
    """{'disk4': {'device_key', 'lun', 'product'}} from `ioreg -a -r -c IOUSBHostDevice -l`.

    A camera with two card slots is one USB device with two logical units, each its own whole disk.
    The device key is the same for both (location + serial), like the Windows PNP id without its LUN.
    Written from the I/O Registry's documented layout rather than every camera there is, so it is
    forgiving: whatever it cannot place is simply left out, and that card is listed on its own.
    """
    disks: dict[str, dict] = {}

    def walk(node, device: dict | None, lun) -> None:
        if not isinstance(node, dict):
            return
        if node.get("IOObjectClass") == "IOUSBHostDevice" or ("idProduct" in node and "locationID" in node):
            serial = str(node.get("USB Serial Number") or node.get("kUSBSerialNumberString") or "")
            location = node.get("locationID")
            key = f"usb:{location:08x}" if isinstance(location, int) else "usb:"
            device = {"device_key": f"{key}:{serial}" if serial else key,
                      "product": str(node.get("USB Product Name") or node.get("kUSBProductString") or "").strip(),
                      "count": 0}
            lun = None
        if device is not None:
            if isinstance(node.get(_LUN_KEY), int):
                lun = node[_LUN_KEY]
            elif "LogicalUnit" in str(node.get("IOObjectClass", "")) and isinstance(node.get("IOUnit"), int):
                lun = node["IOUnit"]
            bsd = node.get("BSD Name")
            if bsd and node.get("Whole") and bsd not in disks:
                disks[bsd] = {"device_key": device["device_key"], "product": device["product"],
                              "lun": lun if isinstance(lun, int) else device["count"]}
                device["count"] += 1
        for child in node.get("IORegistryEntryChildren") or ():
            walk(child, device, lun)

    for root in data if isinstance(data, list) else [data]:
        walk(root, None, None)
    return {bsd: d for bsd, d in disks.items() if d["device_key"] != "usb:"}


def query_usb(timeout: float = 20.0) -> dict[str, dict]:
    """Which USB device each whole disk sits on. Empty dict on failure."""
    return parse_usb(_plist(_run(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l", "-w0"], timeout)))


def find_cards() -> list[Volume]:
    cards = [v for v in list_volumes() if is_card(v)]
    if cards:
        usb = query_usb()
        for v in cards:
            d = usb.get(v.facts.get("whole", ""))
            if d:
                v.device_key, v.lun = d["device_key"], d["lun"]
                v.model = v.model or d["product"]
    return cards


# ------------------------------------------------------------------- eject

def ejectable(volume: Volume) -> bool:
    """A card's disk, as opposed to anything that must never be ejected by CardCopy: this Mac's own disk,
    a mounted disk image, or an internal fixed disk. Card readers in USB-C hubs often call their cards
    "fixed" rather than "removable", so an external disk counts too (CardCopy only ever lists volumes
    that look like camera cards, and the window keeps the Raw and backup folders' disks out of it)."""
    facts = volume.facts
    if facts.get("boot") or facts.get("virtual"):
        return False
    return volume.drive_type == DRIVE_REMOVABLE or bool(facts.get("ejectable")) or not facts.get("internal", True)


def _holder(text: str) -> str:
    """The app diskutil says is keeping a disk busy ("dissented by PID 812 (Photos)"), or ''."""
    m = re.search(r"dissented by PID (\d+)(?: \(([^)]+)\))?", text)
    if not m:
        return ""
    if m.group(2):
        return os.path.basename(m.group(2))
    out = _run(["ps", "-p", m.group(1), "-o", "comm="], 5).decode("utf-8", "replace").strip()
    return os.path.basename(out) or f"process {m.group(1)}"


def eject_volume(root: str, tries: int = 4) -> tuple[bool, str]:
    """Safely remove one card: unmount it and eject its disk, like Finder's Eject. Nothing is written
    to the card beyond what unmounting itself does. Returns (ok, message).

    Hard rule: never this Mac's own disk, an internal disk, a disk image or a network share. Never
    forced either: a card something is still reading stays mounted, and the message says what has it.
    """
    import time
    if os.environ.get("CARDCOPY_NO_DEVICES"):
        return False, "ejecting is switched off"
    if not os.path.ismount(root):
        return True, "already ejected"                     # went with the other card in the same reader
    info = disk_info(root)
    if not info:
        return False, "macOS has no disk for it (a network share?), left alone"
    volume = volume_from_info(root, info)
    if not ejectable(volume):
        return False, "not a card's disk, left alone"
    whole = volume.facts["whole"] or volume.facts["bsd"]
    if not re.fullmatch(r"disk\d+(s\d+)?", whole):
        return False, "not a disk"
    text = ""
    for attempt in range(tries):                 # Spotlight or a preview may still be reading: give it a moment
        try:
            out = subprocess.run(["diskutil", "eject", whole], capture_output=True, text=True, timeout=90,
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"diskutil did not answer ({exc})"
        if out.returncode == 0:
            return True, "ejected, safe to remove"
        if not os.path.ismount(root):
            return True, "ejected, safe to remove"         # the volume went even though diskutil complained
        text = f"{out.stdout}\n{out.stderr}".strip()
        if attempt + 1 < tries:
            time.sleep(1.5)
    holder = _holder(text)
    if holder:
        return False, f"{holder} is using it: quit {holder} (or close its window) and eject again"
    if re.search(r"dissent|in use|busy|could not be unmounted", text, re.I):
        return False, "still in use by another app (close Finder windows or players showing it)"
    lines = text.splitlines()
    return False, (lines[-1] if lines else "") or "macOS would not eject it"
