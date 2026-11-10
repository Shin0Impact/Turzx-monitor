"""Tray icon: switch what the screen shows, open the control panel, quit."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PIL import Image, ImageDraw

from . import menustyle
from .app import App
from .views import MODES

log = logging.getLogger(__name__)


def icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((14, 4, 50, 60), radius=8, fill=(18, 22, 31), outline=(56, 189, 248), width=4)
    for top, right, color in ((16, 42, (56, 189, 248)), (28, 36, (118, 227, 95)), (40, 40, (167, 139, 250))):
        d.rectangle((22, top, right, top + 6), fill=color)
    return img


def start(app: App, open_panel: Callable[[], None] | None = None):
    """Run the tray icon on its own thread; returns the icon, or None if pystray isn't usable."""
    try:
        import pystray
    except ImportError as e:
        log.info("tray icon disabled (%s)", e)
        return None

    def show(mode: str):
        return lambda icon, _item: app.set("display", "mode", mode)

    def quit_app(icon, _item):
        app.stop.set()
        icon.stop()

    items = []
    if open_panel:
        items.append(pystray.MenuItem("Open control panel", lambda icon, _item: open_panel(), default=True))
    items += [
        pystray.MenuItem(
            "Show",
            pystray.Menu(
                *(
                    pystray.MenuItem(
                        label,
                        show(mode),
                        radio=True,
                        checked=lambda _item, mode=mode: app.cfg["display"]["mode"] == mode,
                    )
                    for mode, label in MODES.items()
                )
            ),
        ),
        pystray.MenuItem("Next GIF", lambda icon, _item: app.command("next_gif")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    ]
    menustyle.apply()
    icon = pystray.Icon("turing-screen", icon_image(), "Turing Screen", pystray.Menu(*items))
    threading.Thread(target=icon.run, daemon=True, name="tray").start()
    return icon
