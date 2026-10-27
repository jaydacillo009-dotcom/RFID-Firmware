@echo off
cd /d "%~dp0"
py -3 -m venv .venv-desktop
if errorlevel 1 goto :failed
.venv-desktop\Scripts\python.exe -m pip install -r requirements-bridge.txt
if errorlevel 1 goto :failed
start "" .venv-desktop\Scripts\pythonw.exe rfid_desktop.py
exit /b 0
:failed
echo Setup failed. Install Python 3.9 or later from python.org with the Python launcher enabled, then try again.
pause
exit /b 1
