"""A fake screen for previews and tests: remembers what would be on the glass."""

from __future__ import annotations

import time

from PIL import Image

from .lcd import Lcd, Orientation


class SimulatedLcd(Lcd):
    """`link_bytes_per_s` > 0 makes blit() take as long as the real serial link would."""

    def __init__(self, orientation: str = "portrait", link_bytes_per_s: int = 0) -> None:
        super().__init__(orientation)
        self.link_bytes_per_s = link_bytes_per_s
        self.canvas = Image.new("RGB", self.size, "white")
        self.brightness = 100
        self.bytes_sent = 0
        self.blits = 0
        self.events: list[str] = []

    def open(self) -> None:
        self.events.append("open")
        self.port = "simulator"

    def close(self) -> None:
        pass

    def set_orientation(self, name: str | None = None) -> None:
        if name:
            self.orientation = Orientation[name.upper()]
        self.canvas = Image.new("RGB", self.size, "white")

    def set_brightness(self, percent: int) -> None:
        self.brightness = percent
        self.events.append(f"brightness {percent}")

    def screen_on(self) -> None:
        self.is_on = True
        self.events.append("on")

    def screen_off(self) -> None:
        self.is_on = False
        self.events.append("off")

    def blit(self, image: Image.Image, x: int, y: int) -> None:
        with self.lock:
            nbytes = image.width * image.height * 2 + 6
            self.bytes_sent += nbytes
            self.blits += 1
            self.canvas.paste(image.convert("RGB"), (x, y))
            if self.link_bytes_per_s:
                time.sleep(nbytes / self.link_bytes_per_s)

    def glass(self) -> Image.Image:
        """What a person would see: black while the screen is off."""
        if not self.is_on:
            return Image.new("RGB", self.size, "black")
        return self.canvas.copy()
