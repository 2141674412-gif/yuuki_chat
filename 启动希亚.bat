@echo off
chcp 936 >nul
title NoaBot Launcher

echo ========================================
echo         NoaBot Launcher
echo ========================================
echo.

set "NAPCAT_DIR=F:\chat\NapCat\NapCat.44498.Shell"
set "BOT_DIR=F:\chat\yuuki-bot"
set "BOT_SCRIPT=bot.py"

if not exist "%NAPCAT_DIR%\napcat.bat" (
    echo [ERROR] napcat.bat not found: %NAPCAT_DIR%\napcat.bat
    pause
    exit /b 1
)

if not exist "%BOT_DIR%\%BOT_SCRIPT%" (
    echo [ERROR] Bot not found: %BOT_DIR%\%BOT_SCRIPT%
    pause
    exit /b 1
)

echo [1/4] Starting NoneBot2 first...
set "NB_CRASH_COUNT=0"
start "NoneBot2" /MIN /D "%BOT_DIR%" cmd /c "set NB_CRASH_COUNT=0 & :nb_restart & echo [%%date%% %%time%%] Starting NoneBot2... (crash count: %%NB_CRASH_COUNT%%) >> nb_restart_log.txt & if exist venv\Scripts\activate.bat (call venv\Scripts\activate.bat && python %BOT_SCRIPT%) else (python %BOT_SCRIPT%) & set /a NB_CRASH_COUNT+=1 & echo [%%date%% %%time%%] NoneBot2 crashed, restarting in 5 seconds... >> nb_restart_log.txt & timeout /t 5 /nobreak >nul & goto nb_restart"
echo       NoneBot2 started (minimized)
echo       Waiting for port 8888 to be ready...
set "PORT_READY=0"
:wait_port
timeout /t 1 /nobreak >nul
for /f "delims=" %%i in ('netstat -ano ^| findstr ":8888.*LISTENING" 2^>nul') do (
    set "PORT_READY=1"
)
if "%PORT_READY%"=="1" (
    echo       Port 8888 is ready!
    goto port_ok
)
echo       Waiting...
goto wait_port
:port_ok

echo.
echo [2/4] Starting NapCat...
start "NapCat" /D "%NAPCAT_DIR%" cmd /c "napcat.bat -q"
echo       NapCat started (-q quick login)

echo       Waiting for NapCat init...
set "WAIT_COUNT=0"
:wait_napcat
timeout /t 3 /nobreak >nul
set /a WAIT_COUNT+=1
if %WAIT_COUNT% geq 15 goto napcat_ready
goto wait_napcat

:napcat_ready
echo.

echo [3/4] Reading WebUI Token...
set "CURRENT_TOKEN="
for /f "delims=" %%i in ('dir /b /s "%NAPCAT_DIR%\versions\*webui.json" 2^>nul') do (
    for /f "delims=" %%j in ('powershell -NoProfile -Command "(Get-Content '%%i' | ConvertFrom-Json).token" 2^>nul') do (
        set "CURRENT_TOKEN=%%j"
    )
    if defined CURRENT_TOKEN goto token_found
)
:token_found
if defined CURRENT_TOKEN (
    echo       Token: %CURRENT_TOKEN%
    echo       WebUI: http://localhost:6099
) else (
    echo       Token not found
)

echo.
echo [4/4] Done!
echo.
echo ========================================
echo   All started!
echo   NoneBot2 - minimized (port 8888)
echo   NapCat  - running
echo.
echo   WebUI: http://localhost:6099
echo   Token: %CURRENT_TOKEN%
echo.
echo   Close this window anytime.
echo   To stop bot, close NapCat/NoneBot2.
echo ========================================
echo.

timeout /t 8 /nobreak >nul
