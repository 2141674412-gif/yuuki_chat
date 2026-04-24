# 天气查询模块

import time
from urllib.parse import quote

import httpx
from nonebot import logger, get_bot
from nonebot.adapters.onebot.v11 import MessageEvent

from nonebot.exception import FinishedException

from .commands_base import _register, _get_http_client, _DATA_DIR, _load_json, _save_json
from .commands_schedule import _get_scheduler

import os

# 天气缓存（10分钟TTL）
_weather_cache: dict = {}  # {city: {"text": str, "time": float}}
_WEATHER_TTL = 600  # 10分钟缓存

# 天气绑定文件
_WEATHER_BINDS_FILE = os.path.join(_DATA_DIR, "weather_binds.json")
# 群绑定: {group_id: {"city": "北京", "hour": 8, "minute": 0}}
# 个人绑定: {user_id: {"city": "上海"}}

def _load_weather_binds() -> dict:
    return _load_json(_WEATHER_BINDS_FILE) or {}

def _save_weather_binds(binds: dict):
    _save_json(_WEATHER_BINDS_FILE, binds)

_weather_binds = _load_weather_binds()


def _get_user_weather_city(user_id: str) -> str:
    """获取个人绑定的天气城市"""
    bind = _weather_binds.get(user_id)
    if bind and isinstance(bind, dict) and "city" in bind:
        return bind["city"]
    return ""


