"""Driver for the Turing Smart Screen 3.5" (hardware revision A, USB serial IDs USB35INCHIPS / USB35INCHIPSV2).

The wire protocol was worked out by the turing-smart-screen-python project (Matthieu Houdebine, GPL-3.0):
https://github.com/mathoudebine/turing-smart-screen-python
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from enum import IntEnum

import numpy as np
import serial
from PIL import Image
from serial.tools import list_ports

NATIVE_SIZE = (320, 480)  # portrait
BAUD_RATE = 115200
WRITE_CHUNK = 2560  # bytes per serial write while sending a bitmap
KNOWN_SERIAL_NUMBERS = ("USB35INCHIPS", "USB35INCHIPSV2")
KNOWN_VID_PID = (0x1A86, 0x5722)


class Command(IntEnum):
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

    @property
    def is_portrait(self) -> bool:
        return self in (Orientation.PORTRAIT, Orientation.REVERSE_PORTRAIT)


ORIENTATION_NAMES = tuple(o.name.lower() for o in Orientation)


class LcdError(Exception):
    """The screen can't be reached (unplugged, asleep, port busy)."""


def encode_command(command: Command, x: int = 0, y: int = 0, ex: int = 0, ey: int = 0) -> bytes:
    """6-byte command: a rectangle (x, y)-(ex, ey) packed in 10-bit fields, then the command byte."""
    return bytes(
        [
            x >> 2,
            ((x & 3) << 6) + (y >> 4),
            ((y & 15) << 4) + (ex >> 6),
            ((ex & 63) << 2) + (ey >> 8),
            ey & 255,
            command,
        ]
    )


def encode_orientation(orientation: Orientation, width: int, height: int) -> bytes:
    data = bytearray(16)
    data[5] = Command.SET_ORIENTATION
    data[6] = orientation + 100
    data[7], data[8] = width >> 8, width & 255
    data[9], data[10] = height >> 8, height & 255
    return bytes(data)


def encode_brightness(percent: int) -> bytes:
    percent = max(0, min(100, int(percent)))
    return encode_command(Command.SET_BRIGHTNESS, int(255 - percent * 255 / 100))  # 0 = brightest on the wire


def rgb565_le(image: Image.Image) -> bytes:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint16)
    packed = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
    return packed.astype("<u2").tobytes()


def find_port() -> str | None:
    ports = list(list_ports.comports())
    for p in ports:
        if p.serial_number in KNOWN_SERIAL_NUMBERS:
            return p.device
    for p in ports:
        if (p.vid, p.pid) == KNOWN_VID_PID:
            return p.device
    return None


class Lcd(ABC):
    """What the app needs from a screen. `lock` serialises access between the render and power threads."""

    def __init__(self, orientation: str = "portrait") -> None:
        self.orientation = Orientation[orientation.upper()]
        self.lock = threading.RLock()
        self.is_on = True
        self.port: str | None = None

    @property
    def size(self) -> tuple[int, int]:
        w, h = NATIVE_SIZE
        return (w, h) if self.orientation.is_portrait else (h, w)

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def set_orientation(self, name: str | None = None) -> None: ...

    @abstractmethod
    def set_brightness(self, percent: int) -> None: ...

    @abstractmethod
    def screen_on(self) -> None: ...

    @abstractmethod
    def screen_off(self) -> None: ...

    @abstractmethod
    def blit(self, image: Image.Image, x: int, y: int) -> None: ...


class SerialLcd(Lcd):
    def __init__(self, port: str = "AUTO", orientation: str = "portrait") -> None:
        super().__init__(orientation)
        self._port_setting = port
        self._serial: serial.Serial | None = None

    def open(self) -> None:
        with self.lock:
            self.close()
            port = find_port() if self._port_setting.upper() == "AUTO" else self._port_setting
            if not port:
                raise LcdError("screen not found (no USB35INCHIPS serial device)")
            try:
                self._serial = serial.Serial(port, BAUD_RATE, timeout=1, write_timeout=5, rtscts=True)
            except (serial.SerialException, OSError) as e:
                if "denied" in str(e).lower():
                    raise LcdError(
                        f"{port} is in use by another program - close the official TURZX / "
                        "USBMonitor app (check the tray) or AIDA64"
                    ) from e
                raise LcdError(f"cannot open {port}: {e}") from e
            self.port = port

    def close(self) -> None:
        with self.lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except (serial.SerialException, OSError):
                    pass
            self._serial = None

    def _write(self, data: bytes) -> None:
        if self._serial is None:
            raise LcdError("not connected")
        try:
            self._serial.write(data)
        except (serial.SerialException, OSError) as e:
            self.close()
            raise LcdError(f"write failed: {e}") from e

    def set_orientation(self, name: str | None = None) -> None:
        with self.lock:
            if name:
                self.orientation = Orientation[name.upper()]
            self._write(encode_orientation(self.orientation, *self.size))

    def set_brightness(self, percent: int) -> None:
        with self.lock:
            self._write(encode_brightness(percent))

    def screen_on(self) -> None:
        with self.lock:
            self._write(encode_command(Command.SCREEN_ON))
            self.is_on = True

    def screen_off(self) -> None:
        with self.lock:
            self._write(encode_command(Command.SCREEN_OFF))
            self.is_on = False

    def blit(self, image: Image.Image, x: int, y: int) -> None:
        w, h = image.size
        if w <= 0 or h <= 0:
            return
        data = rgb565_le(image)
        with self.lock:
            self._write(encode_command(Command.DISPLAY_BITMAP, x, y, x + w - 1, y + h - 1))
            for i in range(0, len(data), WRITE_CHUNK):
                self._write(data[i : i + WRITE_CHUNK])
