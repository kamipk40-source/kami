@echo off
cd /d "%~dp0"
:again
python hr_camera.py run
echo The program stopped. Restarting in 10 seconds... (close this window to stop)
timeout /t 10 >nul
goto again
