"""Full-screen pages. Each page draws a complete frame; the app sends only the pixels that changed."""
import time
from datetime import datetime

from PIL import Image, ImageDraw

from render import (BG, CPU_C, DIM, DOWN_C, EDGE, FAINT, GPU_C, RAM_C, TEXT, UP_C, Dashboard, bar, font,
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


class BigStatsPage(Page):
    """Few values, very large, readable from across the desk. Values are held steady (Calm) so the
    screen only repaints when something really changed."""

    def __init__(self, size, cfg):
        super().__init__(size, cfg)
        self.calm = Calm()
        self.calm_on = cfg.get("calm", True)

    def render(self, data, hist):
        img = self.new()
        d = ImageDraw.Draw(img)
        now = datetime.now()
        g = data.get("gpu") or {}
        c = self.calm
        if self.calm_on:
            cpu_load = c.abs("cpu", data.get("cpu_load"), 3)
            cpu_temp = c.abs("cput", data.get("cpu_temp"), 1.5)
            clk = c.abs("clk", data.get("cpu_clock"), 300)
            gpu_load = c.abs("gpu", g.get("load"), 3)
            gpu_temp = c.abs("gput", g.get("temp"), 1.5)
            gpw = c.abs("gpw", g.get("power"), 10)
            data = {**data, "ram_pct": c.abs("ram", data.get("ram_pct"), 1),
                    "ram_used": c.abs("ramu", data.get("ram_used"), 0.2),
                    "down": c.rel("down", data.get("down")), "up": c.rel("up", data.get("up"))}
        else:
            cpu_load, cpu_temp, clk = data.get("cpu_load"), data.get("cpu_temp"), data.get("cpu_clock")
            gpu_load, gpu_temp, gpw = g.get("load"), g.get("temp"), g.get("power")
        rows = [
            ("CPU", CPU_C, cpu_load, cpu_temp, f"{clk / 1000:.1f} GHz" if clk else ""),
            ("GPU", GPU_C, gpu_load, gpu_temp, f"{gpw:.0f} W" if gpw is not None else ""),
        ]
        if self.W < self.H:  # portrait: header + 4 rows
            hh, mm = self.hhmm(now)
            d.text((10, 4), f"{hh}:{mm}", font=medium(24), fill=TEXT)
            text_right(d, self.W - 10, 8, now.strftime("%a %d %b"), medium(18), DIM)
            top, rh = 36, (self.H - 36) // 4
            boxes = [(0, top + i * rh, self.W, rh) for i in range(4)]
            big = 66
        else:  # landscape: 2 x 2 tiles
            top = 0
            rh = self.H // 2
            boxes = [(0, 0, self.W // 2, rh), (self.W // 2, 0, self.W // 2, rh),
                     (0, rh, self.W // 2, rh), (self.W // 2, rh, self.W // 2, rh)]
            big = 84
        self.num_y = 24 if self.W < self.H else 36
        for (label, col, load, temp, sub), box in zip(rows, boxes):
            self._load_row(d, box, label, col, load, temp, sub, big)
        self._ram_row(d, boxes[2], data, big)
        self._net_row(d, boxes[3], data, hist, big)
        # separators
        for x, y, w, h in boxes:
            if y > 0:
                d.line((x + 10, y, x + w - 10, y), fill=EDGE)
            if x > 0:
                d.line((x, y + 10, x, y + h - 10), fill=EDGE)
        return img

    def _number(self, d, x, y, value, size, suffix="%"):
        s = "--" if value is None else f"{value:.0f}"
        d.text((x, y), s, font=bold(size), fill=TEXT)
        w = d.textlength(s, font=bold(size))
        if value is not None and suffix:
            d.text((x + w + 3, y + size * 0.48), suffix, font=bold(size // 2 - 4), fill=DIM)

    def _load_row(self, d, box, label, col, load, temp, sub, big):
        x, y, w, h = box
        x0, x1 = x + 12, x + w - 12
        d.text((x0, y + 8), label, font=bold(20), fill=col)
        self._number(d, x0 - 3, y + self.num_y, load, big)
        compact = w < 300
        tsize = 30 if compact else 44
        ty = y + (8 if compact else 26)
        text_right(d, x1, ty, fmt_temp(temp, self.unit), bold(tsize), temp_color(temp))
        if sub and not compact:
            text_right(d, x1, y + 76, sub, medium(17), DIM)
        bar(d, x0, y + h - 16, x1 - x0, 9, (load or 0) / 100, col)

    def _ram_row(self, d, box, data, big):
        x, y, w, h = box
        x0, x1 = x + 12, x + w - 12
        d.text((x0, y + 8), "RAM", font=bold(20), fill=RAM_C)
        pct = data.get("ram_pct")
        self._number(d, x0 - 3, y + self.num_y, pct, big)
        used, tot = data.get("ram_used"), data.get("ram_total")
        if used is not None:
            compact = w < 300
            text_right(d, x1, y + (8 if compact else 26), f"{used:.1f}" + (" GB" if compact else ""),
                       bold(30 if compact else 44), TEXT)
            if not compact:
                text_right(d, x1, y + 76, f"of {tot:.0f} GB", medium(17), DIM)
        bar(d, x0, y + h - 16, x1 - x0, 9, (pct or 0) / 100, RAM_C)

    def _net_row(self, d, box, data, hist, big):
        x, y, w, h = box
        x0, x1 = x + 12, x + w - 12
        compact = w < 300
        arrow(d, x0, y + 12, False, DOWN_C, 13)
        d.text((x0 + 18, y + 8), "NET", font=bold(20), fill=DOWN_C)
        v, unit = rate_parts(data.get("down"))
        size = 54  # fixed size: a size change would repaint the whole row
        ny = y + 30 if not compact else y + self.num_y + 8
        d.text((x0 - 2, ny), v, font=bold(size), fill=TEXT)
        d.text((x0 + d.textlength(v, font=bold(size)) + 5, ny + size * 0.5), unit, font=bold(18), fill=DIM)
        uv, uunit = rate_parts(data.get("up"))
        us = f"{uv} {uunit}"
        f = bold(22 if compact else 28)
        uy = y + 8 if compact else y + 30
        text_right(d, x1, uy, us, f, TEXT)
        arrow(d, x1 - d.textlength(us, font=f) - 18, uy + (6 if compact else 8), True, UP_C, 12)
        if not compact:
            d.text((x1 - 60, uy + 40), "upload", font=medium(15), fill=DIM)


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
        fd = medium(26)
        d.text(((self.W - d.textlength(date, font=fd)) / 2, fy), date, font=fd, fill=TEXT)
        fd2 = medium(20)
        d.text(((self.W - d.textlength(date2, font=fd2)) / 2, fy + 34), date2, font=fd2, fill=DIM)
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
