# ========== 定时任务 ==========

# 标准库
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta

# 第三方库
from nonebot import get_driver, get_bot, logger
from nonebot.adapters.onebot.v11 import MessageEvent

# 从子模块导入
from .commands_base import _register, check_superuser, _load_json, _save_json, _DATA_DIR, superusers



async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _get_scheduler():
    """延迟导入 scheduler，避免和 bot.py 的 load_plugin 冲突"""
    from nonebot_plugin_apscheduler import scheduler
    return scheduler

SCHEDULED_TASKS_FILE = os.path.join(_DATA_DIR, "scheduled_tasks.json")
_scheduled_tasks = {}  # {f"{group_id}:{time}": {"content": str, "enabled": bool}}

def _load_scheduled_tasks():
    global _scheduled_tasks
    _scheduled_tasks = _load_json(SCHEDULED_TASKS_FILE)

def _save_scheduled_tasks():
    _save_json(SCHEDULED_TASKS_FILE, _scheduled_tasks)

_load_scheduled_tasks()

async def _cmd_schedule(event: MessageEvent):
    """定时任务：/定时 时间 内容 或 /定时 每天 时间 内容 或 /定时 30m 喝水（一次性）"""
    if not isinstance(event, MessageEvent):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        if not isinstance(event, GroupMessageEvent):
            await _send(event, "...这个命令只能在群里用哦。")
            return
    content = str(event.message).strip()
    for prefix in ["定时"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, 
            "...用法：/定时 08:00 早安\n"
            "或：/定时 每天 08:00 早安\n"
            "或：/定时 30m 喝水（一次性定时）"
        )
        return

    group_id = str(getattr(event, 'group_id', 0))

    # ---- 一次性定时检测：\d+[smhd] 格式 ----
    onetime_match = re.match(r'(\d+[smhd])\s+(.*)', content)
    if onetime_match:
        delay_str = onetime_match.group(1)
        task_content = onetime_match.group(2).strip()
        if not task_content:
            await _send(event, "...格式不对哦。用法：/定时 30m 喝水")
            return
        # 解析延迟时间
        delay_seconds = _parse_delay(delay_str)
        if delay_seconds is None:
            await _send(event, "...延迟格式不对，支持如 30s, 30m, 2h, 1d。")
            return
        if delay_seconds < 1:
            await _send(event, "...延迟时间太短了。")
            return
        run_date = datetime.now() + timedelta(seconds=delay_seconds)
        key = f"{group_id}:once:{run_date.isoformat()}"
        _scheduled_tasks[key] = {
            "content": task_content,
            "enabled": True,
            "type": "once",
            "run_date": run_date.isoformat(),
        }
        _save_scheduled_tasks()
        # 注册一次性 APScheduler 任务
        try:
            _get_scheduler().add_job(
                _execute_scheduled_task,
                "date",
                run_date=run_date,
                args=[group_id, task_content, key],
                id=f"sched_{key}",
                replace_existing=True,
            )
        except Exception as e:
            logger.error(f"[定时] APScheduler 注册失败: {e}")
        delay_display = _format_delay(delay_seconds)
        await _send(event, 
            f"已设置一次性定时：{delay_display}后发送「{task_content}」"
        )
        return

    # ---- 每天定时（原有逻辑） ----
    time_str = None
    task_content = None
    if content.startswith("每天"):
        content = content[2:].strip()
    # 提取时间（HH:MM 格式）
    m = re.match(r'(\d{1,2}:\d{2})\s+(.*)', content)
    if m:
        time_str = m.group(1)
        task_content = m.group(2).strip()
    if not time_str or not task_content:
        await _send(event, "...格式不对哦。用法：/定时 08:00 早安")
        return
    # 验证时间格式
    try:
        h, mi = time_str.split(":")
        h, mi = int(h), int(mi)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        await _send(event, "...时间格式不对，请用 HH:MM 格式。")
        return
    key = f"{group_id}:{time_str}"
    _scheduled_tasks[key] = {"content": task_content, "enabled": True, "type": "daily"}
    _save_scheduled_tasks()
    # 注册 APScheduler 任务
    try:
        _get_scheduler().add_job(
            _execute_scheduled_task,
            "cron",
            hour=h,
            minute=mi,
            args=[group_id, task_content],
            id=f"sched_{key}",
            replace_existing=True,
        )
    except Exception as e:
        logger.error(f"[定时] APScheduler 注册失败: {e}")
    await _send(event, f"已设置定时任务：每天 {time_str} 发送「{task_content}」")


