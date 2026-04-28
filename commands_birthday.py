# 生日提醒模块

import os
import random
import time
from datetime import datetime

from nonebot import logger, get_bot
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent

from .commands_base import _register, _DATA_DIR, _load_json, _save_json
from .commands_schedule import _get_scheduler
from .config import ALLOWED_GROUPS

# 生日数据文件
_BIRTHDAY_FILE = os.path.join(_DATA_DIR, "birthdays.json")
# {group_id: {user_id: {"date": "MM-DD", "name": "昵称"}}}

# 今日已祝福记录（防止重复祝福）
_BLESSED_FILE = os.path.join(_DATA_DIR, "birthday_blessed.json")
# {"YYYY-MM-DD": {group_id: [user_id, ...]}}



async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _load_birthdays() -> dict:
    return _load_json(_BIRTHDAY_FILE) or {}


def _save_birthdays(data: dict):
    _save_json(_BIRTHDAY_FILE, data)


def _load_blessed() -> dict:
    return _load_json(_BLESSED_FILE) or {}


def _save_blessed(data: dict):
    _save_json(_BLESSED_FILE, data)


_birthdays = _load_birthdays()
_blessed = _load_blessed()

# 祝福语模板
_BLESS_TEMPLATES = [
    "🎂 今天是{nick}的生日！生日快乐！🎂",
    "🎉 {nick}生日快乐！新的一岁要加油哦！🎉",
    "🎈 生日快乐{nick}！今天是最特别的一天！🎈",
    "✨ {nick}，生日快乐！愿新的一年一切顺利！✨",
    "🍰 {nick}生日快乐！要永远开心哦！🍰",
    "🎁 祝{nick}生日快乐！今天要好好对自己！🎁",
    "🌟 {nick}生日快乐呀！又长大一岁了呢~🌟",
    "🎊 {nick}生日快乐！希望今天你能收到很多祝福！🎊",
]

# 提前提醒模板（提前1天）
_REMIND_TEMPLATES = [
    "🔔 明天就是{nick}的生日了，大家记得准备祝福哦！",
    "📅 {nick}的生日就在明天！提前祝生日快乐！",
    "💡 提醒一下，明天是{nick}的生日呢~",
]


async def _cmd_birthday(event: MessageEvent):
    """查看生日：/生日 或 /birthday"""
    gid = str(getattr(event, 'group_id', 0))
    if not gid:
        await _send(event, "...只能在群里查看生日。")
        return

    group_data = _birthdays.get(gid, {})
    if not group_data:
        await _send(event, "...这个群还没有人设置生日。\n用法：/设置生日 MM-DD（如：/设置生日 12-01）")
        return

    # 按日期排序
    sorted_list = sorted(group_data.items(), key=lambda x: x[1].get("date", "01-01"))

    # 计算距离下一个生日的天数
    today = datetime.now()
    today_md = today.strftime("%m-%d")
    lines = ["📋 本群生日列表：\n"]

    for uid, info in sorted_list:
        bdate = info.get("date", "??-??")
        name = info.get("name", uid)
        # 计算距离天数
        try:
            bmonth, bday = int(bdate.split("-")[0]), int(bdate.split("-")[1])
            this_year_birthday = datetime(today.year, bmonth, bday)
            if this_year_birthday < today:
                this_year_birthday = datetime(today.year + 1, bmonth, bday)
            days_left = (this_year_birthday - today).days
            if days_left == 0:
                lines.append(f"🎂 {name}（{bdate}）— 今天！")
            elif days_left == 1:
                lines.append(f"🎈 {name}（{bdate}）— 明天！")
            elif days_left <= 7:
                lines.append(f"📅 {name}（{bdate}）— 还有{days_left}天")
            else:
                lines.append(f"   {name}（{bdate}）— {days_left}天后")
        except (ValueError, IndexError):
            lines.append(f"   {name}（{bdate}）")

    await _send(event, "\n".join(lines))


