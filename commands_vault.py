# ========== 密码保险箱（仅私聊，加密存储） ==========

# 标准库
import base64
import hashlib
import hmac
import json
import os
import secrets

# 第三方库
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

# 从子模块导入
from .commands_base import _register, _load_json, _save_json, _DATA_DIR


VAULT_FILE = os.path.join(_DATA_DIR, "vault.enc")

_vault_cache = None  # 进程级缓存，避免重复IO
_vault_cache_mtime = 0  # 文件修改时间，用于失效检查


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _load_vault():
    """加载加密的保险箱数据（带进程级缓存）"""
    global _vault_cache, _vault_cache_mtime
    # 检查文件是否被修改
    try:
        mtime = os.path.getmtime(VAULT_FILE) if os.path.exists(VAULT_FILE) else 0
        if _vault_cache is not None and mtime == _vault_cache_mtime:
            return _vault_cache
    except OSError:
        pass

    if not os.path.exists(VAULT_FILE):
        _vault_cache = {}
        _vault_cache_mtime = 0
        return {}
    try:
        with open(VAULT_FILE, "r", encoding="utf-8") as f:
            _vault_cache = json.load(f)
            _vault_cache_mtime = os.path.getmtime(VAULT_FILE)
            return _vault_cache
    except Exception:
        _vault_cache = {}
        return {}

def _save_vault(data):
    """保存保险箱数据（同时更新缓存）"""
    global _vault_cache, _vault_cache_mtime
    _save_json(VAULT_FILE, data)
    _vault_cache = data
    try:
        _vault_cache_mtime = os.path.getmtime(VAULT_FILE)
    except OSError:
        _vault_cache_mtime = 0

def _derive_key(password, salt):
    """从密码派生加密密钥（PBKDF2-HMAC-SHA256）"""
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000, dklen=32)
    return key

def _hash_password(password):
    """用 scrypt 哈希密码（带随机盐），返回 salt+hash 的 base64"""
    salt = secrets.token_bytes(16)
    pw_hash = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
    )
    return base64.b64encode(salt + pw_hash).decode("ascii")

def _encrypt(text, password):
    """用 AES-256-GCM 加密文本，返回 base64 编码的密文"""
    salt = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    nonce = secrets.token_bytes(12)  # GCM 推荐 96-bit nonce
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, text.encode("utf-8"), None)
    return base64.b64encode(salt + nonce + ciphertext).decode("ascii")

def _decrypt(encoded, password):
    """用 AES-256-GCM 解密文本，失败返回 None"""
    try:
        raw = base64.b64decode(encoded)
        salt = raw[:16]
        nonce = raw[16:28]
        ciphertext = raw[28:]
        key = _derive_key(password, salt)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception:
        return None

def _get_user_password(user_id):
    """获取用户设置的保险箱密码"""
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    return user_data.get("_password_hash", None)

def _verify_password(user_id, password):
    """验证保险箱密码（scrypt 哈希验证）"""
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    pw_stored = user_data.get("_password_hash")
    if not pw_stored:
        return False
    # 兼容旧版 SHA-256 哈希（无盐，64字符hex）
    if len(pw_stored) == 64 and all(c in "0123456789abcdef" for c in pw_stored):
        return hmac.compare_digest(pw_stored, hashlib.sha256(password.encode("utf-8")).hexdigest())
    # 新版 scrypt 哈希（base64 编码的 salt+hash）
    try:
        raw = base64.b64decode(pw_stored)
        salt = raw[:16]
        stored_hash = raw[16:]
        computed = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(stored_hash, computed)
    except Exception:
        return False

def _require_password(user_id, password):
    """检查是否需要密码，返回 (ok, error_msg)"""
    if _get_user_password(user_id) is None:
        return False, "请先设置保险箱密码：/设置密码 你的密码"
    if not _verify_password(user_id, password):
        return False, "密码错误。"
    return True, ""


def _get_user_custom_key(user_id):
    """获取用户设置的自定义密钥"""
    vault = _load_vault()
    keys_data = vault.get("_keys", {})
    return keys_data.get(user_id)


def _set_user_custom_key(user_id, key_value):
    """设置用户自定义密钥"""
    vault = _load_vault()
    if "_keys" not in vault:
        vault["_keys"] = {}
    vault["_keys"][user_id] = key_value
    _save_vault(vault)


def _resolve_vault_password(user_id, cmd_password):
    """解析保险箱密码：优先使用用户自定义密钥，否则使用命令中提供的密码"""
    custom_key = _get_user_custom_key(user_id)
    if custom_key:
        return custom_key
    return cmd_password


