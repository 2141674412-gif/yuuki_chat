@echo off
chcp 65001 >nul
echo ==========================================
echo    Yuuki Bot 一键部署脚本
echo ==========================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/6] 检查Python环境... OK

:: 创建虚拟环境（如果不存在）
if not exist "venv" (
    echo [2/6] 创建虚拟环境...
    python -m venv venv
) else (
    echo [2/6] 虚拟环境已存在
)

:: 激活虚拟环境
echo [3/6] 激活虚拟环境...
call venv\Scripts\activate.bat

:: 安装依赖
echo [4/6] 安装依赖...
pip install -q --upgrade pip
pip install -q nonebot2[fastapi] nonebot-adapter-onebot nonebot-plugin-apscheduler
pip install -q openai httpx pillow qreader

echo [5/6] 检查插件...
if not exist "plugins\yuuki_chat" (
    echo [错误] 未找到 yuuki_chat 插件
    echo 请将插件文件夹放入 plugins\yuuki_chat\
    pause
    exit /b 1
)

:: 创建.env文件（如果不存在）
if not exist ".env" (
    echo [6/6] 创建配置文件...
    echo DRIVER=~fastapi > .env
    echo HOST=127.0.0.1 >> .env
    echo PORT=8888 >> .env
    echo SUPERUSERS=["你的QQ号"] >> .env
    echo LOG_LEVEL=INFO >> .env
    echo.
    echo [提示] 请编辑 .env 文件，将 SUPERUSERS 改为你的QQ号
) else (
    echo [6/6] 配置文件已存在
)

echo.
echo ==========================================
echo    部署完成！
echo ==========================================
echo.
echo 启动命令:
echo   nb run        (推荐)
echo   或双击 start.bat
echo.
echo 配置文件: .env
echo 数据目录: yuuki_data\
echo 排行榜:   http://127.0.0.1:8080
echo.
choice /C YN /M "是否现在启动"
if errorlevel 2 exit /b 0
if errorlevel 1 nb run
