"""Everything at once: per-core load, graphs, VRAM, drives, disk and network speeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw

from ..sensors import History, Sample
from .base import View, ViewOptions
from .theme import (
    BG,
    CARD,
    CPU_C,
    DIM,
    DISK_C,
    DOWN_C,
    EDGE,
    FAINT,
    GPU_C,
    RAM_C,
    SUB,
    TEXT,
    UP_C,
    WARN,
    Color,
    arrow,
    bar,
    fmt_rate,
    fmt_rate_short,
    fmt_temp,
    fmt_uptime,
    graph,
    mono,
    pct,
    sans,
    temp_color,
    text_right,
)

CARD_PADDING = 10


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def inner(self) -> tuple[int, int, int]:
        """(left, right, top) of the content area of a card."""
        return self.x + CARD_PADDING, self.x + self.w - 8, self.y + 6


def draw_card(d: ImageDraw.ImageDraw, box: Box, accent: Color | None = None) -> None:
    d.rounded_rectangle((box.x, box.y, box.x + box.w - 1, box.y + box.h - 1), radius=8, fill=CARD, outline=EDGE)
    if accent:
        d.rounded_rectangle((box.x, box.y + 8, box.x + 2, box.y + box.h - 9), radius=1, fill=accent)


def draw_core_bars(d: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, cores: tuple[float, ...]) -> None:
    gap = 1 if len(cores) > 24 else 2
    width = max(2.0, (w - gap * (len(cores) - 1)) / max(len(cores), 1))
    for i, load in enumerate(cores):
        left = x + i * (width + gap)
        d.rectangle((left, y, left + width - 1, y + h - 1), fill=FAINT)
        filled = int(h * min(load, 100) / 100)
        if filled:
            d.rectangle((left, y + h - filled, left + width - 1, y + h - 1), fill=CPU_C if load < 90 else WARN)


class DetailView(View):
    def __init__(self, size: tuple[int, int], options: ViewOptions) -> None:
        super().__init__(size, options)
        self.boxes = self._portrait_layout() if self.portrait else self._landscape_layout()

    def _portrait_layout(self) -> dict[str, Box]:
        w, h = self.width, self.height
        scale = h / 330  # sized for 330 px of stats and stretched to the full height
        header_h, cpu_h, gpu_h, row_h = (int(v * scale) for v in (42, 104, 82, 46))
        half = (w - 12) // 2
        y = header_h
        boxes = {"header": Box(0, 0, w, header_h), "cpu": Box(4, y, w - 8, cpu_h)}
        y += cpu_h + 4
        boxes["gpu"] = Box(4, y, w - 8, gpu_h)
        y += gpu_h + 4
        boxes["ram"] = Box(4, y, half, row_h)
        boxes["disk"] = Box(8 + half, y, w - 12 - half, row_h)
        y += row_h + 4
        boxes["net"] = Box(4, y, w - 8, h - y - 4)
        return boxes

    def _landscape_layout(self) -> dict[str, Box]:
        w, h = self.width, self.height
        left_w = 244
        right_w = w - left_w - 4
        half = (right_w - 4) // 2
        return {
            "header": Box(left_w, 0, w - left_w, 40),
            "cpu": Box(4, 4, left_w - 8, 156),
            "gpu": Box(4, 164, left_w - 8, h - 168),
            "ram": Box(left_w, 42, half, 46),
            "disk": Box(left_w + half + 4, 42, right_w - half - 4, 46),
            "net": Box(left_w, 92, right_w, h - 96),
        }

    def render(self, sample: Sample, history: History) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), BG)
        d = ImageDraw.Draw(img)
        self._header(d, sample)
        self._cpu(d, sample, history)
        self._gpu(d, sample, history)
        self._ram(d, sample)
        self._disk(d, sample)
        self._net(d, sample, history)
        return img

    def _header(self, d: ImageDraw.ImageDraw, s: Sample) -> None:
        b = self.boxes["header"]
        now = datetime.now()
        text = now.strftime("%H:%M") if self.options.clock_24h else now.strftime("%I:%M").lstrip("0")
        clock_font = mono(min(30, b.h - 8))
        d.text((b.x + 8, b.y + (b.h - clock_font.size) // 2 - 3), text, font=clock_font, fill=TEXT)
        d.text(
            (b.x + 10 + d.textlength(text, font=clock_font), b.y + b.h // 2 - 2),
            now.strftime(":%S"),
            font=mono(13),
            fill=DIM,
        )
        text_right(d, b.x + b.w - 8, b.y + 5, now.strftime("%a %d %b"), sans(13), TEXT)
        if s.uptime is not None:
            text_right(d, b.x + b.w - 8, b.y + 22, "up " + fmt_uptime(s.uptime), sans(11, "Regular"), DIM)

    def _card_title(self, d: ImageDraw.ImageDraw, b: Box, label: str, name: str, color: Color) -> None:
        left, _, top = b.inner
        d.text((left, top), label, font=sans(13, "Bold"), fill=color)
        d.text((left + 34, top + 1), name[:28], font=sans(11, "Regular"), fill=DIM)

    def _cpu(self, d: ImageDraw.ImageDraw, s: Sample, h: History) -> None:
        b = self.boxes["cpu"]
        draw_card(d, b, CPU_C)
        left, right, top = b.inner
        self._card_title(d, b, "CPU", s.cpu_name, CPU_C)
        d.text((left, top + 16), pct(s.cpu_load) + "%" if s.cpu_load is not None else "--", font=mono(30), fill=TEXT)
        info_x = left + 96
        clock = f"{s.cpu_clock / 1000:.2f}GHz" if s.cpu_clock else "--"
        d.text((info_x, top + 20), clock, font=mono(14), fill=TEXT)
        d.text((info_x, top + 38), f"{len(s.cores)} threads", font=sans(11, "Regular"), fill=SUB)
        graph_x = info_x + 116
        if right - graph_x > 30:
            graph(d, graph_x, top + 18, right - graph_x, 34, h.cpu[-30:], CPU_C)
        bars_top = top + 60
        bars_h = b.y + b.h - bars_top - 8
        if bars_h > 70:  # tall card (landscape): a big graph above the core bars
            graph_h = int(bars_h * 0.45)
            graph(d, left, bars_top, right - left, graph_h, h.cpu, CPU_C)
            bars_top += graph_h + 8
            bars_h -= graph_h + 8
        if bars_h >= 8:
            draw_core_bars(d, left, bars_top, right - left, bars_h, s.cores)

    def _gpu(self, d: ImageDraw.ImageDraw, s: Sample, h: History) -> None:
        b = self.boxes["gpu"]
        g = s.gpu
        draw_card(d, b, GPU_C)
        left, right, top = b.inner
        name = (g.name if g else "not found").replace("NVIDIA ", "").replace("GeForce ", "")
        self._card_title(d, b, "GPU", name, GPU_C)
        load = g.load if g else None
        d.text((left, top + 16), pct(load) + "%" if load is not None else "--", font=mono(30), fill=TEXT)
        info_x = left + 96
        temp = g.temp if g else None
        d.text((info_x, top + 20), fmt_temp(temp, self.options.temp_unit), font=mono(14), fill=temp_color(temp))
        power = g.power if g else None
        d.text((info_x + 46, top + 20), f"{power:.0f}W" if power is not None else "--", font=mono(14), fill=TEXT)
        extra = []
        if g and g.clock:
            extra.append(f"{g.clock:.0f} MHz")
        if g and g.fan is not None:
            extra.append(f"fan {g.fan:02.0f}%")
        d.text((info_x, top + 38), "  ".join(extra), font=sans(11, "Regular"), fill=SUB)
        graph_x = info_x + 116
        if right - graph_x > 30:
            graph(d, graph_x, top + 18, right - graph_x, 34, h.gpu[-30:], GPU_C)
        vram_y = b.y + b.h - 18
        free = vram_y - (top + 60) - 8
        if free > 24:  # tall card: a big graph
            graph(d, left, top + 60, right - left, free, h.gpu, GPU_C)
        if vram_y > top + 52:
            known = g is not None and g.mem_used is not None and g.mem_total
            label = f"VRAM {g.mem_used:.1f}/{g.mem_total:.0f}G" if known else "VRAM --"
            d.text((left, vram_y - 2), label, font=sans(11, "Regular"), fill=SUB)
            bar(d, left + 100, vram_y + 2, right - left - 100, 7, g.mem_used / g.mem_total if known else 0, GPU_C)

    def _ram(self, d: ImageDraw.ImageDraw, s: Sample) -> None:
        b = self.boxes["ram"]
        draw_card(d, b, RAM_C)
        left, right, _ = b.inner
        d.text((left, b.y + 5), "RAM", font=sans(12, "Bold"), fill=RAM_C)
        text_right(d, right, b.y + 4, pct(s.ram_percent) + "%" if s.ram_percent is not None else "--", mono(14), TEXT)
        if s.ram_used is not None:
            d.text((left, b.y + 21), f"{s.ram_used:.1f}/{s.ram_total:.0f} GB", font=sans(11, "Regular"), fill=SUB)
        bar(d, left, b.y + b.h - 11, right - left, 5, (s.ram_percent or 0) / 100, RAM_C)

    def _disk(self, d: ImageDraw.ImageDraw, s: Sample) -> None:
        b = self.boxes["disk"]
        draw_card(d, b, DISK_C)
        left, right, _ = b.inner
        small = sans(10, "Regular")
        d.text((left, b.y + 5), "DISK", font=sans(12, "Bold"), fill=DISK_C)
        if s.disk_read is not None:
            speeds = f"R {fmt_rate_short(s.disk_read)}  W {fmt_rate_short(s.disk_write)}"
            if d.textlength(speeds, font=small) < right - left - 38:
                text_right(d, right, b.y + 7, speeds, small, DIM)
        drives = s.drives[:3]
        if drives:
            width = (right - left - 6 * (len(drives) - 1)) / len(drives)
            for i, drive in enumerate(drives):
                x = int(left + i * (width + 6))
                full = drive.percent >= 90
                label = f"{drive.name[:6]} {drive.percent:.0f}%" if width > 40 else f"{drive.percent:.0f}%"
                d.text((x, b.y + 21), label, font=small, fill=WARN if full else TEXT)
                bar(d, x, b.y + b.h - 11, int(width), 5, drive.percent / 100, WARN if full else DISK_C)

    def _net(self, d: ImageDraw.ImageDraw, s: Sample, h: History) -> None:
        b = self.boxes["net"]
        draw_card(d, b)
        left, right, _ = b.inner
        wide = b.w > 200
        speed_font = mono(13)
        arrow(d, left, b.y + 8, False, DOWN_C)
        d.text((left + 15, b.y + 5), fmt_rate(s.down), font=speed_font, fill=TEXT)
        up_x, up_y = (b.x + b.w // 2, b.y + 5) if wide else (left, b.y + 21)
        arrow(d, up_x, up_y + 3, True, UP_C)
        d.text((up_x + 15, up_y), fmt_rate(s.up), font=speed_font, fill=TEXT)
        graph_y = up_y + 20
        graph_h = b.y + b.h - graph_y - 5
        if graph_h >= 8:
            peak = max(max(h.down), max(h.up), 1024.0)
            graph(d, left, graph_y, right - left, graph_h, h.down, DOWN_C, vmax=peak)
            graph(d, left, graph_y, right - left, graph_h, h.up, UP_C, vmax=peak, fill=False)
