@echo off
rem Checks which temperature sources Windows exposes (nothing is installed).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_windows_temp.ps1"
pause
