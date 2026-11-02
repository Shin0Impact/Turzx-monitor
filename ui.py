"""Control panel window: pick what the screen shows, choose GIFs, brightness, rotation, idle behaviour.
Runs in the main thread; talks to the render thread only through app.set() (a queue)."""
import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from gifs import estimate, list_gifs, load_frames, thumbnail
from lcd import ORIENTATIONS
from pages import BIG_ITEMS, MODES

FIT_LABELS = {"cover": "Fill screen (crop edges)", "contain": "Whole GIF (bars)", "original": "Original size"}
DENOISE_LABELS = {0: "Noise clean-up: off", 12: "Noise clean-up: normal", 20: "Noise clean-up: strong"}
IDLE_LABELS = {"clock": "Show the clock", "off": "Turn the screen off"}
ORIENT_LABELS = {o: o.replace("_", " ").capitalize() for o in ORIENTATIONS}
ACCENT = "#38bdf8"
PREVIEW_SCALE = 0.75
TILE = 96


class ControlPanel:
    def __init__(self, app, show=True):
        self.app = app
        self.cmd = queue.Queue()      # from other threads (tray): "open"
        self.results = queue.Queue()  # from GIF analysis threads
        self.root = tk.Tk()
        self.root.title("Turing Screen")
        self.root.minsize(860, 700)
        try:
            import sv_ttk
            sv_ttk.set_theme("dark")
        except Exception:
            pass
        try:
            from main import tray_image
            self._icon = ImageTk.PhotoImage(tray_image())
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.gif_info = {}   # path -> dict(thumb=PhotoImage, est=str, color=str, mtime=float)
        self.tiles = {}      # path -> frame widget
        self.analyzing = set()
        self.known_files = None
        self.todo = queue.Queue()     # GIFs waiting for thumbnail + estimate (one worker thread)
        self._blank = ImageTk.PhotoImage(Image.new("RGB", (TILE, TILE), (11, 13, 18)))
        threading.Thread(target=self._worker, daemon=True, name="gif-analyze").start()
        self._build()
        self._refresh_controls()
        if not show:
            self.root.withdraw()

    # ---------- thread-safe entry points ----------
    def request_open(self):
        self.cmd.put("open")

    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ---------- layout ----------
    def _build(self):
        r = self.root
        outer = ttk.Frame(r, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # left: live preview
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n", padx=(0, 16))
        ttk.Label(left, text="On the screen now", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.preview_lbl = tk.Label(left, bg="black", bd=0)
        self.preview_lbl.pack()
        self.status_lbl = ttk.Label(left, text="", wraplength=250, foreground="#8a93a6")
        self.status_lbl.pack(anchor="w", pady=(8, 0))
        ttk.Button(left, text="Quit app (screen off)", command=self.quit_app).pack(anchor="w", pady=(14, 0))
        ttk.Label(left, text="Closing this window keeps the screen\nrunning in the tray.",
                  foreground="#8a93a6").pack(anchor="w", pady=(6, 0))

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        # mode buttons
        ttk.Label(right, text="Show on screen", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        modes = ttk.Frame(right)
        modes.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        self.mode_btns = {}
        for i, (m, label) in enumerate(MODES.items()):
            b = ttk.Button(modes, text=label, command=lambda m=m: self.app.set("display", "mode", m))
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0), ipady=6)
            modes.columnconfigure(i, weight=1)
            self.mode_btns[m] = b

        # Big stats items
        bs = ttk.Frame(right)
        bs.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(bs, text="Big stats shows:").pack(side="left")
        self.big_vars = {}
        for key, label in BIG_ITEMS.items():
            v = tk.BooleanVar()
            ttk.Checkbutton(bs, text=label, variable=v,
                            command=lambda k=key, v=v: self.app.set("bigstats", k, v.get())).pack(side="left", padx=(10, 0))
            self.big_vars[key] = v

        # GIF library
        gif_box = ttk.LabelFrame(right, text=" GIFs ", padding=10)
        gif_box.grid(row=3, column=0, sticky="nsew")
        gif_box.columnconfigure(0, weight=1)
        gif_box.rowconfigure(1, weight=1)
        bar = ttk.Frame(gif_box)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text="Add GIFs…", command=self.add_gifs, style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Open folder", command=lambda: self._open(self.app.gif_folder)).pack(side="left", padx=6)
        self.slide_var = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Slideshow", variable=self.slide_var,
                        command=lambda: self.app.set("gif", "slideshow", self.slide_var.get())).pack(side="left", padx=6)
        bar2 = ttk.Frame(gif_box)
        bar2.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.fit_var = tk.StringVar()
        fit = ttk.Combobox(bar2, textvariable=self.fit_var, values=list(FIT_LABELS.values()), state="readonly", width=22)
        fit.pack(side="left")
        fit.bind("<<ComboboxSelected>>", lambda e: self._set_fit())
        self.dn_var = tk.StringVar()
        dn = ttk.Combobox(bar2, textvariable=self.dn_var, values=list(DENOISE_LABELS.values()), state="readonly", width=22)
        dn.pack(side="left", padx=8)
        dn.bind("<<ComboboxSelected>>", lambda e: self._set_denoise())

        canvas_wrap = ttk.Frame(gif_box)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.columnconfigure(0, weight=1)
        canvas_wrap.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_wrap, highlightthickness=0, bg=self._bg(), height=230)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=sb.set)
        self.grid_frame = tk.Frame(self.canvas, bg=self._bg())
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._layout_tiles())
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        ttk.Label(gif_box, foreground="#8a93a6", wraplength=480, justify="left",
                  text="This screen only takes about 120 KB/s, so GIFs where only a small part moves "
                       "(a character on a still background, pixel art) play smoothly, while full-screen "
                       "motion plays at under 1 frame per second. The label under each GIF is the estimate."
                  ).grid(row=2, column=0, sticky="w", pady=(8, 0))

        # bottom: idle + screen settings
        bottom = ttk.Frame(right)
        bottom.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        bottom.columnconfigure(1, weight=1)
        bottom.columnconfigure(3, weight=1)

        ttk.Label(bottom, text="When locked or monitors off").grid(row=0, column=0, sticky="w")
        self.idle_var = tk.StringVar()
        idle = ttk.Combobox(bottom, textvariable=self.idle_var, values=list(IDLE_LABELS.values()),
                            state="readonly", width=20)
        idle.grid(row=0, column=1, sticky="w", padx=8)
        idle.bind("<<ComboboxSelected>>", lambda e: self.app.set(
            "display", "idle", {v: k for k, v in IDLE_LABELS.items()}[self.idle_var.get()]))
        ttk.Label(bottom, text="Clock brightness").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.idle_b = tk.IntVar()
        s = ttk.Scale(bottom, from_=5, to=100, variable=self.idle_b, orient="horizontal")
        s.grid(row=0, column=3, sticky="ew", padx=8)
        s.bind("<ButtonRelease-1>", lambda e: self.app.set("display", "idle_brightness", int(self.idle_b.get())))

        ttk.Label(bottom, text="Rotation").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.orient_var = tk.StringVar()
        o = ttk.Combobox(bottom, textvariable=self.orient_var, values=list(ORIENT_LABELS.values()),
                         state="readonly", width=20)
        o.grid(row=1, column=1, sticky="w", padx=8, pady=(10, 0))
        o.bind("<<ComboboxSelected>>", lambda e: self.app.set(
            "screen", "orientation", {v: k for k, v in ORIENT_LABELS.items()}[self.orient_var.get()]))
        ttk.Label(bottom, text="Brightness").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(10, 0))
        self.bright = tk.IntVar()
        s2 = ttk.Scale(bottom, from_=5, to=100, variable=self.bright, orient="horizontal")
        s2.grid(row=1, column=3, sticky="ew", padx=8, pady=(10, 0))
        s2.bind("<ButtonRelease-1>", lambda e: self.app.set("screen", "brightness", int(self.bright.get())))
        self.clock_secs = tk.BooleanVar()
        ttk.Checkbutton(bottom, text="Seconds bar on clock", variable=self.clock_secs,
                        command=lambda: self.app.set("display", "clock_seconds", self.clock_secs.get())
                        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.calm_var = tk.BooleanVar()
        ttk.Checkbutton(bottom, text="Calm numbers", variable=self.calm_var,
                        command=lambda: self.app.set("display", "calm", self.calm_var.get())
                        ).grid(row=2, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(10, 0))
        self.hide_var = tk.BooleanVar()
        ttk.Checkbutton(bottom, text="Hide the wipe when switching (dark while loading)",
                        variable=self.hide_var,
                        command=lambda: self.app.set("display", "hide_redraws", self.hide_var.get())
                        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _bg(self):
        try:
            return ttk.Style().lookup("TFrame", "background") or "#1c1c1c"
        except Exception:
            return "#1c1c1c"

    # ---------- refreshers ----------
    def _refresh_controls(self):
        c = self.app.cfg
        for m, b in self.mode_btns.items():
            b.configure(style="Accent.TButton" if c["display"]["mode"] == m else "TButton")
        self.slide_var.set(bool(c["gif"]["slideshow"]))
        self.fit_var.set(FIT_LABELS.get(c["gif"]["fit"], FIT_LABELS["cover"]))
        self.idle_var.set(IDLE_LABELS.get(c["display"]["idle"], IDLE_LABELS["clock"]))
        self.orient_var.set(ORIENT_LABELS.get(c["screen"]["orientation"], "Portrait"))
        if not self._dragging():
            self.bright.set(c["screen"]["brightness"])
            self.idle_b.set(c["display"]["idle_brightness"])
        self.clock_secs.set(bool(c["display"]["clock_seconds"]))
        self.calm_var.set(bool(c["display"]["calm"]))
        for k, v in self.big_vars.items():
            v.set(bool(c["bigstats"].get(k)))
        self.hide_var.set(bool(c["display"]["hide_redraws"]))
        self.dn_var.set(DENOISE_LABELS.get(c["gif"]["denoise"], f"Noise clean-up: {c['gif']['denoise']}"))
        self._highlight_selected()

    def _dragging(self):
        try:
            return str(self.root.focus_get()).endswith("scale")
        except Exception:
            return False

    def _refresh_preview(self):
        if self.root.state() != "withdrawn":
            img = self.app.preview()
            w, h = img.size
            img = img.resize((int(w * PREVIEW_SCALE), int(h * PREVIEW_SCALE)), Image.Resampling.BILINEAR)
            self._prev_img = ImageTk.PhotoImage(img)
            self.preview_lbl.configure(image=self._prev_img)
            self.status_lbl.configure(text=f"{self.app.status}\nlink ~{self.app.cfg['app']['link_kbps']} KB/s")

    # ---------- GIF library ----------
    def _scan_gifs(self):
        files = list_gifs(self.app.gif_folder)
        key = [(f, os.path.getmtime(f)) for f in files if os.path.exists(f)]
        if key == self.known_files:
            return
        self.known_files = key
        for f in list(self.tiles):
            if f not in files:
                self.tiles.pop(f).destroy()
                self.gif_info.pop(f, None)
        for f in files:
            if f not in self.tiles:
                self._make_tile(f)
            if f not in self.gif_info and f not in self.analyzing:
                self._analyze(f)
        self._layout_tiles()

    def _make_tile(self, path):
        bg = self._bg()
        t = tk.Frame(self.grid_frame, bg=bg, highlightthickness=2, highlightbackground=bg, cursor="hand2")
        img = tk.Label(t, bg="#0b0d12", image=self._blank, bd=0)  # image set now so size is in pixels
        img.pack(padx=4, pady=(4, 2))
        name = os.path.splitext(os.path.basename(path))[0]
        tk.Label(t, text=name[:14], bg=bg, fg="#e8ecf4", font=("Segoe UI", 9)).pack()
        est = tk.Label(t, text="checking…", bg=bg, fg="#8a93a6", font=("Segoe UI", 8))
        est.pack(pady=(0, 4))
        t.img, t.est = img, est
        for w in (t, img, est):
            w.bind("<Button-1>", lambda e, p=path: self.app.set("gif", "file", p))
            w.bind("<Button-3>", lambda e, p=path: self._tile_menu(e, p))
        self.tiles[path] = t

    def _layout_tiles(self):
        width = max(self.canvas.winfo_width(), TILE + 16)
        cols = max(1, width // (TILE + 18))
        for i, path in enumerate(sorted(self.tiles)):
            self.tiles[path].grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="n")
        self._highlight_selected()

    def _highlight_selected(self):
        sel = self.app.cfg["gif"]["file"]
        on_gif = self.app.cfg["display"]["mode"] == "gif"
        for path, t in self.tiles.items():
            c = ACCENT if (path == sel and on_gif) else self._bg()
            t.configure(highlightbackground=c, highlightcolor=c)

    def _analyze(self, path):
        self.analyzing.add(path)
        self.todo.put(path)

    def _worker(self):
        """One GIF at a time: thumbnail first (fast, shown right away), then the playback estimate."""
        while True:
            path = self.todo.get()
            info = {}
            try:
                info["thumb"] = thumbnail(path, (TILE, TILE))
                self.results.put((path, dict(info), False))
                size = self.app.lcd.size
                g = self.app.cfg["gif"]
                frames, durs = load_frames(path, size, g["fit"], g["denoise"])
                est, own = estimate(frames, durs, self.app.cfg["app"]["link_kbps"] * 1024)
                del frames
                if est is None:
                    info["est"], info["color"] = "still image", "#8a93a6"
                elif est >= own * 0.9:
                    info["est"], info["color"] = f"smooth ({own:.0f} fps)", "#76e35f"
                elif est >= 10:
                    info["est"], info["color"] = f"smooth (~{est:.0f} fps)", "#76e35f"
                elif est >= 4:
                    info["est"], info["color"] = f"~{est:.0f} of {own:.0f} fps", "#fbbf24"
                else:
                    info["est"], info["color"] = f"slow: ~{est:.1f} fps", "#f87171"
            except Exception as e:
                info["est"], info["color"] = "can't open", "#f87171"
                info.setdefault("thumb", Image.new("RGB", (TILE, TILE), (40, 20, 20)))
                self.app_log(f"gif analysis failed for {path}: {e}")
            self.results.put((path, info, True))

    def app_log(self, msg):
        import logging
        logging.getLogger("turing").warning(msg)

    def _collect_results(self):
        while not self.results.empty():
            path, info, done = self.results.get_nowait()
            t = self.tiles.get(path)
            if not t:
                self.analyzing.discard(path)
                continue
            if "thumb" in info:
                info["photo"] = ImageTk.PhotoImage(info["thumb"])
                t.photo = info["photo"]
                t.img.configure(image=info["photo"])
            if done:
                self.analyzing.discard(path)
                self.gif_info[path] = info
                t.est.configure(text=info["est"], fg=info["color"])

    def _tile_menu(self, event, path):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Show on screen", command=lambda: self.app.set("gif", "file", path))
        m.add_command(label="Delete from folder", command=lambda: self._delete(path))
        m.tk_popup(event.x_root, event.y_root)

    def _delete(self, path):
        if messagebox.askyesno("Delete GIF", f"Delete {os.path.basename(path)} from the GIF folder?"):
            try:
                os.remove(path)
            except Exception as e:
                messagebox.showerror("Delete GIF", str(e))
            self.known_files = None

    def _set_fit(self):
        fit = {v: k for k, v in FIT_LABELS.items()}[self.fit_var.get()]
        self.app.set("gif", "fit", fit)
        self.app.cfg["gif"]["fit"] = fit  # estimates below use it right away
        self._reestimate()

    def _set_denoise(self):
        dn = {v: k for k, v in DENOISE_LABELS.items()}[self.dn_var.get()]
        self.app.set("gif", "denoise", dn)
        self.app.cfg["gif"]["denoise"] = dn
        self._reestimate()

    def _reestimate(self):
        self.gif_info.clear()
        for t in self.tiles.values():
            t.est.configure(text="checking…", fg="#8a93a6")
        for p in list(self.tiles):
            if p not in self.analyzing:
                self._analyze(p)

    def add_gifs(self):
        paths = filedialog.askopenfilenames(
            title="Add GIFs", filetypes=[("Animations and images", "*.gif *.webp *.png *.apng *.jpg *.jpeg"),
                                         ("All files", "*.*")])
        last = None
        for p in paths:
            base = os.path.basename(p)
            dest = os.path.join(self.app.gif_folder, base)
            n = 1
            while os.path.exists(dest):
                stem, ext = os.path.splitext(base)
                dest = os.path.join(self.app.gif_folder, f"{stem}-{n}{ext}")
                n += 1
            try:
                shutil.copy2(p, dest)
                last = dest
            except Exception as e:
                messagebox.showerror("Add GIFs", f"Could not copy {base}: {e}")
        self.known_files = None
        if last and len(paths) == 1:
            self.app.set("gif", "file", last)

    def _open(self, path):
        try:
            os.startfile(path)
        except Exception:
            pass

    def quit_app(self):
        self.app.stop.set()

    # ---------- loop ----------
    def mainloop(self, worker):
        tick = {"n": 0}

        def poll():
            while not self.cmd.empty():
                if self.cmd.get_nowait() == "open":
                    self.show()
            if self.app.stop.is_set() or not worker.is_alive():
                self.root.destroy()
                return
            self._collect_results()
            if tick["n"] % 10 == 0:
                flag = os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_panel.flag")
                if os.path.exists(flag):
                    try:
                        os.remove(flag)
                    except Exception:
                        pass
                    self.show()
            if tick["n"] % 5 == 0:
                self._refresh_preview()
                self._refresh_controls()
            if tick["n"] % 30 == 0:
                self._scan_gifs()
            tick["n"] += 1
            self.root.after(100, poll)

        self.root.after(50, poll)
        self.root.mainloop()
