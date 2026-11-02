@echo off
setlocal
cd /d "%~dp0"
rem Installs Turing Screen: a private Python environment, the packages, start-with-Windows and a Start Menu entry.

set "PY="
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PY (
        py -%%V -c "pass" >nul 2>nul && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.11 or newer is needed. Opening the download page...
    start https://www.python.org/downloads/
    echo Install it ^(tick "Add python.exe to PATH"^), then run install.bat again.
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo Creating the Python environment...
    %PY% -m venv .venv
    if errorlevel 1 goto failed
)
echo Installing packages...
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

.venv\Scripts\python -m turingscreen install
if errorlevel 1 goto failed
echo.
echo Done. The control panel opens in a moment. Close the other TURZX / USBMonitor app if the screen stays blank.
timeout /t 6 >nul
exit /b 0

:failed
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
