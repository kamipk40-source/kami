@echo off
cd /d "%~dp0"
echo Installing the camera program (needs internet, takes a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. Now copy config.example.ini to config.ini and edit it.
pause
