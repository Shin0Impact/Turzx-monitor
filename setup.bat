@echo off
rem One-time setup (run again after updates): private Python environment in .venv + packages.
cd /d "%~dp0"
if not exist .venv (
    echo Creating Python environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
    echo Could not create the environment. Is Python installed? https://www.python.org/downloads/
    pause
    exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Package install failed - see the messages above.
    pause
    exit /b 1
)
.venv\Scripts\python -c "import tkinter" 2>nul || echo WARNING: tkinter is missing, the control panel won't open. Re-run the Python installer and tick "tcl/tk and IDLE".
echo.
echo Setup done. Next: double-click "Turing Screen.vbs" (or run.bat to see the log).
pause
