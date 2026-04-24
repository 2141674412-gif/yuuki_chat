# 提醒模块

from datetime import datetime, timedelta
import re

from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _save_reminders, reminders


# -- 提醒 --

async def _cmd_remind(event: MessageEvent):
    content = str(event.message).replace("提醒", "").strip()

    if not content:
        await remind_cmd.finish("提醒你什么。说清楚。格式：/提醒 5分钟 写作业")

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
            await remind_cmd.finish("时间已过，请设置未来的时间。")

        if user_id not in reminders:
            reminders[user_id] = []

        reminder_id = max((r["id"] for r in reminders[user_id]), default=0) + 1
        reminders[user_id].append({
            "id": reminder_id, "content": remind_content,
            "time": remind_time, "created": now
        })
        _save_reminders()

        await remind_cmd.finish(f"记住了。{remind_time.strftime('%H:%M')}提醒你{remind_content}。")
    else:
        await remind_cmd.finish("时间格式不对。比如：/提醒 5分钟 写作业")

remind_cmd = _register("提醒", _cmd_remind)

# -- 历史（查看提醒）--

async def _cmd_reminders(event: MessageEvent):
    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await reminders_cmd.finish("你没什么提醒。")

    lines = [f"{r['id']}. {r['content']} ({r['time'].strftime('%H:%M')})" for r in reminders[user_id]]
    await reminders_cmd.finish("你的提醒：\n" + "\n".join(lines))

reminders_cmd = _register("历史", _cmd_reminders)

# -- 取消提醒 --

async def _cmd_cancel_remind(event: MessageEvent):
    remind_id_str = str(event.message).replace("取消提醒", "").strip()

    if not remind_id_str:
        await cancel_remind_cmd.finish("取消哪个。说序号。")

    user_id = str(event.user_id)

    if user_id not in reminders or not reminders[user_id]:
        await cancel_remind_cmd.finish("你本来就没提醒。")

    try:
        remind_id = int(remind_id_str)
    except ValueError:
        await cancel_remind_cmd.finish("...序号格式不对。")
        return

    for i, r in enumerate(reminders[user_id]):
        if r["id"] == remind_id:
            reminders[user_id].pop(i)
            _save_reminders()
            await cancel_remind_cmd.finish(f"取消了。{r['content']}。")
            return

    await cancel_remind_cmd.finish("找不到这个提醒。")

cancel_remind_cmd = _register("取消提醒", _cmd_cancel_remind)
