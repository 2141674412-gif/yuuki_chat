@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  yuuki_chat QQ Bot 一键部署脚本
::  适用于 Windows 10/11
:: ============================================================

:: 颜色定义
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "CYAN=[96m"
set "RESET=[0m"
set "BOLD=[1m"

echo.
echo %BOLD%%CYAN%╔══════════════════════════════════════════════╗%RESET%
echo %BOLD%%CYAN%║     yuuki_chat QQ Bot 一键部署脚本            ║%RESET%
echo %BOLD%%CYAN%╚══════════════════════════════════════════════╝%RESET%
echo.

:: ============================================================
::  第1步：检查 Python 3.10+ 是否已安装
:: ============================================================
echo %BOLD%%CYAN%[步骤 1/10]%RESET% 检查 Python 环境...
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo %YELLOW%[警告] 未检测到 Python，正在下载 Python 3.12...%RESET%

    :: 使用 PowerShell 下载 Python 安装程序
    powershell -Command ^
        "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile '%TEMP%\python-installer.exe'" 2>nul

    if not exist "%TEMP%\python-installer.exe" (
        echo %RED%[错误] Python 下载失败，请手动安装 Python 3.10+ 后重试。%RESET%
        echo %YELLOW%下载地址: https://www.python.org/downloads/%RESET%
        pause
        exit /b 1
    )

    echo %GREEN%[信息] 正在安装 Python（静默安装，请稍候）...%RESET%
    "%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0

    if %errorlevel% neq 0 (
        echo %RED%[错误] Python 安装失败，请尝试手动安装。%RESET%
        pause
        exit /b 1
    )

    del "%TEMP%\python-installer.exe" >nul 2>&1
    echo %GREEN%[成功] Python 安装完成！%RESET%
) else (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
    echo %GREEN%[成功] 已检测到 Python !PYVER!%RESET%
)

:: 验证 Python 版本 >= 3.10
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)

if not defined PYMAJOR (
    :: 重新获取版本号
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
        set "PYMAJOR=%%a"
        set "PYMINOR=%%b"
    )
)

if %PYMAJOR% lss 3 (
    echo %RED%[错误] Python 版本过低（当前: %PYMAJOR%.%PYMINOR%），需要 3.10 或更高版本。%RESET%
    echo %YELLOW%请从 https://www.python.org/downloads/ 下载安装 Python 3.10+%RESET%
    pause
    exit /b 1
)
if %PYMAJOR% equ 3 if %PYMINOR% lss 10 (
    echo %RED%[错误] Python 版本过低（当前: %PYMAJOR%.%PYMINOR%），需要 3.10 或更高版本。%RESET%
    echo %YELLOW%请从 https://www.python.org/downloads/ 下载安装 Python 3.10+%RESET%
    pause
    exit /b 1
)

echo %GREEN%[成功] Python 版本满足要求 (%PYMAJOR%.%PYMINOR%+)%RESET%
echo.

:: ============================================================
::  第2步：创建项目目录
:: ============================================================
echo %BOLD%%CYAN%[步骤 2/10]%RESET% 创建项目目录...
echo.

set "PROJECT_DIR=F:\chat\yuuki-bot"
set "PLUGINS_DIR=%PROJECT_DIR%\plugins"
set "REPO_DIR=%PLUGINS_DIR%\yuuki_chat"

if not exist "%PROJECT_DIR%" (
    mkdir "%PROJECT_DIR%"
    if %errorlevel% neq 0 (
        echo %RED%[错误] 无法创建目录 %PROJECT_DIR%，请检查磁盘或权限。%RESET%
        pause
        exit /b 1
    )
    echo %GREEN%[成功] 已创建项目目录: %PROJECT_DIR%%RESET%
) else (
    echo %YELLOW%[信息] 项目目录已存在: %PROJECT_DIR%%RESET%
)

if not exist "%PLUGINS_DIR%" (
    mkdir "%PLUGINS_DIR%"
    echo %GREEN%[成功] 已创建插件目录: %PLUGINS_DIR%%RESET%
)
echo.

