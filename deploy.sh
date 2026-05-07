#!/bin/bash
# ==========================================
#    Yuuki Bot 一键部署脚本 (Linux/macOS)
# ==========================================

set -e

echo "=========================================="
echo "   Yuuki Bot 一键部署脚本"
echo "=========================================="
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python 3，请先安装Python 3.9+"
    echo "下载地址: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_CMD="python3"
echo "[1/6] 检查Python环境... OK ($($PYTHON_CMD --version))"

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "[2/6] 创建虚拟环境..."
    $PYTHON_CMD -m venv venv
else
    echo "[2/6] 虚拟环境已存在"
fi

# 激活虚拟环境
echo "[3/6] 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "[4/6] 安装依赖..."
pip install --quiet --upgrade pip
pip install --quiet nonebot2[fastapi] nonebot-adapter-onebot nonebot-plugin-apscheduler
pip install --quiet openai httpx pillow qreader

echo "[5/6] 检查插件..."
if [ ! -d "plugins/yuuki_chat" ] && [ ! -f "yuuki_chat.zip" ]; then
    echo "[警告] 未找到插件，请确保插件文件存在"
fi

# 创建.env文件（如果不存在）
if [ ! -f ".env" ]; then
    echo "[6/6] 创建配置文件..."
    cat > .env << 'EOF'
DRIVER=~fastapi
HOST=127.0.0.1
PORT=8888
SUPERUSERS=["你的QQ号"]
LOG_LEVEL=INFO
EOF
    echo ""
    echo "[提示] 请编辑 .env 文件，将 SUPERUSERS 改为你的QQ号"
else
    echo "[6/6] 配置文件已存在"
fi

echo ""
echo "=========================================="
echo "   部署完成！"
echo "=========================================="
echo ""
echo "启动命令:"
echo "  source venv/bin/activate && nb run"
echo ""
echo "配置文件: .env"
echo "数据目录: yuuki_data/"
echo ""
