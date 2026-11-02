"""The screen as the app uses it: remembers what is on the glass and sends only what changed."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from PIL import Image

from .diff import dirty_rects
from .lcd import Lcd, LcdError

log = logging.getLogger(__name__)

HIDE_THRESHOLD = 0.4  # hide a redraw behind a dark backlight when more than this share of the screen changes


@dataclass
class LinkMeter:
    """Measures how fast the screen accepts pixels."""

    bytes_sent: int = 0
    busy_seconds: float = 0.0
    updates: int = 0
    started: float = field(default_factory=time.monotonic)

    def add(self, nbytes: int, seconds: float) -> None:
        self.bytes_sent += nbytes
        self.busy_seconds += seconds

    @property
    def kilobytes_per_second(self) -> float:
        """Speed of the link while it was transferring (not averaged over idle time)."""
        return self.bytes_sent / self.busy_seconds / 1024 if self.busy_seconds else 0.0


class Display:
    def __init__(self, lcd: Lcd, hide_redraws: bool = True) -> None:
        self.lcd = lcd
        self.hide_redraws = hide_redraws
        self.meter = LinkMeter()
        self.connected = False
        self._glass: Image.Image | None = None  # what is on the screen now; None = unknown
        self._level: int | None = None  # brightness last sent

    @property
    def size(self) -> tuple[int, int]:
        return self.lcd.size

    @property
    def is_lit(self) -> bool:
        return self.lcd.is_on

    def connect(self, orientation: str) -> None:
        with self.lcd.lock:
            self.lcd.open()
            self.lcd.set_orientation(orientation)
            self.forget()
            self.wake_hidden()  # a previous run may have left the backlight off
            self.connected = True

    def disconnect(self) -> None:
        self.connected = False
        self.lcd.close()

    def forget(self) -> None:
        """Treat the glass contents as unknown, so the next picture is sent in full."""
        self._glass = None
        self._level = None

    def set_orientation(self, name: str) -> None:
        self.lcd.set_orientation(name)
        self.forget()

    def set_brightness(self, percent: int) -> None:
        if percent != self._level or not self.lcd.is_on:
            self.lcd.set_brightness(percent)
            if not self.lcd.is_on:
                self.lcd.screen_on()
            self._level = percent

    def wake_hidden(self) -> None:
        """Turn the screen on with the backlight at 0; the caller sets the real brightness after drawing."""
        with self.lcd.lock:
            self.lcd.set_brightness(0)
            self.lcd.screen_on()
            self._level = 0

    def go_dark(self) -> None:
        with self.lcd.lock:
            if not self.lcd.is_on:
                return
            try:
                self.lcd.set_brightness(0)
                self.lcd.screen_off()
                self._level = 0
            except LcdError as e:  # the link is already down, so the screen is dark anyway
                log.info("screen already unreachable (%s)", e)
                self.lcd.is_on = False

    def show(self, picture: Image.Image, transition: bool = False) -> None:
        """Send the parts of `picture` that differ from the glass.

        During a `transition` (mode or GIF switch) a mostly-new picture is loaded with the backlight
        off, so you see the finished picture appear instead of a top-to-bottom wipe.
        """
        full = self._glass is None or self._glass.size != picture.size
        rects = [(0, 0, *picture.size)] if full else dirty_rects(self._glass, picture)
        area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
        hide = (
            transition
            and self.hide_redraws
            and self.lcd.is_on
            and bool(self._level)
            and area > HIDE_THRESHOLD * picture.width * picture.height
        )
        if hide:
            self.lcd.set_brightness(0)
        if full:
            self._glass = None
        for rect in rects:
            self._blit(picture.crop(rect), rect[0], rect[1])
        if full:
            self._glass = picture.copy()
        if hide:
            self.lcd.set_brightness(self._level)
        self.meter.updates += 1

    def _blit(self, part: Image.Image, x: int, y: int) -> None:
        started = time.monotonic()
        self.lcd.blit(part, x, y)
        self.meter.add(part.width * part.height * 2, time.monotonic() - started)
        if self._glass is not None:
            self._glass.paste(part, (x, y))

    def preview(self) -> Image.Image:
        """Copy of what is on the glass (black while the screen is off)."""
        glass = self._glass
        if not self.lcd.is_on or glass is None:
            return Image.new("RGB", self.lcd.size, "black")
        return glass.copy()
