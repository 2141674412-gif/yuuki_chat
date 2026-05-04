"""commands_checkin - 签到积分模块

包含签到、积分查询、积分排行榜、签到提醒命令。
"""

# 标准库
import asyncio
import random
import re
from datetime import datetime, timedelta

# 第三方库
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

# 基础模块
from .commands_base import (
    _register,
    _save_checkin_records, _save_points,
    user_points, checkin_records,
    send_msg as _send,
)



def _mask_qq(qq: str) -> str:
    """脱敏 QQ 号：1234567890 -> 123****890"""
    if len(qq) >= 7:
        return qq[:3] + "****" + qq[-3:]
    return qq


# -- 签到 --

# -- 签到里程碑 --
MILESTONES = {
    3: ("三日坚持 🌱", 30),
    7: ("一周达人 ⭐", 50),
    14: ("两周毅力 💪", 100),
    21: ("三周之星 🌟", 150),
    30: ("月签传说 👑", 300),
    60: ("双月勇士 🏆", 500),
    100: ("百日不辍 💎", 1000),
    365: ("一年之约 🎊", 5000),
}


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
    # 连续签到基础 +10，每7天额外递增
    # 连续签到 7 天（一周）：+50 积分
    # 连续签到 30 天（一月）：+200 积分
    if streak % 30 == 0:
        total = 200
        bonus_desc = "（月签奖励 +200）"
    elif streak % 7 == 0:
        total = 50
        bonus_desc = "（周签奖励 +50）"
    else:
        # 连续签到越长，基础积分越高
        base = 10 + min((streak // 7) * 5, 25)  # 每7天多+5，最多+25
        total = base
        bonus_desc = ""
    user_points[user_id] += total

    # 检查里程碑奖励
    milestone_msg = ""
    if streak in MILESTONES:
        milestone_name, milestone_bonus = MILESTONES[streak]
        user_points[user_id] += milestone_bonus
        milestone_msg = f"\n达成里程碑：{milestone_name}！额外 +{milestone_bonus} 积分"

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
        f"当前积分：{user_points[user_id]}{milestone_msg}\n"
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


# ========== 签到提醒 ==========

from .commands_schedule import _get_scheduler


async def _send_checkin_remind(user_id: str):
    """发送签到提醒（私聊优先，失败则群@）"""
    from nonebot import get_bot, get_bots
    try:
        bots = get_bots()
        if not bots:
            logger.warning("[签到提醒] 获取bot实例失败")
            return
        bot = list(bots.values())[0]
    except Exception:
        logger.warning("[签到提醒] 获取bot实例失败")
        return

    msg = "...该签到啦。今天的运势在等着你。"
    try:
        await bot.send_private_msg(user_id=int(user_id), message=msg)
        logger.info(f"[签到提醒] 已向用户 {user_id} 发送签到提醒（私聊）")
    except Exception as e:
        logger.warning(f"[签到提醒] 向用户 {user_id} 发送私聊失败：{e}，尝试群消息")
        sent = False
        try:
            from .config import ALLOWED_GROUPS
            for gid in ALLOWED_GROUPS:
                try:
                    await bot.send_group_msg(
                        group_id=gid,
                        message=f"[CQ:at,qq={user_id}] {msg}",
                    )
                    logger.info(f"[签到提醒] 已通过群 {gid} 向用户 {user_id} 发送签到提醒")
                    sent = True
                    break
                except Exception:
                    continue
        except Exception:
            pass
        if not sent:
            logger.warning(f"[签到提醒] 向用户 {user_id} 发送签到提醒完全失败")


async def _cmd_checkin_remind(event: MessageEvent):
    """设置每日签到提醒：/签到提醒 08:00 或 /签到提醒 关"""
    user_id = str(event.user_id)
    content = str(event.message).strip()
    for prefix in ["签到提醒"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        # 查看当前设置
        remind_time = checkin_records.get(user_id, {}).get("remind_time", "")
        if remind_time:
            await _send(event, f"你的签到提醒时间：每天 {remind_time}\n发送 /签到提醒 关 可以关闭。")
        else:
            await _send(event, "你还没设置签到提醒。\n用法：/签到提醒 08:00")
        return

    if content in ("关", "关闭", "off", "取消"):
        if user_id in checkin_records and checkin_records[user_id].get("remind_time"):
            old_time = checkin_records[user_id].pop("remind_time")
            _save_checkin_records()
            try:
                _get_scheduler().remove_job(f"checkin_remind_{user_id}")
            except Exception:
                pass
            await _send(event, f"已关闭签到提醒（原时间 {old_time}）。")
        else:
            await _send(event, "...你本来就没设置签到提醒。")
        return

    # 解析时间 HH:MM
    m = re.match(r'^(\d{1,2}):(\d{2})$', content)
    if not m:
        await _send(event, "时间格式不对。用法：/签到提醒 08:00\n关闭：/签到提醒 关")
        return

    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        await _send(event, "...时间范围不对。小时 0-23，分钟 0-59。")
        return

    time_str = f"{h:02d}:{mi:02d}"

    if user_id not in checkin_records:
        checkin_records[user_id] = {}

    checkin_records[user_id]["remind_time"] = time_str
    _save_checkin_records()

    # 注册 APScheduler 每日定时任务
    try:
        _get_scheduler().add_job(
            _send_checkin_remind,
            "cron",
            hour=h,
            minute=mi,
            args=[user_id],
            id=f"checkin_remind_{user_id}",
            replace_existing=True,
        )
        logger.info(f"[签到提醒] 已为用户 {user_id} 设置每日 {time_str} 签到提醒")
    except Exception as e:
        logger.error(f"[签到提醒] APScheduler 注册失败：{e}")

    await _send(event, f"记住了。每天 {time_str} 会提醒你签到。\n发送 /签到提醒 关 可以关闭。")


checkin_remind_cmd = _register("签到提醒", _cmd_checkin_remind)


def _restore_checkin_reminders():
    """启动时恢复所有用户的签到提醒"""
    restored = 0
    for user_id, record in checkin_records.items():
        remind_time = record.get("remind_time")
        if not remind_time:
            continue
        try:
            h, mi = remind_time.split(":")
            h, mi = int(h), int(mi)
            _get_scheduler().add_job(
                _send_checkin_remind,
                "cron",
                hour=h,
                minute=mi,
                args=[user_id],
                id=f"checkin_remind_{user_id}",
                replace_existing=True,
            )
            restored += 1
            logger.info(f"[签到提醒] 恢复用户 {user_id} 的签到提醒：{remind_time}")
        except Exception as e:
            logger.error(f"[签到提醒] 恢复用户 {user_id} 的签到提醒失败：{e}")
    if restored:
        logger.info(f"[签到提醒] 共恢复 {restored} 个签到提醒")


# 在 bot 启动时恢复签到提醒
from nonebot import get_driver
_driver = get_driver()

@_driver.on_startup
async def _on_startup_restore_checkin_reminders():
    _restore_checkin_reminders()
