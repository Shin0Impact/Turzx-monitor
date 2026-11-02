"""Few values, very large, readable from across the desk. Each item can be turned off; the rest grow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageDraw

from ..sensors import History, Sample
from .base import View, ViewOptions
from .theme import (
    CPU_C,
    DOWN_C,
    EDGE,
    GPU_C,
    RAM_C,
    SUB,
    TEXT,
    UP_C,
    Color,
    arrow,
    bar,
    bold,
    digit_metrics,
    fmt_temp,
    pct,
    rate_parts,
    sans,
    temp_color,
    text_at_digit_top,
    text_right,
)

ITEMS = {"clock": "Clock & date", "cpu": "CPU", "gpu": "GPU", "ram": "RAM", "net": "Network"}
ROW_ORDER = ("cpu", "gpu", "ram", "net")
WIDE_ROW = 300  # boxes at least this wide get the roomy layout


class Calm:
    """Holds a displayed value steady until the real one moves enough to matter.

    The screen paints each change top to bottom where you can see it, so fewer repaints look calmer.
    """

    def __init__(self) -> None:
        self._shown: dict[str, float] = {}

    def absolute(self, key: str, value: float | None, step: float) -> float | None:
        if value is None:
            self._shown.pop(key, None)
            return None
        if key not in self._shown or abs(value - self._shown[key]) >= step:
            self._shown[key] = value
        return self._shown[key]

    def relative(self, key: str, value: float | None, ratio: float = 0.25, floor: float = 2048) -> float | None:
        """For network speeds: update when the value moves by more than `ratio`, ignoring tiny rates."""
        if value is None:
            return None
        old = self._shown.get(key)
        if old is None or abs(value - old) > max(old * ratio, floor):
            self._shown[key] = value
        return self._shown[key]


@dataclass(frozen=True)
class Reading:
    """The values shown, after Calm has smoothed them."""

    cpu: float | None
    clock_mhz: float | None
    gpu: float | None
    gpu_temp: float | None
    gpu_power: float | None
    ram: float | None
    ram_used: float | None
    ram_total: float | None
    down: float | None
    up: float | None


@dataclass(frozen=True)
class Row:
    label: str
    color: Color
    number: str
    suffix: str
    right: str | None = None
    right_color: Color = TEXT
    sub: str = ""
    fraction: float | None = None
    down_arrow: bool = False
    up_arrow: bool = False


class BigStatsView(View):
    def __init__(self, size: tuple[int, int], options: ViewOptions) -> None:
        super().__init__(size, options)
        self._calm = Calm()
        self.show_clock = options.bigstats["clock"]
        self.rows = [key for key in ROW_ORDER if options.bigstats[key]]
        self.header_height = 0
        if self.show_clock:
            self.header_height = self.height if not self.rows else (74 if self.portrait else 62)
        self.boxes = self._layout()

    def _layout(self) -> dict[str, tuple[int, int, int, int]]:
        count = len(self.rows)
        if not count:
            return {}
        top, w, h = self.header_height, self.width, self.height
        avail = h - top
        if self.portrait:
            row_h = avail // count
            boxes = [(0, top + i * row_h, w, row_h) for i in range(count)]
        elif count == 4:
            half_w, half_h = w // 2, avail // 2
            boxes = [(x, top + y, half_w, half_h) for y in (0, half_h) for x in (0, half_w)]
        else:
            col_w = w // count
            boxes = [(i * col_w, top, col_w, avail) for i in range(count)]
        return dict(zip(self.rows, boxes, strict=True))

    # ---- values ----
    def _reading(self, s: Sample) -> Reading:
        g = s.gpu
        raw = Reading(
            s.cpu_load,
            s.cpu_clock,
            g.load if g else None,
            g.temp if g else None,
            g.power if g else None,
            s.ram_percent,
            s.ram_used,
            s.ram_total,
            s.down,
            s.up,
        )
        if not self.options.calm:
            return raw
        c = self._calm
        return Reading(
            cpu=c.absolute("cpu", raw.cpu, 3),
            clock_mhz=c.absolute("clock", raw.clock_mhz, 300),
            gpu=c.absolute("gpu", raw.gpu, 3),
            gpu_temp=c.absolute("gpu_temp", raw.gpu_temp, 1.5),
            gpu_power=c.absolute("gpu_power", raw.gpu_power, 10),
            ram=c.absolute("ram", raw.ram, 1),
            ram_used=c.absolute("ram_used", raw.ram_used, 0.2),
            ram_total=raw.ram_total,
            down=c.relative("down", raw.down),
            up=c.relative("up", raw.up),
        )

    def _row(self, key: str, r: Reading, wide: bool) -> Row:
        if key == "cpu":
            ghz = None if r.clock_mhz is None else r.clock_mhz / 1000
            right = None if ghz is None else (f"{ghz:.1f}" if wide else f"{ghz:.1f} GHz")
            return Row("CPU", CPU_C, pct(r.cpu), "%", right, TEXT, "GHz", (r.cpu or 0) / 100)
        if key == "gpu":
            power = "" if r.gpu_power is None else f"{r.gpu_power:.0f} W"
            return Row(
                "GPU",
                GPU_C,
                pct(r.gpu),
                "%",
                fmt_temp(r.gpu_temp, self.options.temp_unit),
                temp_color(r.gpu_temp),
                power,
                (r.gpu or 0) / 100,
            )
        if key == "ram":
            right = None if r.ram_used is None else (f"{r.ram_used:.1f}" if wide else f"{r.ram_used:.1f} GB")
            sub = f"of {r.ram_total:.0f} GB" if r.ram_used is not None and r.ram_total else ""
            return Row("RAM", RAM_C, pct(r.ram), "%", right, TEXT, sub, (r.ram or 0) / 100)
        down, down_unit = rate_parts(r.down)
        up, up_unit = rate_parts(r.up)
        return Row(
            "NET", DOWN_C, down, down_unit, f"{up} {up_unit}", TEXT, "upload", None, down_arrow=True, up_arrow=True
        )

    # ---- drawing ----
    def render(self, sample: Sample, history: History | None = None) -> Image.Image:
        img = self.blank()
        d = ImageDraw.Draw(img)
        reading = self._reading(sample)
        if self.show_clock:
            self._draw_header(d)
        for key, box in self.boxes.items():
            x, y, w, h = box
            if y > 0:
                d.line((x + 10, y, x + w - 10, y), fill=EDGE)
            if x > 0:
                d.line((x, y + 10, x, y + h - 10), fill=EDGE)
            self._draw_row(d, box, self._row(key, reading, w >= WIDE_ROW))
        return img

    def _draw_header(self, d: ImageDraw.ImageDraw) -> None:
        now = datetime.now()
        hours, minutes = self.hour_minute(now)
        text = f"{hours}:{minutes}"
        if not self.rows:  # nothing else is on: a full-screen clock
            fnt = bold(110 if self.portrait else 120)
            top = self.height * 0.28
            d.text(((self.width - d.textlength(text, font=fnt)) / 2, top), text, font=fnt, fill=TEXT)
            day = now.strftime("%A  %d %B")
            small = sans(26)
            d.text(((self.width - d.textlength(day, font=small)) / 2, top + 140), day, font=small, fill=SUB)
            return
        h = self.header_height
        fnt = bold(int(h * 0.72))
        d.text((10, (h - fnt.size) / 2 - fnt.size * 0.08), text, font=fnt, fill=TEXT)
        small = sans(int(h * 0.3))
        text_right(d, self.width - 10, h * 0.12, now.strftime("%A"), small, TEXT)
        text_right(d, self.width - 10, h * 0.12 + small.size * 1.15, now.strftime("%d %b"), small, SUB)

    def _draw_row(self, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], row: Row) -> None:
        """One row (wide box) or tile (narrow box), sized to fill its box."""
        x, y, w, h = box
        wide = w >= WIDE_ROW
        scale = h / 111 if wide else min(h / 145, w / 200)
        left, right_edge = x + 12, x + w - 12
        pad = max(6, int(8 * scale))
        label_font = bold(max(14, min(30, int(20 * scale))))
        _, label_h = digit_metrics(label_font)
        label_x = left
        if row.down_arrow:
            arrow(d, left, y + pad + label_h * 0.1, False, DOWN_C, int(label_h * 0.9))
            label_x = left + label_h * 1.25
        text_at_digit_top(d, label_x, y + pad, row.label, label_font, row.color)

        bar_h = max(6, min(14, int(9 * scale)))
        bar_y = y + h - pad - bar_h
        zone_top = y + pad + label_h + pad
        zone_bottom = (bar_y - pad) if row.fraction is not None else (y + h - pad)
        zone_h = zone_bottom - zone_top

        if not wide and row.right:  # tiles: the secondary value shares the label's line
            fnt = bold(max(14, min(34, int(label_font.size * 1.25))))
            if (
                d.textlength(row.right, font=fnt)
                > (right_edge - label_x) - d.textlength(row.label, font=label_font) - 10
            ):
                fnt = bold(label_font.size)
            text_at_digit_top(
                d,
                right_edge,
                y + pad + label_h - digit_metrics(fnt)[1],
                row.right,
                fnt,
                row.right_color,
                right_aligned=True,
            )

        size = self._fit_number(d, row, int(min(140, zone_h / 0.73)), right_edge - left, wide)
        number_font = bold(size)
        suffix_font = bold(max(12, int(size * 0.4)))
        _, number_h = digit_metrics(number_font)
        number_top = zone_top + (zone_h - number_h) / 2
        text_at_digit_top(d, left - 2, number_top, row.number, number_font, TEXT)
        if row.suffix:
            _, suffix_h = digit_metrics(suffix_font)
            text_at_digit_top(
                d,
                left - 2 + d.textlength(row.number, font=number_font) + 4,
                number_top + number_h - suffix_h,
                row.suffix,
                suffix_font,
                SUB,
            )
        if wide and row.right:
            self._draw_side_value(d, row, size, zone_top, zone_h, right_edge)
        if row.fraction is not None:
            bar(d, left, bar_y, right_edge - left, bar_h, row.fraction, row.color)

    @staticmethod
    def _fit_number(d: ImageDraw.ImageDraw, row: Row, size: int, available: float, wide: bool) -> int:
        """Largest font size at which the number (and the side value, in wide rows) fit the width."""
        while size > 16:
            suffix_font = bold(max(12, int(size * 0.4)))
            number_w = d.textlength(row.number, font=bold(size))
            if row.suffix:
                number_w += d.textlength(row.suffix, font=suffix_font) + 4
            side_w = 0.0
            if wide and row.right:
                side_w = d.textlength(row.right, font=bold(int(size * 0.62))) + 14
                side_w += size * 0.4 if row.up_arrow else 0
            if number_w + side_w <= available:
                break
            size -= 2
        return size

    @staticmethod
    def _draw_side_value(
        d: ImageDraw.ImageDraw, row: Row, size: int, zone_top: float, zone_h: float, right_edge: float
    ) -> None:
        """Right column of a wide row: the value, with a caption under it."""
        value_font = bold(int(size * 0.62))
        caption_font = sans(max(12, int(size * 0.25)))
        _, value_h = digit_metrics(value_font)
        caption_h = digit_metrics(caption_font)[1] if row.sub else 0
        block_h = value_h + (value_h * 0.4 + caption_h if row.sub else 0)
        top = zone_top + (zone_h - block_h) / 2
        text_at_digit_top(d, right_edge, top, row.right, value_font, row.right_color, right_aligned=True)
        if row.up_arrow:
            width = d.textlength(row.right, font=value_font)
            arrow(d, right_edge - width - value_h * 0.75, top + value_h * 0.15, True, UP_C, int(value_h * 0.6))
        if row.sub:
            text_at_digit_top(d, right_edge, top + value_h * 1.4, row.sub, caption_font, SUB, right_aligned=True)
