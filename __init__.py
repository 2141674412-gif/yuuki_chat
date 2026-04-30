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

# === 启动时清理废弃文件 ===
_PLUGIN_DIR = _os.path.dirname(_os.path.abspath(__file__))
_DEPRECATED_FILES = ["onebot_client.py", "commands.py", "commands_bilibili.py"]
for _dep in _DEPRECATED_FILES:
    _dep_path = _os.path.join(_PLUGIN_DIR, _dep)
    if _os.path.isfile(_dep_path):
        try:
            _os.remove(_dep_path)
        except Exception:
            pass
# === 清理完毕 ===

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
from . import chat
from . import commands_base
from . import commands_fun
from . import commands_checkin
from . import commands_remind
from . import commands_calc
from . import commands_translate
from . import commands_search
from . import commands_weather
from . import commands_wordcloud
from . import commands_admin
from . import commands_group_admin
from . import commands_birthday
from . import commands_accounting
from . import commands_update
from . import commands_schedule
from . import commands_backup
from . import commands_vault
from . import commands_sticker
from . import commands_remote
from . import commands_diagnose
from . import commands_dongle
from . import commands_mqtt
from . import maimai as mai_cmd

# 启动时间（用于状态检查）
_start_time = time.time()

__all__ = ["chat", "mai_cmd"]

driver = get_driver()


@driver.on_shutdown
async def _shutdown():
    """关闭共享 HTTP 客户端"""
    try:
        from .chat import _save_user_profiles
        _save_user_profiles()
    except Exception:
        pass
    from .utils import shutdown_http_client
    await shutdown_http_client()
