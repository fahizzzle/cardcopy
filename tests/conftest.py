import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Never a real card, a real shutdown, the network or the user's settings, whatever a test does.
os.environ.setdefault("CARDCOPY_NO_DEVICES", "1")
os.environ.setdefault("CARDCOPY_NO_SHUTDOWN", "1")
os.environ.setdefault("CARDCOPY_NO_UPDATE_CHECK", "1")
os.environ.setdefault("CARDCOPY_ASSUME_ONLINE", "1")
os.environ.setdefault("CARDCOPY_NO_ANIMATION", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
