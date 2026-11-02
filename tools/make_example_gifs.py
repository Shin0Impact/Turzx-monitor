"""Regenerates the example GIFs in gifs/ (designed to play smoothly on the screen's slow link).

python tools/make_example_gifs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from example_gifs import scenes, widgets  # noqa: E402

GENERATORS = [
    scenes.cat,
    scenes.fish_tank,
    scenes.campfire,
    widgets.heartbeat,
    widgets.spinner,
    scenes.orbit,
    widgets.bouncing_badge,
    widgets.snake,
    widgets.cradle,
    scenes.ghost,
    scenes.clouds,
    widgets.terminal,
]

if __name__ == "__main__":
    for generate in GENERATORS:
        generate()
