"""Plays one animation (or a slideshow of the folder) full screen."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw

from .gifprep import list_animations, load_frames
from .views.theme import BG, DIM, sans

log = logging.getLogger(__name__)


class GifPlayer:
    """Frames are decoded on a worker thread; frame() always returns quickly with what is due now."""

    def __init__(
        self,
        folder: Path,
        size: tuple[int, int],
        fit: str = "cover",
        selected: Path | None = None,
        slideshow: bool = False,
        switch_seconds: float = 30,
        denoise: int = 12,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.folder = folder
        self._clock = clock
        self.size = size
        self.fit = fit
        self.denoise = denoise
        self.slideshow = slideshow
        self.switch_seconds = switch_seconds
        self.wanted = selected
        self.current: Path | None = None
        self.frame_path: Path | None = None  # file the last returned frame came from
        self.paused = False
        self._lock = threading.Lock()
        self._frames: list[Image.Image] = []
        self._durations: list[float] = []
        self._index = 0
        self._frame_started = 0.0
        self._file_started = 0.0
        self._loading = False
        folder.mkdir(parents=True, exist_ok=True)

    def select(self, path: Path) -> None:
        self.wanted = path
        self._load(path)

    def next(self) -> None:
        files = list_animations(self.folder)
        if not files or self._loading:
            return
        position = files.index(self.current) if self.current in files else -1
        self.wanted = files[(position + 1) % len(files)]
        self._load(self.wanted)

    def _load(self, path: Path) -> None:
        self._loading = True
        threading.Thread(target=self._load_worker, args=(path,), daemon=True, name="gif-load").start()

    def _load_worker(self, path: Path) -> None:
        try:
            started = self._clock()
            frames, durations = load_frames(path, self.size, self.fit, self.denoise)
            with self._lock:
                self._frames, self._durations = frames, durations
                self._index = 0
                self._frame_started = self._file_started = self._clock()
                self.current = path
            log.info("gif: %s (%d frames, loaded in %.1fs)", path.name, len(frames), self._clock() - started)
        except (OSError, ValueError) as e:  # unreadable or not an image
            log.warning("gif: cannot load %s: %s", path, e)
            with self._lock:
                self.current = path  # remember it, so the slideshow moves on instead of retrying
                self._file_started = self._clock()
        finally:
            self._loading = False

    def _start_first(self) -> None:
        if self.wanted and self.wanted.exists():
            self._load(self.wanted)
            return
        files = list_animations(self.folder)
        if files:
            self.wanted = files[0]
            self._load(files[0])

    def frame(self, now: float | None = None) -> Image.Image | None:
        """The frame that should be on screen now (frames are skipped when the screen can't keep up)."""
        now = self._clock() if now is None else now
        if not self._frames:
            if self.current is None and not self._loading:
                self._start_first()
            return None
        with self._lock:
            if not self.paused:
                while now - self._frame_started >= self._durations[self._index]:
                    self._frame_started += self._durations[self._index]
                    self._index = (self._index + 1) % len(self._frames)
                    if now - self._frame_started > 2:  # far behind (for example after sleep): resync
                        self._frame_started = now
            frame = self._frames[self._index]
            self.frame_path = self.current
            due_for_next = self.slideshow and not self._loading and now - self._file_started > self.switch_seconds
        if due_for_next:
            self.next()
        return frame

    @property
    def is_empty(self) -> bool:
        """Nothing to play: no frames loaded, nothing loading, and no files in the folder."""
        return not self._frames and not self._loading and not list_animations(self.folder)

    def seconds_to_next_frame(self, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        with self._lock:
            if not self._frames or self.paused:
                return 0.25
            return max(0.0, self._durations[self._index] - (now - self._frame_started))


def empty_folder_picture(size: tuple[int, int]) -> Image.Image:
    """Shown instead of an animation when the GIF folder has nothing in it."""
    picture = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(picture)
    for i, line in enumerate(("No GIFs yet", "Use Add GIFs in the", "control panel")):
        font = sans(26 if i == 0 else 18)
        d.text(((size[0] - d.textlength(line, font=font)) / 2, size[1] / 2 - 40 + i * 34), line, font=font, fill=DIM)
    return picture