def _parse_vault_args(user_id: str, content: str) -> tuple:
    """解析保险箱命令参数，返回 (name, password, error_msg)
    格式：名称|密码 或 名称（使用自定义密钥）
    """
    custom_key = _get_user_custom_key(user_id)
    pipe_idx = content.find("|")
    if pipe_idx == -1:
        if custom_key:
            name = content.strip()
            return (name, custom_key, None)
        else:
            return (None, None, "...请设置密钥后再使用简写格式。用法：/存 名称|密码 内容")
    else:
        name = content[:pipe_idx].strip()
        pw = content[pipe_idx+1:].strip()
        pw = _resolve_vault_password(user_id, pw)
        return (name, pw, None)


async def _cmd_vault_setpw(event: MessageEvent):
    """设置保险箱密码：/设置密码 xxx"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["设置密码", "设密码"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...密码呢。格式：/设置密码 你的密码")
        return
    if len(content) < 4:
        await _send(event, "...密码太短了，至少4位。")
        return
    user_id = str(event.user_id)
    vault = _load_vault()
    if user_id not in vault:
        vault[user_id] = {}
    if vault[user_id].get("_password_hash"):
        await _send(event, "你已经设置过密码了。如需修改请先 /修改密码")
        return
    vault[user_id]["_password_hash"] = _hash_password(content)
    _save_vault(vault)
    await _send(event, "[OK] 保险箱密码设置成功。\n现在可以用 /存 /取 /删密 了。\n格式：/存 密码名|密码 内容")


async def _cmd_vault_setkey(event: MessageEvent):
    """设置保险箱自定义密钥：/设置密钥 我的密码"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["设置密钥", "设密钥"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...密钥呢。格式：/设置密钥 你的密钥")
        return
    if len(content) < 4:
        await _send(event, "...密钥太短了，至少4位。")
        return
    user_id = str(event.user_id)
    # 验证旧密钥（第一次设置用默认密码验证）
    existing_key = _get_user_custom_key(user_id)
    if existing_key is not None:
        # 已有自定义密钥，需要验证旧密钥
        await _send(event, "你已经设置过密钥了。如需更换，请先 /删除密钥 后重新设置。")
        return
    # 第一次设置，需要验证默认密码
    if _get_user_password(user_id) is None:
        await _send(event, "请先设置保险箱密码：/设置密码 你的密码")
        return
    _set_user_custom_key(user_id, content)
    await _send(event, "[OK] 自定义密钥设置成功。\n以后存/取/删密时会自动使用此密钥，无需每次输入。")


async def _cmd_vault_changepw(event: MessageEvent):
    """修改保险箱密码：/修改密码 旧密码 新密码"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["修改密码", "改密码"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/修改密码 旧密码 新密码")
        return
    parts = content.split(None, 1)
    if len(parts) < 2:
        await _send(event, "...格式：/修改密码 旧密码 新密码")
        return
    old_pw, new_pw = parts[0], parts[1]
    if len(new_pw) < 4:
        await _send(event, "...新密码太短了，至少4位。")
        return
    user_id = str(event.user_id)
    # 如果设置了自定义密钥，不允许直接修改密码（会导致数据锁死）
    if _get_user_custom_key(user_id) is not None:
        await _send(event, "...你设置了自定义密钥，无法直接修改密码。\n请先删除密钥：/设置密钥（不推荐），或联系管理员。")
        return
    ok, err = _require_password(user_id, old_pw)
    if not ok:
        await _send(event, err)
        return
    # 用新密码重新加密所有条目
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    # 获取实际使用的加密密码（可能是自定义密钥）
    actual_pw = _resolve_vault_password(user_id, old_pw)
    for key_name in list(user_data.keys()):
        if key_name.startswith("_"):
            continue
        old_encrypted = user_data[key_name]
        decrypted = _decrypt(old_encrypted, actual_pw)
        if decrypted is not None:
            user_data[key_name] = _encrypt(decrypted, new_pw)
    user_data["_password_hash"] = _hash_password(new_pw)
    vault[user_id] = user_data
    _save_vault(vault)
    await _send(event, "[OK] 密码修改成功，所有数据已重新加密。")


async def _cmd_vault_save(event: MessageEvent):
    """存密码：/存 密码名|密码 内容 或 /存 密码名 内容（使用自定义密钥）"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["存密码", "存密"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if content.startswith("存"):
        content = content[1:].strip()
    if not content:
        await _send(event, "...格式：/存 密码名|密码 内容\n或：/存 密码名 内容（需先设置密钥）")
        return
    user_id = str(event.user_id)
    name, pw, err = _parse_vault_args(user_id, content)
    if err:
        await _send(event, err)
        return
    # 提取要保存的内容（去掉名称和密码部分）
    pipe_idx = content.find("|")
    if pipe_idx == -1:
        parts = content.split(None, 1)
        value_part = parts[1] if len(parts) >= 2 else ""
    else:
        after_pipe = content[pipe_idx+1:].strip()
        # 密码是|后第一个token，内容是剩余部分
        parts = after_pipe.split(None, 1)
        pw_len = len(parts[0]) if parts else 0
        value_part = parts[1] if len(parts) >= 2 else ""
    if not name or not value_part:
        await _send(event, "...格式不对。/存 密码名|密码 内容")
        return
    ok, err = _require_password(user_id, pw)
    if not ok:
        await _send(event, err)
        return
    vault = _load_vault()
    if user_id not in vault:
        vault[user_id] = {}
    vault[user_id][name] = _encrypt(value_part, pw)
    _save_vault(vault)
    await _send(event, f"已保存「{name}」。")


