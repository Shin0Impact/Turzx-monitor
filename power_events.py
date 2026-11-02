"""Windows power/session notifications -> callback(event).

Events: "suspend", "resume", "display_off", "display_on", "display_dim", "lock", "unlock", "shutdown".
Uses a hidden top-level window (message-only windows don't receive power broadcasts), registered for
GUID_CONSOLE_DISPLAY_STATE and WTS session notifications. On other OSes start() does nothing.
"""
import ctypes
import os
import threading


def start(callback, log=print):
    if os.name != "nt":
        log("power events: not Windows, sleep detection disabled")
        return None
    t = threading.Thread(target=_run, args=(callback, log), daemon=True, name="power-events")
    t.start()
    return t


def _run(callback, log):
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    WM_DESTROY = 0x0002
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

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class POWERBROADCAST_SETTING(ctypes.Structure):
        _fields_ = [("PowerSetting", GUID), ("DataLength", wt.DWORD), ("Data", wt.DWORD)]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR)]

    # {6FE69556-704A-47A0-8F24-C28D936FDA47}
    GUID_CONSOLE_DISPLAY_STATE = GUID(0x6FE69556, 0x704A, 0x47A0,
                                      (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))

    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    user32.CreateWindowExW.restype = wt.HWND
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.RegisterPowerSettingNotification.argtypes = [wt.HANDLE, ctypes.POINTER(GUID), wt.DWORD]
    user32.RegisterPowerSettingNotification.restype = wt.HANDLE
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = wt.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wt.HWND, wt.DWORD]
    wtsapi32.WTSRegisterSessionNotification.restype = wt.BOOL

    def emit(ev):
        try:
            callback(ev)
        except Exception as e:
            log(f"power events: callback error on {ev}: {e!r}")

    def wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_POWERBROADCAST:
                if wparam == PBT_APMSUSPEND:
                    emit("suspend")
                elif wparam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                    emit("resume")
                elif wparam == PBT_POWERSETTINGCHANGE and lparam:
                    s = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                    if bytes(s.PowerSetting) == bytes(GUID_CONSOLE_DISPLAY_STATE):
                        emit({0: "display_off", 1: "display_on", 2: "display_dim"}.get(s.Data, "display_on"))
                return 1
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_LOCK:
                    emit("lock")
                elif wparam == WTS_SESSION_UNLOCK:
                    emit("unlock")
                return 0
            if msg == WM_QUERYENDSESSION:
                return 1  # allow shutdown; act on WM_ENDSESSION (shutdown can still be cancelled here)
            if msg == WM_ENDSESSION:
                if wparam:
                    emit("shutdown")
                return 0
        except Exception as e:
            log(f"power events: wndproc error: {e!r}")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(wndproc)  # keep a reference so it isn't garbage-collected
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = "TuringScreenPowerWatcher"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        log(f"power events: RegisterClass failed ({ctypes.get_last_error()})")
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "Turing screen power watcher", 0,
                                  0, 0, 0, 0, None, None, hinst, None)
    if not hwnd:
        log(f"power events: CreateWindow failed ({ctypes.get_last_error()}) - sleep detection disabled")
        return
    if not user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0):
        log(f"power events: display-state notifications unavailable ({ctypes.get_last_error()})")
    if not wtsapi32.WTSRegisterSessionNotification(hwnd, 0):
        log(f"power events: lock notifications unavailable ({ctypes.get_last_error()})")
    log("power events: listening for sleep / lock / display off")

    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    _ = proc
