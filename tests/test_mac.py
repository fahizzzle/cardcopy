"""The macOS answers (diskutil, ioreg, nettop, CloudStorage), fed what those tools print.

They run on any platform: nothing here calls the real tools, so Windows CI checks the Mac logic too.
"""
import os
import plistlib

import pytest

from cardcopy import power
from cardcopy.devices import DRIVE_FIXED, DRIVE_REMOVABLE, Volume
from cardcopy.mac import devices as mac_devices
from cardcopy.mac import gdrive as mac_gdrive
from cardcopy.mac import power as mac_power

SD_CARD = {"VolumeName": "Untitled", "VolumeUUID": "0E2C1D5B-1111-2222-3333-444455556666",
           "DeviceIdentifier": "disk4s1", "ParentWholeDisk": "disk4", "Internal": False, "RemovableMedia": True,
           "Ejectable": True, "MediaName": "Sony ILCE-7M4 Media", "BusProtocol": "USB", "VirtualOrPhysical": "Physical"}


@pytest.fixture(autouse=True)
def not_the_boot_disk(monkeypatch):
    """tmp_path stands in for a card, but on a Mac it sits on the Mac's own disk, which is never a card."""
    monkeypatch.setattr(mac_devices, "on_boot_disk", lambda root: False)


def test_the_macs_own_disk_is_never_a_card(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_devices, "on_boot_disk", lambda root: True)
    assert not mac_devices.is_card(mac_devices.volume_from_info(str(tmp_path), SD_CARD))


def test_volume_from_diskutil(tmp_path):
    v = mac_devices.volume_from_info(str(tmp_path), SD_CARD)
    assert (v.label, v.drive_type, v.model, v.facts["whole"]) == ("Untitled", DRIVE_REMOVABLE, "Sony ILCE-7M4", "disk4")
    assert v.serial.startswith("0E2C1D5B")


def test_what_counts_as_a_card(tmp_path):
    def vol(**info):
        return mac_devices.volume_from_info(str(tmp_path), {**SD_CARD, **info})
    assert mac_devices.is_card(vol())
    assert not mac_devices.is_card(vol(VirtualOrPhysical="Virtual"))                  # a mounted .dmg
    assert not mac_devices.is_card(vol(VolumeName="PMHOME"))                          # Sony's utility drive
    ssd = vol(RemovableMedia=False, Removable=False)
    assert ssd.drive_type == DRIVE_FIXED and not mac_devices.is_card(ssd)              # an external SSD ...
    (tmp_path / "DCIM").mkdir()
    assert mac_devices.is_card(ssd)                                                    # ... unless it holds a DCIM


def test_parse_usb_groups_two_slots_of_one_camera():
    def disk(bsd, lun):
        return {"IOObjectClass": "IOSCSILogicalUnitNub", "SCSI Logical Unit Number": lun, "IORegistryEntryChildren": [
            {"IOObjectClass": "IOMedia", "BSD Name": bsd, "Whole": True, "IORegistryEntryChildren": [
                {"IOObjectClass": "IOMedia", "BSD Name": bsd + "s1", "Whole": False}]}]}
    camera = {"IOObjectClass": "IOUSBHostDevice", "locationID": 0x01100000, "USB Serial Number": "5051234",
              "USB Product Name": "ILCE-7M4", "idProduct": 3, "IORegistryEntryChildren": [
                  {"IOObjectClass": "IOUSBMassStorageDriver", "IORegistryEntryChildren": [disk("disk5", 1), disk("disk4", 0)]}]}
    reader = {"IOObjectClass": "IOUSBHostDevice", "locationID": 0x02100000, "USB Product Name": "SD Reader",
              "idProduct": 9, "IORegistryEntryChildren": [disk("disk6", 0)]}
    found = mac_devices.parse_usb(plistlib.loads(plistlib.dumps([camera, reader])))
    assert found["disk4"]["device_key"] == found["disk5"]["device_key"] != found["disk6"]["device_key"]
    assert (found["disk4"]["lun"], found["disk5"]["lun"]) == (0, 1)
    assert "disk4s1" not in found and found["disk4"]["product"] == "ILCE-7M4"


def test_parse_usb_survives_junk():
    assert mac_devices.parse_usb(None) == {} and mac_devices.parse_usb([{"nothing": 1}]) == {}