:: ============================================================
::  第3步：克隆 yuuki_chat 仓库
:: ============================================================
echo %BOLD%%CYAN%[步骤 3/10]%RESET% 克隆 yuuki_chat 仓库...
echo.

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo %RED%[错误] 未检测到 Git，请先安装 Git。%RESET%
    echo %YELLOW%下载地址: https://git-scm.com/download/win%RESET%
    pause
    exit /b 1
)

if exist "%REPO_DIR%\.git" (
    echo %YELLOW%[信息] 仓库已存在，正在更新...%RESET%
    pushd "%REPO_DIR%"
    git pull --ff-only 2>nul
    if %errorlevel% neq 0 (
        echo %YELLOW%[警告] 更新失败，将使用现有代码。%RESET%
    ) else (
        echo %GREEN%[成功] 仓库已更新。%RESET%
    )
    popd
) else (
    if exist "%REPO_DIR%" (
        echo %YELLOW%[信息] 插件目录已存在但不是 Git 仓库，将删除后重新克隆...%RESET%
        rmdir /s /q "%REPO_DIR%" 2>nul
    )
    git clone https://github.com/2141674412-gif/yuuki_chat.git "%REPO_DIR%"
    if %errorlevel% neq 0 (
        echo %RED%[错误] 仓库克隆失败，请检查网络连接。%RESET%
        pause
        exit /b 1
    )
    echo %GREEN%[成功] 仓库克隆完成: %REPO_DIR%%RESET%
)
echo.

:: ============================================================
::  第4步：创建 requirements.txt（如果不存在）
:: ============================================================
echo %BOLD%%CYAN%[步骤 4/10]%RESET% 检查并创建 requirements.txt...
echo.

set "REQ_FILE=%REPO_DIR%\requirements.txt"

if not exist "%REQ_FILE%" (
    (
        echo nonebot2
        echo nonebot-adapter-onebot
        echo httpx
        echo openai
        echo aiohttp
        echo aiofiles
        echo apscheduler
        echo loguru
        echo pyparsing
        echo wordcloud
        echo matplotlib
        echo jieba
        echo pillow
        echo qrcode
        echo requests
    ) > "%REQ_FILE%"
    echo %GREEN%[成功] 已创建 requirements.txt%RESET%
) else (
    echo %YELLOW%[信息] requirements.txt 已存在，跳过创建。%RESET%
    echo %CYAN%[信息] 内容如下:%RESET%
    type "%REQ_FILE%"
)
echo.

:: ============================================================
::  第5步：创建虚拟环境
:: ============================================================
echo %BOLD%%CYAN%[步骤 5/10]%RESET% 创建 Python 虚拟环境...
echo.

set "VENV_DIR=%PROJECT_DIR%\venv"

if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo %YELLOW%[信息] 虚拟环境已存在，跳过创建。%RESET%
) else (
    if exist "%VENV_DIR%" (
        echo %YELLOW%[信息] 虚拟环境目录存在但损坏，正在重建...%RESET%
        rmdir /s /q "%VENV_DIR%" 2>nul
    )
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo %RED%[错误] 虚拟环境创建失败。%RESET%
        pause
        exit /b 1
    )
    echo %GREEN%[成功] 虚拟环境已创建: %VENV_DIR%%RESET%
)
echo.

:: ============================================================
::  第6步：激活虚拟环境并安装依赖
:: ============================================================
echo %BOLD%%CYAN%[步骤 6/10]%RESET% 安装 Python 依赖...
echo.

call "%VENV_DIR%\Scripts\activate.bat"

:: 升级 pip
echo %CYAN%[信息] 正在升级 pip...%RESET%
python -m pip install --upgrade pip -q 2>nul
if %errorlevel% neq 0 (
    echo %YELLOW%[警告] pip 升级失败，尝试继续安装依赖...%RESET%
)

