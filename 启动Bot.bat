@echo off
chcp 65001 >nul
echo ========================================
echo  Android Game Bot - 启动助手
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 安装依赖
echo [1] 检查并安装依赖...
python -m pip install opencv-python-headless numpy pyyaml -q
echo     依赖已就绪

echo.
echo [2] 请确认已在 config.yaml 中填写了设备 IP
echo     device: "你的IP:5555"
echo.
echo [3] 确认手机开启了"无线调试"
echo.
echo [4] 将要识别的按钮截图放入 templates/ 文件夹
echo.

set /p CONFIRM=准备好了吗？输入 y 启动 Bot: 
if /i "%CONFIRM%"=="y" (
    echo.
    echo 🤖 启动 Bot...
    python bot.py
) else (
    echo 已取消
)

pause
