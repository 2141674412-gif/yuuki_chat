from PIL import Image, ImageDraw, ImageFont
import os
import asyncio
import io
import logging

import httpx

logger = logging.getLogger("yuuki_chat.utils")

try:
    from .config import ACHIEV_LABELS
except ImportError:
    ACHIEV_LABELS = {}

# ── 模块级缓存与预计算 ──────────────────────────────────────────
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_COVER_CACHE_DIR = os.path.join(_PLUGIN_DIR, "cover_cache")
os.makedirs(_COVER_CACHE_DIR, exist_ok=True)
_MAX_COVER_CACHE = 500  # 最大缓存文件数

def _cleanup_cover_cache():
    """清理封面缓存，保留最新的 _MAX_COVER_CACHE 个文件"""
    try:
        files = []
        for f in os.listdir(_COVER_CACHE_DIR):
            if f.endswith(".png"):
                files.append((os.path.join(_COVER_CACHE_DIR, f),
                              os.path.getmtime(os.path.join(_COVER_CACHE_DIR, f))))
        if len(files) > _MAX_COVER_CACHE:
            # 按修改时间排序，删除最旧的
            files.sort(key=lambda x: x[1])
            for path, _ in files[:len(files) - _MAX_COVER_CACHE]:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception:
        pass

_font_cache = {}                                  # 字体缓存 (size, bold) -> Font
_sorted_achiev_labels = sorted(                   # 预排序成就标签（降序）
    ACHIEV_LABELS.items(), key=lambda x: x[0], reverse=True
)


def get_font(size, bold=False):
    """获取字体，优先使用系统字体（带缓存）"""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    if bold:
        font_paths = [
            "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
            "C:/Windows/Fonts/simhei.ttf",     # 黑体（无粗体时用黑体代替）
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "C:/Windows/Fonts/msyh.ttc",      # 回退常规
        ]
    else:
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/simhei.ttf",     # 黑体
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                _font_cache[key] = font
                return font
            except (OSError, IOError):
                continue
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """绘制圆角矩形"""
    x1, y1, x2, y2 = xy
    r = radius
    if fill:
        draw.ellipse([x1, y1, x1 + 2 * r, y1 + 2 * r], fill=fill)
        draw.ellipse([x2 - 2 * r, y1, x2, y1 + 2 * r], fill=fill)
        draw.ellipse([x1, y2 - 2 * r, x1 + 2 * r, y2], fill=fill)
        draw.ellipse([x2 - 2 * r, y2 - 2 * r, x2, y2], fill=fill)
        draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
        draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    if outline:
        draw.arc([x1, y1, x1 + 2 * r, y1 + 2 * r], 180, 270, fill=outline, width=width)
        draw.arc([x2 - 2 * r, y1, x2, y1 + 2 * r], 270, 360, fill=outline, width=width)
        draw.arc([x1, y2 - 2 * r, x1 + 2 * r, y2], 90, 180, fill=outline, width=width)
        draw.arc([x2 - 2 * r, y2 - 2 * r, x2, y2], 0, 90, fill=outline, width=width)
        draw.line([x1 + r, y1, x2 - r, y1], fill=outline, width=width)
        draw.line([x1 + r, y2, x2 - r, y2], fill=outline, width=width)
        draw.line([x1, y1 + r, x1, y2 - r], fill=outline, width=width)
        draw.line([x2, y1 + r, x2, y2 - r], fill=outline, width=width)


def draw_text_with_stroke(draw, pos, text, font, fill, stroke_color="#000000", stroke_width=1):
    """绘制带描边的文字"""
    x, y = pos
    for dx in (-stroke_width, 0, stroke_width):
        for dy in (-stroke_width, 0, stroke_width):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, fill=stroke_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def get_achiev_bar_color(achievements):
    if achievements >= 100:
        return "#00FF7F"
    elif achievements >= 99:
        return "#00BFFF"
    elif achievements >= 97:
        return "#9B59B6"
    elif achievements >= 95:
        return "#FF69B4"
    else:
        return "#808080"


def get_achiev_label(achievements):
    for threshold, label in _sorted_achiev_labels:
        if achievements >= threshold:
            return label
    return "D"


def get_cover_path(song_id):
    """根据 song_id 生成封面文件名（与水鱼前端逻辑一致）"""
    try:
        i = int(song_id)
    except (ValueError, TypeError):
        return "00000.png"
    # 水鱼前端: 10001~19999 减10000，其他直接用
    if 10001 <= i <= 19999:
        i -= 10000
    return str(i).zfill(5) + ".png"


