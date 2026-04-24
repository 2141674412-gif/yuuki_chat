# ========== 群管功能（仅管理员） ==========

# 标准库
import re

# 第三方库
from nonebot import on_command, on_notice, on_message, logger
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


# ========== 自动欢迎 ==========

from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, GroupMessageEvent as _GME

_welcome_enabled = True  # 默认开启
_welcome_msg = "欢迎 {nickname} 加入本群~"

def _load_welcome_config():
    global _welcome_enabled, _welcome_msg
    try:
        from .commands_base import _DATA_DIR
        cfg_file = os.path.join(_DATA_DIR, "group_welcome.json") if 'os' in dir() else None
        if cfg_file and os.path.exists(cfg_file):
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                _welcome_enabled = cfg.get("enabled", True)
                _welcome_msg = cfg.get("message", _welcome_msg)
    except Exception:
        pass

import os
_load_welcome_config()

_welcome_notice = on_notice(priority=5)

@_welcome_notice.handle()
async def _on_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """新成员入群自动欢迎"""
    if not _welcome_enabled:
        return
    if event.sub_type != "approve":
        return
    # 不欢迎bot自己
    try:
        if event.user_id == bot.self_id:
            return
    except Exception:
        pass
    from .config import ALLOWED_GROUPS
    if event.group_id not in ALLOWED_GROUPS:
        return

    try:
        # 获取成员信息
        member_info = await bot.get_group_member_info(
            group_id=event.group_id, user_id=event.user_id
        )
        nickname = member_info.get("nickname", member_info.get("card", "新人"))
    except Exception:
        nickname = "新人"

    msg = _welcome_msg.replace("{nickname}", nickname).replace("{user_id}", str(event.user_id))
    try:
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    except Exception as e:
        logger.debug(f"[欢迎] 发送失败: {e}")


# ========== 关键词过滤 ==========

_filter_words = [
    # 违规/敏感词
    "赌博", "代练", "刷单", "色情", "约炮", "嫖娼",
    "毒品", "冰毒", "大麻", "海洛因",
    "诈骗", "杀猪盘", "洗钱",
    "枪支", "弹药", "炸弹", "炸药",
    "自杀", "自残", "割腕",
    "恐怖", "isis", "恐袭",
    # 广告/引流
    "加群领", "免费领", "扫码领", "点击领取",
    "兼职日结", "日赚", "月入过万", "躺赚",
    "代开发票", "开票", "增值税",
    "低价出售", "低价代购", "特价代购",
    "色诱", "裸聊", "网贷", "套路贷",
    "私服", "外挂", "辅助",
]  # ["关键词1", "关键词2", ...]
_filter_action = "warn"  # "warn"=仅警告, "delete"=撤回, "ban"=撤回+禁言10分钟

def _load_filter_config():
    global _filter_words, _filter_action
    try:
        from .commands_base import _DATA_DIR
        cfg_file = os.path.join(_DATA_DIR, "group_filter.json")
        if os.path.exists(cfg_file):
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                _filter_words = cfg.get("words", [])
                _filter_action = cfg.get("action", "warn")
    except Exception:
        pass

_load_filter_config()

_filter_notice = on_message(priority=5)

@_filter_notice.handle()
async def _on_keyword_filter(bot: Bot, event: _GME):
    """关键词过滤"""
    if not _filter_words:
        return
    from .config import ALLOWED_GROUPS
    from .commands_base import superusers
    gid = getattr(event, 'group_id', None)
    if not gid or gid not in ALLOWED_GROUPS:
        return
    # 管理员不受过滤
    if str(event.user_id) in superusers:
        return

    text = str(event.message).lower()
    for word in _filter_words:
        if word.lower() in text:
            if _filter_action in ("delete", "ban"):
                try:
                    await bot.delete_msg(message_id=event.message_id)
                except Exception:
                    pass
            if _filter_action == "ban":
                try:
                    await bot.set_group_ban(
                        group_id=gid, user_id=event.user_id, duration=600
                    )
                except Exception:
                    pass
            # 通知管理员
            try:
                await bot.send_group_msg(
                    group_id=gid,
                    message=f"[关键词过滤] 检测到违规内容，已处理。\n用户: {event.user_id} | 匹配: {word}"
                )
            except Exception:
                pass
            return


# ========== 群管配置命令 ==========

