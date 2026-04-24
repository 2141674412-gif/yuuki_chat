"""commands_base - 基础模块

提供命令注册器、数据持久化、频率限制、黑名单等基础设施。
所有命令子模块都依赖此模块。
"""

# 标准库
import ast
import json
import logging
import os
import re
import secrets
import shutil
import time
from datetime import datetime

# 第三方库
from nonebot import on_command, get_driver, logger, get_bot
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException

# ---- 全局 HTTP 客户端（连接池复用） ----
from .utils import get_shared_http_client as _get_http_client

# 安全日志：脱敏敏感信息
class _SafeFormatter(logging.Formatter):
    """日志格式化器，自动脱敏敏感词"""
    _SENSITIVE_KEYS = ["token", "password", "密码", "friend_code", "好友码"]
    def format(self, record):
        msg = super().format(record)
        for key in self._SENSITIVE_KEYS:
            # 脱敏 key=value 或 key: value 模式
            msg = re.sub(
                rf'({key})["\s:=]+(["\']?)([^\s"\'\]}}]+)(["\']?)',
                rf'\1=\2***\4',
                msg,
                flags=re.IGNORECASE
            )
        return msg

# 设置日志脱敏
for _handler in logging.root.handlers:
    try:
        if hasattr(_handler, 'formatter') and _handler.formatter and hasattr(_handler.formatter, 'format_string'):
            _handler.setFormatter(_SafeFormatter(_handler.formatter.format_string))
    except Exception:
        pass

# ========== 路径常量 ==========

_DATA_DIR = os.path.join(os.getcwd(), "yuuki_data")
os.makedirs(_DATA_DIR, exist_ok=True)
CHECKIN_FILE = os.path.join(_DATA_DIR, "checkin_records.json")
REMINDERS_FILE = os.path.join(_DATA_DIR, "reminders.json")
POINTS_FILE = os.path.join(_DATA_DIR, "user_points.json")
BLACKLIST_FILE = os.path.join(_DATA_DIR, "user_blacklist.json")

# ========== superusers ==========

superusers = []
try:
    driver = get_driver()
    _su = driver.config.dict().get("superusers", [])
    if _su:
        superusers = [str(s) for s in _su]
except Exception as e:
    logger.warning(f"[superusers加载失败] {e}")

# 兜底：直接读环境变量
if not superusers:
    raw = os.getenv("superusers", "")
    if raw:
        raw = raw.strip()
        if raw.startswith("[") or raw.startswith("("):
            try:
                superusers = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                try:
                    superusers = json.loads(raw)
                except Exception:
                    pass
        else:
            superusers = [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]
        superusers = [str(s) for s in superusers]

logger.info(f"[启动] superusers={superusers}")

# ========== 频率限制（防刷屏） ==========

_rate_limit = {}  # {user_id: last_cmd_time}
_RATE_COOLDOWN = 3  # 每个用户3秒内只能触发一次非AI命令

def _check_rate_limit(user_id: str) -> bool:
    """检查频率限制，返回 True 表示放行"""
    now = time.time()
    # 清理超过1小时的过期条目，防止内存泄漏
    if len(_rate_limit) > 1000:
        expired = [k for k, v in _rate_limit.items() if now - v > 3600]
        for k in expired:
            del _rate_limit[k]
    last = _rate_limit.get(user_id, 0)
    if now - last < _RATE_COOLDOWN:
        return False
    _rate_limit[user_id] = now
    return True

# ========== 签到记录 & 提醒存储 ==========

checkin_records = {}
reminders = {}

# -- 积分数据 --

user_points = {}

# -- 个人黑名单 --

user_blacklist = set()

# ========== 持久化函数 ==========


def _load_json(filepath: str) -> dict:
    """从 JSON 文件加载数据，文件不存在或损坏时返回空字典。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_json(filepath: str, data: dict) -> None:
    """将数据保存到 JSON 文件。"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"[commands] 保存文件失败 {filepath}: {e}")


def _load_checkin_records() -> None:
    global checkin_records
    checkin_records = _load_json(CHECKIN_FILE)


def _save_checkin_records() -> None:
    _save_json(CHECKIN_FILE, checkin_records)


