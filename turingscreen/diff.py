"""Finds which parts of a picture changed. The screen only takes ~125 KB/s, so every byte saved counts."""

from __future__ import annotations

import numpy as np
from PIL import Image

Rect = tuple[int, int, int, int]  # left, top, right, bottom (exclusive)


def _runs(indexes: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """Group sorted indexes into (first, last) runs, merging runs closer than `gap`."""
    runs = []
    start = prev = int(indexes[0])
    for i in indexes[1:]:
        if i - prev > gap:
            runs.append((start, prev))
            start = int(i)
        prev = int(i)
    runs.append((start, prev))
    return runs


def dirty_rects(
    old: Image.Image | None, new: Image.Image, row_gap: int = 6, col_gap: int = 24, max_rects: int = 10
) -> list[Rect]:
    """Rectangles covering every pixel that differs between `old` and `new` (same size).

    Changes are split into horizontal bands, then each band into column runs, so a changed number
    doesn't resend a whole row. With no `old` picture the whole of `new` is returned.
    """
    if old is None:
        return [(0, 0, *new.size)]
    changed = (np.asarray(old) != np.asarray(new)).any(axis=2)
    rows = np.flatnonzero(changed.any(axis=1))
    if rows.size == 0:
        return []
    bands = _runs(rows, row_gap)
    rects: list[Rect] = []
    for top, bottom in bands:
        cols = np.flatnonzero(changed[top : bottom + 1].any(axis=0))
        rects += [(left, top, right + 1, bottom + 1) for left, right in _runs(cols, col_gap)]
    if len(rects) > max_rects:  # too fragmented: one box per band
        rects = []
        for top, bottom in bands:
            cols = np.flatnonzero(changed[top : bottom + 1].any(axis=0))
            rects.append((int(cols[0]), top, int(cols[-1]) + 1, bottom + 1))
    return rects
