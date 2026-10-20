"""Group cards into cameras. No Qt in here."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .copier import FileEntry
from .devices import Volume
from .identify import CardInfo


@dataclass
class Card:
    volume: Volume
    info: CardInfo = field(default_factory=CardInfo)
    files: list[FileEntry] | None = None
    slot: str = ""          # "Card 1" / "Card 2", set by group_cards

    @property
    def key(self) -> str:
        return self.volume.key


# What Sony writes on the card -> what the camera is called.
FRIENDLY_NAMES = {
    "ILME-FX3": "FX3", "ILME-FX3A": "FX3", "ILME-FX30": "FX30", "ILME-FX6": "FX6",
    "ILCE-7M3": "A7 III", "ILCE-7M4": "A7 IV", "ILCE-7M5": "A7 V",
    "ILCE-7RM4": "A7R IV", "ILCE-7RM4A": "A7R IV", "ILCE-7RM5": "A7R V",
    "ILCE-7SM3": "A7S III", "ILCE-7CM2": "A7C II", "ILCE-7CR": "A7CR",
    "ILCE-1": "A1", "ILCE-1M2": "A1 II", "ILCE-9M3": "A9 III",
    "ILCE-6700": "A6700", "ZV-E1": "ZV-E1", "ZV-E10": "ZV-E10",
    "DC-S5": "Lumix S5", "DC-S5M2": "Lumix S5 II", "DC-S5M2X": "Lumix S5 IIX", "DC-S1": "Lumix S1", "DC-S1H": "Lumix S1H",
    "DC-GH5": "Lumix GH5", "DC-GH5M2": "Lumix GH5 II", "DC-GH5S": "Lumix GH5S", "DC-GH6": "Lumix GH6", "DC-GH7": "Lumix GH7",
}


# Model names that mean "this is a video camera", across makes. Anything else with a model name counts as a
# stills camera; the Raw folder drop-down on each camera overrides the guess and is remembered per body.
_VIDEO_MODEL = re.compile(
    r"^(ILME|FX\d|ILCE-7SM|ZV-|PXW|PMW|MPC-|HXR|HDR-|FDR-|NEX-VG|NEX-FS"            # Sony cinema, A7S, vlog, camcorders
    r"|(CANON )?EOS C\d|(CANON )?EOS R5 ?C|(CANON )?XF\d|(CANON )?XA\d|(CANON )?XC\d|VIXIA|LEGRIA"   # Canon
    r"|AG-|AU-|HC-|DC-BGH|DC-BS1|DC-GH|DMC-GH"                                       # Panasonic camcorders, box cams, GH
    r"|HERO|GOPRO|DJI|OSMO|FC\d{3,}|INSTA360|ONE X|ONE R"                           # action cams, drones
    r"|BLACKMAGIC|POCKET CINEMA|BMPCC|URSA|KOMODO|V-RAPTOR|RED |Z ?CAM|E2)"         # cinema cameras
    r"|CINEMA|CAMCORDER", re.I)


# Field recorders. Their name comes from the WAV's BWF header rather than EXIF, but is matched the same way.
# Checked before the video patterns, so a DJI Mic is audio while the rest of DJI stays video.
_AUDIO_MODEL = re.compile(
    r"(ZOOM ?(F|H|M)\d|TASCAM|\bDR-\d{2}|PORTACAPTURE|SOUND ?DEVICES|MIXPRE|SCORPIO|\b7\d{2}T\b"
    r"|ZAXCOM|NOMAD|\bDEVA\b|MARANTZ|\bPMD\d|SONOSAX|CANTAR|AATON"
    r"|R[ØO]DE ?(WIRELESS|NTG|CASTER)|DJI ?MIC|TENTACLE|RECORDER)", re.I)


def default_kind(model: str, photo_bytes: int = 0, video_bytes: int = 0, audio_bytes: int = 0) -> str:
    """'video', 'photo' or 'audio' for a device. The model decides when it is known (an FX3 is a video
    camera even with a few stills on it); a card naming no device goes by what it mostly holds."""
    model = model.strip()
    if model:
        if _AUDIO_MODEL.search(model):
            return "audio"
        return "video" if _VIDEO_MODEL.search(model) else "photo"
    if audio_bytes > photo_bytes and audio_bytes > video_bytes:
        return "audio"
    return "video" if video_bytes > photo_bytes else "photo"


_MAKES = {"NIKON CORPORATION": "Nikon", "NIKON": "Nikon", "FUJIFILM": "Fujifilm", "CANON": "Canon", "SONY": "Sony",
          "PANASONIC": "Panasonic", "OLYMPUS CORPORATION": "Olympus", "OM DIGITAL SOLUTIONS": "OM System",
          "LEICA CAMERA AG": "Leica", "RICOH IMAGING COMPANY, LTD.": "Ricoh", "SIGMA": "Sigma", "DJI": "DJI", "GOPRO": "GoPro",
          "ZOOM": "Zoom", "TASCAM": "Tascam", "SOUND DEVICES": "Sound Devices", "ZAXCOM": "Zaxcom", "RODE": "Rode"}


def friendly_name(model: str, make: str = "") -> str:
    """'ILCE-7M4' -> 'A7 IV', 'NIKON Z 6_2' -> 'Nikon Z 6 II', 'X-T4' + FUJIFILM -> 'Fujifilm X-T4'."""
    model = model.strip()
    if model.upper() in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[model.upper()]
    brand = _MAKES.get(make.strip().upper(), make.strip().title() if make.strip().isupper() else make.strip())
    for shouted, nice in _MAKES.items():
        if model.upper().startswith(shouted + " "):
            model, brand = nice + model[len(shouted):], ""
            break
    model = re.sub(r"_(\d)\b", lambda m: " " + {"2": "II", "3": "III", "4": "IV", "5": "V"}.get(m.group(1), m.group(1)), model)
    if brand and brand.split()[0].upper() not in model.upper():
        model = f"{brand} {model}"
    return model


def split_per_card(cameras: list["Camera"]) -> list["Camera"]:
    """SD card view: one entry per card, still tied to the camera that wrote it."""
    return [Camera(c.identity, c.model, c.default_name, c.name, [card]) for c in cameras for card in c.cards]


@dataclass
class Camera:
    identity: str           # stable key the user's name for it is stored under
    model: str              # as written on the card ("ILCE-7M4"); picks the picture
    default_name: str
    name: str
    cards: list[Card]


def _body_key(card: Card) -> str:
    return f"body:{card.info.model}:{card.info.body_id}" if card.info.body_id else ""


def group_cards(cards: list[Card], names: dict[str, str] | None = None) -> list[Camera]:
    """Cards written by the same body go together; a blank card joins the camera
    it is physically plugged into (same USB device)."""
    names = names or {}
    groups: dict[str, list[Card]] = {}
    by_device: dict[str, str] = {}
    for card in cards:
        key = _body_key(card)
        if key:
            groups.setdefault(key, []).append(card)
            if card.volume.device_key:
                by_device.setdefault(card.volume.device_key, key)
    for card in cards:
        if _body_key(card):
            continue
        dev = card.volume.device_key
        key = by_device.get(dev) or (f"usb:{dev}" if dev else f"vol:{card.volume.key}")
        groups.setdefault(key, []).append(card)

    cameras = []
    for identity, members in groups.items():
        members.sort(key=lambda c: (c.volume.lun if c.volume.lun is not None else 99, c.volume.root))
        for i, card in enumerate(members, 1):
            card.slot = f"Card {i}"
        model = next((c.info.model for c in members if c.info.model), "") \
            or next((c.volume.model for c in members if c.volume.model), "") \
            or members[0].volume.label or "Unknown camera"
        make = next((c.info.make for c in members if c.info.make), "")
        named = next((c.info.model for c in members if c.info.model), "")       # read from the card itself
        cameras.append(Camera(identity, model, friendly_name(named, make) if named else model,
                              names.get(identity, ""), members))

    # Four identical bodies: tell them apart until the user names them.
    counts: dict[str, int] = {}
    for cam in cameras:
        counts[cam.default_name] = counts.get(cam.default_name, 0) + 1
    for cam in cameras:
        if counts[cam.default_name] > 1:
            body = next((c.info.body_id for c in cam.cards if c.info.body_id), "")
            suffix = body[-4:] if body else cam.cards[0].volume.letter
            cam.default_name = f"{cam.default_name} ({suffix})"
        cam.name = cam.name or cam.default_name
    cameras.sort(key=lambda c: c.name.lower())
    return cameras
