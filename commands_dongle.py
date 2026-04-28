"""commands_dongle - 机台狗号查询模块

提供 /查机台 命令，用于查询舞萌DX和中二机台的狗号信息。
数据来源：dongle_data.json（需手动放置到 yuuki_data/ 目录下）
"""

import json
import os

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _DATA_DIR


# 数据文件路径
_DONGLE_FILE = os.path.join(_DATA_DIR, "dongle_data.json")

# 内存缓存
_dongle_cache = {"data": None, "mtime": 0}


def _load_dongle_data():
    """加载狗号数据，带文件修改时间缓存"""
    if not os.path.exists(_DONGLE_FILE):
        return None
    try:
        mtime = os.path.getmtime(_DONGLE_FILE)
        if _dongle_cache["mtime"] == mtime and _dongle_cache["data"] is not None:
            return _dongle_cache["data"]
        with open(_DONGLE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _dongle_cache["data"] = data
        _dongle_cache["mtime"] = mtime
        return data
    except Exception as e:
        logger.error(f"[查机台] 加载数据失败: {e}")
        return None


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _search(data_list, keyword):
    """在数据列表中搜索匹配的条目"""
    keyword_lower = keyword.lower()
    results = []
    for item in data_list:
        if keyword_lower in item["shop"].lower() or keyword_lower in item["province"].lower():
            results.append(item)
    return results


async def _cmd_dongle(event: MessageEvent):
    """查机台命令处理器"""
    content = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["查机台"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _send(event, "...想查什么？用法：/查机台 关键词\n  /查机台 舞萌 关键词\n  /查机台 中二 关键词")
        return

    # 加载数据
    data = _load_dongle_data()
    if data is None:
        await _send(event, "...机台数据文件不存在。请将 dongle_data.json 放到 yuuki_data/ 目录下。")
        return

    # 判断搜索范围
    search_maimai = True
    search_chunithm = True
    keyword = content

    if content.startswith("舞萌") or content.startswith("maimai") or content.startswith("mai"):
        search_chunithm = False
        keyword = content[2:].strip()
        if not keyword:
            await _send(event, "...告诉我店名或地区。用法：/查机台 舞萌 关键词")
            return
    elif content.startswith("中二") or content.startswith("chunithm") or content.startswith("chuni"):
        search_maimai = False
        keyword = content[2:].strip()
        if not keyword:
            await _send(event, "...告诉我店名或地区。用法：/查机台 中二 关键词")
            return

    # 执行搜索
    results = []
    if search_maimai:
        results.extend(_search(data.get("maimai", []), keyword))
    if search_chunithm:
        results.extend(_search(data.get("chunithm", []), keyword))

    if not results:
        await _send(event, f"...没有找到包含「{keyword}」的机台。")
        return

    # 限制结果数量
    if len(results) > 20:
        results = results[:20]
        results.append(None)  # 标记截断

    # 构建输出
    lines = [f"【机台查询「{keyword}」】共找到 {len(results) - (1 if results[-1] is None else 0)} 条结果："]
    lines.append("")

    for item in results:
        if item is None:
            lines.append(f"...结果太多，只显示前20条。")
            break
        lines.append(f"  {item['id']}  {item['shop']}（{item['province']}）")

    await _send(event, "\n".join(lines))


dongle_cmd = _register("查机台", _cmd_dongle, admin_only=True)
