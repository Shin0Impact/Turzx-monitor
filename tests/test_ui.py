"""The control panel window. Needs a display; skipped where tkinter can't open one."""

from __future__ import annotations

import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

from turingscreen.ui.panel import CLOCK_COLORS, ControlPanel  # noqa: E402

from .conftest import Rig  # noqa: E402


@pytest.fixture
def panel(tmp_path):
    rig = Rig(tmp_path)
    rig.settle()
    try:
        window = ControlPanel(rig.app, show=True)
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    window.rig = rig
    yield window
    try:
        window.root.destroy()
    except tk.TclError:  # the test already closed it
        pass


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


def find(panel, cls, text):
    return next(w for w in children(panel.root) if isinstance(w, cls) and str(w.cget("text")) == text)


def click(panel, widget):
    pump(panel)  # the window has to be on screen before it receives events
    widget.event_generate("<Button-1>", x=2, y=2)
    pump(panel)


def pump(panel, times=5):
    for _ in range(times):
        panel.root.update()
        time.sleep(0.01)


def test_mode_buttons_change_the_mode(panel):
    find(panel, tk.ttk.Button, "Clock").invoke()
    panel.rig.step()
    assert panel.rig.app.cfg["display"]["mode"] == "clock"


def test_the_current_mode_is_highlighted(panel):
    panel.rig.app.cfg["display"]["mode"] = "detail"
    panel.refresh()
    assert str(find(panel, tk.ttk.Button, "Detailed stats").cget("style")) == "Accent.TButton"
    assert str(find(panel, tk.ttk.Button, "Clock").cget("style")) == "TButton"


def test_big_stats_checkboxes_match_the_config_and_change_it(panel):
    network = find(panel, tk.ttk.Checkbutton, "Network")
    assert not network.instate(["selected"])
    network.invoke()
    panel.rig.step()
    assert panel.rig.app.cfg["bigstats"]["net"] is True


def test_refresh_mirrors_changes_made_elsewhere(panel):
    panel.rig.app.cfg["bigstats"]["gpu"] = False
    panel.rig.app.cfg["display"]["calm"] = False
    panel.refresh()
    assert not find(panel, tk.ttk.Checkbutton, "GPU").instate(["selected"])
    assert not find(panel, tk.ttk.Checkbutton, "Calm numbers").instate(["selected"])


def test_clock_colour_swatches_and_custom_picker(panel, monkeypatch):
    swatches = [w for w in children(panel.root) if isinstance(w, tk.Label) and w.cget("bg") in CLOCK_COLORS]
    assert len(swatches) == len(CLOCK_COLORS)
    green = next(w for w in swatches if w.cget("bg") == "#76e35f")
    click(panel, green)
    panel.rig.step()
    assert panel.rig.app.cfg["display"]["clock_color"] == "#76e35f"
    monkeypatch.setattr("turingscreen.ui.panel.colorchooser.askcolor", lambda **kw: ((255, 0, 128), "#ff0080"))
    find(panel, tk.ttk.Button, "Custom…").invoke()
    panel.rig.step()
    assert panel.rig.app.cfg["display"]["clock_color"] == "#ff0080"


def test_cancelling_the_colour_picker_changes_nothing(panel, monkeypatch):
    before = panel.rig.app.cfg["display"]["clock_color"]
    monkeypatch.setattr("turingscreen.ui.panel.colorchooser.askcolor", lambda **kw: (None, None))
    find(panel, tk.ttk.Button, "Custom…").invoke()
    panel.rig.step()
    assert panel.rig.app.cfg["display"]["clock_color"] == before


def test_rotation_choice(panel):
    box = next(w for w in children(panel.root) if isinstance(w, tk.ttk.Combobox) and "Landscape" in w.cget("values"))
    box.set("Landscape")
    box.event_generate("<<ComboboxSelected>>")
    pump(panel)
    panel.rig.step()
    assert panel.rig.app.cfg["screen"]["orientation"] == "landscape"


def test_the_preview_shows_what_is_on_the_screen(panel):
    panel._update_preview()
    assert panel._photo.width() == int(320 * 0.75)
    assert "connected" in panel._status.cget("text")


def test_gif_library_lists_files_and_rates_them(panel, gif_folder):
    from tests.test_app import make_gif

    make_gif(gif_folder / "box.gif")
    panel.rig.app.gif_folder = gif_folder
    panel.library.scan()
    assert list(panel.library._tiles) == [gif_folder / "box.gif"]
    for _ in range(100):
        panel.library.collect_results()
        if panel.library._tiles[gif_folder / "box.gif"].caption.cget("text") != "checking…":
            break
        time.sleep(0.05)
    assert "smooth" in panel.library._tiles[gif_folder / "box.gif"].caption.cget("text")


def test_clicking_a_gif_selects_it(panel, gif_folder):
    from tests.test_app import make_gif

    gif = make_gif(gif_folder / "box.gif")
    panel.rig.app.gif_folder = gif_folder
    panel.library.scan()
    click(panel, panel.library._tiles[gif].picture)
    panel.rig.step()
    assert panel.rig.app.cfg["gif"]["file"] == str(gif)
    assert panel.rig.app.cfg["display"]["mode"] == "gif"


def test_a_hidden_window_comes_back_when_asked_and_the_loop_ends_when_the_app_stops(panel):
    panel.root.withdraw()
    panel.request_open()
    worker = threading.Thread(target=threading.Event().wait, args=(5,), daemon=True)
    worker.start()
    threading.Timer(0.6, panel.rig.app.stop.set).start()
    shown = []
    panel.root.after(300, lambda: shown.append(panel.root.state()))
    panel.mainloop(worker)
    assert shown == ["normal"]
