"""Little scenes: a cat, a fish tank, a campfire, an orbit, a ghost, clouds."""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .common import BG, H, W, pixelate, save


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
        d.ellipse((cx - 14, cy, cx + 16, cy + 26), fill=body)  # body
        d.ellipse((cx - 13, cy - 22, cx + 13, cy + 2), fill=body)  # head
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
        for k, (fy, speed, col, size, direction) in enumerate(
            [(150, 1, (255, 140, 40), 20, 1), (260, 2, (90, 200, 255), 14, -1), (330, 1, (255, 220, 60), 12, 1)]
        ):
            span = W + 80
            x = ((i / n) * span * speed) % span - 40
            if direction < 0:
                x = W - x
            y = fy + math.sin(i / n * 2 * math.pi * 2 + k) * 4
            s = size
            d.ellipse((x - s, y - s * 0.6, x + s, y + s * 0.6), fill=col)
            tx = x - s * direction
            d.polygon(
                [(tx, y), (tx - s * 0.8 * direction, y - s * 0.6), (tx - s * 0.8 * direction, y + s * 0.6)], fill=col
            )
            ex = x + s * 0.5 * direction
            d.ellipse((ex - 2, y - 3, ex + 2, y + 1), fill=(20, 20, 30))
        for bx, off in bubbles:
            p = ((i + off) % n) / n
            by = H - 60 - p * 330
            r = 2 + p * 3
            d.ellipse((bx - r, by - r, bx + r, by + r), outline=(190, 230, 255))
        frames.append(im)
    save("fish-tank.gif", frames, 70)


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
                h = (
                    (110 * scale)
                    * (0.55 + 0.45 * abs(math.sin(k * 1.7 + t * (1 + layer * 0.3))))
                    * (1 - abs(k - 3) / 4)
                )
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
        for rx, ry, speed, size, col in ((70, 30, 2, 7, (120, 200, 255)), (130, 56, 1, 11, (240, 120, 90))):
            a = i / n * 2 * math.pi * speed
            x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
            if math.sin(a) < 0 and abs(x - cx) < 24:  # behind the sun
                continue
            d.ellipse((x - size, y - size, x + size, y + size), fill=col)
        frames.append(im)
    save("orbit.gif", frames, 70)


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
            for ox, oy, rr in ((0, 10, 26), (24, 0, 32), (52, 8, 26), (76, 14, 20)):
                rr *= s
                d.ellipse((x + ox * s - rr, y + oy * s - rr, x + ox * s + rr, y + oy * s + rr), fill=(250, 252, 255))
        frames.append(im)
    save("clouds.gif", frames, 110)
