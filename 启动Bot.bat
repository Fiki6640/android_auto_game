@echo off
chcp 65001 >nul
title Android Auto Game Bot
echo ========================================
echo   Android Auto Game Bot
echo ========================================
echo.
echo   [1] 命令行模式
echo   [2] 图形界面模式
echo.
set /p MODE="请选择模式 (1/2): "

if "%MODE%"=="2" (
    echo.
    echo 启动图形界面...
    uv run gui.py
) else (
    echo.
    echo 启动命令行模式...
    uv run bot.py
)

pause
