"""What every view gets: a size, the display options, and a render() that returns a full frame."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image

from ..config import DEFAULTS
from ..sensors import History, Sample
from .theme import BG, CPU_C, Color, parse_hex


@dataclass(frozen=True)
class ViewOptions:
    temp_unit: str = "C"
    clock_24h: bool = True
    clock_seconds: bool = True
    clock_color: Color = CPU_C
    calm: bool = True
    bigstats: dict[str, bool] = field(default_factory=lambda: dict(DEFAULTS["bigstats"]))

    @classmethod
    def from_config(cls, cfg: dict[str, dict]) -> ViewOptions:
        return cls(
            temp_unit=cfg["stats"]["temp_unit"],
            clock_24h=cfg["stats"]["clock_24h"],
            clock_seconds=cfg["display"]["clock_seconds"],
            clock_color=parse_hex(cfg["display"]["clock_color"]),
            calm=cfg["display"]["calm"],
            bigstats=dict(cfg["bigstats"]),
        )


class View(ABC):
    def __init__(self, size: tuple[int, int], options: ViewOptions) -> None:
        self.width, self.height = size
        self.options = options

    @property
    def portrait(self) -> bool:
        return self.width < self.height

    def blank(self) -> Image.Image:
        return Image.new("RGB", (self.width, self.height), BG)

    def hour_minute(self, now: datetime) -> tuple[str, str]:
        if self.options.clock_24h:
            return now.strftime("%H"), now.strftime("%M")
        return now.strftime("%I").lstrip("0") or "12", now.strftime("%M")

    @abstractmethod
    def render(self, sample: Sample, history: History) -> Image.Image: ...
