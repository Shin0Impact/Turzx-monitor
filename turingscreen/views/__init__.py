"""The four things the screen can show."""

from __future__ import annotations

from .base import View, ViewOptions
from .bigstats import ITEMS as BIG_ITEMS
from .bigstats import BigStatsView
from .clock import ClockView
from .detail import DetailView

MODES = {"stats": "Big stats", "detail": "Detailed stats", "gif": "GIF", "clock": "Clock"}
VIEWS = {"stats": BigStatsView, "detail": DetailView, "clock": ClockView}

__all__ = ["BIG_ITEMS", "MODES", "VIEWS", "View", "ViewOptions", "make_view"]


def make_view(mode: str, size: tuple[int, int], options: ViewOptions) -> View:
    return VIEWS[mode](size, options)
