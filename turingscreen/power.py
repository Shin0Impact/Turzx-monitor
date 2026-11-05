"""Windows sleep / lock / monitor-off notifications, delivered to a callback as PowerEvent values.

Uses a hidden top-level window (message-only windows don't receive power broadcasts) registered for
GUID_CONSOLE_DISPLAY_STATE and WTS session notifications. Does nothing on other systems.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from collections.abc import Callable
from enum import StrEnum

log = logging.getLogger(__name__)


class PowerEvent(StrEnum):
    SUSPEND = "suspend"
    RESUME = "resume"
    DISPLAY_OFF = "display_off"
    DISPLAY_ON = "display_on"
    DISPLAY_DIM = "display_dim"
    LOCK = "lock"
    UNLOCK = "unlock"
    SHUTDOWN_PENDING = "shutdown_pending"  # Windows asked whether it may shut down
    SHUTDOWN_CANCELLED = "shutdown_cancelled"
    SHUTDOWN = "shutdown"


WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
DISPLAY_STATES = {0: PowerEvent.DISPLAY_OFF, 1: PowerEvent.DISPLAY_ON, 2: PowerEvent.DISPLAY_DIM}


def start(callback: Callable[[PowerEvent], None]) -> threading.Thread | None:
    if os.name != "nt":
        log.info("not Windows: sleep and lock detection is off")
        return None
    thread = threading.Thread(target=_message_loop, args=(callback,), daemon=True, name="power-events")
    thread.start()
    return thread


def _message_loop(callback: Callable[[PowerEvent], None]) -> None:
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    lresult = ctypes.c_ssize_t
    wndproc_type = ctypes.WINFUNCTYPE(lresult, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class Guid(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class PowerBroadcastSetting(ctypes.Structure):
        _fields_ = [("PowerSetting", Guid), ("DataLength", wt.DWORD), ("Data", wt.DWORD)]

    class WndClass(ctypes.Structure):
        _fields_ = [
            ("style", wt.UINT),
            ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE),
            ("hIcon", wt.HICON),
            ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HBRUSH),
            ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
        ]

    display_state_guid = Guid(
        0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
    )

    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = lresult
    user32.CreateWindowExW.argtypes = [
        wt.DWORD,
        wt.LPCWSTR,
        wt.LPCWSTR,
        wt.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wt.HWND,
        wt.HMENU,
        wt.HINSTANCE,
        wt.LPVOID,
    ]
    user32.CreateWindowExW.restype = wt.HWND
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WndClass)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.RegisterPowerSettingNotification.argtypes = [wt.HANDLE, ctypes.POINTER(Guid), wt.DWORD]
    user32.RegisterPowerSettingNotification.restype = wt.HANDLE
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = wt.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = lresult
    kernel32.SetProcessShutdownParameters.argtypes = [wt.DWORD, wt.DWORD]
    kernel32.SetProcessShutdownParameters.restype = wt.BOOL
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wt.HWND, wt.DWORD]
    wtsapi32.WTSRegisterSessionNotification.restype = wt.BOOL

    def emit(event: PowerEvent) -> None:
        try:
            callback(event)
        except Exception:
            log.exception("power event handler failed on %s", event.value)

    def on_message(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    emit(PowerEvent.SUSPEND)
                elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    emit(PowerEvent.RESUME)
                elif wparam == PBT_POWERSETTINGCHANGE and lparam:
                    setting = ctypes.cast(lparam, ctypes.POINTER(PowerBroadcastSetting)).contents
                    if bytes(setting.PowerSetting) == bytes(display_state_guid):
                        emit(DISPLAY_STATES.get(setting.Data, PowerEvent.DISPLAY_ON))
                return 1
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_LOCK:
                    emit(PowerEvent.LOCK)
                elif wparam == WTS_SESSION_UNLOCK:
                    emit(PowerEvent.UNLOCK)
                return 0
            if msg == WM_QUERYENDSESSION:
                emit(PowerEvent.SHUTDOWN_PENDING)  # blank the screen now: the process may be killed right after
                return 1
            if msg == WM_ENDSESSION:
                emit(PowerEvent.SHUTDOWN if wparam else PowerEvent.SHUTDOWN_CANCELLED)
                return 0
        except Exception:
            log.exception("power window handler failed")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = wndproc_type(on_message)  # keep a reference so it isn't garbage-collected
    instance = kernel32.GetModuleHandleW(None)
    window_class = WndClass()
    window_class.lpfnWndProc = proc
    window_class.hInstance = instance
    window_class.lpszClassName = "TuringScreenPowerWatcher"
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        log.error("RegisterClass failed (%s)", ctypes.get_last_error())
    hwnd = user32.CreateWindowExW(
        0, window_class.lpszClassName, "Turing screen power watcher", 0, 0, 0, 0, 0, None, None, instance, None
    )
    if not hwnd:
        log.error("CreateWindow failed (%s): sleep detection is off", ctypes.get_last_error())
        return
    if not user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(display_state_guid), 0):
        log.warning("monitor-off notifications unavailable (%s)", ctypes.get_last_error())
    if not wtsapi32.WTSRegisterSessionNotification(hwnd, 0):
        log.warning("lock notifications unavailable (%s)", ctypes.get_last_error())
    kernel32.SetProcessShutdownParameters(0x3FF, 0)  # ask to be told early, before most programs close
    log.info("listening for sleep / lock / monitor off")

    message = wt.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