:: 安装依赖
echo %CYAN%[信息] 正在安装依赖包（可能需要几分钟，请耐心等待）...%RESET%
pip install -r "%REQ_FILE%" -q 2>nul
if %errorlevel% neq 0 (
    echo %YELLOW%[警告] 静默安装可能有问题，尝试重新安装...%RESET%
    pip install -r "%REQ_FILE%"
    if %errorlevel% neq 0 (
        echo %RED%[错误] 依赖安装失败，请检查网络或 requirements.txt。%RESET%
        pause
        exit /b 1
    )
)
echo %GREEN%[成功] 所有依赖安装完成！%RESET%
echo.

:: ============================================================
::  第7步：创建 .env 配置文件
:: ============================================================
echo %BOLD%%CYAN%[步骤 7/10]%RESET% 创建 .env 配置文件...
echo.

set "ENV_FILE=%PROJECT_DIR%\.env"

if exist "%ENV_FILE%" (
    echo %YELLOW%[信息] .env 文件已存在，跳过创建。%RESET%
    echo %CYAN%[信息] 当前内容:%RESET%
    type "%ENV_FILE%"
) else (
    (
        echo HOST=127.0.0.1
        echo PORT=8080
        echo SUPERUSERS=["2141674412"]
        echo NICKNAME=["希亚","小希亚","Noa","noa"]
        echo COMMAND_START=["/"]
    ) > "%ENV_FILE%"
    echo %GREEN%[成功] 已创建 .env 配置文件%RESET%
)
echo.

:: ============================================================
::  第8步：创建 bot.py 启动入口
:: ============================================================
echo %BOLD%%CYAN%[步骤 8/10]%RESET% 创建 bot.py 启动入口...
echo.

set "BOT_FILE=%PROJECT_DIR%\bot.py"

if exist "%BOT_FILE%" (
    echo %YELLOW%[信息] bot.py 已存在，跳过创建。%RESET%
) else (
    (
        echo import nonebot
        echo from nonebot.adapters.onebot.v11 import Adapter
        echo.
        echo nonebot.init^(^)
        echo driver = nonebot.get_driver^(^)
        echo adapter = Adapter^(driver=driver^)
        echo nonebot.load_plugins^("plugins/yuuki_chat"^)
        echo nonebot.run^(^)
    ) > "%BOT_FILE%"
    echo %GREEN%[成功] 已创建 bot.py%RESET%
)
echo.

:: ============================================================
::  第9步：下载 NapCat QQ
:: ============================================================
echo %BOLD%%CYAN%[步骤 9/10]%RESET% 下载 NapCat QQ...
echo.

set "NAPCAT_DIR=%PROJECT_DIR%\napcat"

if exist "%NAPCAT_DIR%\NapCat.Shell.exe" (
    echo %YELLOW%[信息] NapCat 已存在，跳过下载。%RESET%
    goto :napcat_done
)

if not exist "%NAPCAT_DIR%" mkdir "%NAPCAT_DIR%"

echo %CYAN%[信息] 正在获取 NapCat 最新版本信息...%RESET%

:: 使用 PowerShell 获取最新 release 的 Windows x64 下载链接
powershell -Command ^
    "$apiUrl = 'https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest'; " ^
    "$response = Invoke-RestMethod -Uri $apiUrl -Headers @{'User-Agent'='Mozilla/5.0'}; " ^
    "$asset = $response.assets | Where-Object { $_.name -like '*windows*x64*.zip' } | Select-Object -First 1; " ^
    "if ($asset) { Write-Output $asset.browser_download_url } else { Write-Output 'NOT_FOUND' }" > "%TEMP%\napcat_url.txt" 2>nul

set /p NAPCAT_URL=<"%TEMP%\napcat_url.txt"
del "%TEMP%\napcat_url.txt" >nul 2>&1

if "%NAPCAT_URL%"=="NOT_FOUND" (
    echo %YELLOW%[警告] 未找到 NapCat Windows x64 版本，尝试通用匹配...%RESET%
    powershell -Command ^
        "$apiUrl = 'https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest'; " ^
        "$response = Invoke-RestMethod -Uri $apiUrl -Headers @{'User-Agent'='Mozilla/5.0'}; " ^
        "$asset = $response.assets | Where-Object { $_.name -like '*.zip' -and $_.name -notlike '*linux*' -and $_.name -notlike '*macos*' -and $_.name -notlike '*darwin*' } | Select-Object -First 1; " ^
        "if ($asset) { Write-Output $asset.browser_download_url } else { Write-Output 'NOT_FOUND' }" > "%TEMP%\napcat_url.txt" 2>nul
    set /p NAPCAT_URL=<"%TEMP%\napcat_url.txt"
    del "%TEMP%\napcat_url.txt" >nul 2>&1
)