def test_eject_refuses_anything_but_removable_media(monkeypatch, tmp_path):
    monkeypatch.delenv("CARDCOPY_NO_DEVICES", raising=False)
    ran = []
    monkeypatch.setattr(mac_devices.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(mac_devices, "disk_info", lambda root: {**SD_CARD, "RemovableMedia": False, "Removable": False})
    ok, why = mac_devices.eject_volume(str(tmp_path))
    assert not ok and "left alone" in why and ran == []


def test_eject_runs_diskutil_on_the_whole_disk(monkeypatch, tmp_path):
    monkeypatch.delenv("CARDCOPY_NO_DEVICES", raising=False)
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "Disk disk4 ejected", ""
    monkeypatch.setattr(mac_devices.subprocess, "run", lambda args, **k: calls.append(args) or Done())
    monkeypatch.setattr(mac_devices, "disk_info", lambda root: SD_CARD)
    assert mac_devices.eject_volume(str(tmp_path)) == (True, "ejected, safe to remove")
    assert calls == [["diskutil", "eject", "disk4"]]


def test_a_card_is_called_by_its_volume_name_on_a_mac(monkeypatch):
    from cardcopy import devices
    monkeypatch.setattr(devices.sys, "platform", "darwin")
    assert Volume(root="/Volumes/Untitled 1", label="Untitled").letter == "Untitled 1"
    assert Volume(root="/Volumes/x", drive_type=-1).letter == ""          # a folder added by hand


NETTOP = """time,,bytes_in,bytes_out,
15:01:02.123456,launchd.1,0,0,
15:01:02.123456,Google Drive.812,1200,350000,
15:01:02.123456,Google Drive Hel.815,10,20,
15:01:02.123456,Safari.900,999999,999999,
"""


def test_parse_nettop_sums_google_drive():
    assert mac_power.parse_nettop(NETTOP) == 1200 + 350000 + 10 + 20
    assert mac_power.parse_nettop("time,,bytes_in,bytes_out,\n1,Safari.1,5,5,\n") is None


def test_drive_watcher_never_calls_an_unreadable_drive_finished():
    clock = iter(range(0, 10000, 30))
    watcher = power.DriveWatcher(sample=lambda: power.UNMEASURABLE, clock=lambda: next(clock),
                                 quiet_seconds=60, check_online=lambda: True)
    for _ in range(20):
        watcher.poll()
    assert watcher.running and not watcher.measurable and not watcher.quiet()


def test_keep_awake_uses_caffeinate_tied_to_our_pid(monkeypatch):
    started = []

    class Proc:
        def __init__(self, args, **kw):
            started.append(args)
            self.done = None

        def poll(self):
            return self.done

        def terminate(self):
            self.done = 0
    monkeypatch.setattr(mac_power.subprocess, "Popen", Proc)
    monkeypatch.setattr(mac_power, "_caffeinate", None)
    assert mac_power.keep_awake(True) and mac_power.keep_awake(True)
    assert len(started) == 1 and started[0][:1] == ["caffeinate"] and str(os.getpid()) in started[0]
    assert mac_power.keep_awake(False) and mac_power._caffeinate is None


def test_shutdown_permission_denied_says_where_to_allow_it(monkeypatch):
    monkeypatch.delenv("CARDCOPY_NO_SHUTDOWN", raising=False)
    monkeypatch.setattr(mac_power, "_osascript",
                        lambda script, timeout: (False, "execution error: Not authorized to send Apple events (-1743)"))
    ok, why = mac_power.prepare_shutdown()
    assert not ok and "Automation" in why


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    monkeypatch.setattr(mac_gdrive.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path), 1))
    my_drive = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com" / "My Drive"
    my_drive.mkdir(parents=True)
    return tmp_path, my_drive


def test_google_drive_on_a_mac(mac_home):
    home, my_drive = mac_home
    assert mac_gdrive.default_raw_folder() == str(my_drive / "Raw")
    assert mac_gdrive.is_drive_path(str(my_drive / "Raw" / "Raw Video"))
    assert not mac_gdrive.is_drive_path(str(home / "Movies"))
    free, where = mac_gdrive.effective_free_space(str(my_drive))
    assert free > 0 and where


def test_same_volume(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert mac_gdrive.same_volume(str(tmp_path / "a"), str(tmp_path / "b"))
