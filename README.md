# Turing Screen

An app for the Turing Smart Screen 3.5" (USB35INCHIPSV2). Pick what the screen shows in the control panel:

- **Big stats**: CPU, GPU, RAM and network in large numbers you can read from your chair
- **Detailed stats**: everything (per-core load, graphs, VRAM, drives, disk and network speed)
- **GIF**: full screen, picked from your GIF library (or a slideshow)
- **Clock**: big full-screen clock

When Windows is **locked or turns the monitors off**, the screen shows a dim clock (or turns off; you choose).
When the PC **sleeps or shuts down**, the screen turns off, because nothing can update it while the PC is asleep.

## Start
1. `setup.bat` (once, and again after updates).
2. Double-click **`Turing Screen.vbs`**. It opens the control panel and adds a tray icon.
   Closing the window keeps the screen running; reopen it from the tray icon or by double-clicking again.
3. `install_startup.bat`: starts it in the background when you log in (`uninstall_startup.bat` undoes it).

`run.bat` does the same as step 2 but with a log window, which is useful when something goes wrong.

## GIFs
Use **Add GIFs…** in the control panel (or drop files into the `gifs` folder). Click a GIF to show it.

This screen takes about 125 KB per second (the benchmark shows that's the screen's own limit), and one
full-screen picture is 307 KB. It also paints top to bottom, with no way to swap in a finished picture.
Only the pixels that change are sent, so the label under each GIF (a playback simulation) tells you how it will look:

**GIFs that play well**
- A small thing moving on a still background: characters, pets, pixel art, loading spinners, logos.
- A flat or solid background. Gradients and photos are fine if they don't move.
- Small GIFs shown with **Original size**: a 160×160 GIF can never cost more than a quarter of the screen.
- Cropping a GIF down to the part that moves (for example at ezgif.com > crop) helps a lot.

**GIFs that play badly**
- Anything where the whole picture moves: video clips, camera pans, zooms, rain or snow over everything, fire.
- Converted videos with colour noise. **Noise clean-up** removes most of it (normal/strong); on a noisy
  test GIF it took playback from 0.4 to about 3.7 fps without leaving trails.

Where to find good ones: search for "pixel art gif", "sprite animation gif" or "transparent gif" (a transparent
background is shown on black, so only the subject moves).

## Repainting
The screen draws every change from top to bottom. To make that less visible:
- **Calm numbers** (Big stats): a number is only redrawn when it really changed (3% load, 1.5° temperature, 25% network speed).
- **Hide the wipe when switching**: the screen goes dark while a whole new picture loads, then lights up finished.

## Speed tuning
`benchmark.bat` (quit the app first) tries 7 link settings. On this screen they all measured ~125 KB/s, so the defaults are fine.

## CPU temperature
Windows doesn't give apps the CPU temperature directly. Install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor),
run it, and turn on **Options > Remote Web Server > Run** (port 8085). Without it, CPU temperature shows `--`.

## If the screen stays blank
The official TURZX / USBMonitor app (or AIDA64) holds the screen's port. Close it, including from the tray, and disable it at startup.

## Files
`main.py` app loop · `ui.py` control panel · `pages.py` big stats/clock · `render.py` detailed stats ·
`gifs.py` GIF player · `lcd.py` screen driver · `sensors.py` stats · `power_events.py` sleep/lock detection ·
`config.toml` settings · `state.json` settings saved by the control panel · `logs\turing.log` log.

The screen protocol is based on turing-smart-screen-python by Matthieu Houdebine (GPL-3.0, see LICENSE).
Fonts: Roboto (Apache 2.0) and JetBrains Mono (OFL), with licenses in `fonts\`.
