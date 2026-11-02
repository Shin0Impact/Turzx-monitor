"""Generates example GIFs made for the Turing 3.5" screen: small moving parts on still backgrounds,
so they play smoothly over its ~125 KB/s link.   python make_examples.py   (writes into gifs/)"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gifs")
W, H = 320, 480
BG = (8, 10, 15)


def font(name, size):
    return ImageFont.truetype(os.path.join(HERE, "fonts", name), size)


def save(name, frames, ms):
    os.makedirs(OUT, exist_ok=True)
    frames = [f.convert("RGB") for f in frames]
    frames[0].save(os.path.join(OUT, name), save_all=True, append_images=frames[1:], duration=ms, loop=0,
                   optimize=False, disposal=1)
    print("wrote", name, len(frames), "frames")


def pixelate(img, scale):
    """Draw small, show big: gives a crisp pixel-art look."""
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


# 1 ---------------------------------------------------------------- pixel cat (tail swish + blink)
def cat():
    frames = []
    n = 36
    for i in range(n):
        im = Image.new("RGB", (80, 120), BG)
        d = ImageDraw.Draw(im)
        d.text((22, 8), "meow", fill=(70, 78, 96))
        body, dark = (240, 170, 90), (190, 120, 60)
        cx, cy = 38, 78
        # tail (behind body)
        sw = math.sin(i / n * 2 * math.pi)
        pts = [(cx + 12 + k * 3, cy + 18 - k * 4 + int(sw * k * k * 0.5)) for k in range(7)]
        d.line(pts, fill=dark, width=4)
        d.ellipse((cx - 14, cy, cx + 16, cy + 26), fill=body)            # body
        d.ellipse((cx - 13, cy - 22, cx + 13, cy + 2), fill=body)         # head
        d.polygon([(cx - 12, cy - 14), (cx - 10, cy - 28), (cx - 2, cy - 20)], fill=body)  # ears
        d.polygon([(cx + 12, cy - 14), (cx + 10, cy - 28), (cx + 2, cy - 20)], fill=body)
        d.polygon([(cx - 10, cy - 16), (cx - 9, cy - 24), (cx - 4, cy - 19)], fill=(250, 140, 150))
        d.polygon([(cx + 10, cy - 16), (cx + 9, cy - 24), (cx + 4, cy - 19)], fill=(250, 140, 150))
        blink = i in (10, 11, 28)
        for ex in (cx - 6, cx + 6):
            if blink:
                d.line((ex - 2, cy - 11, ex + 2, cy - 11), fill=(30, 30, 30))
            else:
                d.rectangle((ex - 2, cy - 13, ex + 1, cy - 9), fill=(30, 30, 30))
        d.point((cx, cy - 7), fill=(250, 140, 150))
        d.line((cx - 4, cy + 26, cx - 4, cy + 22), fill=dark)
        d.line((cx + 5, cy + 26, cx + 5, cy + 22), fill=dark)
        d.line((0, cy + 27, 80, cy + 27), fill=(40, 46, 60))
        frames.append(pixelate(im, 4))
    save("pixel-cat.gif", frames, 70)


# 2 ---------------------------------------------------------------- fish tank
def fish_tank():
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        d.line((0, y, W, y), fill=(int(8 + 10 * t), int(30 + 40 * t), int(60 + 50 * t)))
    d.rectangle((0, H - 50, W, H), fill=(120, 100, 70))
    for x in range(0, W, 7):
        d.point((x, H - 50 + (x * 13) % 40), fill=(150, 130, 90))
    for x in (40, 70, 250):
        d.line((x, H - 50, x - 6, H - 140), fill=(40, 120, 70), width=5)
        d.line((x + 8, H - 50, x + 14, H - 110), fill=(40, 140, 80), width=4)
    n = 60
    frames = []
    bubbles = [(random.Random(k).randint(150, 300), k * 13 % n) for k in range(6)]
    for i in range(n):
        im = bg.copy()
        d = ImageDraw.Draw(im)
        for k, (fy, speed, col, size, direction) in enumerate([(150, 1, (255, 140, 40), 20, 1),
                                                                (260, 2, (90, 200, 255), 14, -1),
                                                                (330, 1, (255, 220, 60), 12, 1)]):
            span = W + 80
            x = ((i / n) * span * speed) % span - 40
            if direction < 0:
                x = W - x
            y = fy + math.sin(i / n * 2 * math.pi * 2 + k) * 4
            s = size
            d.ellipse((x - s, y - s * 0.6, x + s, y + s * 0.6), fill=col)
            tx = x - s * direction
            d.polygon([(tx, y), (tx - s * 0.8 * direction, y - s * 0.6), (tx - s * 0.8 * direction, y + s * 0.6)], fill=col)
            ex = x + s * 0.5 * direction
            d.ellipse((ex - 2, y - 3, ex + 2, y + 1), fill=(20, 20, 30))
        for bx, off in bubbles:
            p = ((i + off) % n) / n
            by = H - 60 - p * 330
            r = 2 + p * 3
            d.ellipse((bx - r, by - r, bx + r, by + r), outline=(190, 230, 255))
        frames.append(im)
    save("fish-tank.gif", frames, 70)


# 3 ---------------------------------------------------------------- campfire
def campfire():
    rnd = random.Random(3)
    bg = Image.new("RGB", (W, H), (6, 8, 20))
    d = ImageDraw.Draw(bg)
    stars = [(rnd.randint(0, W), rnd.randint(0, 260)) for _ in range(40)]
    for x, y in stars:
        d.point((x, y), fill=(160, 170, 200))
    d.rectangle((0, 400, W, H), fill=(20, 18, 16))
    d.polygon([(100, 410), (220, 380), (226, 392), (106, 422)], fill=(90, 55, 30))
    d.polygon([(100, 380), (220, 410), (214, 422), (94, 392)], fill=(110, 65, 35))
    n = 24
    frames = []
    for i in range(n):
        im = bg.copy()
        d = ImageDraw.Draw(im)
        t = i / n * 2 * math.pi
        for layer, (col, scale) in enumerate([((230, 70, 20), 1.0), ((250, 150, 30), 0.72), ((255, 230, 120), 0.42)]):
            pts = [(110 + 20 * (1 - scale) * 2, 400)]
            for k in range(7):
                x = 110 + 20 * (1 - scale) * 2 + k * (100 * scale / 6)
                h = (110 * scale) * (0.55 + 0.45 * abs(math.sin(k * 1.7 + t * (1 + layer * 0.3)))) * (1 - abs(k - 3) / 4)
                pts.append((x, 400 - h))
            pts.append((110 + 20 * (1 - scale) * 2 + 100 * scale, 400))
            d.polygon(pts, fill=col)
        for k in range(4):  # sparks
            p = ((i + k * 6) % n) / n
            sx = 160 + math.sin(k * 2 + p * 6) * 25
            sy = 300 - p * 110
            d.point((sx, sy), fill=(255, 200, 80))
            d.point((sx + 1, sy), fill=(255, 160, 40))
        tw = stars[i % len(stars)]
        d.ellipse((tw[0] - 1, tw[1] - 1, tw[0] + 1, tw[1] + 1), fill=(255, 255, 255))
        frames.append(im)
    save("campfire.gif", frames, 90)


# 4 ---------------------------------------------------------------- heartbeat monitor
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
        dd.polygon([(cx - r * 0.98, cy - r * 0.2), (cx + r * 0.98, cy - r * 0.2), (cx, cy + r * 1.1)], fill=(240, 70, 90))
        frames.append(im)
    save("heartbeat.gif", frames, 60)


# 5 ---------------------------------------------------------------- loading spinner
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


# 6 ---------------------------------------------------------------- orbit
def orbit():
    rnd = random.Random(7)
    bg = Image.new("RGB", (W, H), (4, 5, 12))
    d = ImageDraw.Draw(bg)
    for _ in range(70):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        d.point((x, y), fill=(rnd.randint(80, 200),) * 3)
    cx, cy = 160, 240
    for rx, ry in ((70, 30), (130, 56)):
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(30, 34, 50))
    for g in range(30, 0, -3):
        c = int(60 * (1 - g / 30))
        d.ellipse((cx - g, cy - g, cx + g, cy + g), fill=(70 + c * 2, 50 + c, 10))
    d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), fill=(255, 200, 70))
    n = 60
    frames = []
    for i in range(n):
        im = bg.copy()
        d = ImageDraw.Draw(im)
        for (rx, ry, speed, size, col) in ((70, 30, 2, 7, (120, 200, 255)), (130, 56, 1, 11, (240, 120, 90))):
            a = i / n * 2 * math.pi * speed
            x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
            if math.sin(a) < 0:  # behind the sun
                if abs(x - cx) < 24:
                    continue
            d.ellipse((x - size, y - size, x + size, y + size), fill=col)
        frames.append(im)
    save("orbit.gif", frames, 70)


# 7 ---------------------------------------------------------------- bouncing badge
def bouncing_badge():
    n = 320
    frames = []
    bw, bh = 100, 40
    f = font("Roboto-Bold.ttf", 20)
    cols = [(56, 189, 248), (118, 227, 95), (167, 139, 250), (251, 191, 36), (244, 114, 182)]
    # a closed path: speeds chosen so the badge returns to the start after n frames
    vx, vy = 2 * (W - bw) / 160, 2 * (H - bh) / 320  # x bounces twice per loop, y once
    x, y, dx, dy, ci = 0.0, 0.0, 1, 1, 0
    for i in range(n):
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


# 8 ---------------------------------------------------------------- snake
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
            d.rounded_rectangle((c * cell + 2, r * cell + 2, c * cell + cell - 3, r * cell + cell - 3), radius=4,
                                fill=(60, g, 110))
        ac, ar = path[((i // 40) * 40 + 40) % L]
        d.ellipse((ac * cell + 4, ar * cell + 4, ac * cell + cell - 5, ar * cell + cell - 5), fill=(240, 80, 80))
        d.text((10, H - 32), "SNAKE", font=f, fill=(90, 230, 130))
        frames.append(im)
    save("snake.gif", frames, 60)


# 9 ---------------------------------------------------------------- newton's cradle
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


# 10 --------------------------------------------------------------- ghost
def ghost():
    n = 40
    frames = []
    for i in range(n):
        big = Image.new("RGB", (W, H), (10, 8, 22))
        im = big
        d = ImageDraw.Draw(im)
        t = i / n * 2 * math.pi
        cy = 220 + math.sin(t) * 14
        cx = 160
        sw = 1 - 0.25 * (math.sin(t) + 1) / 2
        d.ellipse((cx - 50 * sw, 372, cx + 50 * sw, 384), fill=(22, 18, 40))  # shadow
        body = (235, 235, 250)
        d.ellipse((cx - 50, cy - 60, cx + 50, cy + 40), fill=body)
        d.rectangle((cx - 50, cy - 10, cx + 50, cy + 50), fill=body)
        for k in range(5):  # wavy hem
            wx = cx - 50 + k * 20
            off = math.sin(t * 2 + k) * 4
            d.ellipse((wx, cy + 40 + off, wx + 20, cy + 64 + off), fill=body)
        blink = i in (14, 15, 33)
        for ex in (cx - 18, cx + 18):
            if blink:
                d.line((ex - 7, cy - 12, ex + 7, cy - 12), fill=(30, 30, 50), width=3)
            else:
                d.ellipse((ex - 7, cy - 22, ex + 7, cy - 4), fill=(30, 30, 50))
        d.ellipse((cx - 8, cy + 6, cx + 8, cy + 18), fill=(30, 30, 50))
        # draw at full size, then shrink to 70% on the same background (smaller moving area)
        small = im.resize((int(W * 0.7), int(H * 0.7)), Image.LANCZOS)
        out = Image.new("RGB", (W, H), (10, 8, 22))
        out.paste(small, ((W - small.width) // 2, (H - small.height) // 2 + 20))
        frames.append(out)
    save("ghost.gif", frames, 70)


# 11 --------------------------------------------------------------- drifting clouds
def clouds():
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        d.line((0, y, W, y), fill=(int(40 + 90 * t), int(110 + 80 * t), int(200 + 40 * t)))
    d.ellipse((220, 60, 290, 130), fill=(255, 230, 120))
    d.polygon([(0, 420), (90, 360), (180, 410), (260, 350), (320, 400), (320, H), (0, H)], fill=(60, 120, 80))
    n = 120
    frames = []
    specs = [(90, 1, 1.0), (180, 2, 0.8), (260, 1, 0.6)]
    for i in range(n):
        im = bg.copy()
        d = ImageDraw.Draw(im)
        for k, (y, laps, s) in enumerate(specs):
            span = W + 160
            x = (k * 140 + i / n * span * laps) % span - 120
            for (ox, oy, rr) in ((0, 10, 26), (24, 0, 32), (52, 8, 26), (76, 14, 20)):
                rr *= s
                d.ellipse((x + ox * s - rr, y + oy * s - rr, x + ox * s + rr, y + oy * s + rr), fill=(250, 252, 255))
        frames.append(im)
    save("clouds.gif", frames, 110)


# 12 --------------------------------------------------------------- terminal typing
def terminal():
    f = font("JetBrainsMono-Medium.ttf", 16)
    lines = ["$ ssh turing", "connected.", "$ uptime", " 12 days, 4:20", "$ echo hello", "hello", "$ _"]
    green = (90, 230, 130)
    frames = []
    text_state = []
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


if __name__ == "__main__":
    for fn in (cat, fish_tank, campfire, heartbeat, spinner, orbit, bouncing_badge, snake, cradle, ghost, clouds, terminal):
        fn()
