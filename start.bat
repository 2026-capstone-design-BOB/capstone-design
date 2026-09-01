@echo off
title Pluiz v2
cd /d "%~dp0"

echo Installing packages...
pip install -q -r requirements.txt

echo.
echo Server: http://127.0.0.1:8765
echo Press Ctrl+C to stop.
echo.

python main.py
pause
