@echo off
rem Runs the dashboard with a visible log window. Close the window or press Ctrl+C to stop.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python main.py %*
pause