async def _cmd_set_birthday(event: MessageEvent):
    """设置生日：/设置生日 MM-DD"""
    content = str(event.message).strip()
    for prefix in ["设置生日", "setbirthday", "setbirth"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    gid = str(getattr(event, 'group_id', 0))
    uid = str(event.user_id)
    if not gid:
        await _send(event, "...只能在群里设置生日。")
        return

    if not content:
        info = _birthdays.get(gid, {}).get(uid)
        if info:
            await _send(event, f"...你设置的生日是：{info['date']}\n修改：/设置生日 MM-DD\n删除：/删除生日")
        else:
            await _send(event, "...你还没设置生日。\n用法：/设置生日 MM-DD（如：/设置生日 12-01）")
        return

    if content in ("取消", "删除", "清除"):
        if gid in _birthdays and uid in _birthdays[gid]:
            del _birthdays[gid][uid]
            if not _birthdays[gid]:
                del _birthdays[gid]
            _save_birthdays(_birthdays)
            await _send(event, "...已删除你的生日设置。")
        else:
            await _send(event, "...你还没设置生日。")
        return

    # 解析日期 MM-DD
    content = content.replace("/", "-").replace(".", "-")
    try:
        parts = content.split("-")
        if len(parts) == 2:
            month, day = int(parts[0]), int(parts[1])
        elif len(parts) == 3:
            # 忽略年份
            month, day = int(parts[1]), int(parts[2])
        else:
            raise ValueError
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError
        # 简单校验天数
        import calendar
        max_day = calendar.monthrange(datetime.now().year, month)[1]
        if day > max_day:
            raise ValueError
    except (ValueError, IndexError):
        await _send(event, "...日期格式不对，用 MM-DD 格式，如：/设置生日 12-01")
        return

    date_str = f"{month:02d}-{day:02d}"

    # 获取发送者昵称
    sender_name = ""
    if hasattr(event, 'sender') and event.sender:
        sender_name = event.sender.card or event.sender.nickname or ""
    if not sender_name:
        sender_name = uid

    if gid not in _birthdays:
        _birthdays[gid] = {}
    _birthdays[gid][uid] = {"date": date_str, "name": sender_name}
    _save_birthdays(_birthdays)

    await _send(event, f"...已设置你的生日为 {date_str}，到时候会自动祝福你！")


async def _cmd_del_birthday(event: MessageEvent):
    """删除生日：/删除生日"""
    gid = str(getattr(event, 'group_id', 0))
    uid = str(event.user_id)

    if gid in _birthdays and uid in _birthdays[gid]:
        del _birthdays[gid][uid]
        if not _birthdays[gid]:
            del _birthdays[gid]
        _save_birthdays(_birthdays)
        await _send(event, "...已删除你的生日设置。")
    else:
        await _send(event, "...你还没设置生日。")


async def _check_birthdays():
    """定时检查生日并发送祝福（每小时检查一次）"""
    today = datetime.now()
    today_str = today.strftime("%m-%d")
    tomorrow = datetime(today.year, today.month, today.day)
    from datetime import timedelta
    tomorrow += timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%m-%d")
    date_key = today.strftime("%Y-%m-%d")

    if date_key not in _blessed:
        _blessed[date_key] = {}

    try:
        bot = get_bot()
    except Exception:
        logger.warning("[生日] 无法获取bot实例")
        return

    for gid, group_data in _birthdays.items():
        if not group_data:
            continue

        # 清理无效群绑定
        try:
            int(gid)
        except (ValueError, TypeError):
            continue
        # 只向白名单群发送
        if int(gid) not in ALLOWED_GROUPS:
            continue

        if gid not in _blessed[date_key]:
            _blessed[date_key][gid] = []

        for uid, info in group_data.items():
            bdate = info.get("date", "")
            name = info.get("name", uid)

            # 当天生日期
            if bdate == today_str and uid not in _blessed[date_key][gid]:
                template = random.choice(_BLESS_TEMPLATES)
                msg = template.format(nick=name)
                try:
                    await bot.send_group_msg(group_id=int(gid), message=msg)
                    logger.info(f"[生日] 已向群{gid}祝福 {name}({uid})")
                    _blessed[date_key][gid].append(uid)
                except Exception as e:
                    logger.error(f"[生日] 祝福发送失败: 群{gid} {e}")
                    # 群无效则清理
                    _blessed[date_key][gid].append(uid)  # 避免重复尝试

            # 提前一天提醒
            if bdate == tomorrow_str and uid not in _blessed[date_key][gid]:
                template = random.choice(_REMIND_TEMPLATES)
                msg = template.format(nick=name)
                try:
                    await bot.send_group_msg(group_id=int(gid), message=msg)
                    logger.info(f"[生日] 已向群{gid}提前提醒 {name}({uid})的生日")
                    _blessed[date_key][gid].append(uid)
                except Exception as e:
                    logger.error(f"[生日] 提醒发送失败: 群{gid} {e}")
                    _blessed[date_key][gid].append(uid)

    _save_blessed(_blessed)


def _register_birthday_jobs():
    """注册生日定时检查任务（每小时检查一次）"""
    try:
        sched = _get_scheduler()
        sched.add_job(
            _check_birthdays,
            "cron",
            minute=0,  # 每小时整点检查
            id="birthday_check",
            replace_existing=True,
        )
        logger.info("[生日] 已注册定时检查任务（每小时）")
    except Exception as e:
        logger.warning(f"[生日] 注册定时任务失败: {e}")


_register_birthday_jobs()

birthday_cmd = _register("生日", _cmd_birthday, aliases=["birthday"])
set_birthday_cmd = _register("设置生日", _cmd_set_birthday, aliases=["setbirthday", "setbirth"])
del_birthday_cmd = _register("删除生日", _cmd_del_birthday, aliases=["delbirthday", "delbirth"])
