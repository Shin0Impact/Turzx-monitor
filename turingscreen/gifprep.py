"""Preparing animations for a 125 KB/s screen: fitting, noise clean-up, and a playback estimate."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageSequence

from .diff import dirty_rects
from .views.theme import BG

EXTENSIONS = (".gif", ".webp", ".png", ".apng", ".jpg", ".jpeg")
MAX_FRAMES = 400
RGB565_MASK = np.array([0xF8, 0xFC, 0xF8], dtype=np.uint8)  # the colour depth the screen can show
BLOCK = 8


def list_animations(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS)


def _fit(frame: Image.Image, size: tuple[int, int], fit: str) -> Image.Image:
    """Place `frame` on a dark canvas: cover = fill (crop), contain = whole picture, original = native size."""
    if fit == "contain" or (fit == "original" and (frame.width > size[0] or frame.height > size[1])):
        frame = ImageOps.contain(frame, size, Image.Resampling.LANCZOS)
    elif fit == "cover":
        frame = ImageOps.fit(frame, size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, BG + (255,))
    canvas.alpha_composite(frame, ((size[0] - frame.width) // 2, (size[1] - frame.height) // 2))
    return canvas.convert("RGB")


def clean_frames(frames: list[Image.Image], threshold: int = 12) -> list[Image.Image]:
    """Remove frame-to-frame noise (dithering shimmer, video compression speckle).

    A frame is rounded to the screen's own colour depth, then a block of it keeps the previous frame's
    pixels when its average colour barely moved and only a few of its pixels changed a lot. Real
    motion changes the average and many pixels, so it still updates; blocks next to a changed block
    always update, so the edges of moving things never leave specks. threshold 0 turns this off.
    """
    if threshold <= 0:
        return frames
    cleaned: list[Image.Image] = []
    previous: np.ndarray | None = None
    for frame in frames:
        current = np.asarray(frame, dtype=np.uint8) & RGB565_MASK
        if previous is not None:
            current = np.where(_keep_mask(current, previous, threshold)[..., None], previous, current)
        cleaned.append(Image.fromarray(current, "RGB"))
        previous = current
    return cleaned


def _keep_mask(current: np.ndarray, previous: np.ndarray, threshold: int) -> np.ndarray:
    """True for pixels that should keep their previous value."""
    height, width, _ = current.shape
    h, w = height - height % BLOCK, width - width % BLOCK
    cur, old = current.astype(np.int16), previous.astype(np.int16)
    diff = np.abs(cur - old).max(axis=2)

    def block_mean(a: np.ndarray) -> np.ndarray:
        return a[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK, 3).mean(axis=(1, 3))

    mean_shift = np.abs(block_mean(cur) - block_mean(old)).max(axis=2)
    strongly_changed = (diff[:h, :w] > threshold * 4).reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean(axis=(1, 3))
    changed = ~((mean_shift <= threshold) & (strongly_changed <= 0.15))
    grown = changed.copy()  # a changed block also refreshes its neighbours
    grown[1:] |= changed[:-1]
    grown[:-1] |= changed[1:]
    grown[:, 1:] |= changed[:, :-1]
    grown[:, :-1] |= changed[:, 1:]
    keep = np.zeros((height, width), bool)
    keep[:h, :w] = np.repeat(np.repeat(~grown, BLOCK, axis=0), BLOCK, axis=1)
    return keep | (diff <= threshold)


def load_frames(
    path: Path, size: tuple[int, int], fit: str = "cover", denoise: int = 12
) -> tuple[list[Image.Image], list[float]]:
    """Frames fitted to the screen, and each frame's duration in seconds."""
    frames, durations = [], []
    with Image.open(path) as image:
        for i, frame in enumerate(ImageSequence.Iterator(image)):
            if i >= MAX_FRAMES:
                break
            milliseconds = frame.info.get("duration") or image.info.get("duration") or 100
            durations.append(max(20, int(milliseconds)) / 1000)
            frames.append(_fit(frame.convert("RGBA"), size, fit))
    if len(frames) == 1:
        return frames, [3600.0]  # a still picture
    return clean_frames(frames, denoise), durations


def estimate(
    frames: list[Image.Image], durations: list[float], link_bytes_per_s: float, max_fps: float = 20, seconds: float = 12
) -> tuple[float, float] | None:
    """(frames per second you will actually see, the animation's own fps); None for a still picture.

    Simulates playback the way the app does it: show the frame that is due now, spend link time on
    the pixels that changed, and skip frames when late.
    """
    if len(frames) < 2:
        return None
    own_fps = len(durations) / sum(durations)
    starts = np.cumsum([0.0, *durations[:-1]])
    total = float(sum(durations))
    seconds = max(seconds, min(total * 2, 30))
    clock, shown, displayed = 0.0, frames[0], 0
    while clock < seconds:
        frame = frames[int(np.searchsorted(starts, clock % total, side="right") - 1)]
        if frame is shown:
            clock += 0.005
            continue
        sent = sum((r[2] - r[0]) * (r[3] - r[1]) * 2 + 6 for r in dirty_rects(shown, frame))
        clock += max(sent / link_bytes_per_s, 1 / max_fps)
        shown = frame
        displayed += 1
    return min(own_fps, displayed / seconds), own_fps


def thumbnail(path: Path, box: tuple[int, int] = (96, 96)) -> Image.Image:
    """A frame from the middle of the animation, cropped square."""
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        image.seek(count // 3 if count > 3 else 0)
        return _fit(image.convert("RGBA"), box, "cover")
