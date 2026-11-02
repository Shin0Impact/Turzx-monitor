"""The wire protocol. Expected bytes come from the original turing-smart-screen-python library."""

from __future__ import annotations

import pytest
from PIL import Image

from turingscreen import lcd
from turingscreen.lcd import (
    Command,
    LcdError,
    Orientation,
    SerialLcd,
    encode_brightness,
    encode_command,
    encode_orientation,
)


@pytest.mark.parametrize("percent, expected", [(0, "3fc00000006e"), (50, "1fc00000006e"), (100, "00000000006e")])
def test_brightness_bytes(percent, expected):
    assert encode_brightness(percent).hex() == expected


def test_brightness_is_clamped():
    assert encode_brightness(-20) == encode_brightness(0)
    assert encode_brightness(500) == encode_brightness(100)


def test_screen_on_off_bytes():
    assert encode_command(Command.SCREEN_ON).hex() == "00000000006d"
    assert encode_command(Command.SCREEN_OFF).hex() == "00000000006c"


@pytest.mark.parametrize(
    "orientation, expected",
    [
        (Orientation.PORTRAIT, "00000000007964014001e00000000000"),
        (Orientation.REVERSE_PORTRAIT, "00000000007965014001e00000000000"),
        (Orientation.LANDSCAPE, "0000000000796601e001400000000000"),
        (Orientation.REVERSE_LANDSCAPE, "0000000000796701e001400000000000"),
    ],
)
def test_orientation_bytes(orientation, expected):
    size = (320, 480) if orientation.is_portrait else (480, 320)
    assert encode_orientation(orientation, *size).hex() == expected


def test_rgb565_packing():
    image = Image.new("RGB", (4, 3))
    image.putdata([(i * 20 % 256, (i * 37) % 256, (i * 91) % 256) for i in range(12)])
    # header for a 4x3 bitmap at (13, 77), then the pixels, as produced by the original library
    header = encode_command(Command.DISPLAY_BITMAP, 13, 77, 16, 79)
    assert header.hex() == "0344d0404fc5"
    assert lcd.rgb565_le(image).hex() == "00002b11562a623bad54d865e47e0f885ba166b291cbbddc"


def test_size_follows_orientation():
    assert SerialLcd(orientation="portrait").size == (320, 480)
    assert SerialLcd(orientation="landscape").size == (480, 320)


class RecordingSerial:
    def __init__(self, *args, **kwargs):
        self.written = bytearray()

    def write(self, data):
        self.written += data

    def close(self):
        pass


def test_blit_sends_header_then_pixels_in_chunks(monkeypatch):
    port = SerialLcd("COM3")
    port._serial = RecordingSerial()
    image = Image.new("RGB", (320, 20), (255, 0, 0))
    port.blit(image, 0, 5)
    sent = bytes(port._serial.written)
    assert sent[:6] == encode_command(Command.DISPLAY_BITMAP, 0, 5, 319, 24)
    assert len(sent) == 6 + 320 * 20 * 2
    assert sent[6:8] == b"\x00\xf8"  # pure red in little-endian RGB565


def test_writing_without_a_connection_raises():
    with pytest.raises(LcdError):
        SerialLcd("COM3").screen_on()


def test_busy_port_gives_a_helpful_message(monkeypatch):
    import serial

    def refuse(*args, **kwargs):
        raise serial.SerialException("could not open port 'COM3': PermissionError(13, 'Access is denied.')")

    monkeypatch.setattr(lcd.serial, "Serial", refuse)
    with pytest.raises(LcdError, match="in use by another program"):
        SerialLcd("COM3").open()


def test_missing_screen_is_reported(monkeypatch):
    monkeypatch.setattr(lcd, "find_port", lambda: None)
    with pytest.raises(LcdError, match="not found"):
        SerialLcd("AUTO").open()
