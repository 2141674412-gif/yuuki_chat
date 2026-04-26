# 提醒模块

from datetime import datetime, timedelta
import re

from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _save_reminders, reminders


# -- 提醒 --

async def _cmd_remind(event: MessageEvent):
    content = str(event.message).replace("提醒", "").strip()

    if not content:
        await remind_cmd.send("提醒你什么。说清楚。格式：/提醒 5分钟 写作业")

    user_id = str(event.user_id)
    now = datetime.now()

    time_match = re.search(r'(\d+)\s*(分钟|小时|秒)', content)
    if time_match:
        num = int(time_match.group(1))
        unit = time_match.group(2)
        delta = {"分钟": timedelta(minutes=num), "小时": timedelta(hours=num), "秒": timedelta(seconds=num)}
        remind_time = now + delta[unit]
        remind_content = content.replace(time_match.group(0), "").strip()

        if remind_time <= now:
            await remind_cmd.send("时间已过，请设置未来的时间。")

        if user_id not in reminders:
            reminders[user_id] = []

        reminder_id = max((r["id"] for r in reminders[user_id]), default=0) + 1
        reminders[user_id].append({
            "id": reminder_id, "content": remind_content,
            "time": remind_time, "created": now
        })
        _save_reminders()

        await remind_cmd.send(f"记住了。{remind_time.strftime('%H:%M')}提醒你{remind_content}。")
    else:
        await remind_cmd.send("时间格式不对。比如：/提醒 5分钟 写作业")

remind_cmd = _register("提醒", _cmd_remind)

# -- 历史（查看提醒）--

async def _cmd_reminders(event: MessageEvent):
    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await reminders_cmd.send("你没什么提醒。")

    now = datetime.now()
    active = [r for r in reminders[user_id] if r["time"] > now]
    if not active:
        await reminders_cmd.send("你没什么提醒。")

    lines = [f"{r['id']}. {r['content']} ({r['time'].strftime('%H:%M')})" for r in active]
    await reminders_cmd.send("你的提醒：\n" + "\n".join(lines))

reminders_cmd = _register("历史", _cmd_reminders)

# -- 取消提醒 --

async def _cmd_cancel_remind(event: MessageEvent):
    remind_id_str = str(event.message).replace("取消提醒", "").strip()

    if not remind_id_str:
        await cancel_remind_cmd.send("取消哪个。说序号。")

    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await cancel_remind_cmd.send("你本来就没提醒。")

    try:
        remind_id = int(remind_id_str)
    except ValueError:
        await cancel_remind_cmd.send("...序号格式不对。")
        return

    for i, r in enumerate(reminders[user_id]):
        if r["id"] == remind_id:
            reminders[user_id].pop(i)
            _save_reminders()
            await cancel_remind_cmd.send(f"取消了。{r['content']}。")
            return

    await cancel_remind_cmd.send("找不到这个提醒。")

cancel_remind_cmd = _register("取消提醒", _cmd_cancel_remind)


# -- 定时检查提醒 --

from .commands_schedule import _get_scheduler
from nonebot import get_bot, logger


async def _check_reminders():
    """遍历所有用户的提醒，找到已到期的，发送私聊消息提醒，然后删除。"""
    now = datetime.now()
    changed = False
    try:
        bot = get_bot()
    except Exception:
        logger.warning("[提醒] 获取bot实例失败，跳过本次检查。")
        return

    for user_id in list(reminders.keys()):
        user_reminders = reminders[user_id]
        expired = [r for r in user_reminders if r["time"] <= now]
        if not expired:
            continue
        for r in expired:
            try:
                await bot.send_private_msg(
                    user_id=int(user_id),
                    message=f"到点了。{r['content']}。",
                )
                logger.info(f"[提醒] 已向用户 {user_id} 发送提醒：{r['content']}")
            except Exception as e:
                logger.warning(f"[提醒] 向用户 {user_id} 发送提醒失败：{e}")
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
