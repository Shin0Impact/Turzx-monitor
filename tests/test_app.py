"""The app's behaviour on a simulated screen: what it shows, when it goes dark, how it recovers."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from turingscreen.app import DARK, IDLE_CLOCK
from turingscreen.power import PowerEvent

from .conftest import Rig, make_sample, wait_for


def make_gif(path: Path, moving: bool = True, frames: int = 8) -> Path:
    images = []
    for i in range(frames):
        image = Image.new("RGB", (320, 480), (8, 10, 15))
        ImageDraw.Draw(image).rectangle((10 + i * 20 if moving else 10, 100, 60 + i * 20, 150), fill="white")
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:], duration=50, loop=0)
    return path


def start(rig: Rig) -> None:
    rig.settle()


def test_starts_on_big_stats_and_lights_up(rig):
    start(rig)
    assert rig.app.view_name == "stats"
    assert rig.lcd.is_on
    assert rig.lcd.brightness == 50
    assert rig.lcd.blits > 0
    assert rig.app.status == "connected on simulator"


def test_the_first_picture_is_drawn_before_the_backlight_comes_up(rig):
    start(rig)
    first_blit = rig.lcd.events.index("on")
    assert rig.lcd.events[: first_blit + 1][-2:] == ["brightness 0", "on"]
    assert rig.lcd.events[-1] == "brightness 50"


def test_only_changed_pixels_are_sent_once_the_screen_is_drawn(rig):
    start(rig)
    before = rig.lcd.bytes_sent
    rig.stats.sample = make_sample(cpu_load=60.0)
    rig.settle()
    assert 0 < rig.lcd.bytes_sent - before < 0.5 * 320 * 480 * 2


def test_lock_shows_a_dim_clock_and_unlock_restores(rig):
    start(rig)
    rig.app.on_power(PowerEvent.LOCK)
    rig.settle()
    assert rig.app.view_name == IDLE_CLOCK
    assert rig.lcd.is_on
    assert rig.lcd.brightness == 25
    rig.app.on_power(PowerEvent.UNLOCK)
    rig.settle()
    assert rig.app.view_name == "stats"
    assert rig.lcd.brightness == 50


def test_idle_can_turn_the_screen_off_instead(rig):
    start(rig)
    rig.app.set("display", "idle", "off")
    rig.app.on_power(PowerEvent.DISPLAY_OFF)
    rig.settle()
    assert not rig.lcd.is_on
    rig.app.on_power(PowerEvent.DISPLAY_ON)
    rig.settle()
    assert rig.lcd.is_on
    assert rig.app.view_name == "stats"


def test_dim_counts_as_the_monitors_being_back_on(rig):
    start(rig)
    rig.app.on_power(PowerEvent.DISPLAY_OFF)
    rig.app.on_power(PowerEvent.DISPLAY_DIM)
    rig.settle()
    assert rig.app.view_name == "stats"


def test_screen_stays_in_idle_until_both_lock_and_monitors_are_cleared(rig):
    start(rig)
    rig.app.on_power(PowerEvent.LOCK)
    rig.app.on_power(PowerEvent.DISPLAY_OFF)
    rig.app.on_power(PowerEvent.DISPLAY_ON)
    rig.settle()
    assert rig.app.view_name == IDLE_CLOCK
    rig.app.on_power(PowerEvent.UNLOCK)
    rig.settle()
    assert rig.app.view_name == "stats"


def test_sleep_goes_dark_immediately_even_when_idle_is_a_clock(rig):
    start(rig)
    rig.app.on_power(PowerEvent.LOCK)
    rig.settle()
    rig.app.on_power(PowerEvent.SUSPEND)
    assert not rig.lcd.is_on  # right away, from the power thread, before the render loop runs again
    assert rig.lcd.brightness == 0
    rig.settle()
    assert rig.app.view_name == DARK
    assert rig.stats.paused


def test_sleep_can_be_disabled(rig):
    rig.app.cfg["dark"]["on_sleep"] = False
    start(rig)
    rig.app.on_power(PowerEvent.SUSPEND)
    rig.settle()
    assert rig.lcd.is_on


def test_nothing_is_drawn_while_dark(rig):
    start(rig)
    rig.app.on_power(PowerEvent.SUSPEND)
    rig.settle()
    blits = rig.lcd.blits
    rig.steps(10)
    assert rig.lcd.blits == blits
    assert rig.lcd.glass().getextrema() == ((0, 0), (0, 0), (0, 0))


def test_resume_reconnects_after_the_usb_link_died_in_sleep(rig):
    start(rig)
    rig.app.on_power(PowerEvent.SUSPEND)
    rig.settle()
    rig.lcd.unplugged = True  # the port disappears while asleep
    rig.app.on_power(PowerEvent.RESUME)
    opens = rig.lcd.opens
    rig.steps(4)
    assert rig.app.view_name != "stats" or not rig.lcd.is_on
    rig.lcd.unplugged = False
    for _ in range(40):  # waits out the retry back-off
        rig.step()
        if rig.lcd.is_on and rig.lcd.opens > opens:
            break
    rig.settle()
    assert rig.lcd.opens > opens
    assert rig.lcd.is_on
    assert rig.app.view_name == "stats"


def test_unplugging_retries_with_growing_delays_then_recovers(rig):
    start(rig)
    rig.lcd.unplugged = True
    rig.app.display.disconnect()
    waits = [rig.step() for _ in range(5)]
    assert waits[:5] == [1, 2, 4, 8, 16]
    assert "screen" in rig.app.status
    rig.lcd.unplugged = False
    rig.step()
    rig.settle()
    assert rig.lcd.is_on
    assert rig.app.view_name == "stats"


def test_shutdown_goes_dark_and_stops_the_loop(rig):
    start(rig)
    rig.app.on_power(PowerEvent.SHUTDOWN)
    assert rig.app.stop.is_set()
    assert not rig.lcd.is_on


def test_shutdown_request_blanks_the_screen_at_once(rig):
    start(rig)
    rig.app.on_power(PowerEvent.SHUTDOWN_PENDING)
    assert not rig.lcd.is_on
    assert not rig.app.stop.is_set()


def test_cancelled_shutdown_brings_the_screen_back(rig):
    start(rig)
    rig.app.on_power(PowerEvent.SHUTDOWN_PENDING)
    rig.app.on_power(PowerEvent.SHUTDOWN_CANCELLED)
    rig.step()
    rig.settle()
    assert rig.lcd.is_on
    assert rig.app.view_name == "stats"


def test_quit_turns_the_screen_off(rig):
    start(rig)
    rig.app.shutdown()
    assert not rig.lcd.is_on


# ---- settings ----


def test_settings_are_applied_and_saved(rig):
    start(rig)
    rig.app.set("screen", "brightness", 30)
    rig.settle()
    assert rig.lcd.brightness == 30
    assert rig.saved[-1]["screen"]["brightness"] == 30


def test_switching_mode(rig):
    start(rig)
    for mode in ("clock", "detail", "stats"):
        rig.app.set("display", "mode", mode)
        rig.settle()
        assert rig.app.view_name == mode


def test_stats_sampling_pauses_on_views_that_do_not_use_it(rig):
    start(rig)
    assert not rig.stats.paused
    rig.app.set("display", "mode", "clock")
    rig.settle()
    assert rig.stats.paused
    rig.app.set("display", "mode", "detail")
    rig.settle()
    assert not rig.stats.paused


def test_rotation_resizes_everything(rig):
    start(rig)
    rig.app.set("screen", "orientation", "landscape")
    rig.settle()
    assert rig.lcd.size == (480, 320)
    assert rig.lcd.glass().size == (480, 320)
    assert rig.app.display.preview().size == (480, 320)
    rig.app.set("screen", "orientation", "portrait")
    rig.settle()
    assert rig.lcd.size == (320, 480)


def test_big_stats_toggle_rebuilds_without_blanking(rig):
    start(rig)
    blackouts = rig.blackouts
    rig.app.set("bigstats", "net", True)
    rig.settle()
    assert rig.app._view.rows == ["cpu", "gpu", "ram", "net"]
    assert rig.blackouts == blackouts


def test_clock_colour_change_is_live_and_does_not_blank(rig):
    rig.app.set("display", "mode", "clock")
    start(rig)
    blackouts = rig.blackouts
    rig.app.set("display", "clock_color", "#ff0000")
    rig.settle()
    assert rig.blackouts == blackouts
    bar = rig.lcd.glass().crop((0, 472, 320, 480))
    assert (255, 0, 0) in {color for _, color in bar.getcolors()}
    assert rig.saved[-1]["display"]["clock_color"] == "#ff0000"


# ---- hiding the top-to-bottom wipe ----


def test_switching_mode_hides_the_redraw_behind_a_dark_backlight(rig):
    start(rig)
    before = rig.blackouts
    rig.app.set("display", "mode", "clock")
    rig.settle()
    assert rig.blackouts == before + 1
    assert rig.lcd.brightness == 50


def test_ordinary_updates_never_blank_the_screen(rig):
    start(rig)
    before = rig.blackouts
    for load in (10, 45, 80, 20):
        rig.stats.sample = make_sample(cpu_load=load)
        rig.settle()
    assert rig.blackouts == before


def test_hiding_can_be_turned_off(rig):
    start(rig)
    rig.app.set("display", "hide_redraws", False)
    before = rig.blackouts
    rig.app.set("display", "mode", "clock")
    rig.settle()
    assert rig.blackouts == before


# ---- GIFs ----


def test_choosing_a_gif_switches_to_it_and_plays(rig, gif_folder):
    gif = make_gif(gif_folder / "box.gif")
    start(rig)
    rig.app.set("gif", "file", str(gif))
    rig.step()
    assert rig.app.cfg["display"]["mode"] == "gif"
    assert wait_for(lambda: rig.app._gif and rig.app._gif.current == gif)
    before = rig.lcd.blits
    for _ in range(40):
        rig.step()
    assert rig.lcd.blits > before + 10
    assert rig.app._gif.frame_path == gif


def test_a_small_moving_gif_costs_far_less_than_full_frames(rig, gif_folder):
    gif = make_gif(gif_folder / "box.gif")
    rig.app.set("gif", "file", str(gif))
    rig.settle()
    assert wait_for(lambda: rig.app._gif and rig.app._gif.current == gif)
    rig.steps(5)
    before, frames = rig.lcd.bytes_sent, rig.app.display.meter.updates
    for _ in range(60):
        rig.step()
    per_frame = (rig.lcd.bytes_sent - before) / max(rig.app.display.meter.updates - frames, 1)
    assert per_frame < 0.25 * 320 * 480 * 2


def test_empty_gif_folder_shows_a_message(rig, gif_folder):
    rig.app.set("display", "mode", "gif")
    rig.steps(10)
    assert rig.app.view_name == "gif"
    assert rig.lcd.blits > 0


def test_a_broken_gif_does_not_stop_the_app(rig, gif_folder):
    broken = gif_folder / "broken.gif"
    broken.write_bytes(b"not a gif")
    rig.app.set("gif", "file", str(broken))
    rig.steps(10)
    assert wait_for(lambda: rig.app._gif.current == broken)
    rig.steps(5)
    assert rig.lcd.is_on


def test_slideshow_moves_to_the_next_file(rig, gif_folder):
    folder = gif_folder
    first, second = make_gif(folder / "a.gif"), make_gif(folder / "b.gif")
    rig.app.cfg["gif"].update(slideshow=True, switch_seconds=2)
    rig.app.set("gif", "file", str(first))
    rig.settle()
    assert wait_for(lambda: rig.app._gif and rig.app._gif.current == first)
    for _ in range(80):
        rig.step()
        if rig.app._gif.current == second:
            break
        wait_for(lambda: not rig.app._gif._loading, 1)
    assert rig.app._gif.current == second


def test_next_gif_command(rig, gif_folder):
    folder = gif_folder
    first, second = make_gif(folder / "a.gif"), make_gif(folder / "b.gif")
    rig.app.set("gif", "file", str(first))
    rig.settle()
    assert wait_for(lambda: rig.app._gif and rig.app._gif.current == first)
    rig.app.command("next_gif")
    rig.step()
    assert wait_for(lambda: rig.app._gif.current == second)


def test_changing_fit_restarts_the_player(rig, gif_folder):
    folder = gif_folder
    gif = make_gif(folder / "a.gif")
    rig.app.set("gif", "file", str(gif))
    rig.settle()
    first_player = rig.app._gif
    rig.app.set("gif", "fit", "contain")
    rig.settle()
    assert rig.app._gif is not first_player
    assert rig.app._gif.fit == "contain"


@pytest.mark.parametrize("interval", [0.5, 2.0])
def test_stats_interval_sets_how_often_the_screen_refreshes(rig, interval):
    rig.app.cfg["stats"]["interval"] = interval
    draws = []
    rig.app.display.show = lambda picture, transition=False: draws.append(rig.time)
    for _ in range(200):
        rig.step()
    gaps = [b - a for a, b in zip(draws, draws[1:], strict=False)]
    assert gaps
    assert all(gap == pytest.approx(interval, abs=0.3) for gap in gaps)
