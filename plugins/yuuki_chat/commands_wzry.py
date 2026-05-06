"""commands_wzry - 王者荣耀战绩查询模块"""

import asyncio
import time
import re

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _get_http_client

_WZRY_API = "https://apione.apibyte.cn/wzry"
_wzry_cooldown = {}  # {user_id: last_cmd_time}
_WZRY_CD = 10  # 10秒冷却


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _check_wzry_cooldown(user_id: str) -> bool:
    """检查王者命令冷却，返回 True 表示放行"""
    now = time.time()
    # 清理超过1小时的过期条目
    if len(_wzry_cooldown) > 500:
        expired = [k for k, v in _wzry_cooldown.items() if now - v > 3600]
        for k in expired:
            del _wzry_cooldown[k]
    last = _wzry_cooldown.get(user_id, 0)
    if now - last < _WZRY_CD:
        return False
    _wzry_cooldown[user_id] = now
    return True


async def _wzry_api(params: dict) -> dict:
    """调用王者API"""
    try:
        client = _get_http_client()
        resp = await client.get(_WZRY_API, params=params, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
        return {"code": -1, "msg": f"API返回状态码 {resp.status_code}"}
    except asyncio.TimeoutError:
        return {"code": -1, "msg": "查询超时，请稍后再试。"}
    except Exception as e:
        return {"code": -1, "msg": f"查询失败: {str(e)}"}


async def _cmd_wzry(event: MessageEvent):
    """搜索玩家：/王者 昵称 或 /wzry 昵称"""
    user_id = str(event.user_id)
    if not _check_wzry_cooldown(user_id):
        remaining = _WZRY_CD - (time.time() - _wzry_cooldown.get(user_id, 0))
        await _send(event, f"...王者查询冷却中，请{int(remaining)}秒后再试。")
        return

    content = str(event.message).strip()
    # 去掉开头的 /
    if content.startswith("/"):
        content = content[1:].strip()
    for prefix in ["王者", "wzry", "王者荣耀"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...搜谁。格式：/王者 昵称")
        return

    await _send(event, f"...正在搜索「{content}」")

    result = await _wzry_api({"action": "query", "name": content})

    if result.get("code") == -1:
        await _send(event, f"...查询失败: {result.get('msg', '未知错误')}")
        return

    data = result.get("data", {})
    players = data.get("players", [])

    if not players:
        await _send(event, f"...没找到「{content}」，换个名字试试？")
        return

    lines = [f"...找到 {data.get('total', len(players))} 个结果：\n"]
    for i, p in enumerate(players, 1):
        nickname = p.get("nickname", "未知")
        uid = p.get("uid", "未知")
        rank = p.get("rank", "未知")
        region = p.get("region", "")
        role_name = p.get("role_name", "")
        lines.append(f"{i}. {nickname}")
        lines.append(f"   UID: {uid}")
        if rank:
            lines.append(f"   段位: {rank}")
        if region:
            lines.append(f"   区服: {region}")
        if role_name:
            lines.append(f"   角色: {role_name}")
        lines.append("")

    text = "\n".join(lines).strip()
    # 限制长度
    if len(text) > 1500:
        text = text[:1500] + "\n...(结果过长，已截断)"
    await _send(event, text)


async def _cmd_wzry_profile(event: MessageEvent):
    """玩家资料：/王者资料 UID 或 /wzry资料 UID"""
    user_id = str(event.user_id)
    if not _check_wzry_cooldown(user_id):
        remaining = _WZRY_CD - (time.time() - _wzry_cooldown.get(user_id, 0))
        await _send(event, f"...王者查询冷却中，请{int(remaining)}秒后再试。")
        return

    content = str(event.message).strip()
    if content.startswith("/"):
        content = content[1:].strip()
    for prefix in ["王者资料", "wzry资料"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...查谁的资料。格式：/王者资料 UID")
        return

    uid = content.strip()
    await _send(event, f"...正在查询 UID: {uid} 的资料")

    result = await _wzry_api({"action": "user", "uid": uid})

    if result.get("code") == -1:
        await _send(event, f"...查询失败: {result.get('msg', '未知错误')}")
        return

    data = result.get("data", {})
    name = data.get("name", "未知")
    status = data.get("status", "")
    stats = data.get("stats", {})
    hero_list = data.get("hero_list", [])

    lines = [f"...【{name}】的王者资料"]
    lines.append(f"UID: {uid}")
    if status:
        lines.append(f"状态: {status}")
    lines.append("")

    # 总体数据
    if stats:
        lines.append("【总览】")
        for key, val in stats.items():
            lines.append(f"  {key}: {val}")
        lines.append("")

    # 英雄列表（按场次排序，取前10）
    if hero_list:
        # 按场次降序排序
        try:
            sorted_heroes = sorted(
                hero_list,
                key=lambda h: int(re.sub(r'[^\d]', '', h.get("场次", "0")) or "0"),
                reverse=True,
            )
        except (ValueError, TypeError):
            sorted_heroes = hero_list[:10]

        lines.append("【常用英雄 TOP10】")
        for i, hero in enumerate(sorted_heroes[:10], 1):
            h_name = hero.get("名称", "未知")
            h_games = hero.get("场次", "0")
            h_winrate = hero.get("胜率", "0%")
            h_power = hero.get("战力", "0")
            lines.append(f"  {i}. {h_name} | 场次:{h_games} | 胜率:{h_winrate} | 战力:{h_power}")
    else:
        lines.append("暂无英雄数据。")

    text = "\n".join(lines).strip()
    if len(text) > 1500:
        text = text[:1500] + "\n...(内容过长，已截断)"
    await _send(event, text)


async def _cmd_wzry_battle(event: MessageEvent):
    """战绩查询：/王者战绩 UID [模式] 或 /wzry战绩 UID [模式]"""
    user_id = str(event.user_id)
    if not _check_wzry_cooldown(user_id):
        remaining = _WZRY_CD - (time.time() - _wzry_cooldown.get(user_id, 0))
        await _send(event, f"...王者查询冷却中，请{int(remaining)}秒后再试。")
        return

    content = str(event.message).strip()
    if content.startswith("/"):
        content = content[1:].strip()
    for prefix in ["王者战绩", "wzry战绩"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...查谁的战绩。格式：/王者战绩 UID")
        return

    # 解析 UID 和可选的模式筛选
    parts = content.split(None, 1)
    uid = parts[0].strip()
    opt = parts[1].strip() if len(parts) > 1 else ""

    filter_desc = f"（筛选: {opt}）" if opt else ""
    await _send(event, f"...正在查询 UID: {uid} 的战绩{filter_desc}")

    params = {"action": "battle", "uid": uid}
    if opt:
        params["opt"] = opt

    result = await _wzry_api(params)

    if result.get("code") == -1:
        await _send(event, f"...查询失败: {result.get('msg', '未知错误')}")
        return

    data = result.get("data", {})
    name = data.get("name", "未知")
    battles = data.get("battles", [])

    if not battles:
        filter_msg = f"（{opt}模式）" if opt else ""
        await _send(event, f"...【{name}】暂无{filter_msg}战绩记录。")
        return

    lines = [f"...【{name}】最近战绩{filter_desc}\n"]

    # 最多显示10场
    display_battles = battles[:10]
    for i, b in enumerate(display_battles, 1):
        result_str = b.get("result", "未知")
        hero = b.get("hero", "未知")
        kda = b.get("kda", "-")
        score = b.get("score", "-")
        b_time = b.get("time", "-")
        mode = b.get("mode", "-")

        # 胜负标记
        mark = "[胜]" if result_str == "胜" else "[负]"

        lines.append(f"{i}. {mark} {hero} | KDA: {kda} | 评分: {score}")
        lines.append(f"   模式: {mode} | 时间: {b_time}")

    if len(battles) > 10:
        lines.append(f"\n...仅显示最近10场，共{len(battles)}场记录。")

    text = "\n".join(lines).strip()
    if len(text) > 1500:
        text = text[:1500] + "\n...(内容过长，已截断)"
    await _send(event, text)


# 注册命令
wzry_cmd = _register("王者", _cmd_wzry, aliases=["wzry", "王者荣耀"])
wzry_profile_cmd = _register("王者资料", _cmd_wzry_profile, aliases=["wzry资料"])
wzry_battle_cmd = _register("王者战绩", _cmd_wzry_battle, aliases=["wzry战绩"])
