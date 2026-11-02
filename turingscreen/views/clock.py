"""Full-screen clock. Only the time changes, so it costs almost no bandwidth."""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from ..sensors import History, Sample
from .base import View
from .theme import DIM, FAINT, SUB, TEXT, light, sans


class ClockView(View):
    def render(self, sample: Sample | None = None, history: History | None = None) -> Image.Image:
        img = self.blank()
        d = ImageDraw.Draw(img)
        now = datetime.now()
        hours, minutes = self.hour_minute(now)
        accent = self.options.clock_color
        if self.portrait:  # hours above minutes
            fnt = light(205)
            for i, (digits, color) in enumerate(((hours, TEXT), (minutes, accent))):
                x = (self.width - d.textlength(digits, font=fnt)) / 2
                d.text((x, -28 + i * 182), digits, font=fnt, fill=color)
            date_y = 392
        else:
            fnt = light(150)
            digits = f"{hours}:{minutes}"
            d.text(((self.width - d.textlength(digits, font=fnt)) / 2, 10), digits, font=fnt, fill=TEXT)
            date_y = 212
        weekday, date = sans(30), sans(24)
        text = now.strftime("%A")
        d.text(((self.width - d.textlength(text, font=weekday)) / 2, date_y), text, font=weekday, fill=TEXT)
        text = now.strftime("%d %B")
        d.text(((self.width - d.textlength(text, font=date)) / 2, date_y + 38), text, font=date, fill=SUB)
        if not self.options.clock_24h:
            d.text((self.width - 44, 10), now.strftime("%p"), font=sans(18), fill=DIM)
        if self.options.clock_seconds:
            top = self.height - 8
            d.rectangle((0, top, self.width - 1, self.height - 1), fill=FAINT)
            d.rectangle((0, top, int((self.width - 1) * now.second / 59), self.height - 1), fill=accent)
        return img
