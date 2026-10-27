@echo off
cd /d "%~dp0"
py -3 -m venv .venv-desktop
if errorlevel 1 goto :failed
.venv-desktop\Scripts\python.exe -m pip install -r requirements-bridge.txt -r requirements-desktop-build.txt
if errorlevel 1 goto :failed
.venv-desktop\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name RFID-Station --hidden-import serial.tools.list_ports_windows rfid_desktop.py
if errorlevel 1 goto :failed
echo Built dist\RFID-Station.exe. Copy this file to your Windows PC to run without Python.
pause
exit /b 0
:failed
echo Build failed. Review the error above. Build on Windows with Python 3.9 or later installed.
pause
exit /b 1
