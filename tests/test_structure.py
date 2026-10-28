"""Where folders go: the Raw folders, Cam folders, and audio kept with the video."""
import os

from cardcopy.structure import build_plan, cam_folders


def rel(plan, base):
    return [os.path.relpath(f, base).replace(os.sep, "/") for f in plan.folders]


def test_audio_in_its_own_raw_folder_by_default(tmp_path):
    plan = build_plan(str(tmp_path), "bob", ["video", "audio"], {"video": 2, "audio": 1})
    assert rel(plan, tmp_path) == ["Raw Video/bob", "Raw Video/bob/Cam 1", "Raw Video/bob/Cam 2",
                                   "Raw Audio/bob", "Raw Audio/bob/Cam 1"]


def test_audio_inside_the_projects_raw_video_folder(tmp_path):
    plan = build_plan(str(tmp_path), "bob", ["video", "audio"], {"video": 2, "audio": 1}, audio_in_video=True)
    assert rel(plan, tmp_path) == ["Raw Video/bob", "Raw Video/bob/Cam 1", "Raw Video/bob/Cam 2", "Raw Video/bob/Audio"]
    assert plan.dest("audio", 1) == os.path.join(str(tmp_path), "Raw Video", "bob", "Audio")
    assert plan.dest("video", 2) == os.path.join(str(tmp_path), "Raw Video", "bob", "Cam 2")


def test_several_recorders_get_numbered_audio_folders(tmp_path):
    plan = build_plan(str(tmp_path), "bob", ["audio"], {"audio": 2}, audio_in_video=True)
    assert rel(plan, tmp_path) == ["Raw Video/bob", "Raw Video/bob/Audio 1", "Raw Video/bob/Audio 2"]
    assert cam_folders("audio", 1, True) == ["Audio"] and cam_folders("video", 2, True) == ["Cam 1", "Cam 2"]


def test_nested_project_and_renamed_raw_folders(tmp_path):
    plan = build_plan(str(tmp_path), "bob/wedding", ["audio"], 1, {"video": "Video"}, audio_in_video=True)
    assert plan.dest("audio", 1) == os.path.join(str(tmp_path), "Video", "bob", "wedding", "Audio")
