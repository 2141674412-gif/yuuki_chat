# ========== 自检诊断命令 ==========

import os
import sys
import time
from datetime import datetime

from nonebot import logger, get_driver
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, check_superuser, _DATA_DIR
import asyncio

# ─────────────────────────────────────────────────────────────

async def _cmd_diagnose(event: MessageEvent):
    """自检诊断：检查bot运行环境和常见问题"""
    if not check_superuser(str(event.user_id)):
        await diagnose_cmd.finish("...你不是管理员。")
        return

    issues = []
    warnings = []

    # ── 1. 依赖检查 ──
    deps = {
        "nonebot": "nonebot",
        "nonebot-adapter-onebot": "nonebot.adapters.onebot.v11",
        "httpx": "httpx",
        "Pillow": "PIL",
        "openai": "openai",
        "jieba": "jieba",
        "wordcloud": "wordcloud",
    }
    missing_deps = []
    for name, module in deps.items():
        try:
            __import__(module.split(".")[0])
        except ImportError:
            missing_deps.append(name)
            if name in ("nonebot", "nonebot-adapter-onebot", "httpx", "Pillow", "openai"):
                issues.append(f"缺少核心依赖: {name}")
            else:
                warnings.append(f"缺少可选依赖: {name}（不影响核心功能）")

    # ── 2. 配置检查 ──
    try:
        from .config import ALLOWED_GROUPS, _PLUGIN_DIR
        from .commands_base import superusers
    except Exception as e:
        issues.append(f"配置加载失败: {e}")

    # ── 3. 数据目录 ──
    if not os.path.exists(_DATA_DIR):
        warnings.append("数据目录不存在，将自动创建")

    # ── 4. 网络检查 ──
    github_ok = False
    ai_ok = False
    try:
        from .utils import get_shared_http_client
        client = get_shared_http_client()

        try:
            resp = await client.get("https://api.github.com", timeout=5.0)
            github_ok = resp.status_code == 200
        except Exception:
            pass

        try:
            from nonebot import get_driver
            _dc = get_driver().config.dict()
            api_base = _dc.get("api_base", "") or ""
            if api_base:
                resp = await client.get(f"{api_base.rstrip('/v1')}/models", timeout=5.0)
                ai_ok = resp.status_code in (200, 401, 403)
        except Exception:
            pass
    except Exception:
        pass

    if not github_ok:
        warnings.append("GitHub 不可访问，更新功能可能受影响")
    if not ai_ok:
        warnings.append("AI API 不可访问，聊天功能可能受影响")

    # ── 5. 文件完整性 ──
    try:
        from .config import _PLUGIN_DIR as _PD
        required = ["__init__.py", "config.py", "chat.py", "utils.py", "commands_base.py"]
        for f in required:
            if not os.path.exists(os.path.join(_PD, f)):
                issues.append(f"文件缺失: {f}")
    except Exception:
        pass

    # ── 6. 进程状态 ──
    mem_str = ""
    try:
        import psutil
        mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        mem_str = f"{mem:.0f}MB"
    except ImportError:
        pass

    # ── 7. 运行时间 ──
    uptime_str = ""
    try:
        from . import _start_time
        if _start_time:
            u = time.time() - _start_time
            uptime_str = f"{int(u//3600)}h{int((u%3600)//60)}m"
    except Exception:
        pass

    # ── 8. 定时任务 ──
    job_count = 0
    try:
        from nonebot_plugin_apscheduler import scheduler
        job_count = len(scheduler.get_jobs())
    except Exception:
        pass

    # ========== 输出 ==========
    # 正常模式：简洁摘要
    # 有问题模式：详细报告

    if not issues and not warnings:
        # 一切正常，只显示简要状态
        msg = "✅ 自检通过，一切正常\n"
        msg += "─" * 20 + "\n"
        msg += f"Python {sys.version.split()[0]} | "
        if mem_str:
            msg += f"内存 {mem_str} | "
        if uptime_str:
            msg += f"运行 {uptime_str} | "
        msg += f"定时任务 {job_count}个\n"
        msg += f"依赖 {len(deps)-len(missing_deps)}/{len(deps)} | "
        msg += f"GitHub {'✅' if github_ok else '❌'} | "
        msg += f"AI {'✅' if ai_ok else '❌'}"
        await diagnose_cmd.finish(msg)
        return

    # 有问题，显示详细报告
    report = []
    report.append("🔍 自检诊断报告")
    report.append("=" * 30)
    report.append(f"Python {sys.version.split()[0]} | "
                   f"{'内存 '+mem_str if mem_str else ''}{' | ' if mem_str else ''}"
                   f"{'运行 '+uptime_str if uptime_str else ''}")
    report.append("")

    # 依赖
    if missing_deps:
        report.append("【依赖】")
        for d in missing_deps:
            tag = "❌" if d in ("nonebot", "nonebot-adapter-onebot", "httpx", "Pillow", "openai") else "⚠️"
            report.append(f"  {tag} {d}: 未安装")
        report.append("")

    # 网络
    if not github_ok or not ai_ok:
        report.append("【网络】")
        report.append(f"  {'✅' if github_ok else '❌'} GitHub API")
        report.append(f"  {'✅' if ai_ok else '❌'} AI API")
        report.append("")

    # 文件
    missing_files = [i for i in issues if "文件缺失" in i]
    if missing_files:
        report.append("【文件】")
        for f in missing_files:
            report.append(f"  ❌ {f.replace('文件缺失: ', '')}")
        report.append("")

    # 定时任务
    report.append(f"【定时任务】 {job_count} 个")

    # 汇总
    report.append("")
    report.append("=" * 30)
    if issues:
        report.append(f"❌ {len(issues)} 个问题:")
        for i, issue in enumerate(issues, 1):
            report.append(f"  {i}. {issue}")
    if warnings:
        report.append(f"⚠️ {len(warnings)} 个警告:")
        for i, warn in enumerate(warnings, 1):
            report.append(f"  {i}. {warn}")

    text = "\n".join(report)

    # 分页发送（每页500字符）
    pages = []
    while len(text) > 500:
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
            await asyncio.sleep(0.3)


