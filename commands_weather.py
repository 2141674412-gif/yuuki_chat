# 天气查询模块

import time
from urllib.parse import quote

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _get_http_client


# 天气缓存（10分钟TTL）
_weather_cache: dict = {}  # {city: {"text": str, "time": float}}
_WEATHER_TTL = 600  # 10分钟缓存

async def _cmd_weather(event: MessageEvent):
    """天气查询：/天气 城市 或 /weather 城市"""
    content = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["天气", "weather"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await weather_cmd.finish("...要查哪个城市的天气？用法：/天气 城市")
        return
    city = content
    # 检查天气缓存
    if city in _weather_cache:
        _cached = _weather_cache[city]
        if time.time() - _cached["time"] < _WEATHER_TTL:
            await weather_cmd.finish(_cached["text"])
            return
    try:
        client = _get_http_client()
        resp = await client.get(
            f"https://wttr.in/{quote(city)}?format=j1",
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
        weather_text = f"【{city}天气】{desc} {temp}°C（体感{feels}°C） 湿度{humidity}% 风速{wind}km/h"
        # 更新缓存
        _weather_cache[city] = {"text": weather_text, "time": time.time()}
        await weather_cmd.finish(weather_text)
    except httpx.TimeoutException:
        await weather_cmd.finish("...天气查询超时了，换个时间试试。")
    except Exception as e:
        logger.error(f"[天气] 查询失败: {e}")
        await weather_cmd.finish("...天气查询失败了，稍后再试试吧。")

weather_cmd = _register("天气", _cmd_weather, aliases=["weather"])