async def _cmd_vault_get(event: MessageEvent):
    """取密码：/取 密码名|密码 或 /取 密码名（使用自定义密钥）"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["取密码", "取密"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if content.startswith("取"):
        content = content[1:].strip()
    if not content:
        await _send(event, "...格式：/取 密码名|密码\n或：/取 密码名（需先设置密钥）")
        return
    user_id = str(event.user_id)
    name, pw, err = _parse_vault_args(user_id, content)
    if err:
        await _send(event, err)
        return
    if not name:
        await _send(event, "...格式不对。/取 密码名|密码")
        return
    ok, err = _require_password(user_id, pw)
    if not ok:
        await _send(event, err)
        return
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    encrypted = user_data.get(name)
    if not encrypted:
        await _send(event, f"没有叫「{name}」的记录。")
        return
    value = _decrypt(encrypted, pw)
    if value is None:
        await _send(event, "解密失败，可能是密码不对或数据损坏。")
        return
    await _send(event, f"【{name}】\n{value}")


async def _cmd_vault_delete(event: MessageEvent):
    """删密码：/删密 密码名|密码 或 /删密 密码名（使用自定义密钥）"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["删密码", "删除密码"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if content.startswith("删密"):
        content = content[3:].strip()
    if not content:
        await _send(event, "...格式：/删密 密码名|密码\n或：/删密 密码名（需先设置密钥）")
        return
    user_id = str(event.user_id)
    name, pw, err = _parse_vault_args(user_id, content)
    if err:
        await _send(event, err)
        return
    if not name:
        await _send(event, "...格式不对。/删密 密码名|密码")
        return
    ok, err = _require_password(user_id, pw)
    if not ok:
        await _send(event, err)
        return
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    if name not in user_data:
        await _send(event, f"没有叫「{name}」的记录。")
        return
    del vault[user_id][name]
    if not vault[user_id]:
        del vault[user_id]
    _save_vault(vault)
    await _send(event, f"已删除「{name}」。")


async def _cmd_vault_list(event: MessageEvent):
    """密码列表：/密码列表 密码 或 /密码列表（使用自定义密钥）"""
    if hasattr(event, 'group_id') and event.group_id:
        await _send(event, "...这个只能私聊用。")
        return
    content = str(event.message).strip()
    for prefix in ["密码列表"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    user_id = str(event.user_id)
    custom_key = _get_user_custom_key(user_id)
    if not content:
        # 没有提供密码，尝试使用自定义密钥
        if custom_key:
            pw = custom_key
        else:
            await _send(event, "...格式：/密码列表 你的密码\n或先 /设置密钥 设置自定义密钥")
            return
    else:
        pw = _resolve_vault_password(user_id, content.strip())
    ok, err = _require_password(user_id, pw)
    if not ok:
        await _send(event, err)
        return
    vault = _load_vault()
    user_data = vault.get(user_id, {})
    items = {k: v for k, v in user_data.items() if not k.startswith("_")}
    if not items:
        await _send(event, "你还没有存过任何密码。")
        return
    msg = "你的密码列表：\n"
    for i, name in enumerate(items.keys(), 1):
        msg += f"{i}. {name}\n"
    await _send(event, msg.strip())


vault_setpw_cmd = _register("设置密码", _cmd_vault_setpw, priority=1)
vault_setkey_cmd = _register("设置密钥", _cmd_vault_setkey, priority=1)
vault_changepw_cmd = _register("修改密码", _cmd_vault_changepw, priority=1)
vault_save_cmd = _register("存", _cmd_vault_save, priority=1)
vault_get_cmd = _register("取", _cmd_vault_get, priority=1)
vault_del_cmd = _register("删密", _cmd_vault_delete, priority=1)
vault_list_cmd = _register("密码列表", _cmd_vault_list, priority=1)
