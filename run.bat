@echo off
cd /d "%~dp0"
rem Runs the app with a log window, which helps when something goes wrong.
if not exist .venv\Scripts\python.exe (
    echo Run install.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python -m turingscreen %*
pause
