"""The GIF library: thumbnails with a playback estimate, click to show, add and delete."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ..app import App
from ..gifprep import EXTENSIONS, estimate, list_animations, load_frames, thumbnail

log = logging.getLogger(__name__)

TILE = 96
FIT_LABELS = {"cover": "Fill screen (crop edges)", "contain": "Whole GIF (bars)", "original": "Original size"}
DENOISE_LABELS = {0: "Noise clean-up: off", 12: "Noise clean-up: normal", 20: "Noise clean-up: strong"}
GREEN, YELLOW, RED, GREY = "#76e35f", "#fbbf24", "#f87171", "#8a93a6"
ACCENT = "#38bdf8"


def rating(result: tuple[float, float] | None) -> tuple[str, str]:
    """Text and colour for a playback estimate."""
    if result is None:
        return "still image", GREY
    shown, own = result
    if shown >= own * 0.9:
        return f"smooth ({own:.0f} fps)", GREEN
    if shown >= 10:
        return f"smooth (~{shown:.0f} fps)", GREEN
    if shown >= 4:
        return f"~{shown:.0f} of {own:.0f} fps", YELLOW
    return f"slow: ~{shown:.1f} fps", RED


class GifLibrary(ttk.LabelFrame):
    def __init__(self, parent: tk.Widget, app: App, background: str) -> None:
        super().__init__(parent, text=" GIFs ", padding=10)
        self.app = app
        self._bg = background
        self._tiles: dict[Path, tk.Frame] = {}
        self._photos: dict[Path, ImageTk.PhotoImage] = {}
        self._known: list[tuple[Path, float]] | None = None
        self._results: queue.Queue[tuple[Path, Image.Image | None, tuple[str, str] | None]] = queue.Queue()
        self._thumbnails_todo: queue.Queue[Path] = queue.Queue()
        self._estimates_todo: queue.Queue[Path] = queue.Queue()
        self._blank = ImageTk.PhotoImage(Image.new("RGB", (TILE, TILE), (11, 13, 18)))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build()
        threading.Thread(target=self._thumbnail_worker, daemon=True, name="gif-thumbnails").start()
        threading.Thread(target=self._estimate_worker, daemon=True, name="gif-estimates").start()

    # ---- layout ----

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="Add GIFs…", command=self._add, style="Accent.TButton").pack(side="left")
        ttk.Button(top, text="Open folder", command=self._open_folder).pack(side="left", padx=6)
        self._slideshow = tk.BooleanVar()
        ttk.Checkbutton(
            top,
            text="Slideshow",
            variable=self._slideshow,
            command=lambda: self.app.set("gif", "slideshow", self._slideshow.get()),
        ).pack(side="left", padx=6)

        wrap = ttk.Frame(self)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(wrap, highlightthickness=0, bg=self._bg, height=230)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._grid = tk.Frame(self._canvas, bg=self._bg)
        self._canvas.create_window((0, 0), window=self._grid, anchor="nw")
        self._grid.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._arrange())
        self._canvas.bind(
            "<Enter>",
            lambda e: self._canvas.bind_all(
                "<MouseWheel>", lambda ev: self._canvas.yview_scroll(int(-ev.delta / 120), "units")
            ),
        )
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        ttk.Label(
            self,
            foreground=GREY,
            wraplength=480,
            justify="left",
            text="The screen takes about 120 KB/s, so GIFs where only a small part moves play smoothly "
            "and full-screen motion is slow. The label under each GIF is the estimate.",
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))

        options = ttk.Frame(self)
        options.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self._fit = tk.StringVar()
        fit = ttk.Combobox(
            options, textvariable=self._fit, values=list(FIT_LABELS.values()), state="readonly", width=22
        )
        fit.pack(side="left")
        fit.bind(
            "<<ComboboxSelected>>",
            lambda e: self._change_option("fit", {v: k for k, v in FIT_LABELS.items()}[self._fit.get()]),
        )
        self._denoise = tk.StringVar()
        denoise = ttk.Combobox(
            options, textvariable=self._denoise, values=list(DENOISE_LABELS.values()), state="readonly", width=22
        )
        denoise.pack(side="left", padx=8)
        denoise.bind(
            "<<ComboboxSelected>>",
            lambda e: self._change_option("denoise", {v: k for k, v in DENOISE_LABELS.items()}[self._denoise.get()]),
        )

    def _make_tile(self, path: Path) -> None:
        tile = tk.Frame(self._grid, bg=self._bg, highlightthickness=2, highlightbackground=self._bg, cursor="hand2")
        picture = tk.Label(tile, bg="#0b0d12", image=self._blank, bd=0)
        picture.pack(padx=4, pady=(4, 2))
        tk.Label(tile, text=path.stem[:14], bg=self._bg, fg="#e8ecf4", font=("Segoe UI", 9)).pack()
        caption = tk.Label(tile, text="checking…", bg=self._bg, fg=GREY, font=("Segoe UI", 8))
        caption.pack(pady=(0, 4))
        tile.picture, tile.caption = picture, caption  # type: ignore[attr-defined]
        for widget in (tile, picture, caption):
            widget.bind("<Button-1>", lambda e, p=path: self.app.set("gif", "file", str(p)))
            widget.bind("<Button-3>", lambda e, p=path: self._menu(e, p))
        self._tiles[path] = tile

    def _arrange(self) -> None:
        columns = max(1, max(self._canvas.winfo_width(), TILE + 16) // (TILE + 18))
        for i, path in enumerate(sorted(self._tiles)):
            self._tiles[path].grid(row=i // columns, column=i % columns, padx=4, pady=4, sticky="n")
        self.highlight()

    def highlight(self) -> None:
        chosen = self.app.cfg["gif"]["file"]
        showing = self.app.cfg["display"]["mode"] == "gif"
        for path, tile in self._tiles.items():
            color = ACCENT if showing and str(path) == chosen else self._bg
            tile.configure(highlightbackground=color, highlightcolor=color)

    def sync_settings(self) -> None:
        g = self.app.cfg["gif"]
        self._slideshow.set(bool(g["slideshow"]))
        self._fit.set(FIT_LABELS.get(g["fit"], FIT_LABELS["cover"]))
        self._denoise.set(DENOISE_LABELS.get(g["denoise"], f"Noise clean-up: {g['denoise']}"))
        self.highlight()

    # ---- files ----

    def scan(self) -> None:
        """Pick up files added or removed in the folder."""
        files = list_animations(self.app.gif_folder)
        signature = [(p, p.stat().st_mtime) for p in files if p.exists()]
        if signature == self._known:
            return
        self._known = signature
        for path in [p for p in self._tiles if p not in files]:
            self._tiles.pop(path).destroy()
            self._photos.pop(path, None)
        for path in files:
            if path not in self._tiles:
                self._make_tile(path)
                self._thumbnails_todo.put(path)
                self._estimates_todo.put(path)
        self._arrange()

    def _add(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in EXTENSIONS)
        chosen = filedialog.askopenfilenames(
            title="Add GIFs", filetypes=[("Animations and images", patterns), ("All files", "*.*")]
        )
        copied: list[Path] = []
        for name in chosen:
            source = Path(name)
            target = self.app.gif_folder / source.name
            counter = 1
            while target.exists():
                target = self.app.gif_folder / f"{source.stem}-{counter}{source.suffix}"
                counter += 1
            try:
                shutil.copy2(source, target)
                copied.append(target)
            except OSError as e:
                messagebox.showerror("Add GIFs", f"Could not copy {source.name}: {e}")
        self._known = None
        if len(copied) == 1:
            self.app.set("gif", "file", str(copied[0]))

    def _open_folder(self) -> None:
        if hasattr(os, "startfile"):
            os.startfile(self.app.gif_folder)

    def _menu(self, event: tk.Event, path: Path) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Show on screen", command=lambda: self.app.set("gif", "file", str(path)))
        menu.add_command(label="Delete from folder", command=lambda: self._delete(path))
        menu.tk_popup(event.x_root, event.y_root)

    def _delete(self, path: Path) -> None:
        if messagebox.askyesno("Delete GIF", f"Delete {path.name} from the GIF folder?"):
            try:
                path.unlink()
            except OSError as e:
                messagebox.showerror("Delete GIF", str(e))
            self._known = None

    # ---- estimates ----

    def _change_option(self, name: str, value) -> None:
        self.app.set("gif", name, value)
        self.app.cfg["gif"][name] = value  # the estimates below use it right away
        for path, tile in self._tiles.items():
            tile.caption.configure(text="checking…", fg=GREY)  # type: ignore[attr-defined]
            self._estimates_todo.put(path)

    def _thumbnail_worker(self) -> None:
        """Thumbnails are quick, so they get their own thread and appear first."""
        while True:
            path = self._thumbnails_todo.get()
            try:
                self._results.put((path, thumbnail(path, (TILE, TILE)), None))
            except (OSError, ValueError) as e:
                log.warning("cannot make a thumbnail of %s: %s", path, e)
                self._results.put((path, Image.new("RGB", (TILE, TILE), (40, 20, 20)), None))

    def _estimate_worker(self) -> None:
        """Estimating playback means decoding the whole animation, so it takes a while per file."""
        while True:
            path = self._estimates_todo.get()
            try:
                g = self.app.cfg["gif"]
                frames, durations = load_frames(path, self.app.display.size, g["fit"], g["denoise"])
                result = estimate(frames, durations, self.app.cfg["app"]["link_kbps"] * 1024, g["max_fps"])
                self._results.put((path, None, rating(result)))
            except (OSError, ValueError) as e:
                log.warning("cannot analyse %s: %s", path, e)
                self._results.put((path, None, ("can't open", RED)))

    def collect_results(self) -> None:
        while True:
            try:
                path, image, text = self._results.get_nowait()
            except queue.Empty:
                return
            tile = self._tiles.get(path)
            if tile is None:
                continue
            if image is not None:
                self._photos[path] = ImageTk.PhotoImage(image)
                tile.picture.configure(image=self._photos[path])  # type: ignore[attr-defined]
            if text is not None:
                tile.caption.configure(text=text[0], fg=text[1])  # type: ignore[attr-defined]
