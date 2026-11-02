@echo off
rem Sets up CPU temperature for the Turing screen (installs LibreHardwareMonitor if needed).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_cpu_temp.ps1"
pause
