# ========== 群管功能（仅管理员） ==========

# 标准库
import re

# 第三方库
from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

# 从子模块导入
from .commands_base import check_superuser


async def _cmd_ban(event: MessageEvent, bot: Bot):
    """禁言：/禁言 @某人 [时长]"""
    if not isinstance(event, GroupMessageEvent):
        await ban_cmd.finish("...这个命令只能在群里用哦。")
        return
    content = str(event.message).strip()
    for prefix in ["禁言"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    # 提取被禁言的用户
    segments = event.message
    target_uid = None
    for seg in segments:
        if seg.type == "at":
            target_uid = str(seg.data.get("qq", ""))
            break
    if not target_uid:
        await ban_cmd.finish("...要禁言谁？请 @ta。")
        return
    # 解析时长
    duration = 30 * 60  # 默认30分钟
    if content:
        m = re.match(r"(\d+)\s*(m|min|分钟|h|小时|d|天)", content)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            if unit in ("h", "小时"):
                duration = val * 3600
            elif unit in ("d", "天"):
                duration = val * 86400
            else:
                duration = val * 60
    try:
        await bot.set_group_ban(group_id=event.group_id, user_id=int(target_uid), duration=duration)
        try:
            await ban_cmd.finish(f"已禁言 {duration // 60} 分钟~")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[禁言] 失败: {e}")
        await ban_cmd.finish("...禁言失败了。")

async def _cmd_kick(event: MessageEvent, bot: Bot):
    """踢人：/踢 @某人"""
    if not isinstance(event, GroupMessageEvent):
        await kick_cmd.finish("...这个命令只能在群里用哦。")
        return
    segments = event.message
    target_uid = None
    for seg in segments:
        if seg.type == "at":
            target_uid = str(seg.data.get("qq", ""))
            break
    if not target_uid:
        await kick_cmd.finish("...要踢谁？请 @ta。")
        return
    try:
        ret = await bot.set_group_kick(group_id=event.group_id, user_id=int(target_uid))
        # 某些OneBot实现踢人后返回非预期结果，但实际成功
        logger.info(f"[踢] 成功: {target_uid}, ret={ret}")
        try:
            await kick_cmd.finish("已送走~")
        except Exception:
            pass  # 发送失败不影响踢人结果
    except Exception as e:
        logger.error(f"[踢] 失败: {e}")
        await kick_cmd.finish("...踢人失败了。")

async def _cmd_recall(event: MessageEvent, bot: Bot):
    """撤回 bot 发送的最后一条消息"""
    if not isinstance(event, GroupMessageEvent):
        await recall_cmd.finish("...这个命令只能在群里用哦。")
        return
    try:
        # 获取最近的消息列表，找到 bot 发送的最后一条
        msgs = await bot.get_group_msg_history(group_id=event.group_id, count=20)
        for msg in reversed(msgs):
            if str(msg.get("user_id", "")) == str(bot.self_id):
                await bot.delete_msg(message_id=msg["message_id"])
                try:
                    await recall_cmd.finish("已撤回~")
                except Exception:
                    pass
                return
        await recall_cmd.finish("...没有找到可以撤回的消息。")
    except Exception as e:
        logger.error(f"[撤回] 失败: {e}")
        await recall_cmd.finish("...撤回失败了。")

# 群管命令需要 Bot 参数，手动注册
_ban_cmd = on_command("禁言", priority=1)
@_ban_cmd.handle()
async def _ban_handler(event: MessageEvent, bot: Bot):
    from .config import ALLOWED_GROUPS
    gid = getattr(event, 'group_id', None)
    if gid and ALLOWED_GROUPS and gid not in ALLOWED_GROUPS:
        return
    if not check_superuser(str(event.user_id)):
        await _ban_cmd.finish("...你不是管理员。")
        return
    await _cmd_ban(event, bot)

_kick_cmd = on_command("踢", priority=1)
@_kick_cmd.handle()
async def _kick_handler(event: MessageEvent, bot: Bot):
    from .config import ALLOWED_GROUPS
    gid = getattr(event, 'group_id', None)
    if gid and ALLOWED_GROUPS and gid not in ALLOWED_GROUPS:
        return
    if not check_superuser(str(event.user_id)):
        await _kick_cmd.finish("...你不是管理员。")
        return
    await _cmd_kick(event, bot)

_recall_cmd = on_command("撤回", priority=1)
@_recall_cmd.handle()
async def _recall_handler(event: MessageEvent, bot: Bot):
    from .config import ALLOWED_GROUPS
    gid = getattr(event, 'group_id', None)
    if gid and ALLOWED_GROUPS and gid not in ALLOWED_GROUPS:
        return
    if not check_superuser(str(event.user_id)):
        await _recall_cmd.finish("...你不是管理员。")
        return
    await _cmd_recall(event, bot)

# 用于 _register 返回的占位（群管命令已手动注册）
ban_cmd = _ban_cmd
kick_cmd = _kick_cmd
recall_cmd = _recall_cmd
