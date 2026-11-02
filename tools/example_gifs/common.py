"""Shared by the generators: screen size, fonts, saving."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "gifs"
W, H = 320, 480
BG = (8, 10, 15)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ROOT / "assets" / "fonts" / name), size)


def save(name: str, frames: list[Image.Image], milliseconds: int) -> None:
    OUT.mkdir(exist_ok=True)
    frames = [f.convert("RGB") for f in frames]
    frames[0].save(
        OUT / name, save_all=True, append_images=frames[1:], duration=milliseconds, loop=0, optimize=False, disposal=1
    )
    print("wrote", name, len(frames), "frames")


def pixelate(img: Image.Image, scale: int) -> Image.Image:
    """Draw small, show big: a crisp pixel-art look."""
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)
