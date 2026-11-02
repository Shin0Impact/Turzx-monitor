"""Control panel window: choose what the screen shows, GIFs, colours, brightness, rotation."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import colorchooser, messagebox, ttk

from PIL import Image, ImageTk

from .. import autostart, config
from ..app import App
from ..lcd import ORIENTATION_NAMES
from ..tray import icon_image
from ..views import BIG_ITEMS, MODES
from .library import GifLibrary

log = logging.getLogger(__name__)

PREVIEW_SCALE = 0.75
GREY = "#8a93a6"
IDLE_LABELS = {"clock": "Show the clock", "off": "Turn the screen off"}
ORIENTATION_LABELS = {name: name.replace("_", " ").capitalize() for name in ORIENTATION_NAMES}
CLOCK_COLORS = ("#38bdf8", "#76e35f", "#a78bfa", "#fbbf24", "#f472b6", "#f87171", "#e8ecf4")


class ControlPanel:
    """Runs on the main thread. It talks to the render thread only through App.set()."""

    def __init__(self, app: App, show: bool = True) -> None:
        self.app = app
        self._open_requests: queue.Queue[bool] = queue.Queue()
        self._refreshers: list[Callable[[], None]] = []
        self._dragging = False
        self.root = tk.Tk()
        self.root.title("Turing Screen")
        self.root.minsize(860, 740)
        try:
            import sv_ttk

            sv_ttk.set_theme("dark")
        except ImportError:
            pass
        self._icon = ImageTk.PhotoImage(icon_image())
        self.root.iconphoto(True, self._icon)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)  # closing keeps the screen running in the tray
        background = ttk.Style().lookup("TFrame", "background") or "#1c1c1c"
        self._build(background)
        self.refresh()
        if not show:
            self.root.withdraw()

    # ---- thread-safe ----

    def request_open(self) -> None:
        self._open_requests.put(True)

    # ---- building ----

    def _build(self, background: str) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        self._build_preview(ttk.Frame(outer))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self._build_modes(right)
        self._build_big_items(right)
        self.library = GifLibrary(right, self.app, background)
        self.library.grid(row=3, column=0, sticky="nsew")
        self._refreshers.append(self.library.sync_settings)
        self._build_settings(right)

    def _build_preview(self, frame: ttk.Frame) -> None:
        frame.grid(row=0, column=0, sticky="n", padx=(0, 16))
        ttk.Label(frame, text="On the screen now", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self._preview = tk.Label(frame, bg="black", bd=0)
        self._preview.pack()
        self._status = ttk.Label(frame, text="", wraplength=250, foreground=GREY)
        self._status.pack(anchor="w", pady=(8, 0))
        ttk.Button(frame, text="Quit app (screen off)", command=self.app.stop.set).pack(anchor="w", pady=(14, 0))
        ttk.Label(frame, text="Closing this window keeps the screen\nrunning in the tray.", foreground=GREY).pack(
            anchor="w", pady=(6, 0)
        )

    def _build_modes(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Show on screen", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        row = ttk.Frame(parent)
        row.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        buttons = {}
        for i, (mode, label) in enumerate(MODES.items()):
            buttons[mode] = ttk.Button(row, text=label, command=lambda m=mode: self.app.set("display", "mode", m))
            buttons[mode].grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0), ipady=6)
            row.columnconfigure(i, weight=1)

        def highlight() -> None:
            for mode, button in buttons.items():
                button.configure(style="Accent.TButton" if self.app.cfg["display"]["mode"] == mode else "TButton")

        self._refreshers.append(highlight)

    def _build_big_items(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(row, text="Big stats shows:").pack(side="left")
        for key, label in BIG_ITEMS.items():
            self._checkbox(row, label, "bigstats", key).pack(side="left", padx=(10, 0))

    def _build_settings(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        ttk.Label(grid, text="When locked or monitors off").grid(row=0, column=0, sticky="w")
        self._choice(grid, IDLE_LABELS, "display", "idle").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(grid, text="Clock brightness").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self._slider(grid, "display", "idle_brightness").grid(row=0, column=3, sticky="ew", padx=8)
        ttk.Label(grid, text="Rotation").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._choice(grid, ORIENTATION_LABELS, "screen", "orientation").grid(
            row=1, column=1, sticky="w", padx=8, pady=(10, 0)
        )
        ttk.Label(grid, text="Brightness").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 0))
        self._slider(grid, "screen", "brightness").grid(row=1, column=3, sticky="ew", padx=8, pady=(10, 0))
        self._build_clock_color(grid).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self._checkbox(grid, "Seconds bar on clock", "display", "clock_seconds").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        self._checkbox(grid, "Calm numbers", "display", "calm").grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(10, 0)
        )
        self._checkbox(grid, "Hide the wipe when switching (dark while loading)", "display", "hide_redraws").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self._build_autostart(grid).grid(row=4, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(6, 0))

    def _build_clock_color(self, parent: ttk.Frame) -> ttk.Frame:
        row = ttk.Frame(parent)
        ttk.Label(row, text="Clock colour").pack(side="left", padx=(0, 10))
        swatches = []
        for color in CLOCK_COLORS:
            swatch = tk.Label(row, bg=color, width=3, height=1, cursor="hand2", bd=2, relief="flat")
            swatch.pack(side="left", padx=2)
            swatch.bind("<Button-1>", lambda e, c=color: self.app.set("display", "clock_color", c))
            swatches.append((color, swatch))
        custom = tk.Label(row, width=3, height=1, bd=2, relief="flat")
        custom.pack(side="left", padx=(8, 2))
        ttk.Button(row, text="Custom…", command=self._pick_color).pack(side="left", padx=4)

        def highlight() -> None:
            current = self.app.cfg["display"]["clock_color"].lower()
            for color, swatch in swatches:
                swatch.configure(relief="solid" if color == current else "flat")
            custom.configure(bg=current if current not in CLOCK_COLORS else self.root.cget("bg"))

        self._refreshers.append(highlight)
        return row

    def _pick_color(self) -> None:
        chosen = colorchooser.askcolor(
            color=self.app.cfg["display"]["clock_color"], parent=self.root, title="Clock colour"
        )[1]
        if chosen:
            self.app.set("display", "clock_color", chosen)

    def _build_autostart(self, parent: ttk.Frame) -> ttk.Checkbutton:
        var = tk.BooleanVar()

        def toggle() -> None:
            try:
                autostart.enable() if var.get() else autostart.disable()
            except OSError as e:
                messagebox.showerror("Start with Windows", str(e))
            var.set(autostart.is_enabled())

        self._refreshers.append(lambda: var.set(autostart.is_enabled()))
        return ttk.Checkbutton(parent, text="Start with Windows", variable=var, command=toggle)

    # ---- settings widgets: each registers a refresher that copies the app's setting into the widget ----

    def _checkbox(self, parent: tk.Widget, text: str, section: str, name: str) -> ttk.Checkbutton:
        var = tk.BooleanVar()
        self._refreshers.append(lambda: var.set(bool(self.app.cfg[section][name])))
        return ttk.Checkbutton(parent, text=text, variable=var, command=lambda: self.app.set(section, name, var.get()))

    def _choice(self, parent: tk.Widget, labels: dict[str, str], section: str, name: str) -> ttk.Combobox:
        var = tk.StringVar()
        by_label = {label: key for key, label in labels.items()}
        self._refreshers.append(lambda: var.set(labels.get(self.app.cfg[section][name], "")))
        box = ttk.Combobox(parent, textvariable=var, values=list(labels.values()), state="readonly", width=20)
        box.bind("<<ComboboxSelected>>", lambda e: self.app.set(section, name, by_label[var.get()]))
        return box

    def _slider(self, parent: tk.Widget, section: str, name: str) -> ttk.Scale:
        var = tk.IntVar()
        self._refreshers.append(lambda: None if self._dragging else var.set(self.app.cfg[section][name]))
        scale = ttk.Scale(parent, from_=5, to=100, variable=var, orient="horizontal")
        scale.bind("<ButtonPress-1>", lambda e: setattr(self, "_dragging", True))
        scale.bind(
            "<ButtonRelease-1>",
            lambda e: (setattr(self, "_dragging", False), self.app.set(section, name, int(var.get()))),
        )
        return scale

    # ---- keeping the window current ----

    def refresh(self) -> None:
        for refresh in self._refreshers:
            refresh()

    def _update_preview(self) -> None:
        picture = self.app.display.preview()
        width, height = picture.size
        picture = picture.resize((int(width * PREVIEW_SCALE), int(height * PREVIEW_SCALE)), Image.Resampling.BILINEAR)
        self._photo = ImageTk.PhotoImage(picture)
        self._preview.configure(image=self._photo)
        self._status.configure(text=f"{self.app.status}\nlink ~{self.app.cfg['app']['link_kbps']} KB/s")

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def mainloop(self, worker: threading.Thread) -> None:
        """Returns when the app is told to stop or the render thread dies."""
        tick = 0

        def poll() -> None:
            nonlocal tick
            if self.app.stop.is_set() or not worker.is_alive():
                self.root.destroy()
                return
            wants_open = not self._open_requests.empty()
            while not self._open_requests.empty():
                self._open_requests.get_nowait()
            if tick % 10 == 0 and config.OPEN_PANEL_FLAG.exists():  # a second launch asked for the panel
                config.OPEN_PANEL_FLAG.unlink(missing_ok=True)
                wants_open = True
            if wants_open:
                self.show()
            self.library.collect_results()
            if tick % 5 == 0 and self.root.state() != "withdrawn":
                self._update_preview()
                self.refresh()
            if tick % 30 == 0:
                self.library.scan()
            tick += 1
            self.root.after(100, poll)

        self.root.after(50, poll)
        self.root.mainloop()
