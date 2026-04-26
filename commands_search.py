# 搜索模块（Wikipedia + DuckDuckGo + Bing + 百度 + 图片搜索）

import asyncio
import re
import time
import html

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

from .commands_base import _register, _get_http_client

# 搜索缓存（5分钟TTL）
_search_cache: dict = {}
_SEARCH_TTL = 300



async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _clean_html(text: str) -> str:
    """清理HTML标签和实体"""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    # 清理多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _is_chinese(text: str) -> bool:
    """检查文本是否包含中文"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def _is_quality_result(title: str, desc: str) -> bool:
    """检查结果质量"""
    # 过滤太短的描述
    if len(desc) < 15:
        return False
    # 过滤纯导航/下载站
    junk_patterns = [
        r'下载', r'免费', r'官网', r'首页', r'登录', r'注册',
        r'有问题，就会有答案',  # 知乎底部水印
        r'百度一下', r'百度百科',
    ]
    for p in junk_patterns:
        if re.search(p, desc) and len(desc) < 50:
            return False
    return True


async def _search_wiki(query):
    """Wikipedia 中文摘要（优先）"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "MaiBot/1.0"}
        resp = await client.get(
            "https://zh.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "utf8": 1, "srlimit": 1,
            },
            headers=headers, timeout=10.0,
        )
        data = resp.json()
        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            return None
        title = search_results[0].get("title", "")
        resp2 = await client.get(
            "https://zh.wikipedia.org/w/api.php",
            params={
                "action": "query", "prop": "extracts", "exintro": 1,
                "explaintext": 1, "titles": title, "format": "json", "utf8": 1,
            },
            headers=headers, timeout=10.0,
        )
        data2 = resp2.json()
        pages = data2.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            extract = page.get("extract", "").strip()
            if extract:
                if len(extract) > 400:
                    extract = extract[:400] + "..."
                return {
                    "source": "wiki",
                    "title": title,
                    "desc": extract,
                    "url": f"https://zh.wikipedia.org/wiki/{title}",
                }
            return None
    except Exception as e:
        logger.warning(f"[搜索Wiki] 失败: {e}")
        return None


async def _search_ddg(query):
    """DuckDuckGo 即时回答"""
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

        if heading and abstract and len(abstract) > 20:
            is_english = bool(url and "en.wikipedia.org" in url)
            return {
                "source": "ddg",
                "title": heading,
                "desc": abstract,
                "url": url,
                "is_english": is_english,  # 标记为英文结果
            }
    except Exception as e:
        logger.warning(f"[搜索DDG] 失败: {e}")
        return None


