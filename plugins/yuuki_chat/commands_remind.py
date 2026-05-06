# 提醒模块

from datetime import datetime, timedelta
import asyncio
import re

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot import logger

from .commands_base import _register, _save_reminders, reminders, send_msg as _send


def _cleanup_expired_reminders():
    """清理已过期的提醒"""
    now = datetime.now()
    changed = False
    for user_id in list(reminders.keys()):
        before = len(reminders[user_id])
        reminders[user_id] = [r for r in reminders[user_id] if r["time"] > now]
        if len(reminders[user_id]) < before:
            changed = True
        if not reminders[user_id]:
            del reminders[user_id]
    if changed:
        _save_reminders()
        logger.info("[提醒] 已清理过期提醒")


_cleanup_expired_reminders()


# ========== 时间解析工具 ==========


def _parse_remind_time(text: str, now: datetime):
    """解析提醒时间文本，返回 (remind_datetime, original_time_str, remaining_content) 或 None。

    支持格式：
    - 数字+单位: 3天, 1天12小时, 1小时30分钟, 5分钟, 30秒
    - 绝对时间: 14:30, 下午3点, 明天8点, 后天14:30, 明天8点30分
    - 组合: 1小时30分钟后
    """
    original = text

    # ---- 1. 绝对时间：明天/后天 前缀 ----
    day_offset = 0
    abs_time_text = text
    m_prefix = re.match(r'^(明天|后天)\s*', text)
    if m_prefix:
        prefix_word = m_prefix.group(1)
        abs_time_text = text[m_prefix.end():]
        day_offset = 1 if prefix_word == "明天" else 2

    # ---- 2. 尝试解析 "下午X点" / "上午X点" / "X点X分" / "HH:MM" ----
    remind_time = None
    consumed_len = 0

    if day_offset > 0 or re.match(r'^(下午|上午|晚上|凌晨|早上|中午|\d{1,2}[:点])', abs_time_text):
        # 下午/上午/晚上/凌晨/早上/中午 + 数字
        period_match = re.match(
            r'^(下午|上午|晚上|凌晨|早上|中午)\s*(\d{1,2})\s*[点时:：]\s*(\d{1,2})?\s*[分]?',
            abs_time_text
        )
        if period_match:
            period = period_match.group(1)
            hour = int(period_match.group(2))
            minute = int(period_match.group(3) or 0)
            # 根据时段调整小时
            if period in ("下午", "晚上"):
                if hour < 12:
                    hour += 12
            elif period == "凌晨":
                if hour == 12:
                    hour = 0
            elif period in ("上午", "早上", "中午"):
                pass  # 保持原样
            remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            consumed_len = len(m_prefix.group(0)) + len(period_match.group(0)) if m_prefix else len(period_match.group(0))
        else:
            # 纯数字时间: "14:30" 或 "8点30分" 或 "8点"
            time_match = re.match(r'^(\d{1,2})\s*[点时:：]\s*(\d{1,2})?\s*[分]?', abs_time_text)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                if hour > 23 or minute > 59:
                    return None
                remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                consumed_len = len(m_prefix.group(0)) + len(time_match.group(0)) if m_prefix else len(time_match.group(0))

        if remind_time is not None:
            remind_time += timedelta(days=day_offset)
            if remind_time <= now:
                # 如果是今天的时间已过，且没有前缀，自动推到明天
                if day_offset == 0:
                    remind_time += timedelta(days=1)
                else:
                    return None  # 明天/后天指定的时间不应该已过
            remaining = text[consumed_len:].strip()
            # 去掉可能的 "后" 字
            remaining = re.sub(r'^后\s*', '', remaining)
            original_time_str = text[:consumed_len].strip()
            return (remind_time, original_time_str, remaining)

    # ---- 3. 数字+单位（支持天、小时、分钟、秒，可组合） ----
    # 匹配如: 1天12小时, 1小时30分钟, 3天, 5分钟, 30秒, 1小时30分钟后
    delta_match = re.match(
        r'^((?:\d+\s*(?:天|小时|分钟|分|秒)\s*)+)',
        text
    )
    if delta_match:
        delta_str = delta_match.group(1).strip()
        # 去掉末尾的 "后"
        delta_str_clean = re.sub(r'后$', '', delta_str)
        # 解析各单位
        total_seconds = 0
        parts = re.findall(r'(\d+)\s*(天|小时|分钟|分|秒)', delta_str_clean)
        if not parts:
            return None
        for num_str, unit in parts:
            num = int(num_str)
            if unit == "天":
                total_seconds += num * 86400
            elif unit == "小时":
                total_seconds += num * 3600
            elif unit in ("分钟", "分"):
                total_seconds += num * 60
            elif unit == "秒":
                total_seconds += num
        if total_seconds <= 0:
            return None
        remind_time = now + timedelta(seconds=total_seconds)
        remaining = text[len(delta_match.group(0)):].strip()
        remaining = re.sub(r'^后\s*', '', remaining)
        original_time_str = delta_str_clean
        return (remind_time, original_time_str, remaining)

    return None


def _format_timedelta(td: timedelta) -> str:
    """将 timedelta 格式化为可读字符串"""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return ""
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    if seconds > 0 and not parts:
        parts.append(f"{seconds}秒")
    return "".join(parts)


# -- 提醒 --


