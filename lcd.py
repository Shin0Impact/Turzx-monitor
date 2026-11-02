# SPDX-License-Identifier: GPL-3.0-or-later
"""Driver for the Turing Smart Screen 3.5" (hardware revision A, serial USB35INCHIPS / USB35INCHIPSV2).

The serial protocol comes from turing-smart-screen-python by Matthieu Houdebine
(https://github.com/mathoudebine/turing-smart-screen-python, GPL-3.0). This is a trimmed rewrite
that adds a lock around the serial port (the sleep handler and the render loop both talk to the
screen) and raises LcdError instead of exiting, so the app can reconnect after sleep or unplugging.
"""
import threading
import time
from enum import IntEnum

import numpy as np
from PIL import Image

NATIVE_W, NATIVE_H = 320, 480  # portrait


class Cmd(IntEnum):
    RESET = 101
    CLEAR = 102
    SCREEN_OFF = 108
    SCREEN_ON = 109
    SET_BRIGHTNESS = 110
    SET_ORIENTATION = 121
    DISPLAY_BITMAP = 197


class Orientation(IntEnum):
    PORTRAIT = 0
    REVERSE_PORTRAIT = 1
    LANDSCAPE = 2
    REVERSE_LANDSCAPE = 3


ORIENTATIONS = {
    "portrait": Orientation.PORTRAIT,
    "reverse_portrait": Orientation.REVERSE_PORTRAIT,
    "landscape": Orientation.LANDSCAPE,
    "reverse_landscape": Orientation.REVERSE_LANDSCAPE,
}


class LcdError(Exception):
    pass


def to_rgb565le(image: Image.Image) -> bytes:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint16)
    v = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
    return v.astype("<u2").tobytes()


def find_port():
    from serial.tools.list_ports import comports
    for p in comports():
        if p.serial_number in ("USB35INCHIPS", "USB35INCHIPSV2"):
            return p.device
    for p in comports():
        if p.vid == 0x1A86 and p.pid == 0x5722:
            return p.device
    return None


class BaseLcd:
    def __init__(self, orientation="portrait"):
        self.orientation = ORIENTATIONS[orientation]
        self.lock = threading.RLock()
        self.bytes_sent = 0
        self.is_on = True

    @property
    def size(self):
        if self.orientation in (Orientation.PORTRAIT, Orientation.REVERSE_PORTRAIT):
            return NATIVE_W, NATIVE_H
        return NATIVE_H, NATIVE_W


class TuringRevA(BaseLcd):
    def __init__(self, port="AUTO", orientation="portrait", chunk_size=2560, flow_control=True):
        super().__init__(orientation)
        self.port_setting = port
        self.chunk_size = int(chunk_size)  # bytes per write() call; 0 = whole image at once
        self.flow_control = bool(flow_control)
        self.port = None
        self.ser = None

    # ---- connection ----
    def open(self):
        import serial
        with self.lock:
            self.close()
            port = find_port() if self.port_setting.upper() == "AUTO" else self.port_setting
            if not port:
                raise LcdError("screen not found (no USB35INCHIPS serial device)")
            try:
                self.ser = serial.Serial(port, 115200, timeout=1, write_timeout=5, rtscts=self.flow_control)
            except Exception as e:
                if "denied" in str(e).lower() or "PermissionError" in str(e):
                    raise LcdError(f"{port} is in use by another program - close the official TURZX / "
                                   f"USBMonitor app (check the tray) or AIDA64") from e
                raise LcdError(f"cannot open {port}: {e}") from e
            self.port = port

    def close(self):
        with self.lock:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def _write(self, data: bytes):
        if self.ser is None:
            raise LcdError("not connected")
        try:
            self.ser.write(data)
            self.bytes_sent += len(data)
        except Exception as e:
            self.close()
            raise LcdError(f"write failed: {e}") from e

    def _cmd(self, cmd, x=0, y=0, ex=0, ey=0):
        b = bytearray(6)
        b[0] = x >> 2
        b[1] = ((x & 3) << 6) + (y >> 4)
        b[2] = ((y & 15) << 4) + (ex >> 6)
        b[3] = ((ex & 63) << 2) + (ey >> 8)
        b[4] = ey & 255
        b[5] = cmd
        self._write(bytes(b))

    # ---- commands ----
    def set_orientation(self, name=None):
        with self.lock:
            if name:
                self.orientation = ORIENTATIONS[name]
            w, h = self.size
            b = bytearray(16)
            b[5] = Cmd.SET_ORIENTATION
            b[6] = self.orientation + 100
            b[7], b[8] = w >> 8, w & 255
            b[9], b[10] = h >> 8, h & 255
            self._write(bytes(b))

    def set_brightness(self, percent: int):
        percent = max(0, min(100, int(percent)))
        with self.lock:
            # 0 = brightest, 255 = darkest
            self._cmd(Cmd.SET_BRIGHTNESS, int(255 - percent * 255 / 100))

    def screen_off(self):
        with self.lock:
            self._cmd(Cmd.SCREEN_OFF)
            self.is_on = False

    def screen_on(self):
        with self.lock:
            self._cmd(Cmd.SCREEN_ON)
            self.is_on = True

    def blit(self, image: Image.Image, x: int, y: int):
        w, h = image.size
        if w <= 0 or h <= 0:
            return
        data = to_rgb565le(image)
        with self.lock:
            self._cmd(Cmd.DISPLAY_BITMAP, x, y, x + w - 1, y + h - 1)
            step = self.chunk_size or len(data)
            for i in range(0, len(data), step):
                self._write(data[i:i + step])


class SimulatedLcd(BaseLcd):
    """Fake screen used for previews and tests: keeps what would be on the glass in a PIL image.
    bytes_per_second simulates the serial link speed so timing behaves like the real screen."""

    def __init__(self, orientation="portrait", bytes_per_second=0):
        super().__init__(orientation)
        self.canvas = Image.new("RGB", self.size, "white")
        self.bps = bytes_per_second
        self.brightness = 100
        self.events = []
        self.blits = 0

    def open(self):
        self.events.append("open")

    def close(self):
        pass

    connected = True

    def set_orientation(self, name=None):
        if name:
            self.orientation = ORIENTATIONS[name]
        self.canvas = Image.new("RGB", self.size, "white")

    def set_brightness(self, percent):
        self.brightness = percent
        self.events.append(f"brightness {percent}")

    def screen_off(self):
        with self.lock:
            self.is_on = False
            self.events.append("off")

    def screen_on(self):
        with self.lock:
            self.is_on = True
            self.events.append("on")

    def blit(self, image, x, y):
        with self.lock:
            n = image.size[0] * image.size[1] * 2 + 6
            self.bytes_sent += n
            self.blits += 1
            self.canvas.paste(image.convert("RGB"), (x, y))
            if self.bps:
                time.sleep(n / self.bps)

    def glass(self):
        """What a person would see: black when the screen is off."""
        if not self.is_on:
            return Image.new("RGB", self.size, "black")
        return self.canvas.copy()
