"""The few AppKit touches Qt has no call for, made through the Objective-C runtime with ctypes.

  unify_titlebar  an empty NSToolbar in the unified style: the title bar grows to the 52 pt of a modern
                  Mac window, so the traffic lights sit level with CardCopy's own toolbar
  add_vibrancy    an NSVisualEffectView (the "sidebar" material) behind the window's content, which
                  shows wherever Qt leaves the window transparent -- the sidebar
  dock_badge      text on the Dock icon ("42%" while copying)

No PyObjC: these are a handful of messages, and ctypes keeps the app free of another native dependency.
Every call is optional: any failure returns False and the window simply keeps its plain look.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

_objc = None


class CGRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("w", ctypes.c_double), ("h", ctypes.c_double)]


def _runtime():
    global _objc
    if _objc is None:
        if sys.platform != "darwin":
            raise OSError("not a Mac")
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return _objc


def _cls(name: str):
    return _runtime().objc_getClass(name.encode())


def send(obj, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """[obj selector:args...] with an exact prototype (required on Apple silicon: objc_msgSend is not variadic)."""
    objc = _runtime()
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(address)
    return fn(obj, objc.sel_registerName(selector.encode()), *args)


def _responds(obj, selector: str) -> bool:
    sel = _runtime().sel_registerName(selector.encode())
    return bool(send(obj, "respondsToSelector:", sel, restype=ctypes.c_bool, argtypes=[ctypes.c_void_p]))


def _nsstring(text: str):
    return send(_cls("NSString"), "stringWithUTF8String:", text.encode(), argtypes=[ctypes.c_char_p])


def _window(widget):
    """The NSWindow behind a shown top-level QWidget (its winId is the NSView Qt draws into)."""
    view = ctypes.c_void_p(int(widget.winId()))
    return view, send(view, "window")


def unify_titlebar(widget) -> bool:
    try:
        view, window = _window(widget)
        if not window:
            return False
        toolbar = send(send(_cls("NSToolbar"), "alloc"), "initWithIdentifier:", _nsstring("CardCopy"),
                       argtypes=[ctypes.c_void_p])
        if _responds(toolbar, "setShowsBaselineSeparator:"):
            send(toolbar, "setShowsBaselineSeparator:", False, restype=None, argtypes=[ctypes.c_bool])
        send(window, "setToolbar:", toolbar, restype=None, argtypes=[ctypes.c_void_p])
        if _responds(window, "setToolbarStyle:"):
            send(window, "setToolbarStyle:", 1, restype=None, argtypes=[ctypes.c_long])   # unified
        send(window, "setTitleVisibility:", 1, restype=None, argtypes=[ctypes.c_long])     # hidden
        send(window, "setTitlebarAppearsTransparent:", True, restype=None, argtypes=[ctypes.c_bool])
        mask = send(window, "styleMask", restype=ctypes.c_ulong)
        if not mask & (1 << 15):                                                         # full-size content view
            send(window, "setStyleMask:", mask | (1 << 15), restype=None, argtypes=[ctypes.c_ulong])
        return True
    except Exception:
        return False


def add_vibrancy(widget, width: int) -> bool:
    """Put the sidebar material behind the left `width` points of the window."""
    try:
        view, window = _window(widget)
        frame_view = send(view, "superview")
        if not (window and frame_view):
            return False
        effect = send(send(_cls("NSVisualEffectView"), "alloc"), "initWithFrame:",
                      CGRect(0, 0, float(width), float(widget.height())), argtypes=[CGRect])
        send(effect, "setMaterial:", 7, restype=None, argtypes=[ctypes.c_long])           # .sidebar
        send(effect, "setBlendingMode:", 0, restype=None, argtypes=[ctypes.c_long])       # .behindWindow
        send(effect, "setState:", 0, restype=None, argtypes=[ctypes.c_long])              # follows the window
        send(effect, "setAutoresizingMask:", 16 | 4, restype=None, argtypes=[ctypes.c_ulong])  # height, fixed width
        send(frame_view, "addSubview:positioned:relativeTo:", effect, -1, view, restype=None,
             argtypes=[ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p])                  # below Qt's view
        return True
    except Exception:
        return False


def dock_badge(text: str) -> bool:
    try:
        app = send(_cls("NSApplication"), "sharedApplication")
        tile = send(app, "dockTile")
        send(tile, "setBadgeLabel:", _nsstring(text) if text else None, restype=None, argtypes=[ctypes.c_void_p])
        return True
    except Exception:
        return False