async def _cmd_remind(event: MessageEvent):
    content = str(event.message).strip()
    if content.startswith("提醒"):
        content = content[len("提醒"):].strip()

    if not content:
        await _send(event, "提醒你什么。说清楚。格式：/提醒 5分钟 写作业")
        return

    user_id = str(event.user_id)
    now = datetime.now()

    result = _parse_remind_time(content, now)
    if result:
        remind_time, original_time_str, remind_content = result
        if remind_time < now:
            await _send(event, "时间已过，请设置未来的时间。")
            return
        if not remind_content:
            await _send(event, "提醒内容呢。你想让我提醒你什么。")
            return
        if user_id not in reminders:
            reminders[user_id] = []
        reminder_id = max((r.get("id", 0) for r in reminders[user_id]), default=0) + 1
        reminders[user_id].append({
            "id": reminder_id, "content": remind_content,
            "time": remind_time, "created": now,
            "original_time": original_time_str,
        })
        _save_reminders()
        td = remind_time - now
        time_desc = _format_timedelta(td)
        await _send(event, f"记住了。{time_desc}后（{remind_time.strftime('%m-%d %H:%M')}）提醒你{remind_content}。")
    else:
        await _send(event, "时间格式不对。支持的格式：\n"
                         "  /提醒 5分钟 写作业\n"
                         "  /提醒 1天12小时 开会\n"
                         "  /提醒 14:30 喝水\n"
                         "  /提醒 下午3点 起床\n"
                         "  /提醒 明天8点30分 早读")

remind_cmd = _register("提醒", _cmd_remind, aliases=["tx"])

# -- 历史（查看提醒）--

async def _cmd_reminders(event: MessageEvent):
    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await _send(event, "你没什么提醒。")
        return

    now = datetime.now()
    active = [r for r in reminders[user_id] if r["time"] > now]
    if not active:
        await _send(event, "你没什么提醒。")
        return

    lines = []
    for r in active:
        original = r.get("original_time", "")
        if original:
            lines.append(f"{r['id']}. {r['content']} ({r['time'].strftime('%m-%d %H:%M')}, 设定于{original})")
        else:
            lines.append(f"{r['id']}. {r['content']} ({r['time'].strftime('%m-%d %H:%M')})")
    await _send(event, "你的提醒：\n" + "\n".join(lines))

reminders_cmd = _register("历史", _cmd_reminders, aliases=["ls"])

# -- 提醒列表 --

async def _cmd_remind_list(event: MessageEvent):
    """查看所有待处理提醒（与历史命令相同功能，额外别名）"""
    await _cmd_reminders(event)

remind_list_cmd = _register("提醒列表", _cmd_remind_list, aliases=["提醒历史", "remindlist", "txlb"])

# -- 取消提醒 --

async def _cmd_cancel_remind(event: MessageEvent):
    remind_id_str = str(event.message).strip()
    if remind_id_str.startswith("取消提醒"):
        remind_id_str = remind_id_str[len("取消提醒"):].strip()

    if not remind_id_str:
        await _send(event, "取消哪个。说序号。")
        return

    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await _send(event, "你本来就没提醒。")
        return

    try:
        remind_id = int(remind_id_str)
    except ValueError:
        await _send(event, "...序号格式不对。")
        return

    for i, r in enumerate(reminders[user_id]):
        if r["id"] == remind_id:
            reminders[user_id].pop(i)
            _save_reminders()
            await _send(event, f"取消了。{r['content']}。")
            return

    await _send(event, "找不到这个提醒。")

cancel_remind_cmd = _register("取消提醒", _cmd_cancel_remind, aliases=["qxtx"])


# -- 定时检查提醒 --

from .commands_schedule import _get_scheduler
from .commands_base import get_bot_safe


async def _check_reminders():
    """遍历所有用户的提醒，找到已到期的，发送私聊消息提醒，然后删除。"""
    now = datetime.now()
    changed = False
    try:
        bot = get_bot_safe()
        if bot is None:
            logger.warning("[提醒] 获取bot实例失败，跳过本次检查。")
            return
    except Exception:
        logger.warning("[提醒] 获取bot实例失败，跳过本次检查。")
        return

    for user_id in list(reminders.keys()):
        user_reminders = reminders[user_id]
        expired = [r for r in user_reminders if r["time"] <= now]
        if not expired:
            continue
        for r in expired:
            original = r.get("original_time", "")
            context = f"（设定于{original}）" if original else ""
            try:
                await bot.send_private_msg(
                    user_id=int(user_id),
                    message=f"到点了。{r['content']}。{context}",
                )
                logger.info(f"[提醒] 已向用户 {user_id} 发送提醒：{r['content']}")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[提醒] 向用户 {user_id} 发送私聊提醒失败：{e}，尝试群消息发送")
                # 私聊失败，尝试发送到已知群
                sent = False
                try:
                    from .config import ALLOWED_GROUPS
                    for gid in ALLOWED_GROUPS:
                        try:
                            await bot.send_group_msg(
                                group_id=gid,
                                message=f"[CQ:at,qq={user_id}] 到点了。{r['content']}。{context}",
                            )
                            logger.info(f"[提醒] 已通过群 {gid} 向用户 {user_id} 发送提醒")
                            sent = True
                            await asyncio.sleep(0.5)
                            break
                        except Exception:
                            continue
                except Exception:
                    pass
                if not sent:
                    logger.warning(f"[提醒] 向用户 {user_id} 发送提醒完全失败")
        reminders[user_id] = [r for r in user_reminders if r["time"] > now]
        changed = True

    if changed:
        _save_reminders()


def _register_reminder_jobs():
    """用APScheduler注册每分钟执行一次 _check_reminders。"""
    try:
        scheduler = _get_scheduler()
        scheduler.add_job(
            _check_reminders,
            "interval",
            minutes=1,
            id="check_reminders",
            replace_existing=True,
        )
        logger.info("[提醒] 定时检查任务已注册，每分钟执行一次。")
    except Exception as e:
        logger.warning(f"[提醒] 注册定时任务失败：{e}")


_register_reminder_jobs()
