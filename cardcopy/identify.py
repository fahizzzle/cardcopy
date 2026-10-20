"""Work out which camera wrote a card, and what is on it. No Qt in here."""
from __future__ import annotations

import glob
import os
import re
import struct
from dataclasses import dataclass

from .copier import FileEntry, walk_files

IMAGE_EXTS = {".jpg", ".jpeg", ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw",
              ".tif", ".tiff"}   # files read_exif can name the camera from
VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".braw", ".crm", ".r3d"}
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f",
            ".3fr", ".iiq", ".rwl", ".srf", ".sr2"}
JPEG_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".hif", ".tif", ".tiff", ".png"}   # the camera's processed pictures
# Field recorders (Zoom, Tascam, Sound Devices, Zaxcom ...), and the voice memo some cameras write beside a photo.
AUDIO_EXTS = {".wav", ".bwf", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus"}


@dataclass
class CopyOptions:
    """What comes off a card. RAW photos, video clips and audio recordings always do; the rest is opt-in."""
    jpeg: bool = False      # JPG / HEIF pictures shot alongside (or instead of) RAW
    xml: bool = False       # the XML metadata file Sony writes next to every clip

    def wants(self, kind: str) -> bool:
        return kind in ("raw", "video", "audio") or (kind == "jpeg" and self.jpeg) or (kind == "xml" and self.xml)


@dataclass
class CardInfo:
    make: str = ""
    model: str = ""
    body_id: str = ""       # camera body serial / unique id, when the card records one
    files: int = 0
    raws: int = 0
    jpegs: int = 0
    videos: int = 0
    audios: int = 0
    xmls: int = 0
    raw_size: int = 0
    jpeg_size: int = 0
    video_size: int = 0
    audio_size: int = 0
    xml_size: int = 0
    newest: float = 0.0
    scanned: bool = False   # counts are filled in

    def selected(self, options: CopyOptions) -> tuple[int, int]:
        """(files, bytes) that would be copied with these options."""
        count = self.raws + self.videos + self.audios
        size = self.raw_size + self.video_size + self.audio_size
        if options.jpeg:
            count, size = count + self.jpegs, size + self.jpeg_size
        if options.xml:
            count, size = count + self.xmls, size + self.xml_size
        return count, size


# Camera housekeeping that looks like media: clip thumbnails and proxy files.
_NOT_MEDIA_DIRS = {"thmbnl", "sub", "private"}


def classify(rel: str) -> str | None:
    """'raw', 'jpeg', 'video', 'audio' or None for a path relative to the card root (XML needs tag_files)."""
    parts = rel.replace("/", "\\").lower().split("\\")
    ext = os.path.splitext(parts[-1])[1]
    if ext in VIDEO_EXTS:
        return None if "sub" in parts[:-1] else "video"
    if ext in AUDIO_EXTS:
        return None if _NOT_MEDIA_DIRS & set(parts[:-1]) else "audio"
    if ext in RAW_EXTS or ext in JPEG_EXTS:
        if _NOT_MEDIA_DIRS & set(parts[:-1]):
            return None
        return "raw" if ext in RAW_EXTS else "jpeg"
    return None


def tag_files(files: list[FileEntry]) -> list[FileEntry]:
    """Set every entry's kind. A clip's XML is the one beside it whose name starts with the clip's
    (C0001.MP4 -> C0001M01.XML); card-level files such as MEDIAPRO.XML are not clip metadata."""
    clips: dict[str, list[str]] = {}
    for f in files:
        f.kind = classify(f.rel) or ""
        if f.kind == "video":
            folder, name = os.path.split(f.rel.lower())
            clips.setdefault(folder, []).append(os.path.splitext(name)[0])
    for f in files:
        if not f.kind and f.rel.lower().endswith(".xml"):
            folder, name = os.path.split(f.rel.lower())
            if any(name.startswith(stem) for stem in clips.get(folder, ())):
                f.kind = "xml"
    return files


# ---------------------------------------------------------------- Sony XML

def _read_text(path: str, limit: int = 65536) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _attr(text: str, name: str) -> str:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', text)
    return m.group(1).strip() if m else ""


def _from_sony_xml(root: str) -> CardInfo | None:
    """M4ROOT/MEDIAPRO.XML names the body and its unique id; clip sidecars are the fallback.

    Seen on a real FX3 (exFAT card): M4ROOT sits at the card root. Older bodies and SDHC cards
    keep it under PRIVATE. The clip XML's serialNo is a placeholder (4294967295) on some bodies.
    """
    for m4 in (os.path.join(root, "M4ROOT"), os.path.join(root, "PRIVATE", "M4ROOT")):
        text = _read_text(os.path.join(m4, "MEDIAPRO.XML"))
        model, body = _attr(text, "systemKind"), _attr(text, "systemId")
        if not (model and body):
            for xml in sorted(glob.glob(os.path.join(m4, "CLIP", "*.XML")))[:3]:
                m = re.search(r"<Device\b[^>]*>", _read_text(xml))
                if m:
                    model = model or _attr(m.group(0), "modelName")
                    serial = _attr(m.group(0), "serialNo")
                    if serial not in ("", "0", "4294967295"):
                        body = body or serial
                    break
        if model or body:
            return CardInfo(make="Sony", model=model, body_id=body)
    return None


# -------------------------------------------------------------------- EXIF

def _tiff_tags(buf: bytes, base: int) -> dict[int, str]:
    """Make, Model (IFD0) and BodySerialNumber (Exif IFD) from a TIFF block."""
    order = buf[base:base + 2]
    e = "<" if order == b"II" else ">" if order == b"MM" else None
    if e is None:
        return {}
    out: dict[int, str] = {}

    def read_ifd(off: int, wanted: set[int]) -> dict[int, tuple[int, int, bytes]]:
        pos = base + off
        if pos + 2 > len(buf):
            return {}
        (n,) = struct.unpack_from(e + "H", buf, pos)
        found = {}
        for i in range(min(n, 200)):
            p = pos + 2 + i * 12
            if p + 12 > len(buf):
                break
            tag, typ, count = struct.unpack_from(e + "HHI", buf, p)
            if tag in wanted:
                found[tag] = (typ, count, buf[p + 8:p + 12])
        return found

    def text(entry: tuple[int, int, bytes]) -> str:
        typ, count, value = entry
        if typ != 2:
            return ""
        if count <= 4:
            raw = value[:count]
        else:
            (off,) = struct.unpack(e + "I", value)
            raw = buf[base + off:base + off + count]
        return raw.split(b"\0")[0].decode("ascii", "replace").strip()

    try:
        (ifd0,) = struct.unpack_from(e + "I", buf, base + 4)
        tags = read_ifd(ifd0, {0x010F, 0x0110, 0x8769})
        for tag in (0x010F, 0x0110):
            if tag in tags:
                out[tag] = text(tags[tag])
        if 0x8769 in tags:
            (exif_off,) = struct.unpack(e + "I", tags[0x8769][2])
            sub = read_ifd(exif_off, {0xA431})
            if 0xA431 in sub:
                out[0xA431] = text(sub[0xA431])
    except struct.error:
        pass
    return out


def read_exif(path: str) -> CardInfo | None:
    try:
        with open(path, "rb") as f:
            buf = f.read(512 * 1024)
    except OSError:
        return None
    if buf[:2] == b"\xff\xd8":
        i = buf.find(b"Exif\0\0")
        if i < 0:
            return None
        tags = _tiff_tags(buf, i + 6)
    elif buf[:8] == b"FUJIFILM":                       # Fuji RAF: the model is plain text in the header
        model = buf[28:60].split(b"\0")[0].decode("ascii", "replace").strip()
        return CardInfo(make="FUJIFILM", model=model) if model else None
    elif buf[4:12] == b"ftypcrx ":                      # Canon CR3: a TIFF block with make and model sits in box CMT1
        i = buf.find(b"CMT1")
        tags = _tiff_tags(buf, i + 4) if i >= 0 else {}
    else:
        tags = _tiff_tags(buf, 0)
    if not tags:
        return None
    return CardInfo(make=tags.get(0x010F, ""), model=tags.get(0x0110, ""), body_id=tags.get(0xA431, ""))


def _first_image(root: str) -> str | None:
    dcim = os.path.join(root, "DCIM")
    for folder, dirs, names in os.walk(dcim if os.path.isdir(dcim) else root):
        dirs.sort()
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                return os.path.join(folder, name)
    return None


# -------------------------------------------------------------- recorders

def _riff_chunks(buf: bytes, limit: int = 60) -> dict[bytes, bytes]:
    """The chunks of a RIFF/WAVE header: {b'bext': payload, b'LIST': payload, ...}.

    Written from the BWF spec rather than observed on a real recorder, so it is deliberately
    forgiving: a file it cannot read simply leaves the recorder unnamed.
    """
    if buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        return {}
    out: dict[bytes, bytes] = {}
    pos = 12
    for _ in range(limit):
        if pos + 8 > len(buf):
            break
        name, size = buf[pos:pos + 4], int.from_bytes(buf[pos + 4:pos + 8], "little")
        body = buf[pos + 8:pos + 8 + size]
        out.setdefault(name, body)
        if name == b"data":                       # the audio itself: nothing past it is worth reading
            break
        pos += 8 + size + (size & 1)              # chunks are padded to an even length
    return out


def _clean(raw: bytes) -> str:
    return raw.split(b"\0")[0].decode("ascii", "replace").strip()


def read_wav_info(path: str) -> CardInfo | None:
    """Name the recorder that wrote a WAV, from its BWF/RIFF header.

    Broadcast Wave files carry a 'bext' chunk whose Originator field is the machine that recorded
    them ("ZOOM F6", "TASCAM DR-40X", "Sound Devices MixPre-6 II"); plain WAVs sometimes name it in
    a LIST/INFO IPRD (product) or ISFT (software) field instead.
    """
    try:
        with open(path, "rb") as f:
            buf = f.read(128 * 1024)
    except OSError:
        return None
    chunks = _riff_chunks(buf)
    if not chunks:
        return None
    model = ""
    bext = chunks.get(b"bext", b"")
    if len(bext) >= 288:
        model = _clean(bext[256:288])                       # Description[256], then Originator[32]
    if not model:
        info = chunks.get(b"LIST", b"")
        if info[:4] == b"INFO":
            for tag in (b"IPRD", b"ICMT", b"ISFT"):         # product, comment, software
                i = info.find(tag, 4)
                if i >= 0:
                    size = int.from_bytes(info[i + 4:i + 8], "little")
                    model = _clean(info[i + 8:i + 8 + min(size, 64)])
                    if model:
                        break
    if not model:
        return None
    make = model.split()[0]
    return CardInfo(make=make if make.isupper() or make.istitle() else "", model=model)


def _first_audio(root: str) -> str | None:
    """The first recording on the card, preferring the folders recorders actually use."""
    likely = [os.path.join(root, name) for name in ("FOLDER01", "MUSIC", "RECORD", "AUDIO", "SD_CARD")]
    for start in [p for p in likely if os.path.isdir(p)] + [root]:
        for folder, dirs, names in os.walk(start):
            dirs.sort()
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in (".wav", ".bwf"):
                    return os.path.join(folder, name)
    return None


# --------------------------------------------------------------------- API

def identify(root: str) -> CardInfo:
    """Quick look: which camera or recorder does this card belong to?"""
    info = _from_sony_xml(root)
    if info is None or not info.body_id:
        sample = _first_image(root)
        exif = read_exif(sample) if sample else None
        if exif is not None:
            if info is None:
                info = exif
            else:
                info.model = info.model or exif.model
                info.body_id = info.body_id or exif.body_id
    if info is None or not info.model:
        # no camera named the card: an audio recorder writes its name into the WAVs instead
        sample = _first_audio(root)
        heard = read_wav_info(sample) if sample else None
        if heard is not None:
            if info is None:
                info = heard
            else:
                info.make, info.model = info.make or heard.make, info.model or heard.model
    return info or CardInfo()


def scan(root: str, info: CardInfo | None = None) -> tuple[CardInfo, list[FileEntry]]:
    """Full walk: fill in the counts. Returns the file list so the copy can reuse it."""
    info = info or identify(root)
    files = list(walk_files(root))
    tag_files(files)
    info.files = len(files)
    for name in ("raws", "jpegs", "videos", "audios", "xmls",
                 "raw_size", "jpeg_size", "video_size", "audio_size", "xml_size"):
        setattr(info, name, 0)
    for f in files:
        if f.kind:
            setattr(info, f.kind + "s", getattr(info, f.kind + "s") + 1)
            setattr(info, f.kind + "_size", getattr(info, f.kind + "_size") + f.size)
    info.newest = max((f.mtime for f in files if f.kind in ("raw", "jpeg", "video", "audio")), default=0.0)
    info.scanned = True
    return info, files
