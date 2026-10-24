"""Finding an update: versions, build numbers, the Mac preview feed, and installing it on a Mac."""
import io
import json
import os
import sys

import pytest

from cardcopy import updates, version_label
from cardcopy.mac import selfupdate as mac_selfupdate

SHA = "a" * 64


def feed(version, build=0, notes="", url="https://example.com/CardCopy-Installer.pkg"):
    return json.dumps({"version": version, "build": build, "url": url, "zip": url, "sha256": SHA, "notes": notes})


def test_a_higher_build_of_the_same_version_is_an_update():
    found = updates.parse(feed("1.20.0", 57), "1.20.0", current_build=52)
    assert found is not None and found.build == 57 and found.label == "1.20.0 (build 57)"
    assert found.can_self_install()


def test_the_same_or_an_older_build_is_not():
    assert updates.parse(feed("1.20.0", 52), "1.20.0", current_build=52) is None
    assert updates.parse(feed("1.20.0", 40), "1.20.0", current_build=52) is None
    assert updates.parse(feed("1.19.0", 99), "1.20.0", current_build=1) is None


def test_windows_feeds_without_builds_work_as_before():
    assert updates.parse(feed("1.20.0"), "1.19.0").label == "1.20.0"
    assert updates.parse(feed("1.19.0"), "1.19.0") is None


def test_a_mac_preview_build_follows_both_feeds(monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    assert updates.feed_urls("preview")[-1] == updates.PREVIEW_URL
    assert updates.PREVIEW_URL not in updates.feed_urls("")


def test_check_offers_the_newest_of_the_feeds(monkeypatch):
    monkeypatch.delenv("CARDCOPY_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("CARDCOPY_UPDATE_URL", raising=False)
    pages = {"https://a/latest-mac.json": feed("1.20.0", 0), "https://b/latest-mac.json": feed("1.20.0", 61)}
    monkeypatch.setattr(updates, "feed_urls", lambda channel="": list(pages) + ["https://missing/latest-mac.json"])

    def urlopen(request, timeout=0, context=None):
        if request.full_url not in pages:
            raise OSError("404")
        return io.BytesIO(pages[request.full_url].encode())
    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)
    found = updates.check("1.20.0", build=57)
    assert found is not None and found.build == 61


def test_version_label():
    assert version_label("1.20.0", 57) == "1.20.0 (build 57)" and version_label("1.20.0", 0) == "1.20.0"


def test_mac_update_needs_the_packaged_app(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_selfupdate.sys, "executable", "/usr/local/bin/python3", raising=False)
    assert mac_selfupdate.app_bundle() == "" and not mac_selfupdate.is_installed()
    monkeypatch.setattr(mac_selfupdate.sys, "executable", "/Applications/CardCopy.app/Contents/MacOS/CardCopy")
    assert mac_selfupdate.app_bundle() == "/Applications/CardCopy.app"


def test_mac_update_leaves_a_runner_that_installs_with_one_password_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_selfupdate, "is_installed", lambda folder=None: True)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    pkg = tmp_path / "CardCopy-1.20.0-61-Setup.pkg"
    pkg.write_bytes(b"xar!")
    runner = mac_selfupdate.apply(str(pkg), run=False)
    text = open(runner, encoding="utf-8").read()
    assert "with administrator privileges" in text and "/usr/sbin/installer -pkg" in text and "/usr/bin/open" in text
    with pytest.raises(ValueError):
        mac_selfupdate.apply(str(tmp_path / "not-a-package.zip"), run=False)


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is a POSIX shell script")
def test_mac_runner_is_valid_shell(tmp_path, monkeypatch):
    import subprocess
    script = tmp_path / "run.sh"
    script.write_text(mac_selfupdate._RUNNER)
    assert subprocess.run(["/bin/sh", "-n", str(script)]).returncode == 0
    assert os.access(str(script), os.R_OK)


@pytest.mark.skipif(sys.platform != "darwin", reason="only a Mac brings its own certificates")
def test_a_mac_trusts_what_macos_trusts():
    context = updates.tls_context()
    assert context is not None and context.verify_mode.name == "CERT_REQUIRED" and context.check_hostname
    assert context.cert_store_stats()["x509_ca"] > 50


def test_windows_keeps_pythons_own_https_checks(monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "win32")
    assert updates.tls_context() is None
