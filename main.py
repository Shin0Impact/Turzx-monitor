"""Turing Smart Screen 3.5" app: big stats / detailed stats / GIF / clock, chosen from a control panel.

    python main.py              run (opens the control panel)
    python main.py --quiet      run in the background (tray icon only) - used at Windows startup
    python main.py --simulate   no screen needed: writes previews/preview.png
    python main.py --benchmark  measure screen speed with different link settings
"""
import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _crash(exc_type, exc, tb):
    """Background launchers have no console: write any crash to logs/crash.log (and show it if we can)."""
    import traceback
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
        with open(os.path.join(HERE, "logs", "crash.log"), "a", encoding="utf-8") as f:
            import datetime
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n{text}\n")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _crash

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

from PIL import Image

import power_events
from gifs import GifPlayer, list_gifs, make_sample_gifs
from lcd import ORIENTATIONS, LcdError, SimulatedLcd, TuringRevA
from pages import BIG_DEFAULTS, MODES, ClockPage, make_page
from render import dirty_rects
from sensors import Stats

log = logging.getLogger("turing")

DEFAULTS = {
    "screen": {"port": "AUTO", "orientation": "portrait", "brightness": 50, "chunk_size": 2560,
               "flow_control": True},
    "display": {"mode": "stats", "idle": "clock", "idle_brightness": 25, "clock_seconds": True,
                "hide_redraws": True, "calm": True},
    "dark": {"on_sleep": True, "on_exit": True},
    "stats": {"interval": 1.0, "drives": "auto", "network_interface": "auto",
              "librehardwaremonitor_url": "",
              "temp_unit": "C", "clock_24h": True},
    "gif": {"folder": "gifs", "file": "", "slideshow": False, "switch_seconds": 30, "fit": "cover", "max_fps": 20,
            "denoise": 12},
    "app": {"tray": True, "link_kbps": 120},
    "bigstats": dict(BIG_DEFAULTS),
}
STATE_FILE = os.path.join(HERE, "state.json")
# settings the control panel can change; saved in state.json so they survive restarts
STATE_KEYS = {("screen", "orientation"), ("screen", "brightness"), ("display", "mode"), ("display", "idle"),
              ("display", "idle_brightness"), ("display", "clock_seconds"), ("gif", "file"),
              ("gif", "slideshow"), ("gif", "fit"), ("app", "link_kbps"), ("display", "hide_redraws"),
              ("display", "calm"), ("gif", "denoise")} | {("bigstats", k) for k in BIG_DEFAULTS}


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(path) and tomllib:
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        for key, v in st.items():
            sec, _, name = key.partition(".")
            if (sec, name) in STATE_KEYS:
                cfg[sec][name] = v
    except Exception:
        pass
    return cfg


def save_state(cfg):
    try:
        st = {f"{s}.{n}": cfg[s][n] for s, n in STATE_KEYS}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log.warning(f"cannot save settings: {e}")


