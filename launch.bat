@echo off
title Pluiz v2 Launcher
cd /d "%~dp0"

echo Installing Python packages...
pip install -q -r requirements.txt

echo Installing Playwright browsers (chromium)...
playwright install chromium --quiet 2>nul || python -m playwright install chromium

echo.
echo [1/2] Starting Pluiz server...
start "Pluiz Server" cmd /k "cd /d "%~dp0" && python main.py"

echo Waiting for server to start...
timeout /t 3 /nobreak >nul

echo [2/2] Starting Pluiz UI...
cd /d "%~dp0electron-ui"

if not exist node_modules (
    echo Installing Electron...
    npm install
)

start "Pluiz UI" cmd /k "npx electron ."

echo.
echo Pluiz is running!
echo Close the two terminal windows to stop.