async def _search_bing(query):
    """Bing 搜索（取前3个高质量结果）"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-Hans"},
            headers=headers, timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        results = []
        blocks = re.split(r'class="b_algo"', text)
        for block in blocks[1:6]:
            title_m = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            desc_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            if not desc_m:
                desc_m = re.search(r'class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.DOTALL)
            if title_m and desc_m:
                title = _clean_html(title_m.group(1))
                desc = _clean_html(desc_m.group(1))
                if _is_quality_result(title, desc):
                    results.append({"source": "bing", "title": title, "desc": desc})
        return results[:3] if results else None
    except Exception as e:
        logger.warning(f"[搜索Bing] 失败: {e}")
        return None


async def _search_baidu(query):
    """百度搜索（备用）"""
    try:
        client = _get_http_client()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(
            "https://www.baidu.com/s",
            params={"wd": query},
            headers=headers, timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        results = []
        blocks = re.split(r'class="result"', text)
        for block in blocks[1:5]:
            title_m = re.search(r'<h3[^>]*>.*?<a[^>]*>(.*?)</a>', block, re.DOTALL)
            desc_m = re.search(r'<span class="content-right_[^"]*">(.*?)</span>', block, re.DOTALL)
            if not desc_m:
                desc_m = re.search(r'class="c-abstract[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
            if title_m and desc_m:
                title = _clean_html(title_m.group(1))
                desc = _clean_html(desc_m.group(1))
                if _is_quality_result(title, desc):
                    results.append({"source": "baidu", "title": title, "desc": desc})
        return results[:3] if results else None
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
            headers=headers, timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        text = resp.text
        images = []
        img_urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', text)
        if not img_urls:
            img_urls = re.findall(r'"murl":"(.*?)"', text)
        if not img_urls:
            img_urls = re.findall(r'src="(https://tse\d+\.mm\.bing\.net/[^"]+)"', text)
        for url in img_urls[:count]:
            if url.startswith("http"):
                images.append(url)
        return images if images else None
    except Exception as e:
        logger.warning(f"[搜图] 失败: {e}")
        return None


def _format_results(raw_results: list) -> str:
    """格式化搜索结果，去重+排序，中文优先"""
    wiki_results = []  # 中文百科
    en_results = []    # 英文百科（兜底）
    list_results = []  # 搜索列表
    seen_titles = set()

    for r in raw_results:
        if isinstance(r, dict):
            title = r.get("title", "")
            if title in seen_titles:
                continue
            seen_titles.add(title)

            if r.get("source") in ("wiki", "ddg"):
                if r.get("is_english"):
                    en_results.append(r)
                else:
                    wiki_results.append(r)
            else:
                list_results.append(r)
        elif isinstance(r, list):
            for item in r:
                title = item.get("title", "")
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                list_results.append(item)

    lines = []

    # 中文百科（优先）
    if wiki_results:
        w = wiki_results[0]
        lines.append(f"📖 【{w['title']}】")
        lines.append(w['desc'])
        if w.get('url'):
            lines.append(f"🔗 {w['url']}")
        lines.append("")

    # 搜索列表（最多3条）
    count = 0
    for r in list_results:
        if count >= 3:
            break
        title = r.get("title", "")
        desc = r.get("desc", "")
        if wiki_results and title == wiki_results[0].get("title", ""):
            continue
        lines.append(f"【{title}】")
        lines.append(desc)
        count += 1

    # 如果没有中文结果，用英文兜底
    if not wiki_results and not list_results and en_results:
        w = en_results[0]
        lines.append(f"📖 【{w['title']}】（English）")
        lines.append(w['desc'])
        if w.get('url'):
            lines.append(f"🔗 {w['url']}")

    return "\n".join(lines).strip()


async def _cmd_search(event: MessageEvent):
    """搜索：/搜索 关键词"""
    content = str(event.message).strip()
    for prefix in ["搜索", "查一查", "搜一下"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...搜什么。格式：/搜索 关键词")
        return

    # 检查缓存
    cache_key = content.lower()
    if cache_key in _search_cache:
        cached = _search_cache[cache_key]
        if time.time() - cached["time"] < _SEARCH_TTL:
            await _send(event, cached["text"])

    await _send(event, "正在搜索中...")

    # 并行请求所有搜索 API
    async def _safe_search(fn, q):
        try:
            return await fn(q)
        except Exception as e:
            logger.warning(f"[搜索失败] {fn.__name__}: {e}")
            return None

    search_fns = [_search_wiki, _search_ddg, _search_bing, _search_baidu]
    tasks = [asyncio.create_task(_safe_search(fn, content)) for fn in search_fns]
    all_results = []
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED, timeout=15.0)
        for t in done:
            results = t.result()
            if results:
                if isinstance(results, list):
                    all_results.extend(results)
                else:
                    all_results.append(results)
    except Exception as e:
        logger.debug(f"[搜索] {e}")

    if all_results:
        text = _format_results(all_results)
        if text:
            # 缓存
            _search_cache[cache_key] = {"text": text, "time": time.time()}
            if len(_search_cache) > 50:
                oldest = min(_search_cache, key=lambda k: _search_cache[k]["time"])
                del _search_cache[oldest]
            await _send(event, text)

    await _send(event, f"...没搜到「{content}」的相关结果。换个关键词试试？")


async def _cmd_image_search(event: MessageEvent):
    """图片搜索：/搜图 关键词"""
    content = str(event.message).strip()
    for prefix in ["搜图", "图片搜索", "imgsearch"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...搜什么图。格式：/搜图 关键词")
        return

    await _send(event, "正在搜图中...")

    images = await _search_images(content, count=3)
    if not images:
        await _send(event, f"...没搜到「{content}」的图片。换个关键词试试？")

    msg = MessageSegment.text(f"🖼️ 「{content}」的搜索结果：\n")
    for i, url in enumerate(images):
        msg += MessageSegment.image(url)
        if i < len(images) - 1:
            msg += MessageSegment.text("\n")

    await _send(event, msg)


search_cmd = _register("搜索", _cmd_search, aliases=["搜一下", "查一查"])
img_search_cmd = _register("搜图", _cmd_image_search, aliases=["图片搜索", "imgsearch"])