async def _cmd_set_welcome(event: MessageEvent):
    """设置欢迎语"""
    global _welcome_enabled, _welcome_msg
    content = str(event.message).strip()
    for prefix in ["设置欢迎", "setwelcome"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _set_welcome_cmd.finish(
            f"...当前欢迎语：{_welcome_msg}\n"
            f"状态：{'开启' if _welcome_enabled else '关闭'}\n"
            f"用法：/设置欢迎 欢迎内容（{{nickname}}代表新人昵称）\n"
            f"      /设置欢迎 开启/关闭"
        )
        return

    if content in ("开启", "on"):
        _welcome_enabled = True
        await _set_welcome_cmd.finish("...自动欢迎已开启。")
        return
    if content in ("关闭", "off"):
        _welcome_enabled = False
        await _set_welcome_cmd.finish("...自动欢迎已关闭。")
        return

    _welcome_msg = content
    # 保存配置
    try:
        from .commands_base import _DATA_DIR
        import json
        cfg_file = os.path.join(_DATA_DIR, "group_welcome.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"enabled": _welcome_enabled, "message": _welcome_msg}, f, ensure_ascii=False)
    except Exception:
        pass
    await _set_welcome_cmd.finish(f"...欢迎语已设置：{content}")


async def _cmd_add_filter(event: MessageEvent):
    """添加过滤关键词"""
    content = str(event.message).strip()
    for prefix in ["加过滤", "addfilter", "加屏蔽"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        status = "开启" if _filter_words else "关闭"
        words = "、".join(_filter_words[:10]) if _filter_words else "无"
        await _add_filter_cmd.finish(
            f"...关键词过滤：{status}（{_filter_action}）\n"
            f"当前词：{words}\n"
            f"用法：/加过滤 关键词\n"
            f"      /删过滤 关键词\n"
            f"      /过滤模式 warn/delete/ban"
        )
        return

    if content not in _filter_words:
        _filter_words.append(content)
    # 保存
    try:
        from .commands_base import _DATA_DIR
        import json
        cfg_file = os.path.join(_DATA_DIR, "group_filter.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"words": _filter_words, "action": _filter_action}, f, ensure_ascii=False)
    except Exception:
        pass
    await _add_filter_cmd.finish(f"...已添加过滤词：{content}（共{len(_filter_words)}个）")


async def _cmd_del_filter(event: MessageEvent):
    """删除过滤关键词"""
    content = str(event.message).strip()
    for prefix in ["删过滤", "delfilter", "删屏蔽"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _del_filter_cmd.finish("...删哪个？用法：/删过滤 关键词")
        return

    if content in _filter_words:
        _filter_words.remove(content)
    try:
        from .commands_base import _DATA_DIR
        import json
        cfg_file = os.path.join(_DATA_DIR, "group_filter.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"words": _filter_words, "action": _filter_action}, f, ensure_ascii=False)
    except Exception:
        pass
    await _del_filter_cmd.finish(f"...已删除过滤词：{content}（剩余{len(_filter_words)}个）")


async def _cmd_filter_mode(event: MessageEvent):
    """设置过滤模式"""
    global _filter_action
    content = str(event.message).strip()
    for prefix in ["过滤模式", "filtermode"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _filter_mode_cmd.finish(
            f"...当前模式：{_filter_action}\n"
            f"warn=仅通知 | delete=撤回 | ban=撤回+禁言10分钟\n"
            f"用法：/过滤模式 warn/delete/ban"
        )
        return

    if content in ("warn", "delete", "ban"):
        _filter_action = content
        try:
            from .commands_base import _DATA_DIR
            import json
            cfg_file = os.path.join(_DATA_DIR, "group_filter.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({"words": _filter_words, "action": _filter_action}, f, ensure_ascii=False)
        except Exception:
            pass
        mode_names = {"warn": "仅通知", "delete": "撤回", "ban": "撤回+禁言"}
        await _filter_mode_cmd.finish(f"...过滤模式已设为：{mode_names.get(content, content)}")
    else:
        await _filter_mode_cmd.finish("...无效模式，可选：warn/delete/ban")


from .commands_base import _register
_set_welcome_cmd = _register("设置欢迎", _cmd_set_welcome, aliases=["setwelcome"], admin_only=True)
_add_filter_cmd = _register("加过滤", _cmd_add_filter, aliases=["addfilter", "加屏蔽"], admin_only=True)
_del_filter_cmd = _register("删过滤", _cmd_del_filter, aliases=["delfilter", "删屏蔽"], admin_only=True)
_filter_mode_cmd = _register("过滤模式", _cmd_filter_mode, aliases=["filtermode"], admin_only=True)
