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
