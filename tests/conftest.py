"""Shared fixtures: a sample of system stats, a fake stats source, and an app wired to a simulated screen."""

from __future__ import annotations

import copy
import math
import time

import pytest

from turingscreen import config
from turingscreen.app import App
from turingscreen.display import Display
from turingscreen.lcd import LcdError
from turingscreen.sensors import Drive, Gpu, History, Sample
from turingscreen.simulator import SimulatedLcd


def make_sample(**overrides) -> Sample:
    values = {
        "cpu_name": "Ryzen 9 9900X",
        "cpu_load": 6.2,
        "cpu_clock": 5300.0,
        "cores": tuple([10.0] * 24),
        "ram_used": 21.4,
        "ram_total": 31.1,
        "ram_percent": 68.8,
        "gpu": Gpu("NVIDIA GeForce RTX 3070", 31.0, 61.0, 182.0, 45.0, 1905.0, 6.6, 8.0),
        "down": 2.5e6,
        "up": 4.6e5,
        "disk_read": 1.2e7,
        "disk_write": 6e5,
        "drives": (Drive("C:", 75.2), Drive("D:", 91.0)),
        "uptime": 3e5,
    }
    values.update(overrides)
    return Sample(**values)


def make_history() -> History:
    wave = [20 + 10 * math.sin(i / 5) for i in range(60)]
    return History(cpu=list(wave), gpu=list(wave), down=[1e6 * (1 + math.sin(i / 7)) for i in range(60)], up=[1e5] * 60)


@pytest.fixture
def sample() -> Sample:
    return make_sample()


@pytest.fixture
def history() -> History:
    return make_history()


class FakeStats:
    """Stands in for the sensor thread."""

    def __init__(self) -> None:
        self.paused = False
        self.sample = make_sample()
        self.history = make_history()

    def pause(self, paused: bool = True) -> None:
        self.paused = paused

    def snapshot(self):
        return self.sample, self.history


class FlakyLcd(SimulatedLcd):
    """A simulated screen whose USB link can be 'unplugged'."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.unplugged = False
        self.opens = 0

    def _check(self) -> None:
        if self.unplugged:
            raise LcdError("write failed")

    def open(self) -> None:
        if self.unplugged:
            raise LcdError("screen not found")
        self.opens += 1
        super().open()

    def blit(self, image, x, y) -> None:
        self._check()
        super().blit(image, x, y)

    def set_brightness(self, percent) -> None:
        self._check()
        super().set_brightness(percent)

    def screen_on(self) -> None:
        self._check()
        super().screen_on()

    def screen_off(self) -> None:
        self._check()
        super().screen_off()

    def set_orientation(self, name=None) -> None:
        self._check()
        super().set_orientation(name)


class Rig:
    """An App on a simulated screen with a fake clock. step() advances the clock by the wait it returns."""

    def __init__(self, tmp_path) -> None:
        self.time = 1_000_000.0
        self.lcd = FlakyLcd()
        self.stats = FakeStats()
        self.saved: list[dict] = []
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["gif"]["folder"] = str(tmp_path / "gifs")
        self.app = App(
            cfg,
            Display(self.lcd),
            self.stats,
            gif_folder=tmp_path / "gifs",
            now=lambda: self.time,
            save_settings=lambda c: self.saved.append(copy.deepcopy(c)),
        )

    @property
    def blackouts(self) -> int:
        """How many times the backlight was switched to 0 (a hidden redraw or going dark)."""
        return self.lcd.events.count("brightness 0")

    def step(self, seconds: float = 0.0) -> float:
        self.time += seconds
        wait = self.app.step()
        self.time += wait
        return wait

    def steps(self, count: int = 5) -> None:
        for _ in range(count):
            self.step()

    def settle(self) -> None:
        """Run until the app has nothing more to draw this second."""
        self.steps(6)


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


@pytest.fixture
def gif_folder(tmp_path):
    folder = tmp_path / "gifs"
    folder.mkdir()
    return folder


def wait_for(condition, timeout: float = 5.0) -> bool:
    """Poll a condition that depends on a worker thread (GIF decoding)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False
