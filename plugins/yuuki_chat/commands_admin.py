# ========== 管理员命令 ==========

# 标准库
import json
import os
import re
import subprocess
import sys

# 第三方库
from nonebot.adapters.onebot.v11 import MessageEvent

# 从子模块导入
from .commands_base import _register, check_superuser, check_admin, check_owner, _save_blacklist, user_blacklist, admins, _save_admins, superusers, _DATA_DIR, send_msg as _send
from .config import load_persona, save_persona, PERSONA_FILE
from .chat import chat_history


# ========== 查看当前人设 ==========



async def _cmd_view_persona(event: MessageEvent):
    await _send(event, f"当前人设：\n{load_persona()}")

view_persona_cmd = _register("查看人设", _cmd_view_persona, priority=1, admin_only=True)

# -- 修改人设 --

async def _cmd_set_persona(event: MessageEvent):
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能修改人设。")
        return
    new_persona = str(event.message).replace("修改人设", "").strip()

    if not new_persona:
        await _send(event, "...内容呢。格式：/修改人设 [内容]")
        return

    try:
        save_persona(new_persona)
        new_system = {"role": "system", "content": new_persona}
        for uid in chat_history:
            if chat_history[uid] and chat_history[uid][0].get("role") == "system":
                chat_history[uid][0] = new_system
            else:
                chat_history[uid].insert(0, new_system)
        await _send(event, "...知道了。人设已更新。")
    except OSError as e:
        await _send(event, f"保存人设失败：{str(e)}")

set_persona_cmd = _register("修改人设", _cmd_set_persona, priority=1, admin_only=True)

# -- 重置人设 --

async def _cmd_reset_persona(event: MessageEvent):
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能重置人设。")
        return
    try:
        if os.path.exists(PERSONA_FILE):
            os.remove(PERSONA_FILE)
    except OSError as e:
        await _send(event, f"删除人设文件失败：{str(e)}")
        return

    chat_history.clear()
    await _send(event, "人设已重置。")

reset_persona_cmd = _register("重置人设", _cmd_reset_persona, priority=1, admin_only=True)

# -- 重启 --

async def _cmd_restart(event: MessageEvent):
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能重启。")
        return
    user_id = str(event.user_id)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 插件在 plugins/yuuki_chat/ 下，回两级到项目根目录
    project_dir = os.path.normpath(os.path.join(current_dir, '..', '..'))
    restart_file = os.path.join(project_dir, 'restart_flag.txt')
    restart_data = {'user_id': user_id}

    if hasattr(event, 'group_id') and event.group_id:
        restart_data['group_id'] = str(event.group_id)

    try:
        with open(restart_file, 'w', encoding='utf-8') as f:
            json.dump(restart_data, f)
    except OSError as e:
        await _send(event, f"写入重启标记失败：{str(e)}")
        return

    try:
        bot_path = os.path.join(project_dir, 'bot.py')
        if sys.platform == 'win32':
            subprocess.Popen([sys.executable, bot_path], creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=project_dir)
        else:
            subprocess.Popen([sys.executable, bot_path], cwd=project_dir)
        # 刷新所有文件缓冲区后退出
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    except OSError as e:
        await _send(event, f"重启失败：{str(e)}")

restart_cmd = _register("重启", _cmd_restart, priority=1, admin_only=True)


# ========== 群白名单管理（仅私聊） ==========

def _get_allowed_groups_file():
    """获取白名单配置文件路径"""
    project_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    return os.path.join(project_dir, 'allowed_groups.json')


def _load_allowed_groups():
    """读取白名单列表"""
    fpath = _get_allowed_groups_file()
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # 从环境变量读取
    from .config import ALLOWED_GROUPS
    return list(ALLOWED_GROUPS)


def _save_allowed_groups(groups):
    """保存白名单列表"""
    fpath = _get_allowed_groups_file()
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(groups, f, ensure_ascii=False, indent=2)
    except OSError as e:
        from nonebot import logger
        logger.warning(f"[白名单] 保存失败: {e}")


