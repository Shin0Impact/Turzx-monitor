# Turing Screen

Live system stats, GIFs and a clock for the **Turing Smart Screen 3.5"** (USB, serial ID `USB35INCHIPSV2`),
with a small control panel on your PC. It goes dark when the PC sleeps and shows a dim clock while Windows is locked.

## At a glance

| | |
|---|---|
| **What** | Desktop app that drives a Turing Smart Screen 3.5" over USB: live stats, GIFs and a clock, with a control panel on the PC |
| **Stack** | Python for Windows; own display protocol layer, tray icon and control panel |
| **Quality** | 150+ pytest tests: protocol bytes, drawing, app behaviour on a simulated screen, and the control panel |

## What it shows

| Show | What it is |
|---|---|
| **Big stats** | CPU, GPU, RAM (and network) in large numbers readable from across the desk. Each item can be turned off; the rest grow to fill the screen. |
| **Detailed stats** | Everything at once: per-core load, graphs, VRAM, drives, disk and network speeds. |
| **GIF** | Any animation from your library, full screen, or a slideshow. |
| **Clock** | Large full-screen clock in a colour you choose. |

## Install

1. Install [Python 3.11 or newer](https://www.python.org/downloads/) (tick "Add python.exe to PATH").
2. Double-click **`install.bat`**.

It builds a private Python environment in this folder, installs the packages, makes the app **start with Windows**,
adds a **Turing Screen** entry to the Start Menu, and starts it. To remove: **`uninstall.bat`**, then delete the folder.

If the screen stays blank, close the official TURZX / USBMonitor app (and stop it starting with Windows): only one
program can use the screen at a time.

## Using it

The control panel opens on install. Closing it keeps the screen running (tray icon, bottom right); open it again
from the tray icon or the Start Menu. Everything you change is remembered.

- **Show on screen**: pick Big stats, Detailed stats, GIF or Clock.
- **GIFs**: *Add GIFs…*, then click one. Each GIF shows how smoothly it will play (see below).
- **Clock colour**: a few presets or any colour.
- **Locked or monitors off**: show a dim clock, or turn the screen off. A sleeping or shutting-down PC always turns it off.
- **Start with Windows** can be switched off in the panel.

Advanced settings are in `config.toml`. `run.bat` starts the app with a log window if something goes wrong; the log is
`logs\turing.log`, and startup crashes are written to `logs\crash.log`.

## GIFs on a slow screen

The screen accepts about 125 KB/s and one full picture is 307 KB, and it draws top to bottom. So only the pixels that
change are sent:

- **Plays well:** a small thing moving on a still background (characters, pixel art, spinners, logos), small GIFs
  shown at *Original size*, anything cropped to the part that moves.
- **Plays badly:** the whole picture moving (video clips, camera pans). Expect about 1 frame per second.
- *Noise clean-up* removes colour noise from converted videos so they send less (a noisy test clip went from 0.4 to
  about 3.7 fps).
- 14 examples made for this screen are in `gifs/`. For more, search "pixel art gif" or "transparent gif".

To make the switch between pictures look clean, *Hide the wipe when switching* keeps the screen dark for the ~2 s a
new picture takes to load. *Calm numbers* redraws a number only when it really changed.

## CPU temperature

Not shown. Windows doesn't give normal programs the CPU temperature of a Ryzen; reading it needs a hardware driver
or a separate monitoring program, which this app deliberately avoids. `tools\check_windows_temp.bat` reports what your
PC exposes if you want to check. The CPU row shows clock speed instead; GPU temperature works (NVIDIA driver).

## Development

```
pip install -r requirements-dev.txt
pytest          # 150+ tests: protocol bytes, drawing, the app's behaviour on a simulated screen, the control panel
ruff check .
python -m turingscreen --simulate --no-ui --seconds 5    # no screen needed; writes previews/preview.png
python tools/make_example_gifs.py                          # regenerate the example GIFs
```

| Path | Purpose |
|---|---|
| `turingscreen/lcd.py`, `simulator.py` | Screen protocol and a fake screen |
| `turingscreen/display.py`, `diff.py` | Remembers what's on the glass, sends only what changed |
| `turingscreen/app.py` | Decides what to show; sleep, lock, reconnecting, settings |
| `turingscreen/views/` | Big stats, Detailed stats, Clock |
| `turingscreen/gifs.py`, `gifprep.py` | GIF playback, clean-up and speed estimate |
| `turingscreen/sensors.py`, `power.py` | System stats; Windows sleep and lock events |
| `turingscreen/ui/`, `tray.py` | Control panel and tray icon |
| `turingscreen/cli.py`, `autostart.py` | Command line, install, start with Windows |

## Credits and licence

The screen protocol comes from [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python)
by Matthieu Houdebine (GPL-3.0), so this project is also **GPL-3.0** (see `LICENSE`). Fonts: Roboto (Apache 2.0) and
JetBrains Mono (OFL), licences in `assets/fonts/`.
