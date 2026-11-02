@echo off
cd /d "%~dp0"
python -m pip install --quiet pyserial
python detect_screen.py
pause