def setup_logging(console=True):
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(os.path.join(HERE, "logs", "turing.log"), maxBytes=1_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console and sys.stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


class App:
    def __init__(self, cfg, lcd, simulate=False):
        self.cfg = cfg
        self.lcd = lcd
        self.simulate = simulate
        self.stop = threading.Event()
        self.state_lock = threading.RLock()
        self.dark_reasons = set()   # sleep / shutdown -> backlight off
        self.idle_reasons = set()   # lock / monitors off -> idle view (clock or off)
        self.connected = False
        self.status = "starting"
        self.requests = queue.Queue()
        self.listeners = []         # callbacks(app) when settings change (control panel refresh)
        self.stats = Stats(dict(cfg["stats"]))
        self.stats.start()
        log.info(f"CPU: {self.stats.cpu_name} | GPU: {self.stats.gpu.name or 'none'} ({self.stats.gpu.mode})")
        g = cfg["gif"]
        self.gif_folder = g["folder"] if os.path.isabs(g["folder"]) else os.path.join(HERE, g["folder"])
        if not list_gifs(self.gif_folder):
            make_sample_gifs(self.gif_folder)
            log.info("gif: folder was empty, added sample GIFs")
        self.view = None            # what is being shown: a mode name, "idle_clock" or "dark"
        self.page = None
        self.gif = None
        self.glass = None           # what is on the screen right now (None = unknown -> full redraw)
        self.brightness_now = None
        self.next_draw = 0
        self.last_gif_draw = 0
        self.gif_shown = None
        self.gif_file_shown = None
        self.transition = True
        self.counter = {"bytes": 0, "blit_time": 0.0, "frames": 0, "t0": time.time()}

    # ---------- settings ----------
    def get(self, section, name):
        return self.cfg[section][name]

    def set(self, section, name, value):
        """Thread-safe: called from the control panel / tray. Applied by the render thread."""
        self.requests.put((section, name, value))

    def _apply_request(self, section, name, value):
        if section == "cmd":
            if name == "next_gif" and self.gif:
                self.gif.next()
            return
        self.cfg[section][name] = value
        save_state(self.cfg)
        log.info(f"setting {section}.{name} = {value}")
        if (section, name) == ("screen", "orientation"):
            self.lcd.set_orientation(value)
            self.view = None
            self.glass = None
        elif section == "screen" and name == "brightness":
            self.brightness_now = None
        elif section == "display":
            self.view = None if name in ("mode", "idle", "clock_seconds", "calm") else self.view
            self.brightness_now = None
        elif section == "bigstats":
            if self.view == "stats":
                self.view = None
        elif section == "gif":
            if name == "file" and value:
                self.cfg["display"]["mode"] = "gif"
                save_state(self.cfg)
                if self.view == "gif" and self.gif:
                    self.gif.select(value)
                else:
                    self.view = None
            elif self.view == "gif":
                self.view = None  # rebuild player with new fit / slideshow
        for cb in list(self.listeners):
            try:
                cb(self)
            except Exception:
                pass

    # ---------- power events ----------
    def on_power(self, ev):
        log.info(f"power event: {ev}")
        with self.state_lock:
            if ev == "suspend" and self.cfg["dark"]["on_sleep"]:
                self.dark_reasons.add("sleep")
            elif ev == "resume":
                self.dark_reasons.discard("sleep")
                self.connected = False  # the USB serial link usually dies during sleep: reopen it
            elif ev == "display_off":
                self.idle_reasons.add("monitors off")
            elif ev in ("display_on", "display_dim"):
                self.idle_reasons.discard("monitors off")
            elif ev == "lock":
                self.idle_reasons.add("locked")
            elif ev == "unlock":
                self.idle_reasons.discard("locked")
            elif ev == "shutdown" and self.cfg["dark"]["on_exit"]:
                self.dark_reasons.add("shutdown")
                self.stop.set()
            if self.wanted_view() == "dark":
                self._go_dark()  # right now, before Windows suspends

    def wanted_view(self):
        if self.dark_reasons:
            return "dark"
        if self.idle_reasons:
            return "idle_clock" if self.cfg["display"]["idle"] == "clock" else "dark"
        return self.cfg["display"]["mode"]

    def _go_dark(self):
        self.stats.pause(True)
        if not self.lcd.is_on:
            return
        try:
            with self.lcd.lock:
                self.lcd.set_brightness(0)
                self.lcd.screen_off()
            self.brightness_now = 0
            log.info(f"screen dark ({', '.join(sorted(self.dark_reasons | self.idle_reasons))})")
        except LcdError as e:
            self.lcd.is_on = False
            log.info(f"screen dark (link already down: {e})")
        self.status = "screen off"

    # ---------- screen I/O ----------
    def connect(self):
        with self.state_lock:
            self.lcd.open()
            self.lcd.set_orientation(self.cfg["screen"]["orientation"])
            self.lcd.screen_on()  # a previous run may have left the backlight off
            self.glass = None
            self.brightness_now = None
            self.connected = True
            self.status = f"connected on {getattr(self.lcd, 'port', None) or 'simulator'}"
            log.info(f"{self.status} ({self.lcd.size[0]}x{self.lcd.size[1]})")

    def blit(self, img, x, y):
        t = time.time()
        self.lcd.blit(img, x, y)
        self.counter["blit_time"] += time.time() - t
        self.counter["bytes"] += img.size[0] * img.size[1] * 2
        if self.glass is not None:
            self.glass.paste(img, (x, y))

    def show(self, img, transition=False):
        """Send only the parts of img that differ from what's on the screen.
        transition=True (mode / GIF switch): if most of the screen changes and hide_redraws is on, the
        backlight goes off while the picture loads, so you see a clean switch instead of a wipe."""
        full = self.glass is None or self.glass.size != img.size
        rects = [(0, 0, img.width, img.height)] if full else dirty_rects(self.glass, img, (0, 0, img.width, img.height))
        area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
        hide = (transition and self.cfg["display"]["hide_redraws"] and self.lcd.is_on
                and area > 0.4 * img.width * img.height and self.brightness_now)
        if hide:
            self.lcd.set_brightness(0)
        if full:
            self.glass = None
            self.blit(img, 0, 0)
            self.glass = img.copy()
        else:
            for r in rects:
                self.blit(img.crop(r), r[0], r[1])
        if hide:
            self.lcd.set_brightness(self.brightness_now)
        self.counter["frames"] += 1

    def preview(self):
        """Copy of what's on the glass, for the control panel."""
        if not self.lcd.is_on or self.glass is None:
            return Image.new("RGB", self.lcd.size, "black")
        try:
            return self.glass.copy()
        except Exception:
            return Image.new("RGB", self.lcd.size, "black")

    def _enter_view(self, view):
        size = self.lcd.size
        st = {**self.cfg["stats"], "clock_seconds": self.cfg["display"]["clock_seconds"],
              "calm": self.cfg["display"]["calm"], "bigstats": dict(self.cfg["bigstats"])}
        self.gif = None
        self.gif_shown = None
        if view == "gif":
            g = self.cfg["gif"]
            sel = g["file"] if g["file"] and os.path.exists(g["file"]) else None
            self.gif = GifPlayer(self.gif_folder, size, g["fit"], sel, g["slideshow"], g["switch_seconds"],
                                 log=log.info, denoise=g["denoise"])
            self.page = None
        elif view == "idle_clock":
            self.page = ClockPage(size, st)
        else:
            self.page = make_page(view, size, st)
        self.stats.pause(view in ("gif", "idle_clock", "clock"))
        self.view = view
        self.next_draw = 0
        self.transition = True
        self.gif_file_shown = None
        log.info(f"showing: {MODES.get(view, 'clock (idle)')}")

    def _set_brightness_for_view(self):
        want = self.cfg["display"]["idle_brightness"] if self.view == "idle_clock" else self.cfg["screen"]["brightness"]
        if want != self.brightness_now:
            self.lcd.set_brightness(want)
            if not self.lcd.is_on:
                self.lcd.screen_on()
            self.brightness_now = want

    def report(self):
        c = self.counter
        dt = time.time() - c["t0"]
        if dt >= 60:
            if c["blit_time"] > 5:  # enough data to trust
                kbps = c["bytes"] / c["blit_time"] / 1024
                self.cfg["app"]["link_kbps"] = round(kbps)
                save_state(self.cfg)
            log.info(f"perf: view {self.view}, {c['bytes'] / dt / 1024:.0f} KB/s sent, "
                     f"link ~{self.cfg['app']['link_kbps']} KB/s, {c['frames'] / dt:.1f} updates/s, "
                     f"link busy {100 * c['blit_time'] / dt:.0f}%")
            self.counter = {"bytes": 0, "blit_time": 0.0, "frames": 0, "t0": time.time()}

    # ---------- main loop ----------
    def run(self, duration=None, on_frame=None):
        backoff = 1
        t_end = time.time() + duration if duration else None
        max_fps = max(1, self.cfg["gif"]["max_fps"])
        while not self.stop.is_set() and not (t_end and time.time() > t_end):
            try:
                while not self.requests.empty():
                    self._apply_request(*self.requests.get_nowait())
                want = self.wanted_view()
                if want == "dark":
                    if self.lcd.is_on and self.connected:
                        self._go_dark()
                    self.view = "dark"
                    time.sleep(0.2)
                    continue
                if not self.connected:
                    self.connect()
                if want != self.view:
                    self._enter_view(want)
                self._set_brightness_for_view()
                now = time.time()
                if self.view == "gif":
                    if now - self.last_gif_draw >= 1 / max_fps:
                        frame = self.gif.frame(now)
                        if frame is not None and frame is not self.gif_shown:
                            path = self.gif.frame_path
                            new_file = path != self.gif_file_shown
                            self.show(frame, transition=self.transition or new_file)
                            self.transition = False
                            self.gif_file_shown = path
                            self.gif_shown = frame
                            self.last_gif_draw = now
                            if on_frame:
                                on_frame()
                    now = time.time()
                    wait = max(self.gif.time_to_next_frame(now), self.last_gif_draw + 1 / max_fps - now)
                elif now >= self.next_draw:
                    data, hist = self.stats.snapshot()
                    self.show(self.page.render(data, hist), transition=self.transition)
                    self.transition = False
                    iv = self.cfg["stats"]["interval"] if self.view in ("stats", "detail") else 1.0
                    self.next_draw = (int(now) + 1) if iv == 1 else now + iv  # tick on the second
                    if on_frame:
                        on_frame()
                    wait = self.next_draw - time.time()
                else:
                    wait = self.next_draw - now
                self.status = f"connected on {getattr(self.lcd, 'port', None) or 'simulator'}"
                self.report()
                time.sleep(min(max(0.005, wait), 0.25))
                backoff = 1
            except LcdError as e:
                self.connected = False
                self.status = str(e)
                if self.wanted_view() == "dark":
                    continue
                log.warning(f"screen link problem: {e} - retrying in {backoff}s")
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def shutdown(self):
        if self.cfg["dark"]["on_exit"]:
            try:
                with self.lcd.lock:
                    self.lcd.set_brightness(0)
                    self.lcd.screen_off()
            except Exception:
                pass
        self.lcd.close()
        log.info("stopped")


# ---------- tray icon ----------
def tray_image():
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((14, 4, 50, 60), radius=8, fill=(18, 22, 31), outline=(56, 189, 248), width=4)
    dr.rectangle((22, 16, 42, 22), fill=(56, 189, 248))
    dr.rectangle((22, 28, 36, 34), fill=(118, 227, 95))
    dr.rectangle((22, 40, 40, 46), fill=(167, 139, 250))
    return img


def start_tray(app, open_panel=None):
    try:
        import pystray
    except Exception as e:
        log.info(f"tray icon disabled ({e})")
        return None

    def set_mode(m):
        return lambda icon, item: app.set("display", "mode", m)

    def quit_(icon, item):
        app.stop.set()
        icon.stop()

    items = []
    if open_panel:
        items.append(pystray.MenuItem("Open control panel", lambda icon, item: open_panel(), default=True))
    items += [
        pystray.MenuItem("Show", pystray.Menu(*[
            pystray.MenuItem(label, set_mode(m), checked=lambda item, m=m: app.cfg["display"]["mode"] == m,
                             radio=True) for m, label in MODES.items()])),
        pystray.MenuItem("Next GIF", lambda icon, item: app.set("cmd", "next_gif", True)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_),
    ]
    icon = pystray.Icon("turing-screen", tray_image(), "Turing screen", pystray.Menu(*items))
    threading.Thread(target=icon.run, daemon=True, name="tray").start()
    return icon


def single_instance():
    if os.name != "nt":
        return True
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Local\\TuringScreenDashboard")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def benchmark(cfg):
    """Try link settings to find the fastest one that doesn't corrupt the picture."""
    from PIL import ImageDraw
    from render import mono
    results = []
    combos = [(True, 2560), (True, 16384), (True, 65536), (True, 0),
              (False, 2560), (False, 16384), (False, 0)]
    for n_combo, (flow, chunk) in enumerate(combos, 1):
        lcd = TuringRevA(cfg["screen"]["port"], "portrait", chunk_size=chunk, flow_control=flow)
        try:
            lcd.open()
            lcd.set_orientation()
            lcd.set_brightness(40)
            lcd.screen_on()
            label = f"test {n_combo}/{len(combos)}"
            n, sent = 0, 0
            t0 = time.time()
            while time.time() - t0 < 4:
                im = Image.new("RGB", (320, 480), ((n * 50) % 200, 60, 180 - (n * 40) % 160))
                d = ImageDraw.Draw(im)
                for y in range(0, 480, 20):  # stripes make corruption easy to see
                    d.line((0, y, 320, y), fill="white")
                d.rectangle((40, 190, 280, 290), fill="black")
                d.text((60, 205), label, font=mono(30), fill="white")
                d.text((60, 245), f"frame {n}", font=mono(24), fill="yellow")
                lcd.blit(im, 0, 0)
                n += 1
                sent += 320 * 480 * 2
            dt = time.time() - t0
            line = (f"test {n_combo}: flow_control={flow} chunk_size={chunk}: "
                    f"{sent / dt / 1024:.0f} KB/s ({n / dt:.2f} full screens/s)")
        except Exception as e:
            line = f"test {n_combo}: flow_control={flow} chunk_size={chunk}: FAILED ({e})"
        finally:
            lcd.close()
            time.sleep(0.5)
        results.append(line)
        log.info("benchmark " + line)
        print(line)
    print("\nDid any test show a scrambled / shifted picture? Tell Claude which test number.")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.toml"))
    ap.add_argument("--simulate", action="store_true", help="no screen: write previews/preview.png")
    ap.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="background mode: no console, panel stays closed")
    ap.add_argument("--no-ui", action="store_true", help="don't create the control panel")
    args = ap.parse_args()

    setup_logging(console=not args.quiet)
    cfg = load_config(args.config)
    log.info(f"starting (python {sys.version.split()[0]})")

    if args.simulate:
        lcd = SimulatedLcd(cfg["screen"]["orientation"], bytes_per_second=cfg["app"]["link_kbps"] * 1024)
    else:
        if not single_instance():
            if args.benchmark:
                print("The app is running - quit it first (tray icon > Quit), then run the benchmark again.")
                return
            # ask the running copy to open its control panel, then exit
            open(os.path.join(HERE, "open_panel.flag"), "w").close()
            log.info("already running - asked it to open the control panel")
            return
        if args.benchmark:
            benchmark(cfg)
            return
        lcd = TuringRevA(cfg["screen"]["port"], cfg["screen"]["orientation"],
                         cfg["screen"]["chunk_size"], cfg["screen"]["flow_control"])

    app = App(cfg, lcd, simulate=args.simulate)
    power_events.start(app.on_power, log=log.info)

    on_frame = None
    if args.simulate:
        os.makedirs(os.path.join(HERE, "previews"), exist_ok=True)

        def on_frame():
            lcd.glass().save(os.path.join(HERE, "previews", "preview.png"))

    worker = threading.Thread(target=app.run, kwargs={"duration": args.seconds, "on_frame": on_frame},
                              daemon=True, name="render")
    worker.start()

    panel = None
    if not args.no_ui:
        try:
            import ui
            panel = ui.ControlPanel(app, show=not args.quiet)
        except Exception as e:
            log.warning(f"control panel unavailable ({e!r}) - use the tray icon")
    tray = start_tray(app, panel.request_open if panel else None) if cfg["app"]["tray"] and not args.simulate else None

    try:
        if panel:
            panel.mainloop(worker)  # returns when the app stops
        else:
            while worker.is_alive():
                worker.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        worker.join(5)
        app.shutdown()
        if tray:
            try:
                tray.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
