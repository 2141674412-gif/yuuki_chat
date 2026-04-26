# B站视频卡片模块

import re
import asyncio
import json

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment, Bot

from .commands_base import _get_http_client

# B站链接匹配
_BILI_PATTERNS = [
    r'bilibili\.com/video/(BV[a-zA-Z0-9]+)',
    r'b23\.tv/([a-zA-Z0-9]+)',
    r'bilibili\.com/video/(av\d+)',
]

_bili_video = on_message(priority=2, block=False)


def _extract_bili_urls(text: str):
    """从文本中提取B站视频BV号/av号/短链接"""
    results = []
    for pattern in _BILI_PATTERNS:
        for m in re.finditer(pattern, text):
            results.append(m.group(1))
    return results


def _format_num(n):
    """格式化数字：12345678 -> 1234.6万"""
    if n is None:
        return "-"
    n = int(n)
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    elif n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


async def _resolve_short_url(client, short_id: str) -> str:
    """解析b23.tv短链接，返回BV号"""
    try:
        resp = await client.get(
            f"https://b23.tv/{short_id}",
            headers=_BILI_HEADERS,
            timeout=5.0,
            follow_redirects=True
        )
        location = str(resp.url)
        m = re.search(r'BV[a-zA-Z0-9]+', location)
        if m:
            return m.group(0)
    except Exception as e:
        logger.warning(f"[B站] 解析短链接失败: {e}")
    return ""


_BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


async def _get_video_info(client, bvid: str):
    """调用B站API获取视频信息"""
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=_BILI_HEADERS,
            timeout=5.0
        )
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
        else:
            logger.warning(f"[B站] API返回错误: {data.get('message', '')} code={data.get('code')}")
    except Exception as e:
        logger.warning(f"[B站] 获取视频信息失败: {e}")
    return {}


async def _get_video_url(client, bvid: str, cid: int):
    """获取视频播放地址（用于发送视频消息）"""
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "qn": "32", "fnval": "16"},
            timeout=5.0
        )
        data = resp.json()
        if data.get("code") == 0:
            durl = data.get("data", {}).get("durl", [])
            if durl:
                return durl[0].get("url", "")
    except Exception as e:
        logger.debug(f"[B站] 获取视频URL失败: {e}")
    return ""


@_bili_video.handle()
async def handle_bilibili(bot: Bot, event: MessageEvent):
    """检测B站链接，发送视频卡片"""
    text = ""
    for seg in event.message:
        if seg.type == "text":
            text += seg.data.get("text", "")

    bili_ids = _extract_bili_urls(text)
    if not bili_ids:
        return

    logger.info(f"[B站] 检测到链接: {bili_ids}")
    client = _get_http_client()

    for bid in bili_ids:
        # 解析短链接
        if not bid.startswith("BV") and not bid.startswith("av"):
            bid = await _resolve_short_url(client, bid)
            if not bid:
                continue

        # 获取视频信息
        if bid.startswith("BV"):
            info = await _get_video_info(client, bid)
        else:
            # av号转BV号
            info = {}
            try:
                resp = await client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"aid": bid[2:]},
                    timeout=5.0
                )
                data = resp.json()
                if data.get("code") == 0:
                    info = data.get("data", {})
            except Exception:
                pass

        if not info:
            continue

        # 提取信息
        title = info.get("title", "未知标题")
        desc = info.get("desc", "")
        owner = info.get("owner", {})
        up_name = owner.get("name", "未知UP主")
        up_face = owner.get("face", "")
        pic = info.get("pic", "")
        stat = info.get("stat", {})
        view = _format_num(stat.get("view"))
        like = _format_num(stat.get("like"))
        danmaku = _format_num(stat.get("danmaku"))
        bvid = info.get("bvid", bid)
        cid = info.get("cid", 0)
        duration = info.get("duration", 0)
        minutes, seconds = divmod(duration, 60)

        # 构建卡片图片
        card_img = await _build_card_image(
            title=title,
            up_name=up_name,
            up_face=up_face,
            pic=pic,
            view=view,
            like=like,
            danmaku=danmaku,
            bvid=bvid,
            duration=f"{minutes}:{seconds:02d}" if duration > 0 else "",
        )

        # 发送卡片
        try:
            msg = MessageSegment.image(f"file://{card_img}")
            await _bili_video.send(msg)
        except Exception as e:
            logger.warning(f"[B站] 发送卡片失败: {e}")
            # 降级：发送纯文本
            try:
                await _bili_video.send(
                    f"🎬 {title}\n"
                    f"UP: {up_name} | ▶{view} 👍{like} 💬{danmaku}\n"
                    f"https://bilibili.com/video/{bvid}"
                )
            except Exception:
                pass

        await asyncio.sleep(0.5)  # 多个视频间隔发送


