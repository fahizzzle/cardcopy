"""Write the update feeds for an official release: dist/latest.json (Windows) and the notes in
dist/latest-mac.json (made by the Mac build). Run by the release job of .github/workflows/build.yml.

    python scripts/release_feeds.py v1.20.0 dist

The tag must match cardcopy.__version__, or nothing is published. "What's new" in the app is the first
paragraph of the tag's message (dist/notes.md); the release page shows all of it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

REPO = "https://github.com/fahizzzle/cardcopy"


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(tag: str, dist: str) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "cardcopy", "__init__.py"), encoding="utf-8") as f:
        version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
    if tag != f"v{version}":
        print(f"tag {tag} does not match the app's version {version}: nothing published", file=sys.stderr)
        return 1
    with open(os.path.join(dist, "notes.md"), encoding="utf-8") as f:
        notes = f.read().strip()
    whats_new = re.split(r"\n\s*\n", notes, maxsplit=1)[0].strip()[:600] if notes else ""
    base = f"{REPO}/releases/download/{tag}"
    windows = {"version": version, "url": f"{base}/CardCopy-Setup.exe", "zip": f"{base}/CardCopy-Setup.zip",
               "sha256": sha256(os.path.join(dist, "CardCopy-Setup.zip")), "notes": whats_new}
    with open(os.path.join(dist, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(windows, f, indent=2)
    mac_path = os.path.join(dist, "latest-mac.json")
    with open(mac_path, encoding="utf-8") as f:
        mac = json.load(f)
    if mac.get("version") != version or not mac.get("url", "").startswith(base + "/"):
        print(f"latest-mac.json is not for {tag}: {mac}", file=sys.stderr)
        return 1
    mac["notes"] = whats_new
    with open(mac_path, "w", encoding="utf-8") as f:
        json.dump(mac, f, indent=2)
    print(json.dumps({"latest.json": windows, "latest-mac.json": mac}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
