@echo off
title Pluiz v2 Setup
cd /d "%~dp0"

echo ========================================
echo  Pluiz v2 Setup
echo ========================================

echo [1/3] Creating conda environment (pluiz, Python 3.11)...
call conda create -n pluiz python=3.11 -y
if errorlevel 1 (
    echo conda not found or failed. Skipping.
)

echo [2/3] Activating environment...
call conda activate pluiz 2>nul

echo [3/3] Installing packages...
pip install -r requirements.txt

if not exist .env (
    copy .env.example .env
    echo Created .env - please add your GEMINI_API_KEY
)

echo.
echo Setup complete!
echo Run: start.bat
pause