async def _cmd_add_group(event: MessageEvent):
    """添加群到白名单：/加群 群号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能加群。")
        return
    # 只允许私聊使用
    if hasattr(event, 'group_id') and event.group_id:
        return
    content = str(event.message).strip()
    # 先清理CQ码残留
    content = re.sub(r'\[CQ:[^\]]+\]', '', content).strip()
    # 去掉命令前缀
    for prefix in ["加群", "addgroup", "add_group"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...群号呢。格式：/加群 群号")
        return
    try:
        gid = int(content)
    except ValueError:
        await _send(event, "...群号格式不对。")
        return
    groups = _load_allowed_groups()
    if gid in groups:
        await _send(event, f"群 {gid} 已经在白名单里了。")
        return
    groups.append(gid)
    _save_allowed_groups(groups)
    # 更新运行时配置
    from .config import ALLOWED_GROUPS
    ALLOWED_GROUPS.clear()
    ALLOWED_GROUPS.extend(groups)
    await _send(event, f"[OK] 已添加群 {gid} 到白名单。当前白名单：{groups}")


async def _cmd_remove_group(event: MessageEvent):
    """从白名单移除群：/移群 群号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能移群。")
        return
    if hasattr(event, 'group_id') and event.group_id:
        return
    content = str(event.message).strip()
    # 先清理CQ码残留
    content = re.sub(r'\[CQ:[^\]]+\]', '', content).strip()
    for prefix in ["移群", "delgroup", "del_group"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...群号呢。格式：/移群 群号")
        return
    try:
        gid = int(content)
    except ValueError:
        await _send(event, "...群号格式不对。")
        return
    groups = _load_allowed_groups()
    if gid not in groups:
        await _send(event, f"群 {gid} 不在白名单里。")
        return
    groups.remove(gid)
    _save_allowed_groups(groups)
    from .config import ALLOWED_GROUPS
    ALLOWED_GROUPS.clear()
    ALLOWED_GROUPS.extend(groups)
    await _send(event, f"[OK] 已从白名单移除群 {gid}。当前白名单：{groups}")


async def _cmd_list_groups(event: MessageEvent):
    """查看白名单列表：/群列表"""
    if hasattr(event, 'group_id') and event.group_id:
        return
    groups = _load_allowed_groups()
    if not groups:
        await _send(event, "当前没有设置白名单，仅默认群可用。用 /加群 <群号> 添加。")
        return
    msg = "当前白名单群：\n"
    for i, gid in enumerate(groups, 1):
        msg += f"{i}. {gid}\n"
    await _send(event, msg.strip())


add_group_cmd = _register("加群", _cmd_add_group, priority=1, admin_only=True)
remove_group_cmd = _register("移群", _cmd_remove_group, priority=1, admin_only=True)
list_groups_cmd = _register("群列表", _cmd_list_groups, priority=1, admin_only=True)

# -- 黑名单管理 --

async def _cmd_blacklist_add(event: MessageEvent):
    """拉黑用户：/拉黑 @某人 或 /拉黑 QQ号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能拉黑。")
        return
    content = str(event.message).strip()
    for prefix in ["拉黑", "/拉黑", "加黑", "/加黑"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    # 提取QQ号（支持@和纯数字）
    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq", ""))
            break
    if not target_id:
        # 尝试从文本提取数字
        m = re.search(r'\d{5,12}', content)
        if m:
            target_id = m.group()

    if not target_id:
        await _send(event, "...要拉黑谁？@Ta 或发QQ号。")
        return
    if check_superuser(target_id):
        await _send(event, "...不能拉黑管理员。")
        return

    user_blacklist.add(target_id)
    _save_blacklist()
    await _send(event, f"[OK] 已拉黑 {target_id}")

blacklist_add_cmd = _register("拉黑", _cmd_blacklist_add, aliases=["加黑"], priority=1, admin_only=True)

async def _cmd_blacklist_remove(event: MessageEvent):
    """解除拉黑：/解黑 @某人 或 /解黑 QQ号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能解黑。")
        return
    content = str(event.message).strip()
    for prefix in ["解黑", "/解黑", "移黑", "/移黑"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    target_id = None
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data.get("qq", ""))
            break
    if not target_id:
        # 尝试从文本提取数字
        m = re.search(r'\d{5,12}', content)
        if m:
            target_id = m.group()

    if not target_id:
        await _send(event, "...要解黑谁？@Ta 或发QQ号。")
        return

    if target_id in user_blacklist:
        user_blacklist.discard(target_id)
        _save_blacklist()
        await _send(event, f"[OK] 已解除拉黑 {target_id}")
    else:
        await _send(event, f"{target_id} 不在黑名单里。")

blacklist_remove_cmd = _register("解黑", _cmd_blacklist_remove, aliases=["移黑"], priority=1, admin_only=True)

async def _cmd_blacklist_list(event: MessageEvent):
    """查看黑名单：/黑名单"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能查看。")
        return
    if not user_blacklist:
        await _send(event, "黑名单为空。")
        return
    msg = f"黑名单（{len(user_blacklist)}人）\n"
    for uid in sorted(user_blacklist):
        msg += f"  {uid}\n"
    await _send(event, msg.strip())

blacklist_list_cmd = _register("黑名单", _cmd_blacklist_list, priority=1, admin_only=True)

# -- 数据迁移 --

async def _cmd_migrate_data(event: MessageEvent):
    """手动迁移数据到新路径"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能迁移数据。")
        return
    from .commands_base import _migrate_data
    _migrate_data()
    await _send(event, f"[OK] 数据迁移完成。\n当前数据目录: {_DATA_DIR}\n文件列表: {os.listdir(_DATA_DIR)}")

