"""Widgets and toys: heartbeat, spinner, bouncing badge, snake, Newton's cradle, terminal."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .common import BG, H, W, font, save


def heartbeat():
    def ecg(x):
        p = (x % 160) / 160
        if 0.40 < p < 0.44:
            return -10 * math.sin((p - 0.40) / 0.04 * math.pi)
        if 0.46 < p < 0.48:
            return 12 * (p - 0.46) / 0.02
        if 0.48 < p < 0.51:
            return 12 - 80 * (p - 0.48) / 0.03
        if 0.51 < p < 0.54:
            return -68 + 85 * (p - 0.51) / 0.03
        if 0.54 < p < 0.56:
            return 17 - 17 * (p - 0.54) / 0.02
        if 0.64 < p < 0.74:
            return -14 * math.sin((p - 0.64) / 0.10 * math.pi)
        return 0

    base = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(base)
    for x in range(0, W, 20):
        d.line((x, 170, x, 330), fill=(16, 30, 22))
    for y in range(170, 331, 20):
        d.line((0, y, W, y), fill=(16, 30, 22))
    d.text((20, 60), "BPM", font=font("Roboto-Medium.ttf", 20), fill=(80, 200, 120))
    d.text((20, 84), "72", font=font("Roboto-Bold.ttf", 56), fill=(120, 255, 160))
    trace = base.copy()
    n = 64
    step = W / n * 2
    frames = []
    ys = [250 + ecg(x) for x in range(W + 1)]
    canvas = trace.copy()
    dc = ImageDraw.Draw(canvas)
    dc.line([(x, ys[x]) for x in range(W)], fill=(80, 255, 140), width=2)  # start with a full trace
    for i in range(n):
        head = int((i * step) % W)
        nxt = int(min(W, head + step))
        # erase a gap ahead of the write head, then draw the new segment
        canvas.paste(base.crop((nxt, 168, min(W, nxt + 16), 332)), (nxt, 168))
        canvas.paste(base.crop((head, 168, nxt + 1, 332)), (head, 168))
        ImageDraw.Draw(canvas).line([(x, ys[x]) for x in range(head, nxt + 1)], fill=(80, 255, 140), width=2)
        im = canvas.copy()
        dd = ImageDraw.Draw(im)
        beat = 1 + 0.18 * max(0, math.cos((i % 32) / 32 * 2 * math.pi * 2)) if (i % 32) < 8 else 1
        r = 22 * beat
        cx, cy = 250, 110
        dd.ellipse((cx - r, cy - r * 0.9, cx, cy + r * 0.2), fill=(240, 70, 90))
        dd.ellipse((cx, cy - r * 0.9, cx + r, cy + r * 0.2), fill=(240, 70, 90))
        dd.polygon(
            [(cx - r * 0.98, cy - r * 0.2), (cx + r * 0.98, cy - r * 0.2), (cx, cy + r * 1.1)], fill=(240, 70, 90)
        )
        frames.append(im)
    save("heartbeat.gif", frames, 60)


def spinner():
    n = 30
    frames = []
    f = font("Roboto-Medium.ttf", 22)
    for i in range(n):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        cx, cy, r = 160, 220, 56
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(30, 36, 50), width=10)
        a = i / n * 360
        for k in range(12):
            col = tuple(int(c * (k + 1) / 12 + 30 * (1 - (k + 1) / 12)) for c in (56, 189, 248))
            d.arc((cx - r, cy - r, cx + r, cy + r), a + k * 10, a + k * 10 + 11, fill=col, width=10)
        dots = "." * (1 + (i // 10) % 3)
        d.text((112, 310), "loading" + dots, font=f, fill=(140, 150, 170))
        frames.append(im)
    save("spinner.gif", frames, 60)


def bouncing_badge():
    n = 320
    frames = []
    bw, bh = 100, 40
    f = font("Roboto-Bold.ttf", 20)
    cols = [(56, 189, 248), (118, 227, 95), (167, 139, 250), (251, 191, 36), (244, 114, 182)]
    # a closed path: speeds chosen so the badge returns to the start after n frames
    vx, vy = 2 * (W - bw) / 160, 2 * (H - bh) / 320  # x bounces twice per loop, y once
    x, y, dx, dy, ci = 0.0, 0.0, 1, 1, 0
    for _ in range(n):
        im = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((x, y, x + bw, y + bh), radius=10, fill=cols[ci])
        d.text((x + 13, y + 8), "SCREEN", font=f, fill=(0, 0, 0))
        frames.append(im)
        x += vx * dx
        y += vy * dy
        if x <= 0 or x >= W - bw:
            dx = -dx
            x = max(0, min(W - bw, x))
            ci = (ci + 1) % len(cols)
        if y <= 0 or y >= H - bh:
            dy = -dy
            y = max(0, min(H - bh, y))
            ci = (ci + 1) % len(cols)
    save("bouncing-badge.gif", frames, 50)


def snake():
    cell = 20
    cols, rows = W // cell, (H - 40) // cell
    # a closed loop path through the grid (serpentine), snake follows it forever
    path = []
    for c in range(cols):
        rng = range(1, rows) if c % 2 == 0 else range(rows - 1, 0, -1)
        path += [(c, r) for r in rng]
    path += [(c, 0) for c in range(cols - 1, -1, -1)]
    L = len(path)
    length = 14
    n = L  # one full lap
    f = font("JetBrainsMono-Bold.ttf", 18)
    frames = []
    for i in range(n):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W - 1, rows * cell - 1), outline=(30, 36, 50))
        for k in range(length):
            c, r = path[(i - k) % L]
            g = 230 - k * 8
            d.rounded_rectangle(
                (c * cell + 2, r * cell + 2, c * cell + cell - 3, r * cell + cell - 3), radius=4, fill=(60, g, 110)
            )
        ac, ar = path[((i // 40) * 40 + 40) % L]
        d.ellipse((ac * cell + 4, ar * cell + 4, ac * cell + cell - 5, ar * cell + cell - 5), fill=(240, 80, 80))
        d.text((10, H - 32), "SNAKE", font=f, fill=(90, 230, 130))
        frames.append(im)
    save("snake.gif", frames, 60)


def cradle():
    n = 40
    frames = []
    top, length, r = 190, 105, 15
    xs = [160 + (k - 2) * 2 * r for k in range(5)]
    for i in range(n):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle((70, top - 8, 250, top), fill=(80, 90, 110))
        ph = math.sin(i / n * 2 * math.pi)
        for k, x in enumerate(xs):
            a = 0
            if k == 0 and ph < 0:
                a = ph * 0.6
            if k == 4 and ph > 0:
                a = ph * 0.6
            bx = x + length * math.sin(a)
            by = top + length * math.cos(a)
            d.line((x, top, bx, by), fill=(120, 130, 150), width=1)
            d.ellipse((bx - r, by - r, bx + r, by + r), fill=(190, 200, 215))
            d.ellipse((bx - r * 0.5, by - r * 0.6, bx - r * 0.1, by - r * 0.2), fill=(240, 245, 255))
        frames.append(im)
    save("newtons-cradle.gif", frames, 60)


def terminal():
    f = font("JetBrainsMono-Medium.ttf", 16)
    lines = ["$ ssh turing", "connected.", "$ uptime", " 12 days, 4:20", "$ echo hello", "hello", "$ _"]
    green = (90, 230, 130)
    frames = []
    seq = []
    for li, line in enumerate(lines[:-1]):
        if line.startswith("$"):
            for c in range(1, len(line) + 1):
                seq.append((li, c))
        else:
            seq.append((li, len(line)))
        seq += [(li, len(line))] * 3
    seq += [(len(lines) - 2, len(lines[-2]))] * 14
    for k, (li, c) in enumerate(seq):
        im = Image.new("RGB", (W, H), (6, 10, 8))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, 26), fill=(30, 36, 34))
        for j, col in enumerate(((240, 90, 90), (240, 200, 80), (110, 220, 110))):
            d.ellipse((10 + j * 18, 8, 20 + j * 18, 18), fill=col)
        y = 50
        for j in range(li + 1):
            s = lines[j] if j < li else lines[j][:c]
            d.text((14, y), s, font=f, fill=green if s.startswith("$") else (200, 220, 205))
            y += 26
        cx = 14 + d.textlength(lines[li][:c], font=f)
        if (k // 4) % 2 == 0:
            d.rectangle((cx + 2, y - 24, cx + 11, y - 6), fill=green)
        frames.append(im)
    save("terminal.gif", frames, 80)


def bouncing_ball() -> None:
    """Small area moving on a still background: the best case for this screen."""
    frames = []
    for i in range(40):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.text((92, 30), "bouncing ball", fill=(128, 138, 158))
        y = 330 - abs(math.sin(i / 40 * 2 * math.pi)) * 200
        d.ellipse((140, y, 180, y + 40), fill=(56, 189, 248))
        d.line((60, 372, 260, 372), fill=(58, 66, 84), width=3)
        frames.append(im)
    save("sample-ball.gif", frames, 50)


def waves() -> None:
    """Every pixel moves: the worst case for this screen (about 1 fps), kept to show the difference."""
    colors = [(56, 189, 248), (118, 227, 95), (167, 139, 250), (251, 191, 36), (244, 114, 182)]
    frames = []
    for i in range(24):
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        t = i / 24 * 2 * math.pi
        for k, color in enumerate(colors):
            points = [(x, 240 + math.sin(x / 38 + t + k * 0.7) * (120 - k * 15)) for x in range(0, W + 1, 4)]
            d.line(points, fill=color, width=4)
        frames.append(im)
    save("sample-waves.gif", frames, 80)
