@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed, or "Add python.exe to PATH" was not ticked.
  echo Install Python 3.11 from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)
:again
python hr_camera.py run
echo The program stopped. Restarting in 10 seconds... (close this window to stop)
timeout /t 10 >nul
goto again