migrate_cmd = _register("迁移数据", _cmd_migrate_data, priority=1, admin_only=True)

# ========== 管理员管理（仅主人） ==========

async def _cmd_set_admin(event: MessageEvent):
    """设置管理员：/设管理 @某人 或 /设管理 QQ号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能设置管理员。")
        return
    content = str(event.message).strip()
    for prefix in ["设管理", "设置管理员", "添加管理员"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/设管理 @某人 或 /设管理 QQ号")
        return
    # Extract QQ number from @mention or plain number
    m = re.search(r'\[CQ:at,qq=(\d+)\]', content) or re.search(r'(\d{5,12})', content)
    if not m:
        await _send(event, "...无法识别QQ号。")
        return
    target = m.group(1)
    if target in superusers:
        await _send(event, "...这是主人，不需要设置。")
        return
    if target in admins:
        await _send(event, "...已经是管理员了。")
        return
    admins.append(target)
    _save_admins()
    await _send(event, f"...已设置 {target} 为管理员。")

async def _cmd_remove_admin(event: MessageEvent):
    """撤销管理员：/撤管理 @某人 或 /撤管理 QQ号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能撤销管理员。")
        return
    content = str(event.message).strip()
    for prefix in ["撤管理", "撤销管理员", "删除管理员"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/撤管理 @某人 或 /撤管理 QQ号")
        return
    m = re.search(r'\[CQ:at,qq=(\d+)\]', content) or re.search(r'(\d{5,12})', content)
    if not m:
        await _send(event, "...无法识别QQ号。")
        return
    target = m.group(1)
    if target in superusers:
        await _send(event, "...无法撤销主人的权限。")
        return
    if target not in admins:
        await _send(event, "...该用户不是管理员。")
        return
    admins.remove(target)
    _save_admins()
    await _send(event, f"...已撤销 {target} 的管理员权限。")

set_admin_cmd = _register("设管理", _cmd_set_admin, aliases=["设置管理员", "添加管理员"], admin_only=True)
remove_admin_cmd = _register("撤管理", _cmd_remove_admin, aliases=["撤销管理员", "删除管理员"], admin_only=True)

# ========== 私聊白名单管理 ==========

async def _cmd_add_private(event: MessageEvent):
    """添加私聊白名单：/加私聊 @某人 或 /加私聊 QQ号"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能设置。")
        return
    content = str(event.message).strip()
    for prefix in ["加私聊", "添加私聊"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/加私聊 @某人")
        return
    m = re.search(r'\[CQ:at,qq=(\d+)\]', content) or re.search(r'(\d{5,12})', content)
    if not m:
        await _send(event, "...无法识别QQ号。")
        return
    target = m.group(1)
    from .config import CHAT_WHITELIST, _save_chat_whitelist
    if target in CHAT_WHITELIST:
        await _send(event, "...已经在私聊白名单里了。")
        return
    CHAT_WHITELIST.append(target)
    _save_chat_whitelist()
    await _send(event, f"...已添加 {target} 到私聊白名单。")

async def _cmd_remove_private(event: MessageEvent):
    """移除私聊白名单：/撤私聊 @某人"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能设置。")
        return
    content = str(event.message).strip()
    for prefix in ["撤私聊", "移除私聊"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/撤私聊 @某人")
        return
    m = re.search(r'\[CQ:at,qq=(\d+)\]', content) or re.search(r'(\d{5,12})', content)
    if not m:
        await _send(event, "...无法识别QQ号。")
        return
    target = m.group(1)
    from .config import CHAT_WHITELIST, _save_chat_whitelist
    if target not in CHAT_WHITELIST:
        await _send(event, "...不在私聊白名单里。")
        return
    CHAT_WHITELIST.remove(target)
    _save_chat_whitelist()
    await _send(event, f"...已将 {target} 从私聊白名单移除。")

async def _cmd_list_private(event: MessageEvent):
    """查看私聊白名单：/私聊列表"""
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能查看。")
        return
    from .config import CHAT_WHITELIST
    if not CHAT_WHITELIST:
        await _send(event, "...私聊白名单为空。")
        return
    lines = ["【私聊白名单】"]
    for uid in CHAT_WHITELIST:
        lines.append(f"  {uid}")
    await _send(event, "\n".join(lines))

add_private_cmd = _register("加私聊", _cmd_add_private, aliases=["添加私聊"], admin_only=True)
remove_private_cmd = _register("撤私聊", _cmd_remove_private, aliases=["移除私聊"], admin_only=True)
list_private_cmd = _register("私聊列表", _cmd_list_private, aliases=["查看私聊"], admin_only=True)
