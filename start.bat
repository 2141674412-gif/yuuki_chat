@echo off
chcp 65001 >nul 2>&1
title yuuki_chat QQ Bot

:: ============================================================
::  yuuki_chat QQ Bot 启动脚本
::  使用前请确保已运行 deploy.bat 完成部署
:: ============================================================

set "PROJECT_DIR=F:\chat\yuuki-bot"
set "NAPCAT_DIR=%PROJECT_DIR%\napcat"
set "VENV_DIR=%PROJECT_DIR%\venv"

echo.
echo [1/2] 正在启动 NapCat QQ...
echo.

:: 启动 NapCat
if exist "%NAPCAT_DIR%\NapCat.Shell.exe" (
    start "NapCat QQ" "%NAPCAT_DIR%\NapCat.Shell.exe"
    echo [信息] NapCat 已启动，等待 10 秒...
) else if exist "%NAPCAT_DIR%\napcat.sh" (
    echo [警告] 检测到 Linux 版 NapCat，Windows 下可能无法运行。
    echo [警告] 请下载 Windows 版本: https://github.com/NapNeko/NapCatQQ/releases/latest
    pause
    exit /b 1
) else (
    echo [错误] 未找到 NapCat，请先运行 deploy.bat 或手动安装。
    pause
    exit /b 1
)

:: 等待 NapCat 初始化
timeout /t 10 /nobreak >nul
echo.
echo [2/2] 正在启动 yuuki_chat Bot...
echo.

:: 激活虚拟环境并启动机器人
call "%VENV_DIR%\Scripts\activate.bat"
cd /d "%PROJECT_DIR%"
python bot.py

pause