diagnose_cmd = _register("诊断", _cmd_diagnose, aliases=["自检", "diag"], priority=1, admin_only=True)


# ─────────────────────────────────────────────────────────────
# 快速状态（所有人可用）

async def _cmd_status(event: MessageEvent):
    """快速状态检查"""
    try:
        from .config import ALLOWED_GROUPS

        status = []
        status.append("📊 状态")
        status.append("─" * 20)

        # AI
        try:
            from nonebot import get_driver
            _dc = get_driver().config.dict()
            api_key = _dc.get("api_key", "") or ""
            api_base = _dc.get("api_base", "") or ""
            if api_key and api_key != "ollama":
                from .utils import get_shared_http_client
                client = get_shared_http_client()
                resp = await client.get(f"{api_base.rstrip('/v1')}/models", timeout=5.0)
                if resp.status_code in (200, 401, 403):
                    status.append(f"AI: ✅")
                else:
                    status.append(f"AI: ⚠️ {resp.status_code}")
            else:
                status.append(f"AI: {'✅ Ollama' if api_key == 'ollama' else '❌'}")
        except Exception as e:
            status.append(f"AI: ❌")

        # 内存
        try:
            import psutil
            mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
            status.append(f"内存: {mem:.0f}MB")
        except Exception:
            pass

        # 运行时间
        try:
            from . import _start_time
            if _start_time:
                u = time.time() - _start_time
                status.append(f"运行: {int(u//3600)}h{int((u%3600)//60)}m")
        except Exception:
            pass

        status.append(f"群: {len(ALLOWED_GROUPS)}")

        await status_cmd.finish("\n".join(status))
    except Exception as e:
        await status_cmd.finish(f"状态检查失败: {e}")


status_cmd = _register("状态", _cmd_status, priority=1)
