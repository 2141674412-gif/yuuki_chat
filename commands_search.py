# 搜索模块（DuckDuckGo + Wikipedia + Bing）

import asyncio
import re

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _get_http_client


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
        # 即时回答
        abstract = data.get("Abstract", "").strip()
        heading = data.get("Heading", "").strip()
        url = data.get("AbstractURL", "").strip()
        related = data.get("RelatedTopics", [])
        results = []
        if heading and abstract:
            results.append(f"【{heading}】\n{abstract}")
            if url:
                results.append(f"🔗 {url}")
        # 相关主题（取前3个有文本的）
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
        # 先搜索
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
        # 获取摘要
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
                if len(extract) > 300:
                    extract = extract[:300] + "..."
                return [f"【{title}】（维基百科）\n{extract}", f"🔗 https://zh.wikipedia.org/wiki/{title}"]
            return None
    except Exception as e:
        logger.warning(f"[搜索Wiki] 失败: {e}")
        return None


async def _search_bing(query):
    """Bing 搜索摘要（备用）"""
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
        # Bing 搜索结果：用 class 分割而不是 </li>
        blocks = re.split(r'class="b_algo"', text)
        for block in blocks[1:4]:  # 跳过第一个（正文前内容），取前3个
            # 提取标题
            title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            # 提取摘要
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

    await search_cmd.send("正在搜索中...")

    # 并行请求所有搜索 API，取第一个有结果返回的
    async def _safe_search(fn, q):
        try:
            return await fn(q)
        except Exception as e:
            logger.warning(f"[搜索失败] {fn.__name__}: {e}")
            return None

    search_fns = [_search_ddg, _search_wiki, _search_bing]
    tasks = [asyncio.create_task(_safe_search(fn, content)) for fn in search_fns]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            results = t.result()
            if results and len(results) >= 2:
                for p in pending:
                    p.cancel()
                await search_cmd.finish("\n".join(results[:6]))
        # 第一个完成的没有足够结果，等待剩余任务
        if pending:
            done2, pending2 = await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
            for t in done2:
                results = t.result()
                if results:
                    await search_cmd.finish("\n".join(results[:6]))
    except Exception as e:
        logger.debug(f"[搜索] {e}")

    await search_cmd.finish(f"...没搜到「{content}」的相关结果。换个关键词试试？")


search_cmd = _register("搜索", _cmd_search, aliases=["搜一下", "查一查"])
