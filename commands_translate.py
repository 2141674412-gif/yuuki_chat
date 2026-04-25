# 翻译模块（多API备用）

import asyncio
import re
import time

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _get_http_client

_translate_cache = {}  # {f"{text}|{lang}": {"result": str, "time": float}}
_TRANSLATE_TTL = 300  # 5分钟


async def _translate_api1(text, target_lang):
    """MyMemory 翻译API"""
    client = _get_http_client()
    resp = await client.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": f"auto|{target_lang}"},
        timeout=10.0,
    )
    data = resp.json()
    if data.get("responseStatus") == 200:
        return data["responseData"]["translatedText"]
    return None


async def _translate_api2(text, target_lang):
    """LibreTranslate 翻译API"""
    client = _get_http_client()
    resp = await client.post(
        "https://libretranslate.de/translate",
        json={"q": text, "source": "auto", "target": target_lang, "format": "text"},
        timeout=10.0,
    )
    data = resp.json()
    if "translatedText" in data:
        return data["translatedText"]
    return None


async def _translate_api3(text, target_lang):
    """Lingva 翻译API（Google翻译前端）"""
    client = _get_http_client()
    resp = await client.get(f"https://lingva.ml/api/v1/auto/{target_lang}/{text}", timeout=10.0)
    data = resp.json()
    if "translation" in data:
        return data["translation"]
    return None


async def _cmd_translate(event: MessageEvent):
    content = str(event.message).replace("翻译", "", 1).strip().lstrip("/").strip()

    if not content:
        await translate_cmd.finish("翻译什么。说清楚。格式：/翻译 内容\n或 /翻译 en 内容")

    target_lang = "en"
    text_to_translate = content
    lang_match = re.match(r'^(zh|en|ja|ko|fr|de|ru|es|ar)\s+(.+)', content, re.IGNORECASE)
    if lang_match:
        target_lang = lang_match.group(1).lower()
        text_to_translate = lang_match.group(2).strip()

    if not lang_match:
        if re.search(r'[\u4e00-\u9fff]', content):
            target_lang = "en"
        else:
            target_lang = "zh"

    # 检查缓存
    _cache_key = f"{text_to_translate}|{target_lang}"
    if _cache_key in _translate_cache:
        _cached = _translate_cache[_cache_key]
        if time.time() - _cached["time"] < _TRANSLATE_TTL:
            await translate_cmd.finish(f"{text_to_translate}\n→ {_cached['result']}（缓存）")

    apis = [_translate_api1, _translate_api2, _translate_api3]

    # 并行请求所有翻译 API，取第一个成功的结果
    _timeout_hit = False

    def _save_to_cache(result_text):
        """将翻译结果存入缓存（上限50条，LRU淘汰）"""
        if len(_translate_cache) >= 50:
            # 淘汰最旧的条目
            oldest_key = min(_translate_cache, key=lambda k: _translate_cache[k]["time"])
            del _translate_cache[oldest_key]
        _translate_cache[_cache_key] = {"result": result_text, "time": time.time()}

    async def _safe_call(api_fn):
        nonlocal _timeout_hit
        try:
            return await api_fn(text_to_translate, target_lang)
        except httpx.TimeoutException:
            _timeout_hit = True
            logger.warning(f"[翻译API超时] {api_fn.__name__}")
            return None
        except Exception as e:
            logger.warning(f"[翻译API失败] {api_fn.__name__}: {e}")
            return None

    tasks = [asyncio.create_task(_safe_call(fn)) for fn in apis]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # 从已完成任务中找第一个成功结果
        for t in done:
            result = t.result()
            if result:
                # 取到结果，取消其他未完成任务
                for p in pending:
                    p.cancel()
                _save_to_cache(result)
                await translate_cmd.finish(f"{text_to_translate}\n→ {result}")
        # 第一个完成的没有结果，等待剩余任务
        if pending:
            done2, pending2 = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
            for t in done2:
                result = t.result()
                if result:
                    _save_to_cache(result)
                    await translate_cmd.finish(f"{text_to_translate}\n→ {result}")
    except Exception as e:
        logger.debug(f"[翻译] {e}")

    if _timeout_hit:
        await translate_cmd.finish("...翻译超时了，稍后再试。")
    else:
        await translate_cmd.finish("...翻译服务都连不上了。检查一下网络。")

translate_cmd = _register("翻译", _cmd_translate)
