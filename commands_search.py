# 搜索模块（DuckDuckGo + Wikipedia + Bing + 图片搜索）

import asyncio
import re
import time

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

from .commands_base import _register, _get_http_client

# 搜索缓存（5分钟TTL）
_search_cache: dict = {}  # {query: {"results": list, "time": float}}
_SEARCH_TTL = 300


async def _search_ddg(query):
    """DuckDuckGo 即时回答 API"""
    try:
        client = _get_http_client()
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10.0,
        )
        data = resp.json()
        abstract = data.get("Abstract", "").strip()
        heading = data.get("Heading", "").strip()
        url = data.get("AbstractURL", "").strip()
        related = data.get("RelatedTopics", [])
        results = []
        if heading and abstract:
            results.append(f"【{heading}】\n{abstract}")
            if url:
                results.append(f"🔗 {url}")
        count = 0
        for topic in related:
            if count >= 3:
                break
            text = topic.get("Text", "").strip()
            link = topic.get("FirstURL", "").strip()
            if text:
                results.append(f"• {text}")
                if link:
                    results.append(f"  🔗 {link}")
                count += 1
        return results
    except Exception as e:
        logger.warning(f"[搜索DDG] 失败: {e}")
        return None


async def _search_wiki(query):
    """Wikipedia 中文摘要"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "MaiBot/1.0"}
        resp = await client.get(
            "https://zh.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query, "format": "json", "utf8": 1, "srlimit": 1},
            headers=headers,
            timeout=10.0,
        )
        data = resp.json()
        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            return None
        title = search_results[0].get("title", "")
        resp2 = await client.get(
            "https://zh.wikipedia.org/w/api.php",
            params={"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "titles": title, "format": "json", "utf8": 1},
            headers=headers,
            timeout=10.0,
        )
        data2 = resp2.json()
        pages = data2.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            extract = page.get("extract", "").strip()
            if extract:
                if len(extract) > 500:
                    extract = extract[:500] + "..."
                return [f"📖 【{title}】（维基百科）\n{extract}", f"🔗 https://zh.wikipedia.org/wiki/{title}"]
            return None
    except Exception as e:
        logger.warning(f"[搜索Wiki] 失败: {e}")
        return None


async def _search_bing(query):
    """Bing 搜索摘要"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-Hans"},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        results = []
        blocks = re.split(r'class="b_algo"', text)
        for block in blocks[1:5]:  # 取前4个结果
            title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            desc_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            if title_m and desc_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
                if title and desc and len(desc) > 5:
                    results.append(f"【{title}】\n{desc}")
        return results if results else None
    except Exception as e:
        logger.warning(f"[搜索Bing] 失败: {e}")
        return None


async def _search_baidu(query):
    """百度搜索摘要（备用）"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(
            "https://www.baidu.com/s",
            params={"wd": query},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        results = []
        # 百度搜索结果块
        blocks = re.split(r'class="result"', text)
        for block in blocks[1:4]:
            title_m = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            desc_m = re.search(r'<span class="content-right_[^"]*">(.*?)</span>', block, re.DOTALL)
            if not desc_m:
                desc_m = re.search(r'class="c-abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
            if title_m and desc_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                desc = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
                if title and desc and len(desc) > 5:
                    results.append(f"【{title}】\n{desc}")
        return results if results else None
    except Exception as e:
        logger.warning(f"[搜索Baidu] 失败: {e}")
        return None


async def _search_images(query, count=3):
    """图片搜索（Bing Images）"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(
            "https://www.bing.com/images/search",
            params={"q": query, "first": 1, "count": count, "setlang": "zh-Hans"},
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        images = []
        # 提取图片URL
        img_urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', text)
        if not img_urls:
            img_urls = re.findall(r'"murl":"(.*?)"', text)
        if not img_urls:
            # 备用模式
            img_urls = re.findall(r'src="(https://tse\d+\.mm\.bing\.net/[^"]+)"', text)
        for url in img_urls[:count]:
            if url.startswith("http"):
                images.append(url)
        return images if images else None
    except Exception as e:
        logger.warning(f"[搜图] 失败: {e}")
        return None


async def _cmd_search(event: MessageEvent):
    """搜索：/搜索 关键词"""
    content = str(event.message).strip()
    for prefix in ["搜索", "查一查", "搜一下"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await search_cmd.finish("...搜什么。格式：/搜索 关键词")
        return

    # 检查缓存
    cache_key = content.lower()
    if cache_key in _search_cache:
        cached = _search_cache[cache_key]
        if time.time() - cached["time"] < _SEARCH_TTL:
            await search_cmd.finish("\n".join(cached["results"][:6]))

    await search_cmd.send("正在搜索中...")

    # 并行请求所有搜索 API
    async def _safe_search(fn, q):
        try:
            return await fn(q)
        except Exception as e:
            logger.warning(f"[搜索失败] {fn.__name__}: {e}")
            return None

    search_fns = [_search_ddg, _search_wiki, _search_bing, _search_baidu]
    tasks = [asyncio.create_task(_safe_search(fn, content)) for fn in search_fns]
    all_results = []
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED, timeout=15.0)
        for t in done:
            results = t.result()
            if results:
                all_results.extend(results)
    except Exception as e:
        logger.debug(f"[搜索] {e}")

    if all_results:
        # 缓存
        _search_cache[cache_key] = {"results": all_results, "time": time.time()}
        if len(_search_cache) > 50:
            oldest = min(_search_cache, key=lambda k: _search_cache[k]["time"])
            del _search_cache[oldest]
        await search_cmd.finish("\n".join(all_results[:6]))

    await search_cmd.finish(f"...没搜到「{content}」的相关结果。换个关键词试试？")


async def _cmd_image_search(event: MessageEvent):
    """图片搜索：/搜图 关键词"""
    content = str(event.message).strip()
    for prefix in ["搜图", "图片搜索", "imgsearch"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await img_search_cmd.finish("...搜什么图。格式：/搜图 关键词")
        return

    await img_search_cmd.send("正在搜图中...")

    images = await _search_images(content, count=3)
    if not images:
        await img_search_cmd.finish(f"...没搜到「{content}」的图片。换个关键词试试？")

    # 发送图片
    msg = MessageSegment.text(f"🖼️ 「{content}」的搜索结果：\n")
    for i, url in enumerate(images):
        msg += MessageSegment.image(url)
        if i < len(images) - 1:
            msg += MessageSegment.text("\n")

    await img_search_cmd.finish(msg)


search_cmd = _register("搜索", _cmd_search, aliases=["搜一下", "查一查"])
img_search_cmd = _register("搜图", _cmd_image_search, aliases=["图片搜索", "imgsearch"])