def _parse_delay(delay_str: str):
    """解析延迟字符串（如 30s, 2h, 1d）为秒数，失败返回 None"""
    m = re.match(r'^(\d+)([smhd])$', delay_str.lower())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers.get(unit, 0)


def _format_delay(seconds: float) -> str:
    """将秒数格式化为可读字符串"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        return f"{int(seconds // 60)}分钟"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        if mins > 0:
            return f"{hours}小时{mins}分钟"
        return f"{hours}小时"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        if hours > 0:
            return f"{days}天{hours}小时"
        return f"{days}天"


async def _execute_scheduled_task(group_id: str, content: str, task_key: str = None):
    """执行定时任务：向指定群发送消息"""
    try:
        from nonebot import get_bot
        bot = get_bot()
        await bot.send_group_msg(group_id=int(group_id), message=content)
        logger.info(f"[定时] 已向群 {group_id} 发送定时消息: {content}")
        # 一次性任务执行后自动删除
        if task_key and task_key in _scheduled_tasks:
            del _scheduled_tasks[task_key]
            _save_scheduled_tasks()
            logger.info(f"[定时] 已删除一次性任务: {task_key}")
    except Exception as e:
        logger.error(f"[定时] 发送失败: {e}")

async def _cmd_schedule_list(event: MessageEvent):
    """查看定时任务列表"""
    group_id = str(getattr(event, 'group_id', 0))
    if not group_id or group_id == "0":
        await _send(event, "...这个命令只能在群里用哦。")
        return
    tasks = []
    now = datetime.now()
    expired_keys = []
    for key, val in _scheduled_tasks.items():
        if not key.startswith(f"{group_id}:"):
            continue
        task_type = val.get("type", "daily")
        if task_type == "once":
            # 一次性任务：显示剩余时间
            run_date_str = val.get("run_date", "")
            try:
                run_date = datetime.fromisoformat(run_date_str)
                if run_date <= now:
                    expired_keys.append(key)
                    continue
                remaining = run_date - now
                remaining_str = _format_delay(remaining.total_seconds())
                tasks.append(f"  [一次性] {remaining_str}后 — {val['content']}")
            except (ValueError, TypeError):
                tasks.append(f"  [一次性] {run_date_str} — {val['content']}")
        else:
            # 每天定时任务
            time_part = key.split(":", 1)[1]
            status = "开启" if val.get("enabled", True) else "关闭"
            tasks.append(f"  [每天] {time_part} — {val['content']} [{status}]")
    # 清理已过期的一次性任务
    for ek in expired_keys:
        del _scheduled_tasks[ek]
    if expired_keys:
        _save_scheduled_tasks()
    if not tasks:
        await _send(event, "...当前群没有定时任务。")
        return
    lines = ["【定时任务列表】"] + tasks
    lines.append(f"\n共 {len(tasks)} 个任务")
    await _send(event, "\n".join(lines))

async def _cmd_cancel_schedule(event: MessageEvent):
    """取消定时任务：/取消定时 时间"""
    group_id = str(getattr(event, 'group_id', 0))
    if not group_id or group_id == "0":
        await _send(event, "...这个命令只能在群里用哦。")
        return
    content = str(event.message).strip()
    for prefix in ["取消定时"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...用法：/取消定时 08:00")
        return
    key = f"{group_id}:{content}"
    if key in _scheduled_tasks:
        del _scheduled_tasks[key]
        _save_scheduled_tasks()
        try:
            _get_scheduler().remove_job(f"sched_{key}")
        except Exception:
            pass
        await _send(event, f"已取消 {content} 的定时任务。")
    else:
        await _send(event, f"...没有找到 {content} 的定时任务。")

schedule_cmd = _register("定时", _cmd_schedule)
schedule_list_cmd = _register("定时列表", _cmd_schedule_list)
cancel_schedule_cmd = _register("取消定时", _cmd_cancel_schedule)

# 启动时恢复所有定时任务
def _restore_scheduled_tasks():
    now = datetime.now()
    expired_keys = []
    for key, val in list(_scheduled_tasks.items()):
        if not val.get("enabled", True):
            continue
        task_type = val.get("type", "daily")
        if task_type == "once":
            # 恢复一次性任务（如果未过期）
            run_date_str = val.get("run_date", "")
            try:
                run_date = datetime.fromisoformat(run_date_str)
                if run_date <= now:
                    expired_keys.append(key)
                    continue
                parts = key.split(":", 2)
                if len(parts) < 3:
                    expired_keys.append(key)
                    continue
                group_id = parts[0]
                _get_scheduler().add_job(
                    _execute_scheduled_task,
                    "date",
                    run_date=run_date,
                    args=[group_id, val["content"], key],
                    id=f"sched_{key}",
                    replace_existing=True,
                )
                logger.info(f"[定时] 恢复一次性任务: {key} -> {val['content']}")
            except Exception as e:
                logger.error(f"[定时] 恢复一次性任务失败 {key}: {e}")
        else:
            # 恢复每天定时任务
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            group_id, time_str = parts
            try:
                h, mi = time_str.split(":")
                h, mi = int(h), int(mi)
                _get_scheduler().add_job(
                    _execute_scheduled_task,
                    "cron",
                    hour=h,
                    minute=mi,
                    args=[group_id, val["content"]],
                    id=f"sched_{key}",
                    replace_existing=True,
                )
                logger.info(f"[定时] 恢复任务: {key} -> {val['content']}")
            except Exception as e:
                logger.error(f"[定时] 恢复任务失败 {key}: {e}")
    # 清理已过期的一次性任务
    for ek in expired_keys:
        del _scheduled_tasks[ek]
    if expired_keys:
        _save_scheduled_tasks()

_driver = get_driver()
@_driver.on_startup
async def _on_startup_restore_tasks():
    _restore_scheduled_tasks()


# ========== 异常告警 ==========

ALERT_CONFIG_FILE = os.path.join(_DATA_DIR, "alert_config.json")
_alert_config = {}  # {group_id: {"enabled": bool}}

def _load_alert_config():
    global _alert_config
    _alert_config = _load_json(ALERT_CONFIG_FILE)

def _save_alert_config():
    _save_json(ALERT_CONFIG_FILE, _alert_config)

_load_alert_config()

HEARTBEAT_FILE = os.path.join(_DATA_DIR, "heartbeat.txt")

async def _write_heartbeat():
    """写入心跳文件（异步，避免阻塞事件循环）"""
    try:
        await asyncio.to_thread(_sync_write_heartbeat)
    except Exception as e:
        logger.error(f"[告警] 心跳写入失败: {e}")

def _sync_write_heartbeat():
    """同步写入心跳文件"""
    with open(HEARTBEAT_FILE, "w") as f:
        f.write(str(time.time()))

async def _cmd_set_alert(event: MessageEvent):
    """设置告警：/设置告警 开/关"""
    from nonebot.adapters.onebot.v11 import GroupMessageEvent
    if not isinstance(event, GroupMessageEvent):
        await _send(event, "...这个命令只能在群里用哦。")
        return
    if not check_superuser(str(event.user_id)):
        await _send(event, "...你不是管理员。")
        return
    content = str(event.message).strip()
    for prefix in ["设置告警"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if content in ("开", "开启", "on", "1", "true"):
        group_id = str(event.group_id)
        _alert_config[group_id] = {"enabled": True}
        _save_alert_config()
        await _send(event, "已开启掉线告警~")
    elif content in ("关", "关闭", "off", "0", "false"):
        group_id = str(event.group_id)
        _alert_config[group_id] = {"enabled": False}
        _save_alert_config()
        await _send(event, "已关闭掉线告警。")
    else:
        await _send(event, "...用法：/设置告警 开 或 /设置告警 关")

set_alert_cmd = _register("设置告警", _cmd_set_alert)

# 定期写入心跳
def _setup_heartbeat():
    try:
        _get_scheduler().add_job(
            _write_heartbeat,
            "interval",
            minutes=5,
            id="heartbeat_writer",
            replace_existing=True,
        )
        logger.info("[告警] 心跳任务已注册（每5分钟）")
    except Exception as e:
        logger.error(f"[告警] 心跳任务注册失败: {e}")

@_driver.on_startup
async def _on_startup_heartbeat():
    _write_heartbeat()
    _setup_heartbeat()
    # 检查上次心跳
    try:
        if os.path.exists(HEARTBEAT_FILE):
            with open(HEARTBEAT_FILE, "r") as f:
                last_beat = float(f.read().strip())
            gap = time.time() - last_beat
            if gap > 600:  # 超过10分钟
                logger.warning(f"[告警] 检测到上次心跳距今 {gap:.0f} 秒，可能曾掉线")
                # 通知所有开启了告警的群
                for gid, cfg in _alert_config.items():
                    if cfg.get("enabled", False):
                        try:
                            from nonebot import get_bot
                            bot = get_bot()
                            await bot.send_group_msg(
                                group_id=int(gid),
                                message=f"...刚才好像断线了 {gap/60:.1f} 分钟，现在已恢复。"
                            )
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"[告警] 启动检查失败: {e}")
