from __future__ import annotations

import itertools

import pytest
from PIL import ImageChops

from turingscreen.config import DEFAULTS
from turingscreen.views import MODES, ViewOptions, make_view
from turingscreen.views.bigstats import BigStatsView
from turingscreen.views.theme import fmt_rate, fmt_temp, fmt_uptime, parse_hex, pct, rate_parts

from .conftest import make_sample

SIZES = [(320, 480), (480, 320)]
VIEW_MODES = [mode for mode in MODES if mode != "gif"]


@pytest.mark.parametrize("mode, size", list(itertools.product(VIEW_MODES, SIZES)))
def test_every_view_renders_at_screen_size(mode, size, sample, history):
    image = make_view(mode, size, ViewOptions()).render(sample, history)
    assert image.size == size
    assert image.mode == "RGB"


@pytest.mark.parametrize("mode, size", list(itertools.product(VIEW_MODES, SIZES)))
def test_views_cope_with_missing_sensors(mode, size, history):
    empty = make_sample(
        cpu_load=None,
        cpu_clock=None,
        cores=(),
        ram_used=None,
        ram_percent=None,
        gpu=None,
        down=None,
        up=None,
        disk_read=None,
        disk_write=None,
        drives=(),
        uptime=None,
    )
    assert make_view(mode, size, ViewOptions()).render(empty, history).size == size


@pytest.mark.parametrize(
    "hidden", [(), ("clock",), ("cpu",), ("gpu", "ram"), ("cpu", "gpu", "ram"), ("clock", "cpu", "gpu", "ram")]
)
@pytest.mark.parametrize("net", [False, True])
@pytest.mark.parametrize("size", SIZES)
def test_big_stats_item_toggles(hidden, net, size, sample, history):
    items = {**DEFAULTS["bigstats"], "net": net, **dict.fromkeys(hidden, False)}
    view = BigStatsView(size, ViewOptions(bigstats=items))
    expected = [k for k in ("cpu", "gpu", "ram", "net") if items[k]]
    assert view.rows == expected
    assert view.render(sample, history).size == size


def test_big_stats_rows_fill_the_screen(sample):
    two = BigStatsView((320, 480), ViewOptions(bigstats={**DEFAULTS["bigstats"], "gpu": False, "ram": False}))
    four = BigStatsView((320, 480), ViewOptions(bigstats={**DEFAULTS["bigstats"], "net": True}))
    assert two.boxes["cpu"][3] > four.boxes["cpu"][3]
    last = list(two.boxes.values())[-1]
    assert last[1] + last[3] >= 478


def test_network_is_off_by_default():
    assert BigStatsView((320, 480), ViewOptions()).rows == ["cpu", "gpu", "ram"]


def test_single_digit_percentages_have_a_leading_zero():
    assert pct(6.2) == "06"
    assert pct(0) == "00"
    assert pct(100) == "100"
    assert pct(None) == "--"


def test_big_stats_rows_carry_the_padded_number(sample):
    view = BigStatsView((320, 480), ViewOptions())
    reading = view._reading(sample)
    assert view._row("cpu", reading, wide=True).number == "06"


def test_cpu_row_shows_clock_speed_not_temperature(sample):
    view = BigStatsView((320, 480), ViewOptions())
    row = view._row("cpu", view._reading(sample), wide=True)
    assert row.right == "5.3"
    assert row.sub == "GHz"


def test_calm_ignores_small_changes_but_follows_big_ones(sample):
    view = BigStatsView((320, 480), ViewOptions(calm=True))
    first = view._reading(sample)
    assert view._reading(make_sample(cpu_load=7.5)).cpu == first.cpu  # 1.3 points: not worth a repaint
    assert view._reading(make_sample(cpu_load=40)).cpu == 40


def test_calm_can_be_turned_off(sample):
    view = BigStatsView((320, 480), ViewOptions(calm=False))
    view._reading(sample)
    assert view._reading(make_sample(cpu_load=7.5)).cpu == 7.5


def test_clock_uses_the_chosen_colour(sample, history):
    red = (255, 0, 0)
    options = ViewOptions(clock_color=red, clock_seconds=True)
    image = make_view("clock", (320, 480), options).render(sample, history)
    bar = image.crop((0, 472, 320, 480))
    assert red in {color for _, color in bar.getcolors()}
    other = make_view("clock", (320, 480), ViewOptions(clock_color=(0, 255, 0))).render(sample, history)
    assert ImageChops.difference(image, other).getbbox() is not None


def test_clock_seconds_bar_is_optional(sample, history):
    with_bar = make_view("clock", (320, 480), ViewOptions(clock_seconds=True)).render(sample, history)
    without = make_view("clock", (320, 480), ViewOptions(clock_seconds=False)).render(sample, history)
    assert with_bar.crop((0, 472, 320, 480)).getcolors() != without.crop((0, 472, 320, 480)).getcolors()


def test_options_come_from_the_config():
    cfg = {
        "stats": {"temp_unit": "F", "clock_24h": False},
        "bigstats": {"net": True, "clock": False},
        "display": {"clock_seconds": False, "clock_color": "#ff8800", "calm": False},
    }
    options = ViewOptions.from_config(cfg)
    assert options.temp_unit == "F"
    assert options.clock_color == (255, 136, 0)
    assert options.bigstats["net"] is True
    assert options.calm is False


@pytest.mark.parametrize(
    "text, expected",
    [
        ("#38bdf8", (56, 189, 248)),
        ("ff0000", (255, 0, 0)),
        ("#zzzzzz", (56, 189, 248)),
        ("#fff", (56, 189, 248)),
        ("", (56, 189, 248)),
    ],
)
def test_hex_colours(text, expected):
    assert parse_hex(text) == expected


def test_formatting_helpers():
    assert fmt_temp(61.4) == "61°"
    assert fmt_temp(100, "F") == "212°"
    assert fmt_temp(None) == "--°"
    assert rate_parts(None) == ("--", "")
    assert rate_parts(512) == ("512", "B/s")
    assert rate_parts(2 * 2**20) == ("2.0", "MB/s")
    assert fmt_rate(1.5 * 2**30) == "1.5 GB/s"
    assert fmt_uptime(3 * 86400 + 5 * 3600 + 12 * 60) == "3d 5h 12m"
    assert fmt_uptime(7260) == "2h 01m"