if "%NAPCAT_URL%"=="NOT_FOUND" (
    echo %RED%[错误] 无法获取 NapCat 下载链接。%RESET%
    echo %YELLOW%请手动下载: https://github.com/NapNeko/NapCatQQ/releases/latest%RESET%
    echo %YELLOW%下载后解压到: %NAPCAT_DIR%%RESET%
    goto :napcat_done
)

echo %CYAN%[信息] 下载地址: %NAPCAT_URL%%RESET%
echo %CYAN%[信息] 正在下载 NapCat（文件较大，请耐心等待）...%RESET%

set "NAPCAT_ZIP=%TEMP%\napcat.zip"

powershell -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
    "Invoke-WebRequest -Uri '%NAPCAT_URL%' -OutFile '%NAPCAT_ZIP%' -UseBasicParsing" 2>nul

if not exist "%NAPCAT_ZIP%" (
    echo %RED%[错误] NapCat 下载失败，请检查网络连接。%RESET%
    echo %YELLOW%请手动下载: https://github.com/NapNeko/NapCatQQ/releases/latest%RESET%
    echo %YELLOW%下载后解压到: %NAPCAT_DIR%%RESET%
    goto :napcat_done
)

echo %CYAN%[信息] 正在解压 NapCat...%RESET%
powershell -Command ^
    "if (Get-Command Expand-Archive -ErrorAction SilentlyContinue) { " ^
    "  Expand-Archive -Path '%NAPCAT_ZIP%' -DestinationPath '%TEMP%\napcat_extract' -Force; " ^
    "  $extracted = Get-ChildItem -Path '%TEMP%\napcat_extract' -Directory | Select-Object -First 1; " ^
    "  if ($extracted) { " ^
    "    Copy-Item -Path ($extracted.FullName + '\*') -Destination '%NAPCAT_DIR%' -Recurse -Force; " ^
    "  } else { " ^
    "    Copy-Item -Path '%TEMP%\napcat_extract\*' -Destination '%NAPCAT_DIR%' -Recurse -Force; " ^
    "  } " ^
    "  Remove-Item -Path '%TEMP%\napcat_extract' -Recurse -Force; " ^
    "} else { " ^
    "  Write-Output 'EXPAND_FAILED'; " ^
    "}" 2>nul

del "%NAPCAT_ZIP%" >nul 2>&1

if exist "%NAPCAT_DIR%\NapCat.Shell.exe" (
    echo %GREEN%[成功] NapCat 下载并解压完成！%RESET%
) else (
    echo %YELLOW%[警告] NapCat 解压可能不完整，请检查目录: %NAPCAT_DIR%%RESET%
    echo %YELLOW%或手动下载: https://github.com/NapNeko/NapCatQQ/releases/latest%RESET%
)

:napcat_done
echo.

:: ============================================================
::  第10步：创建 start.bat 启动脚本
:: ============================================================
echo %BOLD%%CYAN%[步骤 10/10]%RESET% 创建启动脚本 start.bat...
echo.

set "START_FILE=%PROJECT_DIR%\start.bat"

