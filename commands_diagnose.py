# ========== 自检诊断命令 ==========

import os
import sys
import time
import ast
import traceback
from datetime import datetime

from nonebot import logger, get_driver
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, check_superuser, _DATA_DIR
import asyncio

# ─────────────────────────────────────────────────────────────

def _check_code_bugs():
    """静态代码检查：检测常见的bug模式"""
    bugs = []

    try:
        from .config import _PLUGIN_DIR as _PD
    except Exception:
        _PD = os.path.dirname(os.path.abspath(__file__))

    # 要检查的文件
    check_files = [
        "chat.py", "commands_base.py", "commands_update.py",
        "commands_group_admin.py", "commands_weather.py",
        "commands_fun.py", "commands_checkin.py", "commands_schedule.py",
        "commands_birthday.py", "commands_wordcloud.py", "config.py",
        "__init__.py",
    ]

    for fname in check_files:
        fpath = os.path.join(_PD, fname)
        if not os.path.exists(fpath):
            bugs.append(f"❌ 文件缺失: {fname}")
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            lines = source.split("\n")
        except Exception as e:
            bugs.append(f"❌ 无法读取 {fname}: {e}")
            continue

        # 1. SyntaxError 检查
        try:
            ast.parse(source)
        except SyntaxError as e:
            bugs.append(f"❌ {fname} 第{e.lineno}行: SyntaxError: {e.msg}")
            continue

        # 2. global 声明位置检查（必须在函数开头，忽略docstring和注释）
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("global "):
                # 向上查找，跳过空行、注释、docstring、其他global
                for j in range(i - 2, max(i - 30, -1), -1):
                    prev = lines[j].strip()
                    if not prev or prev.startswith("#") or prev.startswith("global "):
                        continue
                    # 跳过 docstring（三引号字符串）
                    if prev.startswith('"""') or prev.startswith("'''") or prev.endswith('"""') or prev.endswith("'''"):
                        continue
                    if prev.startswith("def ") or prev.startswith("async def "):
                        break
                    # 跳过类型注解（-> xxx:）
                    if prev.startswith("->") or prev.startswith(") ->") or prev.endswith(":"):
                        continue
                    # global 前有实际代码语句
                    bugs.append(f"⚠️ {fname} 第{i}行: global 声明不在函数开头（前面有代码）")
                    break

        # 3. f-string 中未转义的变量引用检查
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if 'f"' in stripped or "f'" in stripped:
                import re
                fstring_vars = re.findall(r'\{([a-zA-Z_]\w*)\}', stripped)
                for var in fstring_vars:
                    if var in ("nickname",) and f"{{{var}}}" not in stripped:
                        bugs.append(f"⚠️ {fname} 第{i}行: f-string 中 '{var}' 可能未定义，需要用 '{{{var}}}' 转义")

        # 4. 检查 except Exception 是否遗漏 FinishedException
        # 只检查包含 .finish() 或 .send() 的函数（这些才会抛出 FinishedException）
        # 先找出哪些函数调用了 finish/send
        finish_functions = set()
        for i, line in enumerate(lines, 1):
            if ".finish(" in line or ".send(" in line:
                # 找到这个函数的范围
                func_start = -1
                for j in range(i - 1, max(i - 50, -1), -1):
                    if lines[j].strip().startswith("def ") or lines[j].strip().startswith("async def "):
                        func_start = j + 1
                        break
                if func_start > 0:
                    finish_functions.add(func_start)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("except Exception"):
                # 找到这个 except 所在的函数起始行
                func_start = -1
                for j in range(i - 1, max(i - 50, -1), -1):
                    if lines[j].strip().startswith("def ") or lines[j].strip().startswith("async def "):
                        func_start = j + 1
                        break
                # 只检查调用了 finish/send 的函数
                if func_start not in finish_functions:
                    continue
                # 检查前面是否有 except FinishedException
                found_finished = False
                for j in range(i - 2, max(i - 10, -1), -1):
                    if "FinishedException" in lines[j]:
                        found_finished = True
                        break
                    if "try:" in lines[j] or "except" in lines[j]:
                        continue
                if not found_finished and "FinishedException" in source:
                    bugs.append(f"⚠️ {fname} 第{i}行: except Exception 可能吞掉 FinishedException")

        # 5. 检查 open() 没有 with 语句
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "open(" in stripped and "with " not in stripped and "with(" not in stripped:
                # 排除一些安全的情况
                if "json.load(" in stripped or "json.dump(" in stripped:
                    continue
                if "= open(" in stripped and ".read()" in lines[min(i, len(lines)-1)]:
                    bugs.append(f"⚠️ {fname} 第{i}行: open() 未使用 with 语句，可能泄漏文件句柄")

        # 6. 检查 _cmd_update_cmd.send / _cmd_update_cmd.finish（旧代码残留）
        for i, line in enumerate(lines, 1):
            if "_cmd_update_cmd.send(" in line or "_cmd_update_cmd.finish(" in line:
                bugs.append(f"❌ {fname} 第{i}行: 使用了旧的 _cmd_update_cmd.send/finish，应改用 bot 直接发送")

    return bugs


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
    weather_ok = False
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

        try:
            resp = await client.get("https://wttr.in", headers={"User-Agent": "curl/7.68.0"}, timeout=5.0)
            weather_ok = resp.status_code in (200, 301, 302)
        except Exception:
            pass
    except Exception:
        pass

    if not github_ok:
        warnings.append("GitHub 不可访问，更新功能可能受影响")
    if not ai_ok:
        warnings.append("AI API 不可访问，聊天功能可能受影响")
    if not weather_ok:
        warnings.append("天气API不可访问，天气功能可能受影响")

    # ── 5. 文件完整性 ──
    try:
        from .config import _PLUGIN_DIR as _PD
        required = [
            "__init__.py", "config.py", "chat.py", "utils.py", "commands_base.py",
            "commands_fun.py", "commands_checkin.py", "commands_remind.py",
            "commands_calc.py", "commands_translate.py", "commands_search.py",
            "commands_weather.py", "commands_wordcloud.py", "commands_admin.py",
            "commands_group_admin.py", "commands_update.py", "commands_schedule.py",
            "commands_backup.py", "commands_vault.py", "commands_sticker.py",
            "commands_remote.py", "commands_diagnose.py", "commands_birthday.py",
        ]
        for f in required:
            if not os.path.exists(os.path.join(_PD, f)):
                issues.append(f"文件缺失: {f}")
    except Exception:
        pass

    # ── 6. 代码bug检查 ──
    code_bugs = _check_code_bugs()
    for bug in code_bugs:
        if bug.startswith("❌"):
            issues.append(bug)
        else:
            warnings.append(bug)

    # ── 7. 进程状态 ──
    mem_str = ""
    try:
        import psutil
        mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        mem_str = f"{mem:.0f}MB"
    except ImportError:
        pass

    # ── 8. 运行时间 ──
    uptime_str = ""
    try:
        from . import _start_time
        if _start_time:
            u = time.time() - _start_time
            uptime_str = f"{int(u//3600)}h{int((u%3600)//60)}m"
    except Exception:
        pass

    # ── 9. 定时任务 ──
    job_count = 0
    try:
        from nonebot_plugin_apscheduler import scheduler
        job_count = len(scheduler.get_jobs())
    except Exception:
        pass

    # ── 10. 版本信息 ──
    version_str = ""
    try:
        vfile = os.path.join(_DATA_DIR, ".version")
        if os.path.exists(vfile):
            with open(vfile) as f:
                version_str = f.read().strip()
    except Exception:
        pass

    # ── 11. 群白名单状态 ──
    group_info = ""
    try:
        from .config import ALLOWED_GROUPS
        group_info = f"{len(ALLOWED_GROUPS)}个群"
    except Exception:
        pass

    # ── 12. 数据文件大小 ──
    data_size = 0
    try:
        for f in os.listdir(_DATA_DIR):
            fp = os.path.join(_DATA_DIR, f)
            if os.path.isfile(fp):
                data_size += os.path.getsize(fp)
        if data_size > 1024 * 1024:
            data_str = f"{data_size/1024/1024:.1f}MB"
        else:
            data_str = f"{data_size/1024:.0f}KB"
    except Exception:
        data_str = "?"

    # ========== 输出 ==========
    if not issues and not warnings:
        msg = "✅ 自检通过，一切正常\n"
        msg += "─" * 24 + "\n"
        msg += f"版本 {version_str or '?'} | Python {sys.version.split()[0]}\n"
        if mem_str:
            msg += f"内存 {mem_str} | "
        if uptime_str:
            msg += f"运行 {uptime_str} | "
        msg += f"定时任务 {job_count}个\n"
        msg += f"依赖 {len(deps)-len(missing_deps)}/{len(deps)} | "
        msg += f"数据 {data_str}\n"
        msg += f"GitHub {'✅' if github_ok else '❌'} | "
        msg += f"AI {'✅' if ai_ok else '❌'} | "
        msg += f"天气 {'✅' if weather_ok else '❌'} | "
        msg += f"群 {group_info}"
        await diagnose_cmd.finish(msg)
        return

    # 有问题，显示详细报告
    report = []
    report.append("🔍 自检诊断报告")
    report.append("=" * 30)
    report.append(f"版本 {version_str or '?'} | Python {sys.version.split()[0]} | "
                   f"{'内存 '+mem_str if mem_str else ''}{' | ' if mem_str else ''}"
                   f"{'运行 '+uptime_str if uptime_str else ''}")
    report.append("")

    # 代码bug
    code_issues = [b for b in code_bugs if b.startswith("❌")]
    code_warnings = [b for b in code_bugs if b.startswith("⚠️")]
    if code_issues or code_warnings:
        report.append("【代码检查】")
        for b in code_issues + code_warnings:
            report.append(f"  {b}")
        report.append("")

    # 依赖
    if missing_deps:
        report.append("【依赖】")
        for d in missing_deps:
            tag = "❌" if d in ("nonebot", "nonebot-adapter-onebot", "httpx", "Pillow", "openai") else "⚠️"
            report.append(f"  {tag} {d}: 未安装")
        report.append("")

    # 网络
    if not github_ok or not ai_ok or not weather_ok:
        report.append("【网络】")
        report.append(f"  {'✅' if github_ok else '❌'} GitHub API")
        report.append(f"  {'✅' if ai_ok else '❌'} AI API")
        report.append(f"  {'✅' if weather_ok else '❌'} 天气 API")
        report.append("")

    # 文件
    missing_files = [i for i in issues if "文件缺失" in i]
    if missing_files:
        report.append("【文件】")
        for f in missing_files:
            report.append(f"  {f}")
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
