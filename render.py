"""Draws the dashboard into a PIL image. Layouts for portrait (320x480) and landscape (480x320)."""
import os
import time
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")

BG = (8, 10, 15)
CARD = (18, 22, 31)
EDGE = (32, 38, 52)
TEXT = (232, 236, 244)
DIM = (128, 138, 158)
FAINT = (58, 66, 84)
CPU_C = (56, 189, 248)
GPU_C = (118, 227, 95)
RAM_C = (167, 139, 250)
DISK_C = (251, 191, 36)
DOWN_C = (45, 212, 191)
UP_C = (244, 114, 182)
WARN = (251, 146, 60)
HOT = (248, 80, 80)

_fonts = {}


def font(name, size):
    key = (name, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    return _fonts[key]


def mono(size):
    return font("JetBrainsMono-Bold.ttf", size)


def sans(size, weight="Medium"):
    return font(f"Roboto-{weight}.ttf", size)


def mix(c, bg, a):
    return tuple(int(c[i] * a + bg[i] * (1 - a)) for i in range(3))


def temp_color(t, base=TEXT):
    if t is None:
        return DIM
    if t >= 85:
        return HOT
    if t >= 70:
        return WARN
    return base


def fmt_rate(b):
    if b is None:
        return "--"
    for unit, div in (("GB/s", 2**30), ("MB/s", 2**20), ("KB/s", 2**10)):
        if b >= div * 0.95:
            v = b / div
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{b:.0f} B/s"


def fmt_rate_short(b):
    if b is None:
        return "--"
    for unit, div in (("G", 2**30), ("M", 2**20), ("K", 2**10)):
        if b >= div * 0.95:
            v = b / div
            return f"{v:.1f}{unit}" if v < 10 else f"{v:.0f}{unit}"
    return f"{b:.0f}B"


def arrow(d, x, y, up, color, size=10):
    """Triangle arrow (Roboto has no arrow glyphs)."""
    h = size
    if up:
        d.polygon([(x, y + h), (x + h, y + h), (x + h / 2, y)], fill=color)
    else:
        d.polygon([(x, y), (x + h, y), (x + h / 2, y + h)], fill=color)


def fmt_uptime(s):
    d, s = divmod(int(s), 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    return f"{d}d {h}h {m:02d}m" if d else f"{h}h {m:02d}m"


def fmt_temp(t, unit="C"):
    if t is None:
        return "--°"
    if unit.upper() == "F":
        t = t * 9 / 5 + 32
    return f"{t:.0f}°"


class Box:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def rect(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def card(d, b: Box, accent=None):
    d.rounded_rectangle((b.x, b.y, b.x + b.w - 1, b.y + b.h - 1), radius=8, fill=CARD, outline=EDGE)
    if accent:
        d.rounded_rectangle((b.x, b.y + 8, b.x + 2, b.y + b.h - 9), radius=1, fill=accent)


def bar(d, x, y, w, h, frac, color, bg=FAINT):
    frac = 0 if frac is None else max(0.0, min(1.0, frac))
    r = h // 2
    d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=r, fill=bg)
    if frac > 0:
        fw = max(h, int(w * frac))
        d.rounded_rectangle((x, y, x + fw - 1, y + h - 1), radius=r, fill=color)


def graph(d, x, y, w, h, values, color, vmax=100.0, autoscale=False, fill=True):
    if not values:
        return
    if autoscale:
        vmax = max(max(values), 1.0)
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        px = x + (w - 1) * i / max(n - 1, 1)
        py = y + h - 1 - (h - 1) * min(max(v, 0) / vmax, 1.0)
        pts.append((px, py))
    if fill:
        d.polygon([(x, y + h - 1)] + pts + [(x + w - 1, y + h - 1)], fill=mix(color, CARD, 0.22))
    d.line(pts, fill=color, width=2, joint="curve")


def text_right(d, xr, y, s, f, fill):
    d.text((xr - d.textlength(s, font=f), y), s, font=f, fill=fill)


def core_bars(d, x, y, w, h, cores, color):
    n = len(cores) or 1
    gap = 1 if n > 24 else 2
    bw = max(2, (w - gap * (n - 1)) / n)
    for i, c in enumerate(cores):
        bx = x + i * (bw + gap)
        d.rectangle((bx, y, bx + bw - 1, y + h - 1), fill=FAINT)
        fh = int(h * min(c, 100) / 100)
        if fh:
            col = color if c < 90 else WARN
            d.rectangle((bx, y + h - fh, bx + bw - 1, y + h - 1), fill=col)


class Dashboard:
    def __init__(self, size, cfg):
        self.W, self.H = size
        self.cfg = cfg
        self.unit = cfg.get("temp_unit", "C")
        self.h24 = cfg.get("clock_24h", True)
        self.gif_on = cfg.get("gif_enabled", True)
        if self.W < self.H:
            self._portrait()
        else:
            self._landscape()

    # ---------- layouts ----------
    def _portrait(self):
        W = self.W
        gif_h = self.cfg.get("gif_height", 150) if self.gif_on else 0
        self.gif_box = Box(0, self.H - gif_h, W, gif_h) if gif_h else None
        avail = self.H - gif_h
        # base heights designed for 330px of stats, stretched if the GIF panel is off
        s = avail / 330
        y = 0
        self.header = Box(0, y, W, int(42 * s)); y += self.header.h
        self.cpu = Box(4, y, W - 8, int(104 * s)); y += self.cpu.h + 4
        self.gpu = Box(4, y, W - 8, int(82 * s)); y += self.gpu.h + 4
        half = (W - 12) // 2
        rh = int(46 * s)
        self.ram = Box(4, y, half, rh)
        self.disk = Box(8 + half, y, W - 12 - half, rh); y += rh + 4
        self.net = Box(4, y, W - 8, avail - y - 4)
        self.panels = [self.header, self.cpu, self.gpu, self.ram, self.disk, self.net]

    def _landscape(self):
        W, H = self.W, self.H  # 480 x 320
        lw = 244
        self.header = Box(lw, 0, W - lw, 40)
        self.cpu = Box(4, 4, lw - 8, 156)
        self.gpu = Box(4, 164, lw - 8, H - 168)
        rw = W - lw - 4
        y = 42
        half = (rw - 4) // 2
        self.ram = Box(lw, y, half, 46)
        self.disk = Box(lw + half + 4, y, rw - half - 4, 46); y += 50
        gif_h = 136 if self.gif_on else 0
        self.net = Box(lw, y, rw, H - y - 4 - gif_h - (4 if gif_h else 0))
        self.gif_box = Box(lw, H - gif_h - 4, rw, gif_h) if gif_h else None
        self.panels = [self.header, self.cpu, self.gpu, self.ram, self.disk, self.net]

    # ---------- drawing ----------
    def draw(self, data, hist, gif_frame=None):
        img = Image.new("RGB", (self.W, self.H), BG)
        d = ImageDraw.Draw(img)
        self._header(d, data)
        self._cpu(d, data, hist)
        self._gpu(d, data, hist)
        self._ram(d, data)
        self._disk(d, data)
        self._net(d, data, hist)
        if self.gif_box and gif_frame is not None:
            img.paste(gif_frame, (self.gif_box.x, self.gif_box.y))
        return img

    def _header(self, d, data):
        b = self.header
        now = datetime.now()
        t = now.strftime("%H:%M") if self.h24 else now.strftime("%I:%M").lstrip("0")
        big = mono(min(30, b.h - 8))
        d.text((b.x + 8, b.y + (b.h - big.size) // 2 - 3), t, font=big, fill=TEXT)
        tw = d.textlength(t, font=big)
        d.text((b.x + 10 + tw, b.y + b.h // 2 - 2), now.strftime(":%S"), font=mono(13), fill=DIM)
        f = sans(13)
        text_right(d, b.x + b.w - 8, b.y + 5, now.strftime("%a %d %b"), f, TEXT)
        up = data.get("uptime")
        if up is not None:
            text_right(d, b.x + b.w - 8, b.y + 22, "up " + fmt_uptime(up), sans(11, "Regular"), DIM)

    def _cpu(self, d, data, hist):
        b = self.cpu
        card(d, b, CPU_C)
        x0, y0, x1 = b.x + 10, b.y + 6, b.x + b.w - 8
        d.text((x0, y0), "CPU", font=sans(13, "Bold"), fill=CPU_C)
        d.text((x0 + 34, y0 + 1), (data.get("cpu_name") or "")[:28], font=sans(11, "Regular"), fill=DIM)
        load = data.get("cpu_load")
        temp = data.get("cpu_temp")
        big = mono(30)
        s = f"{load:.0f}%" if load is not None else "--"
        d.text((x0, y0 + 16), s, font=big, fill=TEXT)
        info_x = x0 + 96
        f = mono(14)
        d.text((info_x, y0 + 20), fmt_temp(temp, self.unit), font=f, fill=temp_color(temp))
        clk = data.get("cpu_clock")
        d.text((info_x + 46, y0 + 20), f"{clk / 1000:.2f}GHz" if clk else "--", font=f, fill=TEXT)
        pw = data.get("cpu_power")
        d.text((info_x, y0 + 38), f"{pw:.0f} W" if pw else ("LHM off" if temp is None else ""),
               font=sans(11, "Regular"), fill=DIM)
        # graph on the right part of the top row
        gx = info_x + 116
        if x1 - gx > 30:
            graph(d, gx, y0 + 18, x1 - gx, 34, hist["cpu"][-30:], CPU_C)
        cores = data.get("cores") or []
        top = y0 + 60
        ch = b.y + b.h - top - 8
        if ch > 70:  # tall card: big graph above the core bars
            gh = int(ch * 0.45)
            graph(d, x0, top, x1 - x0, gh, hist["cpu"], CPU_C)
            top += gh + 8
            ch -= gh + 8
        if ch >= 8:
            core_bars(d, x0, top, x1 - x0, ch, cores, CPU_C)

    def _gpu(self, d, data, hist):
        b = self.gpu
        card(d, b, GPU_C)
        g = data.get("gpu") or {}
        x0, y0, x1 = b.x + 10, b.y + 6, b.x + b.w - 8
        name = (data.get("gpu_name") or "not found").replace("NVIDIA ", "").replace("GeForce ", "")
        d.text((x0, y0), "GPU", font=sans(13, "Bold"), fill=GPU_C)
        d.text((x0 + 34, y0 + 1), name[:28], font=sans(11, "Regular"), fill=DIM)
        load = g.get("load")
        d.text((x0, y0 + 16), f"{load:.0f}%" if load is not None else "--", font=mono(30), fill=TEXT)
        info_x = x0 + 96
        f = mono(14)
        t = g.get("temp")
        d.text((info_x, y0 + 20), fmt_temp(t, self.unit), font=f, fill=temp_color(t))
        p = g.get("power")
        d.text((info_x + 46, y0 + 20), f"{p:.0f}W" if p is not None else "--", font=f, fill=TEXT)
        fan = g.get("fan")
        clk = g.get("clock")
        extra = []
        if clk:
            extra.append(f"{clk:.0f} MHz")
        if fan is not None:
            extra.append(f"fan {fan:.0f}%")
        d.text((info_x, y0 + 38), "  ".join(extra), font=sans(11, "Regular"), fill=DIM)
        gx = info_x + 116
        gh = 34
        if x1 - gx > 30:
            graph(d, gx, y0 + 18, x1 - gx, gh, hist["gpu"][-30:], GPU_C)
        # VRAM bar along the bottom
        mu, mt = g.get("mem_used"), g.get("mem_total")
        by = b.y + b.h - 18
        free = by - (y0 + 60) - 8
        if free > 24:  # tall card: big graph
            graph(d, x0, y0 + 60, x1 - x0, free, hist["gpu"], GPU_C)
        if by > y0 + 52:
            lab = f"VRAM {mu:.1f}/{mt:.0f}G" if mu is not None and mt else "VRAM --"
            d.text((x0, by - 2), lab, font=sans(11, "Regular"), fill=DIM)
            bx = x0 + 100
            bar(d, bx, by + 2, x1 - bx, 7, (mu / mt) if mu is not None and mt else 0, GPU_C)

    def _ram(self, d, data):
        b = self.ram
        card(d, b, RAM_C)
        x0, x1 = b.x + 10, b.x + b.w - 8
        d.text((x0, b.y + 5), "RAM", font=sans(12, "Bold"), fill=RAM_C)
        used, tot, pct = data.get("ram_used"), data.get("ram_total"), data.get("ram_pct")
        text_right(d, x1, b.y + 4, f"{pct:.0f}%" if pct is not None else "--", mono(14), TEXT)
        if used is not None:
            d.text((x0, b.y + 21), f"{used:.1f}/{tot:.0f} GB", font=sans(11, "Regular"), fill=DIM)
        bar(d, x0, b.y + b.h - 11, x1 - x0, 5, (pct or 0) / 100, RAM_C)

    def _disk(self, d, data):
        b = self.disk
        card(d, b, DISK_C)
        x0, x1 = b.x + 10, b.x + b.w - 8
        drives = (data.get("drives") or [])[:3]
        d.text((x0, b.y + 5), "DISK", font=sans(12, "Bold"), fill=DISK_C)
        r, w = data.get("disk_read"), data.get("disk_write")
        if r is not None:
            f = sans(10, "Regular")
            s_ = f"R {fmt_rate_short(r)}  W {fmt_rate_short(w)}"
            if d.textlength(s_, font=f) < x1 - x0 - 38:
                text_right(d, x1, b.y + 7, s_, f, DIM)
        n = len(drives)
        if n:
            bw = (x1 - x0 - 6 * (n - 1)) / n
            f = sans(10, "Regular")
            for i, dr in enumerate(drives):
                bx = int(x0 + i * (bw + 6))
                hot = dr["pct"] >= 90
                lab = f"{dr['name'][:6]} {dr['pct']:.0f}%" if bw > 40 else f"{dr['pct']:.0f}%"
                d.text((bx, b.y + 21), lab, font=f, fill=WARN if hot else TEXT)
                bar(d, bx, b.y + b.h - 11, int(bw), 5, dr["pct"] / 100, WARN if hot else DISK_C)

    def _net(self, d, data, hist):
        b = self.net
        card(d, b)
        x0, x1 = b.x + 10, b.x + b.w - 8
        f = mono(13)
        arrow(d, x0, b.y + 8, False, DOWN_C)
        d.text((x0 + 15, b.y + 5), fmt_rate(data.get("down")), font=f, fill=TEXT)
        mid = b.x + b.w // 2 if b.w > 200 else x0
        uy = b.y + 5 if b.w > 200 else b.y + 21
        arrow(d, mid, uy + 3, True, UP_C)
        d.text((mid + 15, uy), fmt_rate(data.get("up")), font=f, fill=TEXT)
        gy = uy + 20
        gh = b.y + b.h - gy - 5
        if gh >= 8:
            peak = max(max(hist["down"]), max(hist["up"]), 1024.0)
            graph(d, x0, gy, x1 - x0, gh, hist["down"], DOWN_C, vmax=peak)
            graph(d, x0, gy, x1 - x0, gh, hist["up"], UP_C, vmax=peak, fill=False)


def dirty_rects(old: Image.Image, new: Image.Image, box, merge_gap=6, col_gap=24, max_rects=10):
    """Rectangles inside `box` (x0,y0,x1,y1) where `new` differs from `old`.
    Splits into horizontal bands, then each band into column runs, so a changed number doesn't
    resend a whole row of the screen. Every byte counts: the screen only takes ~120 KB/s."""
    x0, y0, x1, y1 = box
    if old is None:
        return [box]
    a = np.asarray(old.crop(box))
    b = np.asarray(new.crop(box))
    diff = (a != b).any(axis=2)
    rows = np.flatnonzero(diff.any(axis=1))
    if rows.size == 0:
        return []

    def runs(idx, gap):
        out = []
        start = prev = idx[0]
        for r in idx[1:]:
            if r - prev > gap:
                out.append((start, prev))
                start = r
            prev = r
        out.append((start, prev))
        return out

    rects = []
    for r0, r1 in runs(rows, merge_gap):
        cols = np.flatnonzero(diff[r0:r1 + 1].any(axis=0))
        for c0, c1 in runs(cols, col_gap):
            rects.append((x0 + int(c0), y0 + int(r0), x0 + int(c1) + 1, y0 + int(r1) + 1))
    if len(rects) > max_rects:  # too fragmented: one box per band
        rects = []
        for r0, r1 in runs(rows, merge_gap):
            cols = np.flatnonzero(diff[r0:r1 + 1].any(axis=0))
            rects.append((x0 + int(cols[0]), y0 + int(r0), x0 + int(cols[-1]) + 1, y0 + int(r1) + 1))
    return rects
