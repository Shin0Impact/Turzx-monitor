"""Colours, fonts and small drawing helpers shared by the views."""

from __future__ import annotations

from functools import cache

from PIL import ImageDraw, ImageFont

from ..config import ASSETS_DIR

Color = tuple[int, int, int]

BG: Color = (8, 10, 15)
CARD: Color = (18, 22, 31)
EDGE: Color = (32, 38, 52)
FAINT: Color = (58, 66, 84)
TEXT: Color = (232, 236, 244)
SUB: Color = (208, 215, 230)  # secondary values: GHz, W, "of 31 GB"
DIM: Color = (165, 174, 194)  # labels
CPU_C: Color = (56, 189, 248)
GPU_C: Color = (118, 227, 95)
RAM_C: Color = (167, 139, 250)
DISK_C: Color = (251, 191, 36)
DOWN_C: Color = (45, 212, 191)
UP_C: Color = (244, 114, 182)
WARN: Color = (251, 146, 60)
HOT: Color = (248, 80, 80)


def parse_hex(value: str, default: Color = CPU_C) -> Color:
    """'#38bdf8' -> (56, 189, 248); anything malformed gives `default`."""
    try:
        text = value.lstrip("#")
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)) if len(text) == 6 else default
    except ValueError:
        return default


@cache
def font(file: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS_DIR / "fonts" / file), size)


def sans(size: int, weight: str = "Medium") -> ImageFont.FreeTypeFont:
    return font(f"Roboto-{weight}.ttf", size)


def bold(size: int) -> ImageFont.FreeTypeFont:
    return font("Roboto-Bold.ttf", size)


def light(size: int) -> ImageFont.FreeTypeFont:
    return font("Roboto-Light.ttf", size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return font("JetBrainsMono-Bold.ttf", size)


def mix(color: Color, background: Color, amount: float) -> Color:
    return tuple(int(color[i] * amount + background[i] * (1 - amount)) for i in range(3))  # type: ignore[return-value]


def temp_color(celsius: float | None) -> Color:
    if celsius is None:
        return DIM
    if celsius >= 85:
        return HOT
    if celsius >= 70:
        return WARN
    return TEXT


# ---- number formatting ----


def pct(value: float | None) -> str:
    """Two digits ('06'), so the number keeps its width and repaints less."""
    return "--" if value is None else f"{value:02.0f}"


def fmt_temp(celsius: float | None, unit: str = "C") -> str:
    if celsius is None:
        return "--°"
    return f"{celsius * 9 / 5 + 32 if unit.upper() == 'F' else celsius:.0f}°"


def rate_parts(bytes_per_s: float | None) -> tuple[str, str]:
    """7_700_000 -> ('7.3', 'MB/s')"""
    if bytes_per_s is None:
        return "--", ""
    for unit, size in (("GB/s", 2**30), ("MB/s", 2**20), ("KB/s", 2**10)):
        if bytes_per_s >= size * 0.95:
            value = bytes_per_s / size
            return (f"{value:.1f}" if value < 100 else f"{value:.0f}"), unit
    return f"{bytes_per_s:.0f}", "B/s"


def fmt_rate(bytes_per_s: float | None) -> str:
    value, unit = rate_parts(bytes_per_s)
    return f"{value} {unit}".strip()


def fmt_rate_short(bytes_per_s: float | None) -> str:
    if bytes_per_s is None:
        return "--"
    for unit, size in (("G", 2**30), ("M", 2**20), ("K", 2**10)):
        if bytes_per_s >= size * 0.95:
            value = bytes_per_s / size
            return f"{value:.1f}{unit}" if value < 10 else f"{value:.0f}{unit}"
    return f"{bytes_per_s:.0f}B"


def fmt_uptime(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d {hours}h {rest // 60:02d}m" if days else f"{hours}h {rest // 60:02d}m"


# ---- drawing ----


def text_right(d: ImageDraw.ImageDraw, x_right: float, y: float, text: str, fnt, fill: Color) -> None:
    d.text((x_right - d.textlength(text, font=fnt), y), text, font=fnt, fill=fill)


def digit_metrics(fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """(offset from the text origin to the top of the digits, height of the digits)."""
    _, top, _, bottom = fnt.getbbox("0123456789")
    return top, bottom - top


def text_at_digit_top(
    d: ImageDraw.ImageDraw, x: float, top: float, text: str, fnt, fill: Color, right_aligned: bool = False
) -> None:
    """Draw text so the visible top of its digits sits at `top` (fonts differ in their padding)."""
    offset, _ = digit_metrics(fnt)
    if right_aligned:
        x -= d.textlength(text, font=fnt)
    d.text((x, top - offset), text, font=fnt, fill=fill)


def bar(
    d: ImageDraw.ImageDraw,
    x: float,
    y: float,
    w: float,
    h: float,
    fraction: float | None,
    color: Color,
    background: Color = FAINT,
) -> None:
    fraction = 0.0 if fraction is None else max(0.0, min(1.0, fraction))
    radius = int(h) // 2
    d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, fill=background)
    if fraction > 0:
        d.rounded_rectangle((x, y, x + max(h, int(w * fraction)) - 1, y + h - 1), radius=radius, fill=color)


def graph(
    d: ImageDraw.ImageDraw,
    x: float,
    y: float,
    w: float,
    h: float,
    values: list[float],
    color: Color,
    vmax: float = 100.0,
    fill: bool = True,
) -> None:
    if not values:
        return
    last = max(len(values) - 1, 1)
    points = [
        (x + (w - 1) * i / last, y + h - 1 - (h - 1) * min(max(v, 0.0) / vmax, 1.0)) for i, v in enumerate(values)
    ]
    if fill:
        d.polygon([(x, y + h - 1), *points, (x + w - 1, y + h - 1)], fill=mix(color, CARD, 0.22))
    d.line(points, fill=color, width=2, joint="curve")


def arrow(d: ImageDraw.ImageDraw, x: float, y: float, up: bool, color: Color, size: float = 10) -> None:
    """Triangle arrow (Roboto has no arrow glyphs)."""
    if up:
        d.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=color)
    else:
        d.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=color)
