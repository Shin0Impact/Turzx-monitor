"""Full-screen pages. Each page draws a complete frame; the app sends only the pixels that changed."""
import time
from datetime import datetime

from PIL import Image, ImageDraw

from render import (BG, CPU_C, DIM, DOWN_C, EDGE, FAINT, GPU_C, RAM_C, SUB, TEXT, UP_C, Dashboard, bar, font,
                    fmt_temp, graph, mix, temp_color, text_right, arrow)

MODES = {
    "stats": "Big stats",
    "detail": "Detailed stats",
    "gif": "GIF",
    "clock": "Clock",
}


def bold(size):
    return font("Roboto-Bold.ttf", size)


def medium(size):
    return font("Roboto-Medium.ttf", size)


def light(size):
    return font("Roboto-Light.ttf", size)


def rate_parts(b):
    """Bytes/s -> ("7.7", "MB/s")"""
    if b is None:
        return "--", ""
    for unit, div in (("GB/s", 2**30), ("MB/s", 2**20), ("KB/s", 2**10)):
        if b >= div * 0.95:
            v = b / div
            return (f"{v:.1f}" if v < 100 else f"{v:.0f}"), unit
    return f"{b:.0f}", "B/s"


class Calm:
    """Holds displayed values steady until the real value moves enough to matter.
    Every redraw is visible on this screen (it paints top to bottom), so fewer changes = calmer screen."""

    def __init__(self):
        self.shown = {}

    def abs(self, key, value, step):
        if value is None:
            self.shown.pop(key, None)
            return None
        old = self.shown.get(key)
        if old is None or abs(value - old) >= step:
            self.shown[key] = value
        return self.shown[key]

    def rel(self, key, value, ratio=0.25, floor=2048):
        """For network speeds: change when the value moves by more than `ratio`, ignoring tiny rates."""
        if value is None:
            return None
        old = self.shown.get(key)
        if old is None or abs(value - old) > max(old * ratio, floor):
            self.shown[key] = value
        return self.shown[key]


class Page:
    interval = 1.0

    def __init__(self, size, cfg):
        self.W, self.H = size
        self.cfg = cfg
        self.unit = cfg.get("temp_unit", "C")
        self.h24 = cfg.get("clock_24h", True)

    def new(self):
        return Image.new("RGB", (self.W, self.H), BG)

    def hhmm(self, now):
        if self.h24:
            return now.strftime("%H"), now.strftime("%M")
        return now.strftime("%I").lstrip("0") or "12", now.strftime("%M")


class DetailPage(Page):
    """The original dashboard, using the whole screen."""

    def __init__(self, size, cfg):
        super().__init__(size, cfg)
        self.dash = Dashboard(size, {**cfg, "gif_enabled": False})

    def render(self, data, hist):
        return self.dash.draw(data, hist)


BIG_ITEMS = {"clock": "Clock & date", "cpu": "CPU", "gpu": "GPU", "ram": "RAM", "net": "Network"}
BIG_DEFAULTS = {"clock": True, "cpu": True, "gpu": True, "ram": True, "net": False}


def pct(v):
    """06 instead of 6 (keeps the number the same width, so changing it repaints less)."""
    return "--" if v is None else f"{v:02.0f}"


