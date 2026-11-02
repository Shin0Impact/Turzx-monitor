"""Command line: run the app, or install / uninstall start-with-Windows."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import __version__, autostart, config, power, tray
from .app import App
from .display import Display
from .lcd import Lcd, SerialLcd
from .sensors import Stats
from .simulator import SimulatedLcd

log = logging.getLogger("turingscreen")
ERROR_ALREADY_EXISTS = 183


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="turingscreen", description=__doc__)
    parser.add_argument("command", nargs="?", choices=["run", "install", "uninstall"], default="run")
    parser.add_argument(
        "--background", action="store_true", help="start with the control panel closed (tray icon only)"
    )
    parser.add_argument("--simulate", action="store_true", help="no screen needed: write previews/preview.png")
    parser.add_argument("--seconds", type=float, help="stop after this many seconds (for --simulate)")
    parser.add_argument("--no-ui", action="store_true", help="don't create the control panel")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def setup_logging(console: bool) -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [
        RotatingFileHandler(config.LOG_DIR / "turing.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if console and sys.stdout:
        handlers.append(logging.StreamHandler(sys.stdout))
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def is_first_instance() -> bool:
    """A named mutex stops a second copy from fighting over the screen's serial port."""
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "Local\\TuringScreenDashboard")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def build_lcd(cfg: dict, simulate: bool) -> Lcd:
    if simulate:
        return SimulatedLcd(cfg["screen"]["orientation"], cfg["app"]["link_kbps"] * 1024)
    return SerialLcd(cfg["screen"]["port"], cfg["screen"]["orientation"])


def install() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "Warning: tkinter is missing, so the control panel cannot open. Re-run the Python installer "
            'and tick "tcl/tk and IDLE".'
        )
    autostart.enable()
    autostart.create_shortcut()
    print("Installed: starts with Windows, and there is a 'Turing Screen' entry in the Start Menu.")
    subprocess.Popen(autostart.launcher(), cwd=config.ROOT, creationflags=0x00000008)  # DETACHED_PROCESS
    print("Starting it now...")
    return 0


def uninstall() -> int:
    autostart.disable()
    autostart.remove_shortcut()
    print("Removed from Windows startup and the Start Menu. Delete this folder to remove everything else.")
    return 0


def run(args: argparse.Namespace) -> int:
    setup_logging(console=not args.background)
    cfg = config.load()
    log.info("starting version %s", __version__)
    if not args.simulate and not is_first_instance():
        config.OPEN_PANEL_FLAG.touch()
        log.info("already running: asked it to open the control panel")
        return 0

    stats = Stats(cfg["stats"]["interval"], cfg["stats"]["drives"], cfg["stats"]["network_interface"])
    stats.start()
    log.info("CPU: %s | GPU: %s", stats.cpu_name, stats.gpu.name or "none")
    lcd = build_lcd(cfg, args.simulate)
    app = App(cfg, Display(lcd), stats)
    power.start(app.on_power)

    on_step = None
    if args.simulate:
        preview = config.ROOT / "previews" / "preview.png"
        preview.parent.mkdir(exist_ok=True)
        saved = {"updates": -1}

        def on_step() -> None:
            if app.display.meter.updates != saved["updates"]:
                saved["updates"] = app.display.meter.updates
                lcd.glass().save(preview)

    if args.seconds:
        threading.Timer(args.seconds, app.stop.set).start()
    worker = threading.Thread(target=app.run, kwargs={"on_step": on_step}, daemon=True, name="render")
    worker.start()

    panel = None
    if not args.no_ui:
        try:
            from .ui.panel import ControlPanel

            panel = ControlPanel(app, show=not args.background)
        except Exception:  # tkinter missing or no display: the tray icon still works
            log.exception("control panel unavailable")
    icon = None
    if cfg["app"]["tray"] and not args.simulate:
        icon = tray.start(app, panel.request_open if panel else None)

    try:
        if panel:
            panel.mainloop(worker)
        else:
            while worker.is_alive():
                worker.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        worker.join(5)
        app.shutdown()
        if icon:
            icon.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "install":
        return install()
    if args.command == "uninstall":
        return uninstall()
    return run(args)
