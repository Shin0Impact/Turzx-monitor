@echo off
cd /d "%~dp0"
rem Removes start-with-Windows and the Start Menu entry. Quit the app from its tray icon first.
.venv\Scripts\python -m turingscreen uninstall
pause