def make_default_cover(size=(100, 100), title=""):
    """生成默认封面（显示歌曲首字母）"""
    w, h = size
    # 预计算渐变色带，用 Image.new + putdata 一次性写入，避免逐行绘制
    gradient = []
    for y in range(h):
        ratio = y / max(h - 1, 1)
        r = int(40 + 15 * ratio)
        g = int(35 + 10 * ratio)
        b = int(60 + 20 * ratio)
        gradient.extend([(r, g, b, 255)] * w)
    img = Image.new("RGBA", (w, h))
    img.putdata(gradient)
    draw = ImageDraw.Draw(img)
    # 显示首字母
    initial = title[0] if title else "?"
    font = get_font(32, bold=True)
    tw = draw.textlength(initial, font=font)
    draw.text(((w - tw) / 2, (h - 32) / 2), initial, fill=(100, 100, 140, 200), font=font)
    return img


async def download_cover(http_client, song_id, size=(100, 100)):
    """异步下载歌曲封面，返回 PIL Image 或 None（本地文件夹 > 磁盘缓存 > 网络下载）"""
    if not song_id:
        return None

    # ---- 本地封面文件夹（最高优先级） ----
    try:
        from .config import LOCAL_COVER_DIR
    except ImportError:
        LOCAL_COVER_DIR = ""
    if LOCAL_COVER_DIR and os.path.isdir(LOCAL_COVER_DIR):
        try:
            sid = int(song_id)
        except (ValueError, TypeError):
            sid = 0
        # 水鱼格式：10001~19999 减10000
        if 10001 <= sid <= 19999:
            display_id = sid - 10000
        else:
            display_id = sid
        # 精确匹配候选
        candidates = [
            f"UI_Jacket_{display_id:06d}.png",
            f"UI_Jacket_{display_id:06d}.jpg",
            f"UI_Jacket_{sid:06d}.png",
            f"UI_Jacket_{sid:06d}.jpg",
            f"{display_id:05d}.png",
            f"{display_id:05d}.jpg",
            f"{sid}.png",
            f"{sid}.jpg",
        ]
        for fname in candidates:
            fpath = os.path.join(LOCAL_COVER_DIR, fname)
            if os.path.exists(fpath):
                try:
                    cover_img = Image.open(fpath).convert("RGBA")
                    return cover_img.resize(size, Image.LANCZOS)
                except Exception:
                    pass
        # 模糊匹配：文件名以 UI_Jacket_XXXX_ 开头（如 UI_Jacket_0019_46.png）
        prefix = f"UI_Jacket_{display_id:04d}_"
        prefix2 = f"UI_Jacket_{sid:04d}_"
        try:
            for fname in os.listdir(LOCAL_COVER_DIR):
                if fname.startswith(prefix) or fname.startswith(prefix2):
                    if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                        fpath = os.path.join(LOCAL_COVER_DIR, fname)
                        try:
                            cover_img = Image.open(fpath).convert("RGBA")
                            return cover_img.resize(size, Image.LANCZOS)
                        except Exception:
                            pass
        except Exception:
            pass

    # ---- 磁盘缓存 ----
    cache_path = os.path.join(_COVER_CACHE_DIR, f"{song_id}.png")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        try:
            cover_img = Image.open(cache_path).convert("RGBA")
            return cover_img.resize(size, Image.LANCZOS)
        except Exception:
            pass

    # ---- 网络下载 ----
    cover_filename = get_cover_path(song_id)
    url = f"https://www.diving-fish.com/covers/{cover_filename}"

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = await http_client.get(url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 500:
                try:
                    cover_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                    resized = cover_img.resize(size, Image.LANCZOS)
                    # 保存到磁盘缓存
                    try:
                        cover_img.save(cache_path, "PNG")
                        _cleanup_cover_cache()
                    except Exception as e:
                        logger.debug(f"[封面缓存] 保存失败 song_id={song_id}, error={e}")
                    return resized
                except Exception:
                    # Image.open 失败，可能不是有效图片
                    pass
            return None
        except Exception as e:
            if attempt < max_retries:
                delay = (2 ** attempt)  # 1s, 2s 指数退避
                logger.warning(f"[封面下载失败] song_id={song_id}, 第{attempt+1}次重试, "
                      f"等待{delay}s, error={e}")
                await asyncio.sleep(delay)
            else:
                logger.warning(f"[封面下载失败] song_id={song_id}, 已达最大重试次数, error={e}")
    return None


# ── 全局共享 HTTP 客户端 ──────────────────────────────────────────
_shared_http_client: httpx.AsyncClient | None = None
_http_client_initialized = False

def get_shared_http_client() -> httpx.AsyncClient:
    """获取全局共享的 HTTP 客户端（连接池复用）"""
    global _shared_http_client, _http_client_initialized
    if not _http_client_initialized or _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )
        _http_client_initialized = True
    return _shared_http_client


async def shutdown_http_client():
    """关闭全局共享的 HTTP 客户端"""
    global _shared_http_client
    if _shared_http_client is not None and not _shared_http_client.is_closed:
        await _shared_http_client.aclose()
        _shared_http_client = None
