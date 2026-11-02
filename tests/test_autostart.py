from __future__ import annotations

import sys

import pytest

from turingscreen import autostart
from turingscreen.config import ROOT


def test_launcher_runs_start_pyw_with_this_python():
    command = autostart.launcher()
    assert str(ROOT / "start.pyw") in command
    assert command.startswith('"')
    assert command.split('"')[1] in (sys.executable, sys.executable.replace("python.exe", "pythonw.exe"))


def test_the_startup_entry_starts_in_the_background():
    assert autostart.launcher(background=True).endswith(" --background")
    assert not autostart.launcher().endswith("--background")


def test_shortcut_goes_in_the_start_menu():
    assert autostart.shortcut_path().name == "Turing Screen.lnk"
    assert "Start Menu" in str(autostart.shortcut_path())


@pytest.mark.skipif(autostart.ON_WINDOWS, reason="checks the non-Windows behaviour")
def test_without_windows_nothing_is_enabled_and_enabling_says_why():
    assert autostart.is_enabled() is False
    autostart.disable()  # harmless
    with pytest.raises(OSError, match="only available on Windows"):
        autostart.enable()
