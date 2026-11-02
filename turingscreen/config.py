"""Settings: config.toml holds the defaults you edit by hand, state.json what the control panel changes."""

from __future__ import annotations

import copy
import json
import logging
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.toml"
STATE_FILE = ROOT / "state.json"
LOG_DIR = ROOT / "logs"
OPEN_PANEL_FLAG = ROOT / "open_panel.flag"  # a second launch drops this to ask the running copy to show its panel
ASSETS_DIR = ROOT / "assets"

DEFAULTS: dict[str, dict] = {
    "screen": {"port": "AUTO", "orientation": "portrait", "brightness": 50},
    "display": {
        "mode": "stats",
        "idle": "clock",
        "idle_brightness": 25,
        "clock_seconds": True,
        "clock_color": "#38bdf8",
        "hide_redraws": True,
        "calm": True,
    },
    "bigstats": {"clock": True, "cpu": True, "gpu": True, "ram": True, "net": False},
    "dark": {"on_sleep": True, "on_exit": True},
    "stats": {"interval": 1.0, "drives": "auto", "network_interface": "auto", "temp_unit": "C", "clock_24h": True},
    "gif": {
        "folder": "gifs",
        "file": "",
        "slideshow": False,
        "switch_seconds": 30,
        "fit": "cover",
        "max_fps": 20,
        "denoise": 12,
    },
    "app": {"tray": True, "link_kbps": 120},
}

# What the control panel may change; these are written to state.json and override config.toml.
SAVED_KEYS = (
    ("screen", "orientation"),
    ("screen", "brightness"),
    ("display", "mode"),
    ("display", "idle"),
    ("display", "idle_brightness"),
    ("display", "clock_seconds"),
    ("display", "clock_color"),
    ("display", "hide_redraws"),
    ("display", "calm"),
    *(("bigstats", name) for name in DEFAULTS["bigstats"]),
    ("gif", "file"),
    ("gif", "slideshow"),
    ("gif", "fit"),
    ("gif", "denoise"),
    ("app", "link_kbps"),
)


def load(config_file: Path = CONFIG_FILE, state_file: Path = STATE_FILE) -> dict[str, dict]:
    """Defaults, then config.toml, then state.json."""
    cfg = copy.deepcopy(DEFAULTS)
    if config_file.exists():
        with open(config_file, "rb") as f:
            for section, values in tomllib.load(f).items():
                if isinstance(values, dict):
                    cfg.setdefault(section, {}).update(values)
    try:
        saved = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for key, value in saved.items():
        section, _, name = key.partition(".")
        if (section, name) in SAVED_KEYS:
            cfg[section][name] = value
    return cfg


def save(cfg: dict[str, dict], state_file: Path = STATE_FILE) -> None:
    """Write the control-panel settings; atomic so a crash can't leave a half-written file."""
    data = {f"{section}.{name}": cfg[section][name] for section, name in SAVED_KEYS}
    tmp = state_file.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(state_file)
    except OSError as e:
        log.warning("cannot save settings: %s", e)


def gif_folder(cfg: dict[str, dict]) -> Path:
    folder = Path(cfg["gif"]["folder"])
    return folder if folder.is_absolute() else ROOT / folder
