"""Full-screen GIF player, plus a speed estimate per GIF.

The Turing 3.5" only takes ~120 KB/s and a full 320x480 frame is 307 KB, so a GIF where every pixel
moves plays at well under 1 fps. GIFs that only change a small area (a character on a still
background, pixel art, small GIFs shown at their own size) can play much faster, because only the
pixels that change are sent. estimate() tells the control panel which GIFs will play well.
"""
import os
import threading
import time

import numpy as np
from PIL import Image, ImageOps, ImageSequence

EXTS = (".gif", ".webp", ".png", ".apng", ".jpg", ".jpeg")
MAX_FRAMES = 400
BG = (8, 10, 15)


def list_gifs(folder):
    try:
        fs = sorted(f for f in os.listdir(folder) if f.lower().endswith(EXTS))
    except FileNotFoundError:
        fs = []
    return [os.path.join(folder, f) for f in fs]


def clean_frames(frames, threshold=12, block=8):
    """Remove frame-to-frame noise (dithering shimmer, video compression speckle) so areas that look
    unchanged aren't resent. Works on 8x8 blocks: a block is kept from the previous frame when its
    average colour barely moved and only a few of its pixels changed a lot. Real motion (an object
    moving through the block) changes the average and many pixels, so it still updates.
    Colours are also rounded to the screen's own RGB565 depth first. threshold 0 = off."""
    out = []
    prev = None
    mask565 = np.array([0xF8, 0xFC, 0xF8], dtype=np.uint8)
    for fr in frames:
        a = np.asarray(fr, dtype=np.uint8) & mask565
        if prev is not None and threshold > 0:
            H, W, _ = a.shape
            h, w = H - H % block, W - W % block
            cur = a.astype(np.int16)
            old = prev.astype(np.int16)
            diff = np.abs(cur - old).max(axis=2)
            # per-block stats
            cb = cur[:h, :w].reshape(h // block, block, w // block, block, 3).mean(axis=(1, 3))
            ob = old[:h, :w].reshape(h // block, block, w // block, block, 3).mean(axis=(1, 3))
            mean_shift = np.abs(cb - ob).max(axis=2)
            big = (diff[:h, :w] > threshold * 4).reshape(h // block, block, w // block, block).mean(axis=(1, 3))
            changed = ~((mean_shift <= threshold) & (big <= 0.15))
            # grow changed areas by one block so the edges of moving things never leave specks behind
            grown = changed.copy()
            grown[1:] |= changed[:-1]
            grown[:-1] |= changed[1:]
            grown[:, 1:] |= changed[:, :-1]
            grown[:, :-1] |= changed[:, 1:]
            keep = ~grown
            keep_px = np.zeros((H, W), bool)
            keep_px[:h, :w] = np.repeat(np.repeat(keep, block, axis=0), block, axis=1)
            keep_px |= diff <= threshold  # tiny per-pixel changes anywhere
            a = np.where(keep_px[..., None], prev, a).astype(np.uint8)
        prev = a
        out.append(Image.fromarray(a, "RGB"))
    return out


def load_frames(path, size, fit="cover", denoise=12):
    """fit: cover = fill the screen (crop), contain = whole GIF visible, original = native size, centered.
    denoise: 0 = off, otherwise the noise threshold for clean_frames()."""
    frames, durations = [], []
    with Image.open(path) as im:
        for i, fr in enumerate(ImageSequence.Iterator(im)):
            if i >= MAX_FRAMES:
                break
            d = fr.info.get("duration") or im.info.get("duration") or 100
            durations.append(max(20, int(d)) / 1000)
            fr = fr.convert("RGBA")
            canvas = Image.new("RGBA", size, BG + (255,))
            if fit == "contain":
                fr = ImageOps.contain(fr, size, Image.Resampling.LANCZOS)
            elif fit == "original":
                if fr.width > size[0] or fr.height > size[1]:
                    fr = ImageOps.contain(fr, size, Image.Resampling.LANCZOS)
            else:
                fr = ImageOps.fit(fr, size, Image.Resampling.LANCZOS)
            canvas.alpha_composite(fr, ((size[0] - fr.width) // 2, (size[1] - fr.height) // 2))
            frames.append(canvas.convert("RGB"))
    if len(frames) == 1:
        durations = [3600.0]  # still image
    elif denoise:
        frames = clean_frames(frames, denoise)
    return frames, durations


def estimate(frames, durations, link_bytes_per_s, seconds=12):
    """(fps you'll actually see, the GIF's own fps). Simulates playback the way the app does it:
    show the frame that's due now, pay link time for the pixels that changed, skip frames if late."""
    from render import dirty_rects
    if len(frames) < 2:
        return None, None
    W, H = frames[0].size
    own_fps = len(durations) / sum(durations)
    starts = np.cumsum([0.0] + list(durations[:-1]))
    total = float(sum(durations))
    t, shown, n = 0.0, frames[0], 0
    seconds = max(seconds, min(total * 2, 30))
    while t < seconds:
        i = int(np.searchsorted(starts, t % total, side="right") - 1)
        f = frames[i]
        if f is not shown:
            sent = sum((r[2] - r[0]) * (r[3] - r[1]) * 2 + 6 for r in dirty_rects(shown, f, (0, 0, W, H)))
            start = t
            t = max(t + sent / link_bytes_per_s, start + 1 / 20)  # app draws at most 20 fps
            shown = f
            n += 1
        else:
            t += 0.005
    return min(own_fps, n / seconds), own_fps


def thumbnail(path, box=(96, 96)):
    with Image.open(path) as im:
        im.seek(0)
        fr = im.convert("RGBA")
        canvas = Image.new("RGBA", box, BG + (255,))
        fr = ImageOps.fit(fr, box, Image.Resampling.LANCZOS)
        canvas.alpha_composite(fr)
        return canvas.convert("RGB")


class GifPlayer:
    def __init__(self, folder, size, fit="cover", selected=None, slideshow=False, switch_seconds=30, log=print,
                 denoise=12):
        self.folder = folder
        self.denoise = denoise
        self.size = size
        self.fit = fit
        self.slideshow = slideshow
        self.switch_seconds = switch_seconds
        self.log = log
        self.lock = threading.Lock()
        self.frames, self.durations = [], []
        self.frame_i = 0
        self.frame_start = 0
        self.file_start = 0
        self.current = None
        self.frame_path = None
        self.wanted = selected
        self.loading = False
        self.paused = False
        os.makedirs(folder, exist_ok=True)

    def files(self):
        return list_gifs(self.folder)

    def select(self, path):
        self.wanted = path
        self._load_async(path)

    def _load_async(self, path):
        def work():
            try:
                t = time.time()
                frames, durs = load_frames(path, self.size, self.fit, self.denoise)
                with self.lock:
                    self.frames, self.durations = frames, durs
                    self.frame_i = 0
                    self.frame_start = self.file_start = time.time()
                    self.current = path
                self.log(f"gif: {os.path.basename(path)} ({len(frames)} frames, loaded in {time.time() - t:.1f}s)")
            except Exception as e:
                self.log(f"gif: cannot load {path}: {e}")
                with self.lock:
                    self.current = path  # don't retry forever
                    self.file_start = time.time()
            finally:
                self.loading = False

        self.loading = True
        threading.Thread(target=work, daemon=True, name="gif-load").start()

    def next(self, step=1):
        fs = self.files()
        if not fs or self.loading:
            return
        if self.current in fs:
            path = fs[(fs.index(self.current) + step) % len(fs)]
        else:
            path = fs[0]
        self.wanted = path
        self._load_async(path)

    def frame(self, now=None):
        """Frame that should be on screen now (skips frames when the screen can't keep up)."""
        now = now or time.time()
        if self.current is None and not self.loading:
            fs = self.files()
            if self.wanted and os.path.exists(self.wanted):
                self._load_async(self.wanted)
            elif fs:
                self.wanted = fs[0]
                self._load_async(fs[0])
            return None
        if not self.frames:
            return None
        with self.lock:
            if not self.paused:
                total = len(self.frames)
                while now - self.frame_start >= self.durations[self.frame_i]:
                    self.frame_start += self.durations[self.frame_i]
                    self.frame_i = (self.frame_i + 1) % total
                    if now - self.frame_start > 2:  # far behind (e.g. after sleep): resync
                        self.frame_start = now
            frame = self.frames[self.frame_i]
            self.frame_path = self.current  # which file this frame belongs to (read by the render loop)
            switch = self.slideshow and not self.loading and now - self.file_start > self.switch_seconds
        if switch and len(self.files()) > 1:
            self.next()
        return frame

    def time_to_next_frame(self, now=None):
        now = now or time.time()
        with self.lock:
            if not self.frames or self.paused:
                return 0.25
            return max(0.0, self.durations[self.frame_i] - (now - self.frame_start))


def make_sample_gifs(folder):
    """Two demo GIFs: one that changes a small area (plays smoothly) and one full-screen wave (slow)."""
    import math
    from PIL import ImageDraw
    os.makedirs(folder, exist_ok=True)
    # 1) small bouncing ball on a still background: only a small box changes per frame
    frames = []
    for i in range(40):
        im = Image.new("RGB", (320, 480), BG)
        d = ImageDraw.Draw(im)
        d.text((92, 30), "bouncing ball", fill=(128, 138, 158))
        t = i / 40 * 2 * math.pi
        y = 330 - abs(math.sin(t)) * 200
        d.ellipse((140, y, 180, y + 40), fill=(56, 189, 248))
        d.line((60, 372, 260, 372), fill=(58, 66, 84), width=3)
        frames.append(im)
    frames[0].save(os.path.join(folder, "sample-ball.gif"), save_all=True, append_images=frames[1:],
                   duration=50, loop=0)
    # 2) full-screen waves: every pixel moves, the worst case for this screen
    frames = []
    for i in range(24):
        im = Image.new("RGB", (320, 480), BG)
        d = ImageDraw.Draw(im)
        t = i / 24 * 2 * math.pi
        for k in range(5):
            pts = [(x, 240 + math.sin(x / 38 + t + k * 0.7) * (120 - k * 15)) for x in range(0, 321, 4)]
            c = [(56, 189, 248), (118, 227, 95), (167, 139, 250), (251, 191, 36), (244, 114, 182)][k]
            d.line(pts, fill=c, width=4)
        frames.append(im)
    frames[0].save(os.path.join(folder, "sample-waves.gif"), save_all=True, append_images=frames[1:],
                   duration=80, loop=0)
