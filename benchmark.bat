@echo off
rem Tries 7 link settings (about 40 seconds). Watch the screen: note any test number where the
rem picture looks scrambled or shifted. Quit the app from the tray first.
cd /d "%~dp0"
.venv\Scripts\python main.py --benchmark
pause
