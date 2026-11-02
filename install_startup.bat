@echo off
rem Starts the dashboard automatically when you log in to Windows.
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Turing screen dashboard.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0run_hidden.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo Added to Startup. It will start next time you log in (or double-click run_hidden.vbs now).
pause
