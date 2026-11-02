from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from turingscreen import gifprep
from turingscreen.gifprep import clean_frames, estimate, list_animations, load_frames, thumbnail

SIZE = (320, 480)


def save_gif(path, frames, ms=50):
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0)


def noisy_background(seed, size=SIZE):
    rng = np.random.default_rng(seed)
    base = np.zeros((size[1], size[0], 3), np.int16)
    base[..., 0] = np.linspace(20, 120, size[1])[:, None]
    base[..., 2] = np.linspace(140, 60, size[0])[None, :]
    return np.clip(base + rng.integers(-5, 6, base.shape), 0, 255).astype(np.uint8)


def with_ball(frame, x):
    image = Image.fromarray(frame)
    ImageDraw.Draw(image).ellipse((x, 200, x + 50, 250), fill=(250, 220, 60))
    return image


def test_noise_only_frames_become_identical():
    frames = [Image.fromarray(noisy_background(i)) for i in range(6)]
    cleaned = clean_frames(frames, 12)
    changed = [np.any(np.asarray(a) != np.asarray(b)) for a, b in zip(cleaned[1:], cleaned[2:], strict=False)]
    assert not any(changed)


def test_real_motion_survives_cleaning_and_leaves_no_trail():
    frames = [with_ball(noisy_background(i), 20 + i * 30) for i in range(8)]
    cleaned = clean_frames(frames, 12)
    for i, frame in enumerate(cleaned):
        pixels = np.asarray(frame).astype(int)
        yellow = (pixels[..., 0] > 200) & (pixels[..., 1] > 180) & (pixels[..., 2] < 120)
        original = np.asarray(frames[i]).astype(int)
        expected = (original[..., 0] > 200) & (original[..., 1] > 180) & (original[..., 2] < 120)
        assert yellow.sum() == expected.sum()
        assert not (yellow & ~expected).any()  # nothing left behind where the ball used to be


def test_cleaning_can_be_turned_off():
    frames = [Image.fromarray(noisy_background(i)) for i in range(3)]
    assert clean_frames(frames, 0) is frames


def test_cleaning_makes_noisy_clips_cheaper_to_play():
    frames = [with_ball(noisy_background(i), 20 + i * 8) for i in range(12)]
    durations = [0.04] * 12
    raw = estimate(frames, durations, 124 * 1024)[0]
    cleaned = estimate(clean_frames(frames, 12), durations, 124 * 1024)[0]
    assert cleaned > raw * 3


def test_estimate_small_motion_is_smooth_and_full_screen_motion_is_slow():
    still = Image.new("RGB", SIZE, (8, 10, 15))
    small = [still.copy() for _ in range(10)]
    for i, frame in enumerate(small):
        ImageDraw.Draw(frame).rectangle((10 + i * 5, 100, 40 + i * 5, 130), fill="white")
    shown, own = estimate(small, [0.05] * 10, 124 * 1024)
    assert shown == pytest.approx(own, rel=0.1)

    rng = np.random.default_rng(1)
    video = [Image.fromarray(rng.integers(0, 256, (480, 320, 3), dtype=np.uint8)) for _ in range(6)]
    shown, own = estimate(video, [0.05] * 6, 124 * 1024)
    assert shown < 1.0 < own


def test_estimate_of_a_still_picture_is_none():
    assert estimate([Image.new("RGB", SIZE)], [3600.0], 124 * 1024) is None


def test_load_frames_fits_every_mode(tmp_path):
    source = [Image.new("RGB", (200, 100), c) for c in ("red", "blue", "green")]
    save_gif(tmp_path / "wide.gif", source, ms=80)
    for fit in ("cover", "contain", "original"):
        frames, durations = load_frames(tmp_path / "wide.gif", SIZE, fit, denoise=0)
        assert [f.size for f in frames] == [SIZE] * 3
        assert durations == [0.08] * 3
    contain, _ = load_frames(tmp_path / "wide.gif", SIZE, "contain", denoise=0)
    assert contain[0].getpixel((160, 5)) == gifprep.BG  # bars above and below
    cover, _ = load_frames(tmp_path / "wide.gif", SIZE, "cover", denoise=0)
    assert cover[0].getpixel((160, 5)) == (255, 0, 0)


def test_very_short_frame_durations_are_raised(tmp_path):
    save_gif(tmp_path / "fast.gif", [Image.new("RGB", (20, 20), c) for c in ("red", "blue")], ms=0)
    _, durations = load_frames(tmp_path / "fast.gif", SIZE, denoise=0)
    assert min(durations) >= 0.02


def test_a_still_image_gets_one_long_frame(tmp_path):
    Image.new("RGB", (64, 64), "yellow").save(tmp_path / "still.png")
    frames, durations = load_frames(tmp_path / "still.png", SIZE)
    assert len(frames) == 1
    assert durations[0] > 60


def test_thumbnail_is_square(tmp_path):
    save_gif(tmp_path / "a.gif", [Image.new("RGB", (200, 100), "red")] * 4)
    assert thumbnail(tmp_path / "a.gif", (96, 96)).size == (96, 96)


def test_list_animations_ignores_other_files(tmp_path):
    for name in ("b.gif", "a.WEBP", "notes.txt", "c.png"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in list_animations(tmp_path)] == ["a.WEBP", "b.gif", "c.png"]
    assert list_animations(tmp_path / "missing") == []
