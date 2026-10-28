"""CardCopy: copy camera SD cards into a project folder structure."""

__version__ = "1.21.2"


def _build_info() -> dict:
    """What the build wrote down about itself (the Mac build: assets/build.json). {} when run from source.

        {"number": 57, "commit": "40ff49d", "channel": "preview"}

    number grows with every build, so two builds of one version can be told apart by the update check;
    channel "preview" also looks for updates in the mac-preview pre-release (see updates.feed_urls).
    """
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "build.json"),
                  encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


_INFO = _build_info()
BUILD = str(_INFO.get("commit", ""))[:40]          # the git commit it was built from
try:
    BUILD_NUMBER = int(_INFO.get("number") or 0)
except (TypeError, ValueError):
    BUILD_NUMBER = 0
CHANNEL = str(_INFO.get("channel", ""))


def version_label(version: str = __version__, build: int = BUILD_NUMBER) -> str:
    """'1.20.0 (build 57)', or just '1.20.0' for a build without a number."""
    return f"{version} (build {build})" if build else version
