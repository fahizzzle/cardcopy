"""CardCopy: copy camera SD cards into a project folder structure."""

__version__ = "1.20.0"


def _build() -> str:
    """Which build this is, when the build wrote it down (the Mac build: the git commit it came from)."""
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "build.txt"),
                  encoding="utf-8") as f:
            return f.read().strip()[:40]
    except OSError:
        return ""


BUILD = _build()
