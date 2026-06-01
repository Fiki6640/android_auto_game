@echo off
chcp 65001 >nul
title Android Auto Game Bot
echo ========================================
echo   Android Auto Game Bot
echo ========================================
echo.

set "PYTHON=C:\Users\fikiy\.workbuddy\binaries\python\versions\3.13.12\python.exe"

if not exist "%PYTHON%" (
    echo [Error] Python not found: %PYTHON%
    pause
    exit /b 1
)

echo [1] Installing dependencies...
"%PYTHON%" -m pip install opencv-python-headless numpy pyyaml -q
echo     Dependencies ready
echo.
echo [2] Starting Bot...
echo.

"%PYTHON%" bot.py

pause
