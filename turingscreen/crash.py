"""Background launches have no console, so write unhandled errors to logs/crash.log."""

from __future__ import annotations

import datetime
import sys
import traceback

from .config import LOG_DIR


def _hook(exc_type, exc, tb) -> None:
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with open(LOG_DIR / "crash.log", "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
            f.write("".join(traceback.format_exception(exc_type, exc, tb)) + "\n")
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc, tb)


def install() -> None:
    sys.excepthook = _hook