async def _build_card_image(title, up_name, up_face, pic, view, like, danmaku, bvid, duration):
    """构建B站视频卡片图片"""
    import os
    from PIL import Image, ImageDraw
    from .utils import get_font

    # 下载封面图
    cover_path = os.path.join("/data/user/work", f"bili_cover_{bvid}.jpg")
    cover = None
    try:
        client = _get_http_client()
        resp = await client.get(pic, headers=_BILI_HEADERS, timeout=10.0)
        if resp.status_code == 200:
            with open(cover_path, "wb") as f:
                f.write(resp.content)
            cover = Image.open(cover_path).convert("RGB")
    except Exception as e:
        logger.debug(f"[B站] 下载封面失败: {e}")

    # 卡片尺寸
    card_w = 400
    cover_h = 225  # 16:9
    padding = 12
    title_area_h = 60
    info_area_h = 30
    total_h = padding + cover_h + padding + title_area_h + info_area_h + padding

    # 创建卡片
    card = Image.new("RGB", (card_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(card)

    # 封面
    if cover:
        cover = cover.resize((card_w - padding * 2, cover_h), Image.LANCZOS)
        card.paste(cover, (padding, padding))

        # 封面底部渐变遮罩
        for y in range(cover_h // 3):
            alpha = int(180 * (y / (cover_h // 3)))
            y_pos = padding + cover_h - cover_h // 3 + y
            draw.rectangle(
                [padding, y_pos, card_w - padding, y_pos + 1],
                fill=(0, 0, 0, alpha)
            )

        # 时长标签（右上角）
        if duration:
            font_small = get_font(14)
            tw = font_small.getlength(duration)
            tx = card_w - padding - int(tw) - 12
            ty = padding + cover_h - 28
            draw.rectangle([tx - 4, ty - 2, card_w - padding, ty + 18], fill=(0, 0, 0, 180))
            draw.text((tx, ty), duration, fill=(255, 255, 255), font=font_small)

        # 播放数据（封面底部）
        font_tiny = get_font(12)
        stats_text = f"▶{view}  👍{like}  💬{danmaku}"
        draw.text((padding + 8, padding + cover_h - 22), stats_text, fill=(255, 255, 255), font=font_tiny)
    else:
        # 无封面时的占位
        draw.rectangle([padding, padding, card_w - padding, padding + cover_h], fill=(240, 240, 240))

    # B站标识（粉色小标签）
    font_label = get_font(12)
    label = "bilibili"
    label_w = int(font_label.getlength(label)) + 12
    draw.rectangle([padding, padding + cover_h + padding, padding + label_w, padding + cover_h + padding + 18], fill=(251, 114, 153))
    draw.text((padding + 6, padding + cover_h + padding + 1), label, fill=(255, 255, 255), font=font_label)

    # 标题
    font_title = get_font(16)
    title_y = padding + cover_h + padding + 22
    # 截断标题
    display_title = title
    while font_title.getlength(display_title) > card_w - padding * 2 - 4 and len(display_title) > 1:
        display_title = display_title[:-1]
    if display_title != title:
        display_title += "..."
    draw.text((padding, title_y), display_title, fill=(30, 30, 30), font=font_title)

    # UP主 + BV号
    font_info = get_font(12)
    info_y = title_y + 24
    info_text = f"@{up_name}  |  {bvid}"
    draw.text((padding, info_y), info_text, fill=(150, 150, 150), font=font_info)

    # 保存
    out_path = os.path.join("/data/user/work", f"bili_card_{bvid}.jpg")
    card.save(out_path, "JPEG", quality=90)

    # 清理封面
    try:
        if os.path.exists(cover_path):
            os.remove(cover_path)
    except Exception:
        pass

    return out_path