(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title yuuki_chat QQ Bot
    echo.
    echo :: ============================================================
    echo ::  yuuki_chat QQ Bot 启动脚本
    echo ::  使用前请确保已运行 deploy.bat 完成部署
    echo :: ============================================================
    echo.
    echo set "PROJECT_DIR=F:\chat\yuuki-bot"
    echo set "NAPCAT_DIR=%%PROJECT_DIR%%\napcat"
    echo set "VENV_DIR=%%PROJECT_DIR%%\venv"
    echo.
    echo echo.
    echo echo [1/2] 正在启动 NapCat QQ...
    echo.
    echo :: 启动 NapCat
    echo if exist "%%NAPCAT_DIR%%\NapCat.Shell.exe" ^(
    echo     start "NapCat QQ" "%%NAPCAT_DIR%%\NapCat.Shell.exe"
    echo     echo [信息] NapCat 已启动，等待 10 秒...
    echo ^) else if exist "%%NAPCAT_DIR%%\napcat.sh" ^(
    echo     echo [警告] 检测到 Linux 版 NapCat，Windows 下可能无法运行。
    echo     echo [警告] 请下载 Windows 版本: https://github.com/NapNeko/NapCatQQ/releases/latest
    echo     pause
    echo     exit /b 1
    echo ^) else ^(
    echo     echo [错误] 未找到 NapCat，请先运行 deploy.bat 或手动安装。
    echo     pause
    echo     exit /b 1
    echo ^)
    echo.
    echo :: 等待 NapCat 初始化
    echo timeout /t 10 /nobreak ^>nul
    echo echo.
    echo echo [2/2] 正在启动 yuuki_chat Bot...
    echo echo.
    echo.
    echo :: 激活虚拟环境并启动机器人
    echo call "%%VENV_DIR%%\Scripts\activate.bat"
    echo cd /d "%%PROJECT_DIR%%"
    echo python bot.py
    echo.
    echo pause
) > "%START_FILE%"

if %errorlevel% equ 0 (
    echo %GREEN%[成功] 启动脚本已创建: %START_FILE%%RESET%
) else (
    echo %RED%[错误] 启动脚本创建失败。%RESET%
)
echo.

:: ============================================================
::  部署完成 - 打印使用说明
:: ============================================================
echo.
echo %BOLD%%GREEN%═══════════════════════════════════════════════════════════════%RESET%
echo %BOLD%%GREEN%                  部署完成！%RESET%
echo %BOLD%%GREEN%═══════════════════════════════════════════════════════════════%RESET%
echo.
echo %BOLD%项目信息:%RESET%
echo   项目目录:    %PROJECT_DIR%
echo   仓库位置:    %REPO_DIR%
echo   虚拟环境:    %VENV_DIR%
echo   配置文件:    %ENV_FILE%
echo   启动入口:    %BOT_FILE%
echo   NapCat 目录: %NAPCAT_DIR%
echo   启动脚本:    %START_FILE%
echo.
echo %BOLD%使用步骤:%RESET%
echo.
echo   %CYAN%1.%RESET% 首次使用前，请打开 NapCat 扫码登录 QQ
echo      - 运行: %NAPCAT_DIR%\NapCat.Shell.exe
echo      - 使用手机 QQ 扫描二维码登录
echo.
echo   %CYAN%2.%RESET% 修改配置文件（可选）
echo      - 编辑: %ENV_FILE%
echo      - 可修改端口号、超级用户、昵称等设置
echo.
echo   %CYAN%3.%RESET% 启动机器人
echo      - 双击运行: %START_FILE%
echo      - 或手动执行:
echo        cd /d %PROJECT_DIR%
echo        call %VENV_DIR%\Scripts\activate.bat
echo        python bot.py
echo.
echo   %CYAN%4.%RESET% 配置 NapCat 连接
echo      - 在 NapCat WebUI 中配置 WebSocket 连接
echo      - 地址: ws://127.0.0.1:8080
echo      - 确保与 .env 中的 HOST 和 PORT 一致
echo.
echo %BOLD%常用命令:%RESET%
echo   更新机器人:  cd /d %REPO_DIR% ^&^& git pull
echo   重新安装依赖: pip install -r %REQ_FILE%
echo   查看日志:    运行 bot.py 后在控制台查看
echo.
echo %YELLOW%提示: 如遇到问题，请检查:%RESET%
echo   - Python 版本是否为 3.10+
echo   - 虚拟环境是否正确激活
echo   - NapCat 是否已登录并配置好连接
echo   - 防火墙是否阻止了端口 8080
echo.
echo %BOLD%%GREEN%═══════════════════════════════════════════════════════════════%RESET%
echo.

pause
