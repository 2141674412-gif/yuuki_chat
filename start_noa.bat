@echo off
chcp 65001 >nul
title Yuuki Bot Launcher

echo ========================================
echo         Yuuki Bot Launcher
echo ========================================
echo.

set "BOT_DIR=%~dp0"
set "BOT_SCRIPT=bot.py"

cd /d "%BOT_DIR%"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] 虚拟环境不存在，请先运行 deploy.bat
    pause
    exit /b 1
)

echo [1/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo [2/3] Starting NoneBot2...
python %BOT_SCRIPT%

echo.
echo [3/3] Bot stopped.
pause