async def _fetch_weather(client, city: str) -> str:
    """获取天气信息，返回格式化文本"""
    resp = await client.get(
        f"https://wttr.in/{quote(city)}?format=j1&lang=zh",
        headers={"User-Agent": "curl/7.68.0"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    current = data["current_condition"][0]
    temp = current["temp_C"]
    feels = current["FeelsLikeC"]
    desc = current.get("lang_zh", [{}])[0].get("value", current.get("weatherDesc", [{}])[0].get("value", "未知"))
    humidity = current["humidity"]
    wind = current["windspeedKmph"]
    visibility = current.get("visibility", "未知")
    uv_index = current.get("uvIndex", "未知")
    pressure = current.get("pressure", "未知")
    cloudcover = current.get("cloudcover", "未知")

    # 今日预报
    today = data.get("weather", [{}])[0]
    max_temp = today.get("maxtempC", "?")
    min_temp = today.get("mintempC", "?")
    hourly = today.get("hourly", [])

    # 构建逐时段预报（取几个关键时段）
    time_slots = []
    for h in hourly:
        hour = int(h.get("time", "0")) // 100
        if hour in (6, 9, 12, 15, 18, 21):
            h_desc = h.get("lang_zh", [{}])[0].get("value", h.get("weatherDesc", [{}])[0].get("value", ""))
            h_temp = h.get("tempC", "?")
            h_rain = h.get("chanceofrain", "0")
            h_humidity = h.get("humidity", "?")
            time_slots.append(f"{hour:02d}:00 {h_desc} {h_temp}°C 降雨{h_rain}% 湿度{h_humidity}%")

    # 降雨提醒
    rain_alert = ""
    for h in hourly[:8]:  # 未来几个时段
        rain_chance = int(h.get("chanceofrain", "0"))
        if rain_chance >= 60:
            hour = int(h.get("time", "0")) // 100
            rain_desc = h.get("lang_zh", [{}])[0].get("value", h.get("weatherDesc", [{}])[0].get("value", "有雨"))
            rain_alert = f"\n☔ {hour:02d}:00 降雨概率{rain_chance}%（{rain_desc}），记得带伞！"
            break

    lines = [
        f"【{city}天气】{desc}",
        f"🌡️ 温度：{temp}°C（体感{feels}°C）",
        f"📊 今日：{min_temp}°C ~ {max_temp}°C",
        f"💧 湿度：{humidity}%  ☁️ 云量：{cloudcover}%",
        f"🌬️ 风速：{wind}km/h  👁️ 能见度：{visibility}km",
        f"☀️ UV：{uv_index}  🌀 气压：{pressure}hPa",
    ]

    if time_slots:
        lines.append("─────── 逐时预报 ───────")
        lines.extend(time_slots)

    if rain_alert:
        lines.append(rain_alert)

    return "\n".join(lines)


async def _cmd_weather(event: MessageEvent):
    """天气查询：/天气 城市 或 /天气 省份 城市"""
    content = str(event.message).strip()
    for prefix in ["天气", "weather"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        # 没输入城市，检查个人绑定
        user_id = str(event.user_id)
        city = _get_user_weather_city(user_id)
        if not city:
            await weather_cmd.finish(
                "...要查哪个城市的天气？\n"
                "用法：/天气 深圳\n"
                "      /天气 广东深圳（同名城市加省份区分）\n"
                "      /我的天气 城市（绑定后直接/天气即可）"
            )
            return
    else:
        city = content

    # 检查天气缓存
    if city in _weather_cache:
        _cached = _weather_cache[city]
        if time.time() - _cached["time"] < _WEATHER_TTL:
            await weather_cmd.finish(_cached["text"])
            return

    try:
        client = _get_http_client()
        weather_text = await _fetch_weather(client, city)

        # 更新缓存（上限100条）
        if len(_weather_cache) > 100:
            oldest = min(_weather_cache, key=lambda k: _weather_cache[k]["time"])
            del _weather_cache[oldest]
        _weather_cache[city] = {"text": weather_text, "time": time.time()}
        await weather_cmd.finish(weather_text)
    except FinishedException:
        raise
    except httpx.TimeoutException:
        await weather_cmd.finish("...天气查询超时了，换个时间试试。")
    except httpx.HTTPStatusError as e:
        logger.error(f"[天气] HTTP错误: {e.response.status_code}")
        await weather_cmd.finish(f"...天气服务返回错误（HTTP {e.response.status_code}），换个城市名试试。")
    except Exception as e:
        logger.error(f"[天气] 查询失败: {e}")
        await weather_cmd.finish(f"...天气查询失败了：{type(e).__name__}，稍后再试。")


async def _cmd_weather_bind(event: MessageEvent):
    """绑定群天气：/绑定天气 城市 [时间]
    例：/绑定天气 北京 8:00  （每天8点播报北京天气）
    """
    content = str(event.message).strip()
    for prefix in ["绑定天气", "bindweather"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    gid = str(getattr(event, 'group_id', 0))
    if not gid:
        await weather_bind_cmd.finish("...只能在群里绑定天气。")
        return

    if not content:
        bind = _weather_binds.get(gid)
        if bind:
            h, m = bind.get("hour", 8), bind.get("minute", 0)
            await weather_bind_cmd.finish(
                f"...当前绑定：{bind['city']}，每天{h:02d}:{m:02d}播报\n"
                f"用法：/绑定天气 城市 时间（如：/绑定天气 北京 8:00）\n"
                f"      /解绑天气"
            )
        else:
            await weather_bind_cmd.finish(
                "...未绑定天气。\n"
                f"用法：/绑定天气 城市 时间（如：/绑定天气 北京 8:00）"
            )
        return

    if content in ("取消", "解绑", "删除"):
        if gid in _weather_binds:
            # 删除定时任务
            key = f"weather_{gid}"
            try:
                sched = _get_scheduler()
                if sched.get_job(key):
                    sched.remove_job(key)
            except Exception:
                pass
            del _weather_binds[gid]
            _save_weather_binds(_weather_binds)
            await weather_bind_cmd.finish("...已解绑天气播报。")
        else:
            await weather_bind_cmd.finish("...当前没有绑定天气。")
        return

    # 解析：城市 [时间]
    parts = content.split()
    city = parts[0]
    hour, minute = 8, 0

    if len(parts) >= 2:
        time_str = parts[1]
        if ":" in time_str:
            try:
                h_str, m_str = time_str.split(":")
                hour, minute = int(h_str), int(m_str)
            except ValueError:
                pass
        else:
            try:
                hour = int(time_str)
            except ValueError:
                pass

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        await weather_bind_cmd.finish("...时间格式不对，用 HH:MM 格式，如 8:00")
        return

    # 保存绑定
    _weather_binds[gid] = {"city": city, "hour": hour, "minute": minute}
    _save_weather_binds(_weather_binds)

    # 注册定时任务
    try:
        sched = _get_scheduler()
        key = f"weather_{gid}"
        sched.add_job(
            _send_weather_report,
            "cron",
            hour=hour,
            minute=minute,
            args=[gid],
            id=key,
            replace_existing=True,
        )
    except Exception as e:
        logger.warning(f"[天气] 注册定时任务失败: {e}")

    await weather_bind_cmd.finish(f"...已绑定：{city}，每天{hour:02d}:{minute:02d}播报天气。")


async def _cmd_weather_unbind(event: MessageEvent):
    """解绑天气"""
    content = str(event.message).strip()
    for prefix in ["解绑天气", "unbindweather"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    gid = str(getattr(event, 'group_id', 0))
    if gid in _weather_binds:
        key = f"weather_{gid}"
        try:
            sched = _get_scheduler()
            if sched.get_job(key):
                sched.remove_job(key)
        except Exception:
            pass
        del _weather_binds[gid]
        _save_weather_binds(_weather_binds)
        await weather_unbind_cmd.finish("...已解绑天气播报。")
    else:
        await weather_unbind_cmd.finish("...当前没有绑定天气。")


async def _send_weather_report(group_id: str):
    """定时发送天气播报"""
    bind = _weather_binds.get(group_id)
    if not bind:
        return

    city = bind["city"]
    try:
        client = _get_http_client()
        weather_text = await _fetch_weather(client, city)

        # 更新缓存
        _weather_cache[city] = {"text": weather_text, "time": time.time()}

        bot = get_bot()
        await bot.send_group_msg(
            group_id=int(group_id),
            message=f"🌅 早安天气播报\n{weather_text}"
        )
        logger.info(f"[天气] 已向群 {group_id} 播报 {city} 天气")
    except Exception as e:
        logger.error(f"[天气] 播报失败: {e}")


def _restore_weather_jobs():
    """启动时恢复天气定时任务"""
    for gid, bind in _weather_binds.items():
        try:
            sched = _get_scheduler()
            key = f"weather_{gid}"
            sched.add_job(
                _send_weather_report,
                "cron",
                hour=bind.get("hour", 8),
                minute=bind.get("minute", 0),
                args=[gid],
                id=key,
                replace_existing=True,
            )
            logger.info(f"[天气] 恢复定时播报: 群{gid} {bind['city']} {bind.get('hour',8):02d}:{bind.get('minute',0):02d}")
        except Exception as e:
            logger.warning(f"[天气] 恢复定时任务失败: {e}")


_restore_weather_jobs()

async def _cmd_my_weather(event: MessageEvent):
    """个人天气绑定：/我的天气 城市"""
    content = str(event.message).strip()
    for prefix in ["我的天气", "myweather", "setcity"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    user_id = str(event.user_id)

    if not content:
        city = _get_user_weather_city(user_id)
        if city:
            await my_weather_cmd.finish(f"...你绑定的城市是：{city}\n用法：/我的天气 城市（重新绑定）\n      /我的天气 取消")
        else:
            await my_weather_cmd.finish("...你还没绑定天气城市。\n用法：/我的天气 城市")
        return

    if content in ("取消", "删除", "清除"):
        if user_id in _weather_binds:
            del _weather_binds[user_id]
            _save_weather_binds(_weather_binds)
            await my_weather_cmd.finish("...已取消天气绑定。")
        else:
            await my_weather_cmd.finish("...你还没绑定天气城市。")
        return

    # 绑定
    _weather_binds[user_id] = {"city": content}
    _save_weather_binds(_weather_binds)
    await my_weather_cmd.finish(f"...已绑定天气城市：{content}\n以后直接发 /天气 就能查了。\n提示：同名城市可加省份，如 /我的天气 广东深圳")


weather_cmd = _register("天气", _cmd_weather, aliases=["weather"])
weather_bind_cmd = _register("绑定天气", _cmd_weather_bind, aliases=["bindweather"], admin_only=True)
weather_unbind_cmd = _register("解绑天气", _cmd_weather_unbind, aliases=["unbindweather"], admin_only=True)
my_weather_cmd = _register("我的天气", _cmd_my_weather, aliases=["myweather", "setcity"])
