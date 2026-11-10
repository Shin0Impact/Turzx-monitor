"""Make the tray menu look and behave like a Windows 11 menu.

pystray draws a plain Win32 popup menu, which is always light and opens to the *left* of the cursor.
Two small fixes: follow the system dark/light setting (uxtheme's undocumented but long-stable
SetPreferredAppMode), and open to the right of the cursor like the taskbar's own menus.
Does nothing on other systems.
"""

from __future__ import annotations

import ctypes
import logging
import os

log = logging.getLogger(__name__)

TPM_RIGHTALIGN = 0x0008
ALLOW_DARK = 1  # follow the system setting


def open_right(flags: int) -> int:
    """TrackPopupMenuEx flags with the menu's left edge at the cursor instead of its right edge."""
    return flags & ~TPM_RIGHTALIGN


def apply() -> None:
    if os.name != "nt":
        return
    try:
        _follow_system_theme()
        _open_right_of_cursor()
    except Exception:  # cosmetic only: never stop the tray from starting
        log.exception("could not restyle the tray menu")


def _follow_system_theme() -> None:
    uxtheme = ctypes.WinDLL("uxtheme")
    set_preferred_app_mode = uxtheme[135]  # exported by ordinal only
    set_preferred_app_mode.argtypes = [ctypes.c_int]
    set_preferred_app_mode(ALLOW_DARK)
    uxtheme[136]()  # FlushMenuThemes


def _open_right_of_cursor() -> None:
    from pystray._util import win32

    original = win32.TrackPopupMenuEx

    def track_popup_menu(menu, flags, x, y, window, params):
        return original(menu, open_right(flags), x, y, window, params)

    win32.TrackPopupMenuEx = track_popup_menu
