"""Which look the window wears: glass.py on Windows, aqua.py on a Mac.

Both modules offer the same names (Panel, PillButton, Toggle, Check, NavButton, ActionButton, STYLE ...),
so the window and the camera tiles are written once. CARDCOPY_THEME=mac shows the Mac look on Windows,
which is how its layout is checked without a Mac to hand (native controls are then only approximated).
"""
from __future__ import annotations

import os
import sys

MAC = sys.platform == "darwin" or os.environ.get("CARDCOPY_THEME") == "mac"

if MAC:
    from .aqua import (ACCENT, ASSETS, GREEN, NAME, STYLE, TEXT, TEXT_SOFT, ActionButton, Backdrop, Check,  # noqa: F401
                       LineEdit, Logo, NavButton, Panel, PillButton, ProgressBar, Sidebar, TitleStrip, Toggle,
                       after_first_show, app_stylesheet, heading, hit_test_border, ink, install, mono_font,
                       nav_caption, progress_badge, setup_window, well_text)
else:
    from .glass import (ACCENT, ASSETS, GREEN, NAME, STYLE, TEXT, TEXT_SOFT, ActionButton, Backdrop, Check,  # noqa: F401
                        LineEdit, Logo, NavButton, Panel, PillButton, ProgressBar, Sidebar, TitleStrip, Toggle,
                        after_first_show, app_stylesheet, heading, hit_test_border, ink, install, mono_font,
                        nav_caption, progress_badge, setup_window, well_text)

COMPUTER = "Mac" if MAC else "PC"                   # "Shut down PC" / "Shut down Mac"
FILE_MANAGER = "Finder" if MAC else "Explorer"
