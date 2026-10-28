"""Which cards make up one device: grouping by body, by USB device, and keeping a recorder apart."""
from cardcopy.cameras import Card, group_cards
from cardcopy.devices import DRIVE_REMOVABLE, Volume
from cardcopy.identify import CardInfo

READER = "usb:01100000:SDREADER"           # one USB card reader / hub with an SD and a microSD slot


def card(root, lun=0, dev=READER, make="", model="", body="", raw=0, video=0, audio=0, scanned=True):
    volume = Volume(root=root, label="Untitled", serial=root, drive_type=DRIVE_REMOVABLE, device_key=dev, lun=lun)
    info = CardInfo(make=make, model=model, body_id=body, raw_size=raw, raws=1 if raw else 0,
                    video_size=video, videos=1 if video else 0, audio_size=audio, audios=1 if audio else 0,
                    scanned=scanned)
    return Card(volume, info)


def names(cameras):
    return sorted((cam.default_name, [c.volume.root for c in cam.cards]) for cam in cameras)


def test_recorder_card_in_the_same_reader_as_a_camera_card_stays_apart():
    cams = group_cards([card("/Volumes/SD", 0, make="Sony", model="ILME-FX3", body="5051234", video=10**9),
                        card("/Volumes/MICRO", 1, make="ZOOM", model="ZOOM F3", audio=10**8)])
    assert names(cams) == [("FX3", ["/Volumes/SD"]), ("Zoom F3", ["/Volumes/MICRO"])]


def test_a_recorder_that_names_nobody_is_still_kept_apart_and_called_a_recorder():
    cams = group_cards([card("/Volumes/SD", 0, make="Sony", model="ILME-FX3", body="5051234", video=10**9),
                        card("/Volumes/MICRO", 1, audio=10**8)])
    assert names(cams) == [("Audio recorder", ["/Volumes/MICRO"]), ("FX3", ["/Volumes/SD"])]


def test_a_cameras_blank_second_slot_still_joins_it():
    cams = group_cards([card("/Volumes/A", 0, make="Sony", model="ILCE-7M4", body="9", raw=10**9),
                        card("/Volumes/B", 1)])
    assert names(cams) == [("A7 IV", ["/Volumes/A", "/Volumes/B"])]


def test_second_slot_from_the_same_model_without_a_serial_joins():
    cams = group_cards([card("/Volumes/A", 0, make="Sony", model="ILCE-7M4", body="9", raw=10**9),
                        card("/Volumes/B", 1, make="Sony", model="ILCE-7M4", raw=10**8)])
    assert len(cams) == 1 and len(cams[0].cards) == 2


def test_a_card_another_model_wrote_does_not_join():
    cams = group_cards([card("/Volumes/A", 0, make="Sony", model="ILCE-7M4", body="9", raw=10**9),
                        card("/Volumes/B", 1, make="FUJIFILM", model="X-T4", raw=10**8)])
    assert len(cams) == 2


def test_before_the_card_is_read_it_sits_with_the_camera_then_moves_out():
    camera = card("/Volumes/SD", 0, make="Sony", model="ILME-FX3", body="5051234", video=10**9)
    unread = card("/Volumes/MICRO", 1, scanned=False)
    assert len(group_cards([camera, unread])) == 1
    unread.info.audio_size, unread.info.audios, unread.info.scanned = 10**8, 3, True
    assert len(group_cards([camera, unread])) == 2


def test_loose_cards_of_one_kind_keep_the_plain_device_identity():
    cams = group_cards([card("/Volumes/A", 0, model="ZOOM F6", audio=1), card("/Volumes/B", 1, model="ZOOM F6", audio=1)])
    assert [cam.identity for cam in cams] == [f"usb:{READER}"]


def test_camera_files_left_on_a_recorders_card_do_not_make_it_the_cameras():
    """A microSD once in the FX3 keeps its MEDIAPRO.XML (the FX3's body id) after the recorder fills it."""
    cams = group_cards([card("/Volumes/SD", 0, make="Sony", model="ILME-FX3", body="5051234", video=10**9),
                        card("/Volumes/MICRO", 1, make="Sony", model="ILME-FX3", body="5051234", audio=10**8)])
    assert names(cams) == [("Audio recorder", ["/Volumes/MICRO"]), ("FX3", ["/Volumes/SD"])]


def test_recordings_never_join_a_camera_even_on_another_device():
    cams = group_cards([card("/Volumes/SD", 0, dev="usb:cam", make="Sony", model="ILME-FX3", body="1", video=10**9),
                        card("/Volumes/MICRO", 0, dev="usb:reader", make="Sony", model="ILME-FX3", body="1", audio=10**8)])
    assert len(cams) == 2


def test_every_dji_mic_and_other_wireless_mics_are_audio():
    from cardcopy.cameras import default_kind
    for name in ("DJI Mic", "DJI MIC 2", "DJI_MIC2", "DJIMIC", "DJI Mic Mini", "DJI Mic 3", "DJI Mic2 TX",
                 "Wireless GO II", "RODE Wireless PRO", "Hollyland Lark M2", "Saramonic Blink500 B2", "ZOOM F3"):
        assert default_kind(name) == "audio", name
    for name in ("DJI", "Osmo Action 4", "FC3411", "ILME-FX3"):           # DJI's cameras and drones stay video
        assert default_kind(name) == "video", name


def test_a_card_of_nothing_but_sound_is_audio_whatever_it_says():
    from cardcopy.cameras import default_kind
    assert default_kind("DJI", audio_bytes=10**8) == "audio"              # a DJI Mic writes "DJI" in its files
    assert default_kind("DJI", video_bytes=10**9, audio_bytes=10**6) == "video"   # an Osmo with some sound


def test_a_dji_mic_card_in_the_cameras_reader_gets_its_own_tile_and_name():
    mic = card("/Volumes/DJI_MIC2", 1, make="DJI", model="DJI", audio=10**8)
    mic.volume.label = "DJI_MIC2"
    cams = group_cards([card("/Volumes/SD", 0, make="Sony", model="ILME-FX3", body="5051234", video=10**9), mic])
    assert names(cams) == [("DJI Mic 2", ["/Volumes/DJI_MIC2"]), ("FX3", ["/Volumes/SD"])]


def test_tidy_device_names():
    from cardcopy.cameras import _tidy
    assert [_tidy(n) for n in ("DJI_MIC2", "DJI MIC MINI", "dji mic 2 TX", "ZOOM_F6")] == \
        ["DJI Mic 2", "DJI Mic Mini", "DJI Mic 2 TX", "ZOOM F6"]
