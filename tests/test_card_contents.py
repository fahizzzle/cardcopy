"""What comes off a card, card by card, as the cameras and recorders actually lay them out.

By default only the originals are copied: RAW photos, video clips and recordings. Never the thumbnails,
the low-resolution proxies (Sony SUB, GoPro LRV, DJI LRF, a Proxy folder), the camera's housekeeping,
or what a Mac leaves on any card it has mounted (._ files, .DS_Store, .Spotlight-V100 ...). JPG/HEIF
and clip XML only when "Also copy" asks for them. CI runs this on macOS as well as Windows.
"""
import os

import pytest

from cardcopy.copier import walk_files
from cardcopy.identify import CopyOptions, tag_files

MAC_LEFTOVERS = [".DS_Store", "._DCIM", ".Spotlight-V100/Store-V2/0001/store.db", ".fseventsd/fseventsd-uuid",
                 ".Trashes/501/old.JPG", ".TemporaryItems/folders.501/x", "System Volume Information/IndexerVolumeGuid"]

CARDS = {
    "Sony A7 IV": {
        "copy": ["DCIM/100MSDCF/DSC00001.ARW", "DCIM/100MSDCF/DSC00004.ARW", "PRIVATE/M4ROOT/CLIP/C0001.MP4"],
        "jpeg": ["DCIM/100MSDCF/DSC00001.JPG", "DCIM/100MSDCF/DSC00002.HIF"],
        "xml": ["PRIVATE/M4ROOT/CLIP/C0001M01.XML"],
        "never": ["DCIM/100MSDCF/._DSC00001.ARW", "PRIVATE/M4ROOT/THMBNL/C0001T01.JPG",
                  "PRIVATE/M4ROOT/SUB/C0001S03.MP4", "PRIVATE/M4ROOT/MEDIAPRO.XML", "PRIVATE/M4ROOT/STATUS.BIN",
                  "PRIVATE/SONY/SONYCARD.IND", "AVF_INFO/AVIN0001.BNP", "AVF_INFO/AVIN0001.INP"],
    },
    "Sony FX6 (XDCAM)": {
        "copy": ["XDROOT/Clip/0001.MXF"],
        "never": ["XDROOT/Sub/0001S03.MXF", "XDROOT/General/Sony/XDCAM.XML", "XDROOT/Clip/0001M01.XML_"],
    },
    "Canon R5": {
        "copy": ["DCIM/100EOSR5/IMG_0001.CR3", "DCIM/100EOSR5/MVI_0003.MP4", "DCIM/100EOSR5/A001C001.CRM"],
        "jpeg": ["DCIM/100EOSR5/IMG_0002.JPG"],
        "never": ["DCIM/100EOSR5/MVI_0003.THM", "DCIM/CANONMSC/M0100.CTG", "MISC/GPS/000001.LOG"],
    },
    "Nikon Z9": {
        "copy": ["DCIM/100NCZ_9/DSC_0001.NEF", "DCIM/100NCZ_9/DSC_0002.NEV", "DCIM/100NCZ_9/DSC_0003.MOV"],
        "jpeg": ["DCIM/100NCZ_9/DSC_0001.JPG"],
        "never": ["NIKON001.DSC"],
    },
    "Fujifilm X-T5": {
        "copy": ["DCIM/100_FUJI/DSCF0001.RAF", "DCIM/100_FUJI/DSCF0002.MOV"],
        "jpeg": ["DCIM/100_FUJI/DSCF0001.JPG"],
    },
    "Panasonic GH6": {
        "copy": ["DCIM/100_PANA/P1000001.RW2", "DCIM/100_PANA/P1000002.MOV", "PRIVATE/AVCHD/BDMV/STREAM/00000.MTS"],
        "never": ["PRIVATE/AVCHD/BDMV/INDEX.BDM", "PRIVATE/AVCHD/BDMV/CLIPINF/00000.CPI",
                  "PRIVATE/PANA_GRP/PROXY/P1000002.MP4"],
    },
    "GoPro": {
        "copy": ["DCIM/100GOPRO/GX010001.MP4", "DCIM/100GOPRO/GOPR0003.GPR"],
        "jpeg": ["DCIM/100GOPRO/GOPR0002.JPG"],
        "never": ["DCIM/100GOPRO/GL010001.LRV", "DCIM/100GOPRO/GX010001.THM", "MISC/version.txt"],
    },
    "DJI drone": {
        "copy": ["DCIM/100MEDIA/DJI_0001.DNG", "DCIM/100MEDIA/DJI_0002.MP4"],
        "jpeg": ["DCIM/100MEDIA/DJI_0001.JPG"],
        "never": ["DCIM/100MEDIA/DJI_0002.SRT", "DCIM/100MEDIA/DJI_0002.LRF"],
    },
    "DJI Osmo Pocket 3": {
        "copy": ["DCIM/DJI_001/DJI_20261023140102_0001_D.MP4"],
        "never": ["DCIM/DJI_001/DJI_20261023140102_0001_D.LRF"],
    },
    "Blackmagic Pocket": {
        "copy": ["A001_10231402_C001.braw"],
        "never": ["Proxy/A001_10231402_C001.mp4"],
    },
    "Insta360": {
        "copy": ["DCIM/Camera01/VID_20261023_140102_00_001.insv"],
        "jpeg": ["DCIM/Camera01/IMG_20261023_140200_00_002.insp"],
        "never": ["DCIM/Camera01/LRV_20261023_140102_01_001.lrv"],
    },
    "Zoom F6": {
        "copy": ["FOLDER01/261023_001/261023_001_Tr1.WAV", "FOLDER01/261023_001/261023_001_TrLR.WAV"],
        "never": ["F6_PATCH.TXT", "ZOOM_F6.SYS"],
    },
    "DJI Mic 2": {
        "copy": ["DJI_Audio_001/DJI_01_20261023_140102.WAV"],
        "never": ["DJI_Audio_001/DJI_01_20261023_140102.LOG"],
    },
}


def _card(tmp_path, name: str, layout: dict) -> str:
    root = tmp_path / name.replace(" ", "_").replace("(", "").replace(")", "")
    for group in ("copy", "jpeg", "xml", "never"):
        for rel in layout.get(group, []):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 64)
    for rel in MAC_LEFTOVERS:                                  # every card a Mac has had mounted
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mac")
    return str(root)


def _copied(root: str, options: CopyOptions) -> set[str]:
    files = tag_files(list(walk_files(root)))                  # exactly what a copy (copy_jobs) chooses from
    return {f.rel.replace(os.sep, "/") for f in files if f.kind and options.wants(f.kind)}


@pytest.mark.parametrize("name", list(CARDS))
def test_only_the_originals_by_default(tmp_path, name):
    layout = CARDS[name]
    assert _copied(_card(tmp_path, name, layout), CopyOptions()) == set(layout["copy"])


@pytest.mark.parametrize("name", list(CARDS))
def test_jpg_and_clip_xml_only_when_asked(tmp_path, name):
    layout = CARDS[name]
    root = _card(tmp_path, name, layout)
    assert _copied(root, CopyOptions(jpeg=True)) == set(layout["copy"]) | set(layout.get("jpeg", []))
    assert _copied(root, CopyOptions(jpeg=True, xml=True)) == \
        set(layout["copy"]) | set(layout.get("jpeg", [])) | set(layout.get("xml", []))
