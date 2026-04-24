# ========== 自检诊断命令 ==========

import os
import sys
import json
import time
import subprocess
from datetime import datetime

from nonebot import logger, get_driver
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, check_superuser, _DATA_DIR

# ─────────────────────────────────────────────────────────────

async def _cmd_diagnose(event: MessageEvent):
    """自检诊断：检查bot运行环境和常见问题"""
    if not check_superuser(str(event.user_id)):
        await diagnose_cmd.finish("...你不是管理员。")
        return

    report = []
    report.append("🔍 Bot 自检诊断报告")
    report.append("=" * 30)
    report.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    issues = []
    warnings = []

    # 1. Python 环境
    report.append("【Python 环境】")
    report.append(f"  版本: {sys.version.split()[0]}")
    report.append(f"  路径: {sys.executable}")
    report.append("")

    # 2. 依赖检查
    report.append("【依赖检查】")
    deps = {
        "nonebot": "nonebot",
        "nonebot-adapter-onebot": "nonebot.adapters.onebot.v11",
        "httpx": "httpx",
        "Pillow": "PIL",
        "openai": "openai",
        "jieba": "jieba",
        "wordcloud": "wordcloud",
        "apscheduler": "apscheduler",
    }
    for name, module in deps.items():
        try:
            mod = __import__(module.split(".")[0])
            ver = getattr(mod, "__version__", "已安装")
            report.append(f"  ✅ {name}: {ver}")
        except ImportError:
            report.append(f"  ❌ {name}: 未安装")
            issues.append(f"缺少依赖: {name}")
    report.append("")

    # 3. 配置检查
    report.append("【配置检查】")
    try:
        from .config import ALLOWED_GROUPS, DEFAULT_GROUP, SUPERUSERS, _PLUGIN_DIR
        report.append(f"  插件目录: {_PLUGIN_DIR}")

        # API配置（从chat.py的_cfg读取）
        try:
            from .chat import _cfg
            api_key = _cfg("api_key", "")
            api_base = _cfg("api_base", "")
            model_name = _cfg("model_name", "")
            if api_key and api_key != "ollama":
                report.append(f"  API Key: {'*' * 8}...{api_key[-4:]}")
            else:
                report.append(f"  API Key: {api_key or '未配置'}")
            report.append(f"  API Base: {api_base}")
            report.append(f"  模型: {model_name}")
        except Exception as e:
            report.append(f"  API配置: 读取失败 ({e})")
        report.append(f"  白名单群: {ALLOWED_GROUPS}")
        report.append(f"  超级管理员: {SUPERUSERS}")

        if not ALLOWED_GROUPS:
            warnings.append("ALLOWED_GROUPS 为空，bot不会在任何群响应")

    except Exception as e:
        report.append(f"  ❌ 配置加载失败: {e}")
        issues.append(f"配置错误: {e}")
    report.append("")

    # 4. 数据目录检查
    report.append("【数据目录】")
    report.append(f"  数据目录: {_DATA_DIR}")
    if os.path.exists(_DATA_DIR):
        report.append(f"  ✅ 目录存在")
        # 检查关键文件
        key_files = ["checkin.json", "reminders.json", "user_points.json"]
        for f in key_files:
            path = os.path.join(_DATA_DIR, f)
            if os.path.exists(path):
                size = os.path.getsize(path)
                report.append(f"  ✅ {f}: {size} bytes")
            else:
                report.append(f"  ⚠️ {f}: 不存在（首次运行正常）")
    else:
        report.append(f"  ⚠️ 目录不存在，将自动创建")
        warnings.append(f"数据目录不存在: {_DATA_DIR}")
    report.append("")

    # 5. 网络检查
    report.append("【网络检查】")
    try:
        from .utils import get_shared_http_client
        client = get_shared_http_client()

        # 测试 GitHub API
        try:
            resp = await client.get("https://api.github.com", timeout=5.0)
            if resp.status_code == 200:
                report.append("  ✅ GitHub API: 可访问")
            else:
                report.append(f"  ⚠️ GitHub API: 状态码 {resp.status_code}")
        except Exception as e:
            report.append(f"  ❌ GitHub API: {type(e).__name__}")
            warnings.append("无法访问 GitHub，更新功能可能受影响")

        # 测试 OpenAI API
        try:
            from .config import API_BASE
            resp = await client.get(f"{API_BASE.rstrip('/v1')}/models", timeout=10.0)
            if resp.status_code in (200, 401, 403):
                report.append("  ✅ AI API: 可访问")
            else:
                report.append(f"  ⚠️ AI API: 状态码 {resp.status_code}")
        except Exception as e:
            report.append(f"  ❌ AI API: {type(e).__name__}")
            issues.append(f"AI API 不可访问: {type(e).__name__}")

    except Exception as e:
        report.append(f"  ❌ HTTP客户端初始化失败: {e}")
        issues.append(f"HTTP客户端错误: {e}")
    report.append("")

    # 6. 文件完整性
    report.append("【文件完整性】")
    try:
        from .config import _PLUGIN_DIR
        required_files = [
            "__init__.py", "config.py", "chat.py", "utils.py",
            "commands_base.py", "commands_update.py"
        ]
        for f in required_files:
            path = os.path.join(_PLUGIN_DIR, f)
            if os.path.exists(path):
                report.append(f"  ✅ {f}")
            else:
                report.append(f"  ❌ {f}: 缺失")
                issues.append(f"文件缺失: {f}")

        # 检查 assets 目录
        assets_dir = os.path.join(_PLUGIN_DIR, "assets")
        if os.path.exists(assets_dir):
            stickers = os.path.join(assets_dir, "stickers")
            badges = os.path.join(assets_dir, "badges")
            if os.path.exists(stickers):
                count = len([f for f in os.listdir(stickers) if f.endswith(('.png', '.gif'))])
                report.append(f"  ✅ 表情包: {count} 个")
            else:
                report.append(f"  ⚠️ 表情包目录不存在")
            if os.path.exists(badges):
                count = len([f for f in os.listdir(badges) if f.endswith('.png')])
                report.append(f"  ✅ 徽章: {count} 个")
            else:
                report.append(f"  ⚠️ 徽章目录不存在")
        else:
            report.append(f"  ⚠️ assets 目录不存在")
            warnings.append("assets 目录缺失，部分功能受限")
    except Exception as e:
        report.append(f"  ❌ 检查失败: {e}")
    report.append("")

    # 7. 进程状态
    report.append("【进程状态】")
    try:
        import psutil
        process = psutil.Process(os.getpid())
        report.append(f"  PID: {os.getpid()}")
        report.append(f"  内存: {process.memory_info().rss / 1024 / 1024:.1f} MB")
        report.append(f"  CPU: {process.cpu_percent()}%")
        report.append(f"  线程数: {process.num_threads()}")
    except ImportError:
        report.append(f"  PID: {os.getpid()}")
        report.append(f"  (psutil 未安装，详细信息不可用)")
    report.append("")

    # 8. 定时任务
    report.append("【定时任务】")
    try:
        from nonebot_plugin_apscheduler import scheduler
        jobs = scheduler.get_jobs()
        if jobs:
            for job in jobs[:5]:  # 只显示前5个
                next_run = job.next_run_time
                report.append(f"  ✅ {job.name}: 下次运行 {next_run}")
            if len(jobs) > 5:
                report.append(f"  ... 共 {len(jobs)} 个任务")
        else:
            report.append("  ⚠️ 没有注册定时任务")
    except Exception as e:
        report.append(f"  ❌ 获取定时任务失败: {e}")
    report.append("")

    # 9. 最近错误日志
    report.append("【最近错误】")
    log_file = os.path.join(_DATA_DIR, "..", "logs", "error.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-5:]  # 最后5行
                for line in lines:
                    report.append(f"  {line.strip()[:80]}")
        except Exception:
            report.append("  (无法读取日志)")
    else:
        report.append("  (无错误日志文件)")
    report.append("")

    # 汇总
    report.append("=" * 30)
    report.append("【诊断结果】")

    if issues:
        report.append(f"❌ 发现 {len(issues)} 个问题:")
        for i, issue in enumerate(issues, 1):
            report.append(f"  {i}. {issue}")
    else:
        report.append("✅ 未发现严重问题")

    if warnings:
        report.append(f"⚠️ {len(warnings)} 个警告:")
        for i, warn in enumerate(warnings, 1):
            report.append(f"  {i}. {warn}")

    report.append("")
    report.append("诊断完成。如有问题请检查上述项目。")

    # 分页发送
    text = "\n".join(report)
    # 每页最多500字符
    pages = []
    while len(text) > 500:
        # 找最后一个换行符
        idx = text.rfind("\n", 0, 500)
        if idx == -1:
            idx = 500
        pages.append(text[:idx])
        text = text[idx+1:]
    if text:
        pages.append(text)

    for i, page in enumerate(pages):
        if i == 0:
            await diagnose_cmd.send(page)
        else:
            await diagnose_cmd.send(page)
            await asyncio.sleep(0.5)  # 避免刷屏

import asyncio
diagnose_cmd = _register("诊断", _cmd_diagnose, aliases=["自检", "diag"], priority=1, admin_only=True)


# ─────────────────────────────────────────────────────────────
# 快速状态检查

async def _cmd_status(event: MessageEvent):
    """快速状态检查"""
    try:
        from .config import ALLOWED_GROUPS
        from .utils import get_shared_http_client

        status = []
        status.append("📊 快速状态")
        status.append("─" * 20)

        # API状态
        try:
            from .chat import _cfg
            api_key = _cfg("api_key", "")
            api_base = _cfg("api_base", "")
            if api_key and api_key != "ollama":
                client = get_shared_http_client()
                resp = await client.get(f"{api_base.rstrip('/v1')}/models", timeout=5.0)
                if resp.status_code in (200, 401, 403):
                    status.append(f"AI: ✅ 正常")
                else:
                    status.append(f"AI: ⚠️ {resp.status_code}")
            else:
                status.append(f"AI: {'✅ Ollama' if api_key == 'ollama' else '❌ 未配置'}")
        except Exception as e:
            status.append(f"AI: ❌ {type(e).__name__}")

        # 内存
        try:
            import psutil
            mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
            status.append(f"内存: {mem:.0f}MB")
        except:
            pass

        # 运行时间
        from . import _start_time
        if _start_time:
            uptime = time.time() - _start_time
            hours = int(uptime // 3600)
            mins = int((uptime % 3600) // 60)
            status.append(f"运行: {hours}h {mins}m")

        status.append(f"白名单: {len(ALLOWED_GROUPS)} 群")

        await status_cmd.finish("\n".join(status))

    except Exception as e:
        await status_cmd.finish(f"状态检查失败: {e}")

status_cmd = _register("状态", _cmd_status, priority=1)
