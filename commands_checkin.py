"""commands_checkin - 签到积分模块

包含签到、积分查询、积分排行榜命令。
"""

# 标准库
import random
from datetime import datetime, timedelta

# 第三方库
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

# 基础模块
from .commands_base import (
    _register,
    _save_checkin_records, _save_points,
    user_points, checkin_records,
)



async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _mask_qq(qq: str) -> str:
    """脱敏 QQ 号：1234567890 -> 123****890"""
    if len(qq) >= 7:
        return qq[:3] + "****" + qq[-3:]
    return qq


# -- 签到 --

async def _cmd_checkin(event: MessageEvent):
    user_id = str(event.user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if user_id not in checkin_records:
        checkin_records[user_id] = {"last_date": None, "streak": 0}
    if user_id not in user_points:
        user_points[user_id] = 0

    if checkin_records[user_id]["last_date"] == today:
        await _send(event, "你今天已经签过了。别想骗我。")
        return

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if checkin_records[user_id]["last_date"] == yesterday:
        checkin_records[user_id]["streak"] += 1
    else:
        checkin_records[user_id]["streak"] = 1

    checkin_records[user_id]["last_date"] = today
    streak = checkin_records[user_id]["streak"]

    # 计算积分：递增奖励
    # 连续签到 1-6 天：+10 积分
    # 连续签到 7 天（一周）：+50 积分
    # 连续签到 30 天（一月）：+200 积分
    if streak % 30 == 0:
        total = 200
        bonus_desc = "（月签奖励 +200）"
    elif streak % 7 == 0:
        total = 50
        bonus_desc = "（周签奖励 +50）"
    else:
        total = 10
        bonus_desc = ""
    user_points[user_id] += total
    _save_checkin_records()
    _save_points()

    luck = random.choice(["大吉", "吉", "中吉", "小吉", "凶"])
    luck_msg = {
        "大吉": "今天运气不错。去吃个芭菲庆祝一下吧。",
        "吉": "还行。继续保持。",
        "中吉": "平平淡淡的一天。不过也没坏事。",
        "小吉": "有点小麻烦...但正义的伙伴不会被这种事打倒。",
        "凶": "...今天小心点。我是为你好。"
    }
    streak_msg = f" 连续签到 {streak} 天。"
    if streak >= 30:
        streak_msg += " 一个月了...你比我想象的还要坚持。"
    elif streak >= 7:
        streak_msg += " 还挺坚持的嘛。"

    await _send(event, 
        f"签到成功。+{total}积分{bonus_desc}\n"
        f"当前积分：{user_points[user_id]}\n"
        f"今日运势：{luck} - {luck_msg[luck]}{streak_msg}"
    )

checkin_cmd = _register("签到", _cmd_checkin)

# -- 积分查询 --

async def _cmd_points(event: MessageEvent):
    """查看积分：/积分 或 /积分 @某人"""
    user_id = str(event.user_id)
    # 如果@了别人，查别人的
    for seg in event.message:
        if seg.type == "at" and str(seg.data.get("qq", "")) != user_id:
            target_id = str(seg.data["qq"])
            break
    else:
        target_id = user_id

    points = user_points.get(target_id, 0)
    streak = 0
    if target_id in checkin_records:
        streak = checkin_records[target_id].get("streak", 0)

    if target_id == user_id:
        await _send(event, f"你的积分：{points}\n连续签到：{streak}天")
    else:
        await _send(event, f"Ta的积分：{points}\n连续签到：{streak}天")

points_cmd = _register("积分", _cmd_points, aliases=["我的积分", "查积分"])

# -- 积分排行 --

async def _cmd_ranking(event: MessageEvent):
    """积分排行榜：/排行"""
    if not user_points:
        await _send(event, "还没有人签到过。")
        return

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
    msg = "积分排行榜\n"
    for i, (uid, pts) in enumerate(sorted_users, 1):
        streak = checkin_records.get(uid, {}).get("streak", 0)
        medal = ["1st", "2nd", "3rd"][i-1] if i <= 3 else f"{i}th"
        msg += f"{medal} {pts}分 ({_mask_qq(uid)}) (连签{streak}天)\n"

    await _send(event, msg.strip())

ranking_cmd = _register("排行", _cmd_ranking, aliases=["排行榜", "排名"])
