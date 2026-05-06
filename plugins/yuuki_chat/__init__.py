"""
yuuki_chat - 结城希亚 QQ Bot 插件
NoneBot2 插件，基于 Ollama 本地 AI 的聊天机器人

模块结构：
  config.py   - 配置常量、人设管理
  utils.py    - 工具函数（字体、绘图、封面下载）
  chat.py     - AI 聊天处理器
  commands_base.py       - 基础命令（帮助、状态等）
  commands_fun.py        - 娱乐命令（抽签等）
  commands_checkin.py    - 签到命令
  commands_remind.py     - 提醒命令
  commands_calc.py       - 计算命令
  commands_translate.py  - 翻译命令
  commands_search.py     - 搜索命令
  commands_weather.py    - 天气命令
  commands_wordcloud.py  - 词云命令
  commands_admin.py      - 管理员命令
  commands_group_admin.py - 群管理员命令
  commands_update.py     - 更新命令
  commands_schedule.py   - 定时任务命令
  commands_backup.py     - 备份命令
  commands_vault.py      - 保险箱命令
  maimai.py   - 舞萌DX查询（B50/B40/单曲）
"""

# === 启动时应用待处理的更新（Windows文件锁修复）===
import os as _os, json as _json, shutil as _shutil
_pending = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "_pending_update.json")
_pending = _os.path.normpath(_pending)
if _os.path.isfile(_pending):
    try:
        with open(_pending, "r") as _f:
            _info = _json.load(_f)
        _tmp = _info.get("tmp_dir", "")
        _files = _info.get("files", [])
        if _tmp and _os.path.isdir(_tmp):
            for _name, _target in _files:
                _src = _os.path.join(_tmp, _name)
                if _os.path.isfile(_src):
                    _os.makedirs(_os.path.dirname(_target), exist_ok=True)
                    _shutil.copy2(_src, _target)
            _shutil.rmtree(_tmp, ignore_errors=True)
        _os.remove(_pending)
    except Exception:
        try:
            _os.remove(_pending)
        except Exception:
            pass
# === 更新应用完毕 ===

# === 启动时清理废弃文件（异步执行）===
async def _cleanup_deprecated():
    _PLUGIN_DIR = _os.path.dirname(_os.path.abspath(__file__))
    _DEPRECATED_FILES = ["onebot_client.py", "commands.py", "commands_bilibili.py"]
    for _dep in _DEPRECATED_FILES:
        _dep_path = _os.path.join(_PLUGIN_DIR, _dep)
        if _os.path.isfile(_dep_path):
            try:
                _os.remove(_dep_path)
            except Exception:
                pass

import time

from nonebot import get_driver, logger
from .config import ALLOWED_GROUPS

# 过滤非白名单群的消息日志，减少终端噪音
def _filter_non_whitelist(record):
    msg = str(record["message"])
    if "群:" in msg and ALLOWED_GROUPS:
        import re as _re
        m = _re.search(r'群:(\d+)', msg)
        if m:
            gid = int(m.group(1))
            if gid not in ALLOWED_GROUPS:
                record["message"] = ""  # 清空消息内容
                return False
    return True

# patch loguru的默认handler，添加filter
import sys as _sys
try:
    _logger_core = logger._core
    for _h in _logger_core.handlers.values():
        if hasattr(_h, '_sink') and hasattr(_h._sink, '_stream') and _h._sink._stream is _sys.stderr:
            _h._filter = _filter_non_whitelist
            break
except Exception:
    pass

# ========== 延迟导入优化 ==========
# 不再在模块级别导入所有命令模块，改为按需导入
# 命令模块的实际导入放在 driver.on_startup 中异步执行

# 启动时间（用于状态检查）
_start_time = time.time()

__all__ = ["chat", "mai_cmd"]

driver = get_driver()

# 延迟导入的模块引用
_chat_module = None
_mai_cmd_module = None


def _get_chat_module():
    """延迟获取 chat 模块"""
    global _chat_module
    if _chat_module is None:
        from . import chat
        _chat_module = chat
    return _chat_module


def _get_mai_module():
    """延迟获取 maimai 模块"""
    global _mai_cmd_module
    if _mai_cmd_module is None:
        from . import maimai as mai_cmd
        _mai_cmd_module = mai_cmd
    return _mai_cmd_module


# 命令模块导入顺序（按优先级）
_command_modules = [
    "commands_base",
    "commands_fun",
    "commands_checkin",
    "commands_remind",
    "commands_calc",
    "commands_translate",
    "commands_search",
    "commands_weather",
    "commands_wordcloud",
    "commands_admin",
    "commands_group_admin",
    "commands_birthday",
    "commands_accounting",
    "commands_update",
    "commands_schedule",
    "commands_backup",
    "commands_vault",
    "commands_sticker",
    "commands_remote",
    "commands_diagnose",
    "commands_dongle",
    "commands_mqtt",
]


async def _import_commands():
    """异步导入所有命令模块，提升启动速度"""
    import importlib
    for module_name in _command_modules:
        try:
            importlib.import_module(f".{module_name}", __name__)
            logger.debug(f"[启动] 已导入 {module_name}")
        except Exception as e:
            logger.warning(f"[启动] 导入 {module_name} 失败: {e}")


@driver.on_startup
async def _startup():
    """异步启动初始化"""
    import asyncio
    
    # 并行执行初始化任务
    tasks = [
        _import_commands(),
        _cleanup_deprecated(),
    ]
    
    # 添加 chat 和 maimai 模块的初始化（异步预热）
    async def _warmup_modules():
        try:
            _get_chat_module()
            logger.debug("[启动] chat 模块已加载")
        except Exception as e:
            logger.warning(f"[启动] chat 模块加载失败: {e}")
        
        try:
            _get_mai_module()
            logger.debug("[启动] maimai 模块已加载")
        except Exception as e:
            logger.warning(f"[启动] maimai 模块加载失败: {e}")
    
    tasks.append(_warmup_modules())
    
    # 并行执行所有初始化任务
    await asyncio.gather(*tasks)
    
    # 启动排行榜服务（独立线程）
    _start_dashboard()


def _start_dashboard():
    """后台启动排行榜网页服务（可选功能，需要 dashboard 模块）"""
    import threading
    _PLUGIN_DIR = _os.path.dirname(_os.path.abspath(__file__))
    _dash_dir = _os.path.join(_PLUGIN_DIR, "dashboard")
    if not _os.path.isdir(_dash_dir):
        logger.debug("[排行榜] Dashboard 模块不存在，跳过启动")
        return
    try:
        from .dashboard.server import start_server
        _data_dir = _os.path.join(_os.getcwd(), "yuuki_data")

        def _run():
            try:
                start_server(_data_dir, _dash_dir, port=8080)
            except Exception as e:
                logger.warning(f"[排行榜] Dashboard运行出错: {e}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        logger.info("[排行榜] Dashboard 已启动: http://0.0.0.0:8080")
    except ImportError:
        logger.debug("[排行榜] Dashboard 模块不存在，跳过启动")
    except Exception as e:
        logger.warning(f"[排行榜] Dashboard启动失败: {e}")


@driver.on_shutdown
async def _shutdown():
    """关闭共享 HTTP 客户端"""
    try:
        chat_module = _get_chat_module()
        if chat_module and hasattr(chat_module, '_save_user_profiles'):
            chat_module._save_user_profiles()
    except Exception:
        pass
    try:
        from .utils import shutdown_http_client
        await shutdown_http_client()
    except Exception:
        pass
