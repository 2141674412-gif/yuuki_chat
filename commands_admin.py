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
from .commands_base import _register, check_superuser, _save_blacklist, user_blacklist, _DATA_DIR
from .config import load_persona, save_persona, PERSONA_FILE
from .chat import chat_history


# ========== 查看当前人设 ==========

async def _cmd_view_persona(event: MessageEvent):
    await view_persona_cmd.finish(f"当前人设：\n{load_persona()}")

view_persona_cmd = _register("查看人设", _cmd_view_persona, priority=1, admin_only=True)

# -- 修改人设 --

async def _cmd_set_persona(event: MessageEvent):
    new_persona = str(event.message).replace("修改人设", "").strip()

    if not new_persona:
        await set_persona_cmd.finish("...内容呢。格式：/修改人设 [内容]")

    try:
        save_persona(new_persona)
        chat_history.clear()
        await set_persona_cmd.finish("...知道了。人设已更新。")
    except OSError as e:
        await set_persona_cmd.finish(f"保存人设失败：{str(e)}")

set_persona_cmd = _register("修改人设", _cmd_set_persona, priority=1, admin_only=True)

# -- 重置人设 --

async def _cmd_reset_persona(event: MessageEvent):
    try:
        if os.path.exists(PERSONA_FILE):
            os.remove(PERSONA_FILE)
    except OSError as e:
        await reset_persona_cmd.finish(f"删除人设文件失败：{str(e)}")
        return

    chat_history.clear()
    await reset_persona_cmd.finish("人设已重置。")

reset_persona_cmd = _register("重置人设", _cmd_reset_persona, priority=1, admin_only=True)

# -- 重启 --

async def _cmd_restart(event: MessageEvent):
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
        await restart_cmd.finish(f"写入重启标记失败：{str(e)}")
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
        await restart_cmd.finish(f"重启失败：{str(e)}")

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
    # 只允许私聊使用
    if hasattr(event, 'group_id') and event.group_id:
        return
    content = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["加群", "addgroup", "add_group"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await add_group_cmd.finish("...群号呢。格式：/加群 群号")
        return
    try:
        gid = int(content)
    except ValueError:
        await add_group_cmd.finish("...群号格式不对。")
        return
    groups = _load_allowed_groups()
    if gid in groups:
        await add_group_cmd.finish(f"群 {gid} 已经在白名单里了。")
        return
    groups.append(gid)
    _save_allowed_groups(groups)
    # 更新运行时配置
    from .config import ALLOWED_GROUPS
    ALLOWED_GROUPS.clear()
    ALLOWED_GROUPS.extend(groups)
    await add_group_cmd.finish(f"[OK] 已添加群 {gid} 到白名单。当前白名单：{groups}")


async def _cmd_remove_group(event: MessageEvent):
    """从白名单移除群：/移群 群号"""
    if hasattr(event, 'group_id') and event.group_id:
        return
    content = str(event.message).strip()
    for prefix in ["移群", "delgroup", "del_group"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await remove_group_cmd.finish("...群号呢。格式：/移群 群号")
        return
    try:
        gid = int(content)
    except ValueError:
        await remove_group_cmd.finish("...群号格式不对。")
        return
    groups = _load_allowed_groups()
    if gid not in groups:
        await remove_group_cmd.finish(f"群 {gid} 不在白名单里。")
        return
    groups.remove(gid)
    _save_allowed_groups(groups)
    from .config import ALLOWED_GROUPS
    ALLOWED_GROUPS.clear()
    ALLOWED_GROUPS.extend(groups)
    await remove_group_cmd.finish(f"[OK] 已从白名单移除群 {gid}。当前白名单：{groups}")


async def _cmd_list_groups(event: MessageEvent):
    """查看白名单列表：/群列表"""
    if hasattr(event, 'group_id') and event.group_id:
        return
    groups = _load_allowed_groups()
    if not groups:
        await list_groups_cmd.finish("当前没有设置白名单，仅默认群可用。用 /加群 <群号> 添加。")
        return
    msg = "当前白名单群：\n"
    for i, gid in enumerate(groups, 1):
        msg += f"{i}. {gid}\n"
    await list_groups_cmd.finish(msg.strip())


add_group_cmd = _register("加群", _cmd_add_group, priority=1, admin_only=True)
remove_group_cmd = _register("移群", _cmd_remove_group, priority=1, admin_only=True)
list_groups_cmd = _register("群列表", _cmd_list_groups, priority=1, admin_only=True)

# -- 黑名单管理 --

async def _cmd_blacklist_add(event: MessageEvent):
    """拉黑用户：/拉黑 @某人 或 /拉黑 QQ号"""
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
        await blacklist_add_cmd.finish("...要拉黑谁？@Ta 或发QQ号。")
        return
    if check_superuser(target_id):
        await blacklist_add_cmd.finish("...不能拉黑管理员。")
        return

    user_blacklist.add(target_id)
    _save_blacklist()
    await blacklist_add_cmd.finish(f"[OK] 已拉黑 {target_id}")

blacklist_add_cmd = _register("拉黑", _cmd_blacklist_add, aliases=["加黑"], priority=1, admin_only=True)

async def _cmd_blacklist_remove(event: MessageEvent):
    """解除拉黑：/解黑 @某人 或 /解黑 QQ号"""
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
        await blacklist_remove_cmd.finish("...要解黑谁？@Ta 或发QQ号。")
        return

    if target_id in user_blacklist:
        user_blacklist.discard(target_id)
        _save_blacklist()
        await blacklist_remove_cmd.finish(f"[OK] 已解除拉黑 {target_id}")
    else:
        await blacklist_remove_cmd.finish(f"{target_id} 不在黑名单里。")

blacklist_remove_cmd = _register("解黑", _cmd_blacklist_remove, aliases=["移黑"], priority=1, admin_only=True)

async def _cmd_blacklist_list(event: MessageEvent):
    """查看黑名单：/黑名单"""
    if not user_blacklist:
        await blacklist_list_cmd.finish("黑名单为空。")
        return
    msg = f"黑名单（{len(user_blacklist)}人）\n"
    for uid in sorted(user_blacklist):
        msg += f"  {uid}\n"
    await blacklist_list_cmd.finish(msg.strip())

blacklist_list_cmd = _register("黑名单", _cmd_blacklist_list, priority=1, admin_only=True)

# -- 数据迁移 --

async def _cmd_migrate_data(event: MessageEvent):
    """手动迁移数据到新路径"""
    from .commands_base import _migrate_data
    _migrate_data()
    await migrate_cmd.finish(f"[OK] 数据迁移完成。\n当前数据目录: {_DATA_DIR}\n文件列表: {os.listdir(_DATA_DIR)}")

migrate_cmd = _register("迁移数据", _cmd_migrate_data, priority=1, admin_only=True)