class BigStatsPage(Page):
    """Few values, very large, readable from across the desk. Each item can be turned off; the rest grow
    to fill the screen. Values are held steady (Calm) so the screen only repaints on real changes."""

    def __init__(self, size, cfg):
        super().__init__(size, cfg)
        self.calm = Calm()
        self.calm_on = cfg.get("calm", True)
        show = {**BIG_DEFAULTS, **(cfg.get("bigstats") or {})}
        self.show_clock = show["clock"]
        self.items = [k for k in ("cpu", "gpu", "ram", "net") if show[k]]
        self._layout()

    def _layout(self):
        W, H = self.W, self.H
        n = len(self.items)
        portrait = W < H
        self.header_h = 0
        if self.show_clock:
            self.header_h = (H if n == 0 else (74 if portrait else 62))
        top = self.header_h
        avail = H - top
        boxes = []
        if n:
            if portrait:
                rh = avail // n
                boxes = [(0, top + i * rh, W, rh) for i in range(n)]
            else:
                if n == 4:
                    rh = avail // 2
                    boxes = [(0, top, W // 2, rh), (W // 2, top, W // 2, rh),
                             (0, top + rh, W // 2, rh), (W // 2, top + rh, W // 2, rh)]
                else:
                    cw = W // n
                    boxes = [(i * cw, top, cw, avail) for i in range(n)]
        self.boxes = dict(zip(self.items, boxes))

    # ----- values -----
    def _values(self, data):
        g = data.get("gpu") or {}
        c = self.calm
        raw = {
            "cpu": data.get("cpu_load"), "cput": data.get("cpu_temp"), "clk": data.get("cpu_clock"),
            "gpu": g.get("load"), "gput": g.get("temp"), "gpw": g.get("power"),
            "ram": data.get("ram_pct"), "ramu": data.get("ram_used"), "ramt": data.get("ram_total"),
            "down": data.get("down"), "up": data.get("up"),
        }
        if not self.calm_on:
            return raw
        steps = {"cpu": 3, "cput": 1.5, "clk": 300, "gpu": 3, "gput": 1.5, "gpw": 10, "ram": 1, "ramu": 0.2}
        out = dict(raw)
        for k, step in steps.items():
            out[k] = c.abs(k, raw[k], step)
        out["down"], out["up"] = c.rel("down", raw["down"]), c.rel("up", raw["up"])
        return out

    # ----- drawing -----
    def render(self, data, hist):
        img = self.new()
        d = ImageDraw.Draw(img)
        v = self._values(data)
        if self.show_clock:
            self._header(d)
        for k, box in self.boxes.items():
            x, y, w, h = box
            if y > 0:
                d.line((x + 10, y, x + w - 10, y), fill=EDGE)
            if x > 0:
                d.line((x, y + 10, x, y + h - 10), fill=EDGE)
            if k == "cpu":
                if v["cput"] is None and v["clk"]:  # no temperature on this PC: show the clock speed instead
                    wide = box[2] >= 300
                    self._row(d, box, "CPU", CPU_C, pct(v["cpu"]), "%", f"{v['clk'] / 1000:.1f}" if wide else f"{v['clk'] / 1000:.1f} GHz",
                              TEXT, "GHz", (v["cpu"] or 0) / 100)
                else:
                    self._load(d, box, "CPU", CPU_C, v["cpu"], v["cput"], f"{v['clk'] / 1000:.1f} GHz" if v["clk"] else "")
            elif k == "gpu":
                self._load(d, box, "GPU", GPU_C, v["gpu"], v["gput"], f"{v['gpw']:.0f} W" if v["gpw"] is not None else "")
            elif k == "ram":
                self._ram(d, box, v)
            elif k == "net":
                self._net(d, box, v)
        return img

    def _header(self, d):
        now = datetime.now()
        hh, mm = self.hhmm(now)
        t = f"{hh}:{mm}"
        if not self.items:  # nothing else on: a full clock
            f = bold(110 if self.W < self.H else 120)
            d.text(((self.W - d.textlength(t, font=f)) / 2, self.H * 0.28), t, font=f, fill=TEXT)
            day = now.strftime("%A  %d %B")
            fd = medium(26)
            d.text(((self.W - d.textlength(day, font=fd)) / 2, self.H * 0.28 + 140), day, font=fd, fill=SUB)
            return
        h = self.header_h
        f = bold(int(h * 0.72))
        d.text((10, (h - f.size) / 2 - f.size * 0.08), t, font=f, fill=TEXT)
        day = now.strftime("%A")
        date = now.strftime("%d %b")
        fs = medium(int(h * 0.3))
        text_right(d, self.W - 10, h * 0.12, day, fs, TEXT)
        text_right(d, self.W - 10, h * 0.12 + fs.size * 1.15, date, fs, SUB)

    # ----- one row / tile, fitted to its box -----
    @staticmethod
    def _cap(f):
        """(top offset, height) of digits for a font: lets us place text by its visible top."""
        l, t, r, b = f.getbbox("0123456789")
        return t, b - t

    def _vtext(self, d, x, top, text, f, fill, right=False):
        t, _ = self._cap(f)
        if right:
            x -= d.textlength(text, font=f)
        d.text((x, top - t), text, font=f, fill=fill)

    def _row(self, d, box, label, col, num, suffix, right, right_col, sub, frac, label_arrow=None, right_arrow=None):
        x, y, w, h = box
        wide = w >= 300
        s = h / 111 if wide else min(h / 145, w / 200)
        x0, x1 = x + 12, x + w - 12
        pad = max(6, int(8 * s))
        L = bold(max(14, min(30, int(20 * s))))
        lt, lh = self._cap(L)
        lx = x0
        if label_arrow:
            arrow(d, x0, y + pad + lh * 0.1, False, label_arrow, int(lh * 0.9))
            lx = x0 + lh * 1.25
        self._vtext(d, lx, y + pad, label, L, col)
        bar_h = max(6, min(14, int(9 * s)))
        by = y + h - pad - bar_h
        zt = y + pad + lh + pad
        zb = (by - pad) if frac is not None else (y + h - pad)
        zh = zb - zt
        if not wide and right:  # tiles: secondary value on the label line
            R = bold(max(14, min(34, int(L.size * 1.25))))
            rw = d.textlength(right, font=R)
            if rw > (x1 - lx) - d.textlength(label, font=L) - 10:
                R = bold(L.size)
            self._vtext(d, x1, y + pad + lh - self._cap(R)[1], right, R, right_col, right=True)
        # number size: fill the zone height, then shrink until everything fits the width
        size = int(min(140, zh / 0.73))
        while size > 16:
            F = bold(size)
            Sf = bold(max(12, int(size * 0.4)))
            nw = d.textlength(num, font=F) + (d.textlength(suffix, font=Sf) + 4 if suffix else 0)
            rw = 0
            if wide and right:
                rw = d.textlength(right, font=bold(int(size * 0.62))) + (size * 0.4 if right_arrow else 0) + 14
            if nw + rw <= x1 - x0:
                break
            size -= 2
        F = bold(size)
        nt, nh = self._cap(F)
        top = zt + (zh - nh) / 2
        self._vtext(d, x0 - 2, top, num, F, TEXT)
        if suffix:
            Sf = bold(max(12, int(size * 0.4)))
            st, sh = self._cap(Sf)
            self._vtext(d, x0 - 2 + d.textlength(num, font=F) + 4, top + nh - sh, suffix, Sf, SUB)
        if wide and right:
            T = bold(int(size * 0.62))
            tt, th = self._cap(T)
            S = medium(max(12, int(size * 0.25)))
            sth = self._cap(S)[1] if sub else 0
            block = th + (th * 0.4 + sth if sub else 0)
            rt = zt + (zh - block) / 2
            self._vtext(d, x1, rt, right, T, right_col, right=True)
            if right_arrow:
                aw = d.textlength(right, font=T)
                arrow(d, x1 - aw - th * 0.75, rt + th * 0.15, True, right_arrow, int(th * 0.6))
            if sub:
                self._vtext(d, x1, rt + th * 1.4, sub, S, SUB, right=True)
        if frac is not None:
            bar(d, x0, by, x1 - x0, bar_h, frac, col)

    def _load(self, d, box, label, col, load, temp, sub):
        self._row(d, box, label, col, pct(load), "%", fmt_temp(temp, self.unit), temp_color(temp), sub,
                  (load or 0) / 100)

    def _ram(self, d, box, v):
        used = v["ramu"]
        wide = box[2] >= 300
        right = None if used is None else (f"{used:.1f}" if wide else f"{used:.1f} GB")
        sub = f"of {v['ramt']:.0f} GB" if used is not None and v.get("ramt") else ""
        self._row(d, box, "RAM", RAM_C, pct(v["ram"]), "%", right, TEXT, sub, (v["ram"] or 0) / 100)

    def _net(self, d, box, v):
        val, unit = rate_parts(v["down"])
        uv, uunit = rate_parts(v["up"])
        self._row(d, box, "NET", DOWN_C, val, unit, f"{uv} {uunit}", TEXT, "upload", None,
                  label_arrow=DOWN_C, right_arrow=UP_C)


class ClockPage(Page):
    """Big clock. Minutes change one digit pair; the seconds bar is a few hundred bytes per tick."""

    def __init__(self, size, cfg):
        super().__init__(size, cfg)
        self.seconds = cfg.get("clock_seconds", True)
        self.accent = tuple(cfg.get("clock_accent", CPU_C))

    def render(self, data=None, hist=None):
        img = self.new()
        d = ImageDraw.Draw(img)
        now = datetime.now()
        hh, mm = self.hhmm(now)
        date = now.strftime("%A")
        date2 = now.strftime("%d %B")
        if self.W < self.H:  # stacked digits
            f = light(205)
            for i, (txt, col) in enumerate(((hh, TEXT), (mm, self.accent))):
                w = d.textlength(txt, font=f)
                d.text(((self.W - w) / 2, -28 + i * 182), txt, font=f, fill=col)
            fy = 392
        else:
            f = light(150)
            s = f"{hh}:{mm}"
            w = d.textlength(s, font=f)
            d.text(((self.W - w) / 2, 10), s, font=f, fill=TEXT)
            fy = 212
        fd = medium(30)
        d.text(((self.W - d.textlength(date, font=fd)) / 2, fy), date, font=fd, fill=TEXT)
        fd2 = medium(24)
        d.text(((self.W - d.textlength(date2, font=fd2)) / 2, fy + 38), date2, font=fd2, fill=SUB)
        if not self.h24:
            ap = now.strftime("%p")
            d.text((self.W - 44, 10), ap, font=medium(18), fill=DIM)
        if self.seconds:
            frac = now.second / 59
            y = self.H - 8
            d.rectangle((0, y, self.W - 1, self.H - 1), fill=FAINT)
            d.rectangle((0, y, int((self.W - 1) * frac), self.H - 1), fill=self.accent)
        return img


def make_page(mode, size, cfg):
    if mode == "detail":
        return DetailPage(size, cfg)
    if mode == "clock":
        return ClockPage(size, cfg)
    return BigStatsPage(size, cfg)