def _load_reminders() -> None:
    global reminders
    raw = _load_json(REMINDERS_FILE)
    for user_id, items in raw.items():
        for r in items:
            for key in ("time", "created"):
                if key in r and isinstance(r[key], str):
                    try:
                        r[key] = datetime.fromisoformat(r[key])
                    except (ValueError, TypeError):
                        pass
    reminders = raw


def _save_reminders() -> None:
    serializable = {}
    for user_id, items in reminders.items():
        serializable[user_id] = []
        for r in items:
            entry = dict(r)
            for key in ("time", "created"):
                if key in entry and isinstance(entry[key], datetime):
                    entry[key] = entry[key].isoformat()
            serializable[user_id].append(entry)
    _save_json(REMINDERS_FILE, serializable)


def _load_blacklist() -> None:
    global user_blacklist
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                user_blacklist = set(json.load(f))
        except (json.JSONDecodeError, OSError):
            user_blacklist = set()

def _save_blacklist() -> None:
    try:
        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(user_blacklist), f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"[黑名单] 保存失败: {e}")

def _load_points() -> None:
    global user_points
    user_points = _load_json(POINTS_FILE)

def _save_points() -> None:
    _save_json(POINTS_FILE, user_points)


_load_checkin_records()
_load_reminders()
_load_points()
_load_blacklist()

# ========== 数据迁移（旧路径 → 新路径） ==========

def _migrate_data():
    """启动时检查旧路径的数据文件，迁移到新路径（yuuki_data/）"""
    _plugin_dir = os.path.dirname(os.path.abspath(__file__))
    # 旧路径搜索顺序
    _old_dirs = [
        os.path.join(_plugin_dir, "data"),  # 插件目录下的 data（上一版）
        _plugin_dir,  # 插件根目录（旧版）
        os.path.join(os.path.dirname(_plugin_dir), "yuuki_data"),  # 上级的 yuuki_data（更早版本）
    ]
    _data_files = [
        "checkin_records.json", "reminders.json", "user_points.json",
        "allowed_groups.json", "user_blacklist.json", "persona.txt",
        "maimai_binds.json",
    ]
    for filename in _data_files:
        new_path = os.path.join(_DATA_DIR, filename)
        if os.path.exists(new_path):
            continue
        for old_dir in _old_dirs:
            old_path = os.path.join(old_dir, filename)
            if os.path.exists(old_path) and old_path != new_path:
                try:
                    shutil.copy2(old_path, new_path)
                    logger.info(f"[迁移] {filename}: {old_path} -> {new_path}")
                    break
                except Exception as e:
                    logger.error(f"[迁移] {filename} 失败: {e}")

_migrate_data()

# ========== 辅助函数 ==========


def check_superuser(user_id: str) -> bool:
    """检查用户是否为超级用户。"""
    return str(user_id) in superusers


# ========== 命令注册器 ==========


def _register(name, handler, aliases=None, priority=5, admin_only=False):
    """注册命令，可选别名、优先级和管理员限制。返回 matcher 对象。"""
    cmd = on_command(name, priority=priority)
    # 安全检查函数（主命令和别名共用）
    async def _safe_handler(event: MessageEvent):
        # 群白名单检查（默认不允许任何群，必须手动添加）
        from .config import ALLOWED_GROUPS
        if not ALLOWED_GROUPS:
            gid = getattr(event, 'group_id', None)
            if gid:
                return  # 没有配置白名单，所有群都不可用
        else:
            gid = getattr(event, 'group_id', None)
            if gid and gid not in ALLOWED_GROUPS:
                return  # 不在白名单群里，静默忽略
        if admin_only and not check_superuser(str(event.user_id)):
            await cmd.finish("...你不是管理员。")
            return
        # 黑名单检查（管理员不受限）
        if not check_superuser(str(event.user_id)) and str(event.user_id) in user_blacklist:
            return  # 黑名单用户，静默忽略
        # 频率限制（管理员不受限）
        if not admin_only and not _check_rate_limit(str(event.user_id)):
            return  # 冷却中，静默忽略
        await handler(event)

    if aliases:
        for a in aliases:
            cmd2 = on_command(a, priority=priority)
            @cmd2.handle()
            async def _alias_h(event: MessageEvent):
                await _safe_handler(event)
    @cmd.handle()
    async def _h(event: MessageEvent):
        await _safe_handler(event)
    return cmd
