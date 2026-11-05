"""The app: decides what the screen shows and keeps it drawn."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import config
from .display import Display
from .gifs import GifPlayer, empty_folder_picture
from .lcd import LcdError
from .power import PowerEvent
from .sensors import Stats
from .views import MODES, ViewOptions, make_view

log = logging.getLogger(__name__)

DARK = "dark"  # backlight off: asleep, shutting down, or idle with "turn the screen off"
IDLE_CLOCK = "idle_clock"  # dim clock while Windows is locked or the monitors are off
CLOCK_ONLY_VIEWS = ("gif", "clock", IDLE_CLOCK)  # these don't need live stats
MAX_WAIT = 0.25  # never sleep longer than this, so settings and power events act quickly
MAX_BACKOFF = 30
REPORT_EVERY = 60  # seconds between link-speed log lines
# Changing these rebuilds the view without blanking the screen.
OPTION_KEYS = {
    ("display", "clock_seconds"),
    ("display", "clock_color"),
    ("display", "calm"),
    *(("bigstats", name) for name in config.DEFAULTS["bigstats"]),
}


class App:
    def __init__(
        self,
        cfg: dict[str, dict],
        display: Display,
        stats: Stats,
        gif_folder: Path | None = None,
        now: Callable[[], float] = time.time,
        save_settings: Callable[[dict], None] = config.save,
    ) -> None:
        self.cfg = cfg
        self.display = display
        self.stats = stats
        self.gif_folder = gif_folder or config.gif_folder(cfg)
        self.status = "starting"
        self.stop = threading.Event()
        self._now = now
        self._save_settings = save_settings
        self._requests: queue.Queue[tuple] = queue.Queue()
        self._lock = threading.RLock()
        self._dark_reasons: set[str] = set()  # sleep / shutdown: backlight off
        self._idle_reasons: set[str] = set()  # locked / monitors off: idle view
        self._view_name: str | None = None
        self._view = None
        self._gif: GifPlayer | None = None
        self._rebuild_view = False
        self._transition = True
        self._next_draw = 0.0
        self._last_gif_draw = 0.0
        self._gif_shown = None
        self._gif_file_shown: Path | None = None
        self._backoff = 1
        self._last_report = time.monotonic()
        self.display.hide_redraws = cfg["display"]["hide_redraws"]

    # ---- called from other threads ----

    def set(self, section: str, name: str, value) -> None:
        """Change a setting (control panel / tray). Applied on the render thread."""
        self._requests.put(("set", section, name, value))

    def command(self, name: str) -> None:
        self._requests.put(("cmd", name))

    def on_power(self, event: PowerEvent) -> None:
        log.info("power event: %s", event.value)
        with self._lock:
            if event is PowerEvent.SUSPEND and self.cfg["dark"]["on_sleep"]:
                self._dark_reasons.add("sleep")
            elif event is PowerEvent.RESUME:
                self._dark_reasons.discard("sleep")
                self.display.disconnect()  # the USB link usually dies during sleep: reopen it
            elif event is PowerEvent.DISPLAY_OFF:
                self._idle_reasons.add("monitors off")
            elif event in (PowerEvent.DISPLAY_ON, PowerEvent.DISPLAY_DIM):
                self._idle_reasons.discard("monitors off")
            elif event is PowerEvent.LOCK:
                self._idle_reasons.add("locked")
            elif event is PowerEvent.UNLOCK:
                self._idle_reasons.discard("locked")
            elif event is PowerEvent.SHUTDOWN_PENDING and self.cfg["dark"]["on_exit"]:
                self._dark_reasons.add("shutdown")
            elif event is PowerEvent.SHUTDOWN_CANCELLED:
                self._dark_reasons.discard("shutdown")
            elif event is PowerEvent.SHUTDOWN:
                if self.cfg["dark"]["on_exit"]:
                    self._dark_reasons.add("shutdown")
                self.stop.set()
            if self.wanted_view() == DARK:
                self.stats.pause(True)
                self.display.go_dark()  # right now, before Windows suspends the USB port

    # ---- what to show ----

    def wanted_view(self) -> str:
        with self._lock:
            if self._dark_reasons:
                return DARK
            if self._idle_reasons:
                return IDLE_CLOCK if self.cfg["display"]["idle"] == "clock" else DARK
            return self.cfg["display"]["mode"]

    @property
    def view_name(self) -> str | None:
        return self._view_name

    def _brightness(self) -> int:
        if self._view_name == IDLE_CLOCK:
            return self.cfg["display"]["idle_brightness"]
        return self.cfg["screen"]["brightness"]

    def _enter_view(self, name: str) -> None:
        size = self.display.size
        options = ViewOptions.from_config(self.cfg)
        self._gif = None
        self._gif_shown = None
        self._gif_file_shown = None
        if name == "gif":
            g = self.cfg["gif"]
            chosen = Path(g["file"]) if g["file"] else None
            self._gif = GifPlayer(
                self.gif_folder,
                size,
                g["fit"],
                chosen,
                g["slideshow"],
                g["switch_seconds"],
                g["denoise"],
                clock=self._now,
            )
            self._view = None
        else:
            self._view = make_view("clock" if name == IDLE_CLOCK else name, size, options)
        self.stats.pause(name in CLOCK_ONLY_VIEWS)
        self._view_name = name
        self._next_draw = 0.0
        self._transition = True
        log.info("showing: %s", MODES.get(name, "clock (idle)"))

    # ---- settings ----

    def _drain_requests(self) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                return
            if request[0] == "set":
                self._apply_setting(*request[1:])
            elif request[1] == "next_gif" and self._gif:
                self._gif.next()

    def _apply_setting(self, section: str, name: str, value) -> None:
        self.cfg[section][name] = value
        self._save_settings(self.cfg)
        log.info("setting %s.%s = %s", section, name, value)
        key = (section, name)
        if key == ("screen", "orientation"):
            self.display.set_orientation(value)
            self._view_name = None
        elif key == ("display", "hide_redraws"):
            self.display.hide_redraws = bool(value)
        elif key in OPTION_KEYS:
            self._rebuild_view = True
        elif key == ("gif", "file") and value:
            self.cfg["display"]["mode"] = "gif"
            self._save_settings(self.cfg)
            if self._view_name == "gif" and self._gif:
                self._gif.select(Path(value))
        elif section == "gif":
            self._view_name = None  # fit / denoise / slideshow: start a fresh player
        # Everything else (mode, idle, brightness...) is read from cfg on the next step.

    # ---- the loop ----

    def step(self) -> float:
        """Do one round of work; returns how many seconds to wait before the next one."""
        self._drain_requests()
        wanted = self.wanted_view()
        try:
            if wanted == DARK:
                self._view_name = DARK
                self.stats.pause(True)
                self.display.go_dark()
                self.status = "screen off"
                return MAX_WAIT
            if not self.display.connected:
                self._connect()
            if wanted != self._view_name:
                self._enter_view(wanted)
            elif self._rebuild_view and self._gif is None:
                self._view = make_view(
                    "clock" if wanted == IDLE_CLOCK else wanted, self.display.size, ViewOptions.from_config(self.cfg)
                )
            self._rebuild_view = False
            if not self.display.is_lit:
                self.display.wake_hidden()
            wait = self._draw_gif() if self._gif else self._draw_view()
            self.display.set_brightness(self._brightness())
            self._report_link()
            self._backoff = 1
            self.status = f"connected on {self.display.lcd.port}"
            return min(max(wait, 0.005), MAX_WAIT)
        except LcdError as e:
            self.display.disconnect()
            self.status = str(e)
            delay, self._backoff = self._backoff, min(self._backoff * 2, MAX_BACKOFF)
            log.warning("screen link problem: %s - retrying in %ss", e, delay)
            return delay

    def _connect(self) -> None:
        self.display.connect(self.cfg["screen"]["orientation"])
        log.info("connected on %s (%dx%d)", self.display.lcd.port, *self.display.size)

    def _draw_view(self) -> float:
        now = self._now()
        if now < self._next_draw:
            return self._next_draw - now
        sample, history = self.stats.snapshot()
        self.display.show(self._view.render(sample, history), self._transition)
        self._transition = False
        interval = self.cfg["stats"]["interval"] if self._view_name in ("stats", "detail") else 1.0
        self._next_draw = float(int(now) + 1) if interval == 1 else now + interval  # tick on the second
        return self._next_draw - self._now()

    def _draw_gif(self) -> float:
        now = self._now()
        min_gap = 1 / self.cfg["gif"]["max_fps"]
        if now - self._last_gif_draw >= min_gap:
            frame = self._gif.frame(now)
            if frame is None and self._gif.is_empty and self._gif_shown is None:
                frame = self._gif_shown = empty_folder_picture(self.display.size)
                self.display.show(frame, self._transition)
                self._transition = False
            elif frame is not None and frame is not self._gif_shown:
                path = self._gif.frame_path
                self.display.show(frame, self._transition or path != self._gif_file_shown)
                self._transition = False
                self._gif_file_shown = path
                self._gif_shown = frame
                self._last_gif_draw = now
        return max(self._gif.seconds_to_next_frame(self._now()), self._last_gif_draw + min_gap - self._now())

    def _report_link(self) -> None:
        meter = self.display.meter
        elapsed = time.monotonic() - self._last_report
        if elapsed < REPORT_EVERY:
            return
        if meter.busy_seconds > 5:  # enough data to trust the measured speed
            self.cfg["app"]["link_kbps"] = round(meter.kilobytes_per_second)
            self._save_settings(self.cfg)
        log.info(
            "link: view %s, %.0f KB/s sent, link %.0f KB/s, %.1f updates/s, busy %.0f%%",
            self._view_name,
            meter.bytes_sent / elapsed / 1024,
            meter.kilobytes_per_second,
            meter.updates / elapsed,
            100 * meter.busy_seconds / elapsed,
        )
        self.display.meter = type(meter)()
        self._last_report = time.monotonic()

    def run(self, on_step: Callable[[], None] | None = None) -> None:
        while not self.stop.is_set():
            wait = self.step()
            if on_step:
                on_step()
            self.stop.wait(wait)

    def shutdown(self) -> None:
        if self.cfg["dark"]["on_exit"]:
            self.display.go_dark()
        self.display.disconnect()
        log.info("stopped")
