from __future__ import annotations

from PIL import Image, ImageDraw

from turingscreen.diff import dirty_rects


def blank(size=(100, 100)):
    return Image.new("RGB", size, (0, 0, 0))


def test_no_previous_picture_sends_everything():
    assert dirty_rects(None, blank((30, 20))) == [(0, 0, 30, 20)]


def test_identical_pictures_send_nothing():
    assert dirty_rects(blank(), blank()) == []


def test_one_changed_pixel_is_one_pixel():
    new = blank()
    new.putpixel((40, 60), (255, 255, 255))
    assert dirty_rects(blank(), new) == [(40, 60, 41, 61)]


def test_distant_changes_are_separate_rectangles():
    new = blank()
    ImageDraw.Draw(new).rectangle((5, 5, 10, 10), fill="white")
    ImageDraw.Draw(new).rectangle((80, 80, 90, 90), fill="white")
    assert dirty_rects(blank(), new) == [(5, 5, 11, 11), (80, 80, 91, 91)]


def test_changes_on_one_row_far_apart_are_not_merged_into_one_wide_box():
    new = blank((200, 10))
    new.putpixel((2, 3), (255, 0, 0))
    new.putpixel((190, 3), (255, 0, 0))
    rects = dirty_rects(blank((200, 10)), new)
    assert rects == [(2, 3, 3, 4), (190, 3, 191, 4)]


def test_nearby_changes_merge():
    new = blank()
    new.putpixel((10, 10), (255, 0, 0))
    new.putpixel((20, 12), (255, 0, 0))
    assert dirty_rects(blank(), new) == [(10, 10, 21, 13)]


def test_many_fragments_fall_back_to_one_box_per_band():
    new = blank((400, 10))
    for x in range(0, 400, 30):
        new.putpixel((x, 4), (255, 0, 0))
    assert dirty_rects(blank((400, 10)), new, max_rects=3) == [(0, 4, 391, 5)]


def test_every_changed_pixel_is_covered():
    old, new = blank(), blank()
    for x, y in ((3, 4), (50, 51), (97, 2), (60, 90)):
        new.putpixel((x, y), (9, 9, 9))
    rects = dirty_rects(old, new)
    for x, y in ((3, 4), (50, 51), (97, 2), (60, 90)):
        assert any(r[0] <= x < r[2] and r[1] <= y < r[3] for r in rects)
