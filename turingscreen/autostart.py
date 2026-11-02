"""Start with Windows (a Run-key entry) and a Start Menu shortcut. Everything here is per-user: no admin needed."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)

APP_NAME = "Turing Screen"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "TuringScreen"
ON_WINDOWS = os.name == "nt"


def _windowless_python() -> Path:
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    return windowless if windowless.exists() else python


def launcher(background: bool = False) -> str:
    """Command that starts the app with no console window, using this environment's Python."""
    command = f'"{_windowless_python()}" "{ROOT / "start.pyw"}"'
    return command + " --background" if background else command


def is_enabled() -> bool:
    if not ON_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0] == launcher(background=True)
    except FileNotFoundError:
        return False


def enable() -> None:
    if not ON_WINDOWS:
        raise OSError("start with Windows is only available on Windows")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launcher(background=True))
    log.info("start with Windows: on")


def disable() -> None:
    if not ON_WINDOWS:
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        pass
    log.info("start with Windows: off")


def shortcut_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def create_shortcut() -> None:
    """Start Menu entry, so the control panel can be found by typing 'Turing' after closing it."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TS_LINK);"
        "$s.TargetPath = $env:TS_TARGET; $s.Arguments = $env:TS_ARGS;"
        "$s.WorkingDirectory = $env:TS_DIR; $s.IconLocation = $env:TS_ICON; $s.Save()"
    )
    env = {
        **os.environ,
        "TS_LINK": str(shortcut_path()),
        "TS_TARGET": str(_windowless_python()),
        "TS_ARGS": f'"{ROOT / "start.pyw"}"',
        "TS_DIR": str(ROOT),
        "TS_ICON": str(ROOT / "assets" / "icon.ico"),
    }
    shortcut_path().parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], env=env, check=True, creationflags=0x08000000
    )  # CREATE_NO_WINDOW


def remove_shortcut() -> None:
    shortcut_path().unlink(missing_ok=True)
