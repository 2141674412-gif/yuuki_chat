from nonebot import on_command, logger
from nonebot.exception import FinishedException
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
import httpx
import io
import os
import asyncio
import json
import re
import shutil
import time
import datetime
import tempfile
from PIL import Image, ImageDraw

# ---- 成就徽章图片加载 ----
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_BADGE_SEARCH_PATHS = [
    os.path.join(_PLUGIN_DIR, "assets", "badges"),
    os.path.join(_PLUGIN_DIR, "..", "assets", "badges"),
    os.path.join(_PLUGIN_DIR, "..", "..", "assets", "badges"),
]
_BADGE_DIR = None
for p in _BADGE_SEARCH_PATHS:
    if os.path.isdir(p):
        _BADGE_DIR = p
        break

_BADGE_IMAGES = {}  # key: "ap", "app", "fc", "fcp", "fs", "fsd", "fsdp", "fsp" → PIL Image

# ---- 难度等级标签图片加载 ----
_LEVEL_DIR = os.path.join(_PLUGIN_DIR, "assets", "levels")
_LEVEL_IMAGES = {}  # key: "01"~"15", "07p"~"15p" → PIL Image

def _load_level_images():
    if not os.path.isdir(_LEVEL_DIR):
        return
    for fname in os.listdir(_LEVEL_DIR):
        if fname.lower().endswith(".png"):
            key = fname[:-4]
            try:
                _LEVEL_IMAGES[key] = Image.open(os.path.join(_LEVEL_DIR, fname)).convert("RGBA")
            except Exception:
                pass

_load_level_images()

# ---- DX/SD 图标加载 ----
_ICON_DIR = os.path.join(_PLUGIN_DIR, "assets", "icons")
_ICON_IMAGES = {}  # key: "DX", "SD", "Master", "ReMaster" → PIL Image

def _load_icon_images():
    if not os.path.isdir(_ICON_DIR):
        return
    for fname in os.listdir(_ICON_DIR):
        if fname.lower().endswith(".png"):
            key = fname[:-4]
            try:
                _ICON_IMAGES[key] = Image.open(os.path.join(_ICON_DIR, fname)).convert("RGBA")
            except Exception:
                pass

_load_icon_images()

# ---- DX评分框和星星加载 ----
_RATING_DIR = os.path.join(_PLUGIN_DIR, "assets", "rating")
_DX_RATING_IMG = None  # DX评分框背景
_STAR_IMAGES = {}  # key: "01"~"05" → PIL Image

def _load_rating_images():
    global _DX_RATING_IMG
    if not os.path.isdir(_RATING_DIR):
        return
    # DX评分框
    p = os.path.join(_RATING_DIR, "dx_rating.png")
    if os.path.exists(p):
        try:
            _DX_RATING_IMG = Image.open(p).convert("RGBA")
        except Exception:
            pass
    # 星星图标
    for fname in os.listdir(_RATING_DIR):
        if fname.startswith("star_") and fname.endswith(".png"):
            key = fname[5:7]  # "01"~"05"
            try:
                _STAR_IMAGES[key] = Image.open(os.path.join(_RATING_DIR, fname)).convert("RGBA")
            except Exception:
                pass

_load_rating_images()

def _load_badges():
    """启动时加载所有徽章图片"""
    if not _BADGE_DIR:
        logger.warning("[徽章] 未找到 assets/badges 目录，将使用文字徽章")
        return
    logger.info(f"[徽章] 使用目录: {_BADGE_DIR}")
    mapping = {
        "ap": "AP.png", "app": "APp.png",
        "fc": "FC.png", "fcp": "FCp.png",
        "fs": "FS.png", "fsd": "FSD.png", "fsdp": "FSDp.png", "fsp": "FSp.png",
    }
    for key, filename in mapping.items():
        path = os.path.join(_BADGE_DIR, filename)
        if os.path.exists(path):
            try:
                _BADGE_IMAGES[key] = Image.open(path).convert("RGBA")
                logger.info(f"[徽章] 已加载: {filename}")
            except Exception as e:
                logger.warning(f"[徽章] 加载失败 {filename}: {e}")
        else:
            logger.debug(f"[徽章] 文件不存在: {path}")

_load_badges()

from .config import (
    MAIMAI_API, MAIMAI_MUSIC_API, MAIMAI_COVER_BASE, MAIMAI_VERSIONS,
    MAIMAI_BINDS_FILE, ACHIEV_COLORS, FC_COLORS, DAN_NAMES,
    ALLOWED_GROUPS,
)

# ---- 群白名单检查 ----

def _check_group(event: MessageEvent) -> bool:
    """检查群消息是否在白名单内，返回 True 表示放行"""
    # 黑名单检查
    try:
        from .commands_base import user_blacklist, superusers
        uid = str(event.user_id)
        if uid not in superusers and uid in user_blacklist:
            return False
    except Exception:
        pass
    gid = getattr(event, 'group_id', None)
    if gid and gid not in ALLOWED_GROUPS:
        return False
    return True
from .utils import (
    get_font, draw_rounded_rect, draw_text_with_stroke,
    get_achiev_bar_color, get_achiev_label, get_cover_path,
    make_default_cover, download_cover,
)

# ---- 下载封面并发限制（模块级别） ----
_cover_sem = asyncio.Semaphore(8)

# ---- 全局 HTTP 客户端（连接池复用，避免重复TCP握手） ----
from .utils import get_shared_http_client as get_http_client

# ---- 用户成绩缓存（5分钟TTL） ----
_user_records_cache: dict = {}  # {username: {"data": ..., "time": float}}
_USER_RECORDS_TTL = 300  # 5分钟缓存

# ---- 绑定数据读写 ----

# 旧版路径兼容（迁移用）
_OLD_BINDS_PATHS = [
    os.path.join(_PLUGIN_DIR, "data", "maimai_binds.json"),
    os.path.join(_PLUGIN_DIR, "maimai_binds.json"),
    os.path.join(_PLUGIN_DIR, "binds.json"),
    os.path.join(os.path.dirname(_PLUGIN_DIR), "yuuki_data", "maimai_binds.json"),
]

def _migrate_binds():
    """如果旧路径存在绑定文件，迁移到新路径"""
    if os.path.exists(MAIMAI_BINDS_FILE):
        return
    for old_path in _OLD_BINDS_PATHS:
        if os.path.exists(old_path) and old_path != MAIMAI_BINDS_FILE:
            try:
                shutil.copy2(old_path, MAIMAI_BINDS_FILE)
                logger.info(f"[绑定] 已从旧路径迁移: {old_path}")
            except Exception as e:
                logger.warning(f"[绑定] 迁移失败: {e}")
            return

_migrate_binds()

def load_binds():
    """读取绑定数据"""
    if os.path.exists(MAIMAI_BINDS_FILE):
        try:
            with open(MAIMAI_BINDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.debug(f"[绑定] 已加载 {len(data)} 条绑定: {MAIMAI_BINDS_FILE}")
                return data
        except (json.JSONDecodeError, OSError):
            return {}
    logger.debug(f"[绑定] 文件不存在: {MAIMAI_BINDS_FILE}")
    return {}

def save_binds(binds):
    """保存绑定数据（原子写入）"""
    dir_name = os.path.dirname(MAIMAI_BINDS_FILE)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(binds, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MAIMAI_BINDS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info(f"[绑定] 已保存 {len(binds)} 条绑定: {MAIMAI_BINDS_FILE}")


def _convert_records_to_charts(data: dict) -> None:
    """将 /player/records 格式（records 列表）转换为 /query/player 格式（charts.dx/sd），原地修改 data"""
    if "records" not in data or "charts" in data:
        return
    records = data.get("records", [])
    dx_charts, sd_charts = [], []
    for rec in records:
        song_type = str(rec.get("type", "SD")).upper()
        chart = {
            "song_id": str(rec.get("song_id", "")),
            "title": rec.get("title", "未知"),
            "type": song_type,
            "level": rec.get("level", ""),
            "level_label": rec.get("level_label", ""),
            "level_index": rec.get("level_index", 0),
            "ds": rec.get("ds", 0),
            "achievements": rec.get("achievements", 0),
            "ra": rec.get("ra", 0),
            "dxScore": rec.get("dxScore", 0),
            "fc": rec.get("fc", ""),
            "fs": rec.get("fs", ""),
            "fdx": rec.get("fdx", ""),
        }
        if song_type == "DX":
            dx_charts.append(chart)
        else:
            sd_charts.append(chart)
    data["charts"] = {"dx": dx_charts, "sd": sd_charts}
    logger.info(f"[mai] 转换数据: DX={len(dx_charts)}, SD={len(sd_charts)}")


def _build_song_version_map(music_data: list) -> dict:
    """构建 song_id → 版本来源 的映射"""
    mapping = {}
    for song in music_data:
        sid = int(song.get("id", 0))
        from_ver = song.get("basic_info", {}).get("from", "")
        mapping[sid] = from_ver
        if sid > 10000:
            mapping[sid % 10000] = from_ver
    return mapping


# ---- 水鱼歌曲数据库缓存（带 TTL，1 小时过期） ----

_music_data_cache = None
_music_data_cache_time = 0.0
_MUSIC_DATA_TTL = 3600  # 缓存有效期：1 小时（秒）

async def get_music_data():
    """获取水鱼歌曲数据（带缓存，超过 1 小时自动刷新）"""
    global _music_data_cache, _music_data_cache_time
    now = time.time()
    if _music_data_cache is not None and (now - _music_data_cache_time) < _MUSIC_DATA_TTL:
        return _music_data_cache
    try:
        http_client = get_http_client()
        resp = await http_client.get(MAIMAI_MUSIC_API)
        resp.raise_for_status()
        _music_data_cache = resp.json()
        _music_data_cache_time = now
        return _music_data_cache
    except httpx.TimeoutException:
        # 超时但缓存仍可用时返回旧缓存
        if _music_data_cache is not None:
            return _music_data_cache
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(f"[music_data] HTTP 错误: {e.response.status_code}")
        if _music_data_cache is not None:
            return _music_data_cache
        return None
    except Exception as e:
        logger.warning(f"[music_data] 获取失败: {e}")
        if _music_data_cache is not None:
            return _music_data_cache
        return None

# ---- B50/B40 卡片网格图片生成 ----

async def generate_mai_image(data, is_b50=True):
    """生成舞萌 B50/B40 卡片图片（网格卡片布局）"""
    _t_start = time.time()
    nickname = data.get("nickname", "Unknown")
    rating = data.get("rating", 0)
    dx_rating = data.get("dx_rating", 0) or rating
    additional_rating = data.get("additional_rating", 0)
    plate = data.get("plate", "")

    dan = DAN_NAMES[additional_rating] if 0 <= additional_rating < len(DAN_NAMES) else str(additional_rating)

    charts = data.get("charts", {})
    dx_list = charts.get("dx", [])
    sd_list = charts.get("sd", [])
    all_songs = dx_list + sd_list

    music_data = await get_music_data()
    song_version_map = _build_song_version_map(music_data) if music_data else {}
    latest_version_name = MAIMAI_VERSIONS[-1]
    if music_data:
        all_froms = set(song_version_map.values())
        for v in reversed(MAIMAI_VERSIONS):
            if v in all_froms:
                latest_version_name = v
                break

    old_songs = []
    new_songs = []
    for song in all_songs:
        sid = int(song.get("song_id", 0))
        from_ver = song_version_map.get(sid, "") or song_version_map.get(sid % 10000, "")
        if from_ver == latest_version_name:
            new_songs.append(song)
        else:
            old_songs.append(song)

    old_count = 35 if is_b50 else 25
    new_count = 15

    old_songs_sorted = sorted(old_songs, key=lambda x: x.get("ra", 0), reverse=True)[:old_count]
    new_songs_sorted = sorted(new_songs, key=lambda x: x.get("ra", 0), reverse=True)[:new_count]
    top_songs = old_songs_sorted + new_songs_sorted

    if not top_songs:
        return None

    # ---- 网格布局参数 ----
    COLS = 5  # 每行5张卡片
    CARD_SIZE = 240  # 每张卡片宽度
    CARD_H = 220  # 每张卡片高度（封面 + 信息区）
    COVER_SIZE = 140  # 封面大小
    GAP = 10  # 卡片间距
    MARGIN = 20  # 页面边距
    HEADER_H = 100  # 头部高度
    SEP_H = 34  # 分隔条高度
    FOOTER_H = 28

    W = MARGIN * 2 + COLS * CARD_SIZE + (COLS - 1) * GAP

    # 动态计算高度
    def rows_for(count):
        return (count + COLS - 1) // COLS

    old_rows = rows_for(len(old_songs_sorted))
    new_rows = rows_for(len(new_songs_sorted))
    H = HEADER_H + old_rows * CARD_H + SEP_H + new_rows * CARD_H + FOOTER_H

    # ---- 颜色 ----
    BG = "#F5F5F7"
    CARD_BG = "#FFFFFF"
    TEXT_PRIMARY = "#1a1a2e"
    TEXT_SECONDARY = "#8e8e93"
    ACCENT = "#6c5ce7"
    ACCENT_LIGHT = "#f0edff"
    BORDER = "#e5e5ea"

    DIFF_COLORS_MAP = {
        "remaster": ("#2d3436", "Re:M"),
        "master": ("#6c5ce7", "Mas"),
        "expert": ("#e74c3c", "Exp"),
        "advanced": ("#ffeaa7", "Adv"),
        "basic": ("#00b894", "Bas"),
    }

    # ---- 创建画布 ----
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ---- 字体 ----
    font_title = get_font(24, bold=True)
    font_nickname = get_font(15)
    font_rating = get_font(30, bold=True)
    font_info = get_font(12)
    font_song = get_font(11, bold=True)
    font_achiev = get_font(15, bold=True)
    font_badge = get_font(9, bold=True)
    font_sep = get_font(12, bold=True)
    font_footer = get_font(10)

    # ---- 辅助函数 ----
    def draw_pill(x, y, text, font, bg_color, text_color, padding_h=4, padding_v=1, _draw=None):
        d = _draw or draw
        tw = int(d.textlength(text, font=font))
        pill_w = tw + padding_h * 2
        pill_h = int(font.size * 1.3) + padding_v * 2
        draw_rounded_rect(d, (x, y, x + pill_w, y + pill_h), radius=pill_h // 2, fill=bg_color)
        d.text((x + padding_h, y + padding_v), text, fill=text_color, font=font)
        return pill_w

    def get_diff_info(song):
        level_label = str(song.get("level_label", "")).strip()
        ds = song.get("ds", 0)
        ll = level_label.lower()
        if "re:" in ll or "remaster" in ll:
            return DIFF_COLORS_MAP["remaster"]
        elif "master" in ll:
            return DIFF_COLORS_MAP["master"]
        elif "expert" in ll:
            return DIFF_COLORS_MAP["expert"]
        elif "advanced" in ll:
            return DIFF_COLORS_MAP["advanced"]
        elif "basic" in ll:
            return DIFF_COLORS_MAP["basic"]
        else:
            if ds >= 14: return DIFF_COLORS_MAP["remaster"]
            elif ds >= 13: return DIFF_COLORS_MAP["master"]
            elif ds >= 12: return DIFF_COLORS_MAP["expert"]
            elif ds >= 11: return DIFF_COLORS_MAP["advanced"]
            else: return DIFF_COLORS_MAP["basic"]

    def get_achiev_color(achievements):
        achiev_label = get_achiev_label(achievements)
        color_map = {
            "SSS+": "#FFD700", "SSS": "#FFD700",
            "SS+": "#FF8C00", "SS": "#FF8C00",
            "S+": "#FF69B4", "S": "#FF69B4",
            "AAA": "#4A90D9", "AA": "#7B68EE",
        }
        return color_map.get(achiev_label, "#6c757d")

    # ---- 头部 ----
    tag = "Best 50" if is_b50 else "Best 40"
    draw.text((MARGIN, 12), f"maimai {tag}", fill=TEXT_PRIMARY, font=font_title)

    # 玩家名 + 段位
    draw.text((MARGIN, 42), nickname, fill=TEXT_SECONDARY, font=font_nickname)
    name_w = int(draw.textlength(nickname, font=font_nickname))
    draw_pill(MARGIN + name_w + 8, 44, dan, font_badge, ACCENT_LIGHT, ACCENT)

    # RA 详情
    old_ra = sum(s.get("ra", 0) for s in old_songs_sorted)
    new_ra = sum(s.get("ra", 0) for s in new_songs_sorted)
    if is_b50:
        ra_detail = f"B35: {old_ra:.1f} + B15: {new_ra:.1f}"
    else:
        ra_detail = f"B25: {old_ra:.1f} + B15: {new_ra:.1f}"
    draw.text((MARGIN, 64), ra_detail, fill=TEXT_SECONDARY, font=font_info)

    # DX Rating 方块（用官方图片背景）
    rating_str = f"{dx_rating:.2f}"
    if _DX_RATING_IMG:
        # 用官方DX评分框
        rw = 180
        rh = int(rw * _DX_RATING_IMG.height / _DX_RATING_IMG.width)
        rating_bg = _DX_RATING_IMG.resize((rw, rh), Image.LANCZOS)
        box_x = W - MARGIN - rw
        box_y = 12
        if rating_bg.mode == "RGBA":
            img.paste(rating_bg, (box_x, box_y), rating_bg)
        else:
            img.paste(rating_bg, (box_x, box_y))
        # 在框内写 rating 数字
        rating_tw = int(draw.textlength(rating_str, font=font_rating))
        rating_x = box_x + (rw - rating_tw) // 2
        rating_y = box_y + (rh - font_rating.size) // 2
        draw.text((rating_x, rating_y), rating_str, fill="#FFFFFF", font=font_rating)
    else:
        # 回退：纯色方块
        rating_tw = int(draw.textlength(rating_str, font=font_rating))
        label_tw = int(draw.textlength("DX Rating", font=font_info))
        box_w = max(rating_tw, label_tw) + 36
        box_h = 60
        box_x = W - MARGIN - box_w
        box_y = 12
        draw_rounded_rect(draw, (box_x, box_y, box_x + box_w, box_y + box_h), radius=10, fill=ACCENT)
        label_x = box_x + (box_w - label_tw) // 2
        draw.text((label_x, box_y + 6), "DX Rating", fill="#FFFFFF", font=font_info)
        rating_x = box_x + (box_w - rating_tw) // 2
        draw.text((rating_x, box_y + 24), rating_str, fill="#FFFFFF", font=font_rating)

    # 头部底线
    draw.rectangle([0, HEADER_H - 2, W, HEADER_H], fill=ACCENT)

    # ---- 下载封面 ----
    _t_cover_start = time.time()
    cover_size = (COVER_SIZE, COVER_SIZE)
    http_client = get_http_client()

    async def _limited_download(sid, size):
        async with _cover_sem:
            return await download_cover(http_client, sid, size)

    cover_tasks = []
    for song in top_songs:
        song_id = song.get("song_id", "")
        cover_tasks.append(_limited_download(song_id, cover_size))
    covers = await asyncio.gather(*cover_tasks)

    success_count = sum(1 for c in covers if c is not None)
    _t_cover_end = time.time()
    logger.info(f"[封面下载] 成功 {success_count}/{len(covers)}，耗时 {_t_cover_end - _t_cover_start:.2f}s")

    final_covers = []
    for i, song in enumerate(top_songs):
        if i < len(covers) and covers[i] is not None:
            final_covers.append(covers[i])
        else:
            title = song.get("title", "")
            final_covers.append(make_default_cover(cover_size, title))

    # ---- 绘制网格卡片 ----
    def draw_card(col, row, song, cover_img, start_y):
        """绘制一张网格卡片"""
        cx = MARGIN + col * (CARD_SIZE + GAP)
        cy = start_y + row * CARD_H

        # 卡片背景（白色圆角矩形）
        draw_rounded_rect(draw, (cx, cy, cx + CARD_SIZE, cy + CARD_H), radius=10, fill=CARD_BG)

        # 封面（圆角，居中）
        cover_margin = (CARD_SIZE - COVER_SIZE) // 2
        cover_x = cx + cover_margin
        cover_y = cy + 16
        if cover_img is not None:
            cover_resized = cover_img.resize((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
            if cover_resized.mode == "RGBA":
                mask = Image.new("L", (COVER_SIZE, COVER_SIZE), 0)
                mask_draw = ImageDraw.Draw(mask)
                draw_rounded_rect(mask_draw, (0, 0, COVER_SIZE, COVER_SIZE), radius=8, fill=255)
                img.paste(cover_resized, (cover_x, cover_y), mask)
            else:
                img.paste(cover_resized, (cover_x, cover_y))

        # ---- 封面上方左侧：难度等级标签（官方图片） ----
        level = str(song.get("level", "")).strip()
        level_img_key = None
        if level:
            if level.endswith("+"):
                num = level[:-1]
                level_img_key = num + "p"
            else:
                level_img_key = level.zfill(2)
        if not level_img_key or level_img_key not in _LEVEL_IMAGES:
            ds_val = song.get("ds", 0)
            if ds_val >= 7:
                ds_int = int(ds_val)
                test_key = str(ds_int) + "p"
                if test_key in _LEVEL_IMAGES:
                    level_img_key = test_key
                else:
                    level_img_key = str(ds_int).zfill(2)
            elif ds_val > 0:
                level_img_key = str(int(ds_val)).zfill(2)
        if level_img_key and level_img_key in _LEVEL_IMAGES:
            level_img = _LEVEL_IMAGES[level_img_key]
            lw = int(CARD_SIZE * 0.30)
            lh = int(lw * level_img.height / level_img.width)
            level_resized = level_img.resize((lw, lh), Image.LANCZOS)
            level_x = cx + 2
            level_y = cy + (16 - lh) // 2
            if level_resized.mode == "RGBA":
                img.paste(level_resized, (level_x, level_y), level_resized)
            else:
                img.paste(level_resized, (level_x, level_y))
        else:
            ds_val = song.get("ds", 0)
            ds_str = f"{ds_val:.1f}"
            draw.text((cx + 4, cy + 2), ds_str, fill=TEXT_SECONDARY, font=font_info)

        # ---- 封面上方右侧：Master/ReMaster 图标 ----
        level_index = song.get("level_index", 0)
        diff_names = {3: "Master", 4: "ReMaster"}
        diff_icon_key = diff_names.get(level_index)
        if diff_icon_key and diff_icon_key in _ICON_IMAGES:
            diff_icon = _ICON_IMAGES[diff_icon_key]
            iw = int(CARD_SIZE * 0.28)
            ih = int(iw * diff_icon.height / diff_icon.width)
            diff_resized = diff_icon.resize((iw, ih), Image.LANCZOS)
            diff_x = cx + CARD_SIZE - iw - 2
            diff_y = cy + (16 - ih) // 2
            if diff_resized.mode == "RGBA":
                img.paste(diff_resized, (diff_x, diff_y), diff_resized)
            else:
                img.paste(diff_resized, (diff_x, diff_y))

        # ---- 封面上方中间：DX/SD 标签 ----
        song_type = song.get("type", "")
        if song_type in ("DX", "SD"):
            icon_font = font_info
            type_label = song_type
            type_color = "#FF6B00" if song_type == "DX" else "#4A90D9"
            type_tw = int(draw.textlength(type_label, font=icon_font))
            type_th = int(icon_font.size * 1.2)
            type_bg_w = type_tw + 10
            type_bg_h = type_th + 4
            type_bg_x = cx + (CARD_SIZE - type_bg_w) // 2
            type_bg_y = cy + (16 - type_bg_h) // 2
            type_bg_overlay = Image.new("RGBA", (type_bg_w, type_bg_h), (0, 0, 0, 0))
            type_bg_draw = ImageDraw.Draw(type_bg_overlay)
            draw_rounded_rect(type_bg_draw, (0, 0, type_bg_w, type_bg_h), radius=6,
                              fill=type_color + "CC")
            img.paste(type_bg_overlay, (type_bg_x, type_bg_y), type_bg_overlay)
            draw.text((type_bg_x + 5, type_bg_y + 2), type_label, fill="#FFFFFF", font=icon_font)

        # ---- 封面右下角：FC/AP/FS 徽章 ----
        fc_raw = song.get("fc", "")
        fc = str(fc_raw).lower().strip()
        fs_raw = song.get("fs", "")
        fs = str(fs_raw).lower().strip()
        fdx = str(song.get("fdx", "")).lower().strip()

        # 绘制徽章（FC类放封面左侧空白，FS/FDX类放封面右侧空白）
        badge_size = 32
        fc_badge = None
        fs_badge = None

        # FC类徽章（左侧）
        if fc in ("ap", "app", "fc", "fcp") and fc in _BADGE_IMAGES:
            fc_badge = fc
        # FS/FDX类徽章（右侧）
        if fdx in ("ap", "app", "fsd", "fsdp", "fs", "fsp") and fdx in _BADGE_IMAGES:
            fs_badge = fdx
        elif fs in ("fsd", "fsdp", "fs", "fsp") and fs in _BADGE_IMAGES:
            fs_badge = fs
        elif fdx in ("ap", "app") and fdx in _BADGE_IMAGES:
            fs_badge = fdx

        # FC类 → 封面左侧空白
        if fc_badge:
            badge_img = _BADGE_IMAGES[fc_badge]
            badge_resized = badge_img.resize((badge_size, badge_size), Image.LANCZOS)
            bx = cover_x - badge_size - 2
            by = cover_y + (COVER_SIZE - badge_size) // 2
            if badge_resized.mode == "RGBA":
                img.paste(badge_resized, (bx, by), badge_resized)
            else:
                img.paste(badge_resized, (bx, by))

        # FS/FDX类 → 封面右侧空白
        if fs_badge:
            badge_img = _BADGE_IMAGES[fs_badge]
            badge_resized = badge_img.resize((badge_size, badge_size), Image.LANCZOS)
            bx = cover_x + COVER_SIZE + 2
            by = cover_y + (COVER_SIZE - badge_size) // 2
            if badge_resized.mode == "RGBA":
                img.paste(badge_resized, (bx, by), badge_resized)
            else:
                img.paste(badge_resized, (bx, by))

        # ---- 信息区（封面下方） ----
        info_y = cover_y + COVER_SIZE + 5

        # 歌曲名（左对齐）+ 定数（右对齐）
        title = song.get("title", "未知")
        max_tw = CARD_SIZE - 50  # 右侧留50px给定数
        dt = title
        title_lines = 1
        if draw.textlength(dt, font=font_song) > max_tw:
            mid = len(dt) // 2
            wrapped = False
            for offset in range(min(10, len(dt))):
                for pos in [mid + offset, mid - offset]:
                    if 0 < pos < len(dt) and dt[pos] in (" ", "　", "・"):
                        line1 = dt[:pos]
                        line2 = dt[pos+1:]
                        if draw.textlength(line1, font=font_song) <= max_tw and draw.textlength(line2, font=font_song) <= max_tw:
                            draw.text((cx + 4, info_y), line1, fill=TEXT_PRIMARY, font=font_song)
                            draw.text((cx + 4, info_y + 15), line2, fill=TEXT_PRIMARY, font=font_song)
                            wrapped = True
                            title_lines = 2
                            break
                if wrapped:
                    break
            if not wrapped:
                while draw.textlength(dt, font=font_song) > max_tw and len(dt) > 1:
                    dt = dt[:-1]
                if dt != title:
                    dt += ".."
                draw.text((cx + 4, info_y + 4), dt, fill=TEXT_PRIMARY, font=font_song)
        else:
            draw.text((cx + 4, info_y + 4), dt, fill=TEXT_PRIMARY, font=font_song)

        # 定数（右对齐，和歌名同行）
        ds_val = song.get("ds", 0)
        ds_str = f"{ds_val:.1f}"
        ds_tw = int(draw.textlength(ds_str, font=font_song))
        draw.text((cx + CARD_SIZE - ds_tw - 4, info_y + 4), ds_str, fill=TEXT_SECONDARY, font=font_song)

        # 达成率（左对齐）+ RA值（右对齐）
        achievements = song.get("achievements", 0)
        achiev_color = get_achiev_color(achievements)
        achiev_str = f"{achievements:.4f}%"
        achiev_y = info_y + 32 if title_lines == 1 else info_y + 34
        draw.text((cx + 4, achiev_y), achiev_str, fill=achiev_color, font=font_achiev)

        # RA值（右对齐，和达成率同行）
        ra_val = song.get("ra", 0)
        if ra_val > 0:
            ra_str = f"→{ra_val}"
            ra_tw = int(draw.textlength(ra_str, font=font_song))
            ra_color = "#FFD700" if ra_val >= 200 else "#FF8C00" if ra_val >= 150 else "#AAAAAA"
            draw.text((cx + CARD_SIZE - ra_tw - 4, achiev_y + 2), ra_str, fill=ra_color, font=font_song)


    # ---- 绘制 B35/B25 区域 ----
    grid_start_y = HEADER_H
    for i, song in enumerate(old_songs_sorted):
        col = i % COLS
        row = i // COLS
        draw_card(col, row, song, final_covers[i], grid_start_y)

    # ---- 分隔条 ----
    sep_y = grid_start_y + old_rows * CARD_H
    draw.rectangle([0, sep_y, W, sep_y + SEP_H], fill=ACCENT_LIGHT)
    draw.text((MARGIN, sep_y + 10), f"BEST {old_count} 旧曲", fill=ACCENT, font=font_sep)
    right_text = f"BEST {new_count} 新曲"
    right_tw = int(draw.textlength(right_text, font=font_sep))
    draw.text((W - MARGIN - right_tw, sep_y + 10), right_text, fill=ACCENT, font=font_sep)

    # ---- 绘制 B15 区域 ----
    b15_start_y = sep_y + SEP_H
    for i, song in enumerate(new_songs_sorted):
        col = i % COLS
        row = i // COLS
        ci = len(old_songs_sorted) + i
        draw_card(col, row, song, final_covers[ci], b15_start_y)

    # ---- 底部 ----
    footer_y = H - FOOTER_H
    draw.rectangle([0, footer_y, W, H], fill="#EFEFF0")
    draw.rectangle([0, footer_y, W, footer_y + 1], fill=BORDER)
    draw.text((MARGIN, footer_y + 8), "diving-fish.com", fill=TEXT_SECONDARY, font=font_footer)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_tw = int(draw.textlength(ts, font=font_footer))
    draw.text(((W - ts_tw) // 2, footer_y + 8), ts, fill=TEXT_SECONDARY, font=font_footer)
    count_text = f"{len(all_songs)} songs"
    count_tw = int(draw.textlength(count_text, font=font_footer))
    draw.text((W - MARGIN - count_tw, footer_y + 8), count_text, fill=TEXT_SECONDARY, font=font_footer)

    _t_end = time.time()
    logger.info(f"[图片生成] 总耗时 {_t_end - _t_start:.2f}s（封面 {_t_cover_end - _t_cover_start:.2f}s，绘制 {_t_end - _t_cover_end:.2f}s）")

    return img

# ---- 单曲查询图片生成 ----

def generate_song_image(song_info, user_score=None):
    """生成单曲查询图片"""
    title = song_info.get("title", "未知")
    artist = song_info.get("artist", "")
    genre = song_info.get("genre", "")
    bpm = song_info.get("bpm", "")
    diff_labels = ["Basic", "Advanced", "Expert", "Master", "Re:MASTER"]
    diff_colors = ["#32CD32", "#FFD700", "#FF8C00", "#FF1493", "#FF0000"]
    # 水鱼 API 的 ds 字段是数组 [basic, advanced, expert, master, re:master]
    ds_array = song_info.get("ds", [])
    if not isinstance(ds_array, list):
        ds_array = []

    # 图片参数
    W = 600
    H = 400
    BG = "#1a0a2e"
    CARD_BG = "#1e1e3a"
    HEADER_BG = "#0f0a20"
    TEXT_WHITE = "#e0e0e0"
    TEXT_DIM = "#888888"
    ACCENT = "#e94560"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_title = get_font(26, bold=True)
    font_info = get_font(18)
    font_small = get_font(15)
    font_diff = get_font(16)

    # 头部
    draw.rectangle([0, 0, W, 80], fill=HEADER_BG)
    draw.rectangle([0, 77, W, 80], fill=ACCENT)
    draw_text_with_stroke(draw, (25, 10), "maimai 单曲查询", font_title, ACCENT)
    draw_text_with_stroke(draw, (25, 45), title, font_title, TEXT_WHITE)

    # 歌曲信息
    y = 100
    info_lines = [
        f"艺术家: {artist}",
        f"分类: {genre}",
        f"BPM: {bpm}",
    ]
    for line in info_lines:
        draw_text_with_stroke(draw, (25, y), line, font_info, TEXT_WHITE)
        y += 28

    # 谱面定数
    y += 10
    draw_text_with_stroke(draw, (25, y), "谱面定数:", font_info, TEXT_DIM)
    y += 30

    diff_colors = ["#32CD32", "#FFD700", "#FF8C00", "#FF1493", "#FF0000"]
    for idx, label in enumerate(diff_labels):
        ds_val = ds_array[idx] if idx < len(ds_array) else None
        if ds_val is not None:
            color = diff_colors[idx] if idx < len(diff_colors) else TEXT_WHITE
            draw_text_with_stroke(draw, (40 + idx * 110, y), f"{label}: {ds_val}", font_diff, color)

    # 如果有用户成绩
    if user_score:
        y += 50
        draw.rectangle([15, y, W - 15, y + 2], fill=ACCENT)
        y += 15
        draw_text_with_stroke(draw, (25, y), "你的成绩:", font_info, ACCENT)
        y += 30

        achievements = user_score.get("achievements", 0)
        ra = user_score.get("ra", 0)
        dx_score = user_score.get("dxScore", 0)
        label = get_achiev_label(achievements)
        label_color = ACHIEV_COLORS.get(label, TEXT_WHITE)

        score_lines = [
            f"达成率: {achievements:.4f}%",
            f"评级: {label}",
            f"RA: {ra:.1f}",
            f"DX Score: {dx_score}",
        ]

        fc = user_score.get("fc", "")
        fs = user_score.get("fs", "")
        fdx = user_score.get("fdx", "")
        fc_str = ""
        if fdx in ("AP+", "FDX"):
            fc_str = fdx
        elif fs in ("AP+", "FS"):
            fc_str = fs
        elif fc in ("AP+", "AP", "FC"):
            fc_str = fc
        if fc_str:
            score_lines.append(f"全连: {fc_str}")

        for line in score_lines:
            if "评级" in line:
                draw_text_with_stroke(draw, (40, y), line, font_info, label_color)
            elif "全连" in line:
                fc_color = FC_COLORS.get(fc_str, TEXT_WHITE)
                draw_text_with_stroke(draw, (40, y), line, font_info, fc_color)
            else:
                draw_text_with_stroke(draw, (40, y), line, font_info, TEXT_WHITE)
            y += 28

        # 达成率进度条
        y += 5
        bar_x = 40
        bar_w = W - 80
        bar_h = 16
        draw_rounded_rect(draw, (bar_x, y, bar_x + bar_w, y + bar_h), radius=4, fill="#2a2a4a")
        fill_w = int(bar_w * min(achievements / 100.0, 1.0))
        if fill_w > 0:
            bar_color = get_achiev_bar_color(achievements)
            draw_rounded_rect(draw, (bar_x, y, bar_x + fill_w, y + bar_h), radius=4, fill=bar_color)

    return img

# ---- 舞萌命令处理 ----

mai_cmd = on_command("mai", priority=5)

@mai_cmd.handle()
async def handle_mai(event: MessageEvent):
    if not _check_group(event):
        return
    message = str(event.message)
    content = message.lstrip("/").strip()
    # 去掉 "mai" 命令前缀
    if content.lower().startswith("mai"):
        content = content[3:].strip()

    # /mai 歌曲 歌名 或 /mai song 歌名
    if content.startswith("歌曲") or content.lower().startswith("song"):
        song_name = content[2:].strip() if content.startswith("歌曲") else content[4:].strip()
        if not song_name:
            await mai_cmd.finish("...歌名呢。格式：/mai 歌曲 歌名")
            return
        try:
            # 并行获取歌曲数据和用户绑定信息
            user_id = str(event.user_id)
            binds = load_binds()

            async def _fetch_music_data():
                return await get_music_data()

            async def _fetch_player_data():
                if user_id in binds:
                    bind_info = binds[user_id]
                    # 兼容旧格式（字符串）和新格式（dict）
                    if isinstance(bind_info, dict):
                        df_username = bind_info.get("diving_fish", "")
                    elif isinstance(bind_info, str):
                        df_username = bind_info
                    else:
                        return None
                    if not df_username:
                        return None
                    try:
                        body = {"username": df_username, "b50": "1"}
                        http_client = get_http_client()
                        resp = await http_client.post(MAIMAI_API, json=body)
                        resp.raise_for_status()
                        return resp.json()
                    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                        logger.warning(f"[用户成绩] 获取失败: {e}")
                        return None
                return None

            # 并行请求：歌曲数据库 + 用户成绩
            results = await asyncio.gather(
                _fetch_music_data(),
                _fetch_player_data(),
                return_exceptions=True,
            )
            music_data = results[0] if not isinstance(results[0], Exception) else None
            player_data = results[1] if not isinstance(results[1], Exception) else None

            if not music_data:
                await mai_cmd.finish("...获取歌曲数据失败了。稍后再试。")
                return

            # 搜索匹配的歌曲
            matched = None
            for song in music_data:
                if song.get("title", "").lower() == song_name.lower():
                    matched = song
                    break
            if not matched:
                # 模糊搜索
                for song in music_data:
                    if song_name.lower() in song.get("title", "").lower():
                        matched = song
                        break

            if not matched:
                await mai_cmd.finish(f"找不到叫「{song_name}」的歌。检查一下歌名？")
                return

            # 从已获取的玩家数据中查找对应歌曲成绩
            user_score = None
            if player_data and "error" not in player_data and "status" not in player_data:
                charts = player_data.get("charts", {})
                all_songs = charts.get("dx", []) + charts.get("sd", [])
                for s in all_songs:
                    if str(s.get("song_id", "")) == str(matched.get("id", "")) or s.get("title", "") == matched.get("title", ""):
                        user_score = s
                        break

            song_img = generate_song_image(matched, user_score)
            buf = io.BytesIO()
            song_img.save(buf, format="PNG")
            buf.seek(0)
            await mai_cmd.finish(MessageSegment.image(buf))

        except FinishedException:
            raise
        except httpx.TimeoutException:
            await mai_cmd.finish("...水鱼API超时了，网络可能不太稳定，稍后再试吧。")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                await mai_cmd.finish("...请求太频繁了，水鱼限制了访问。等一会儿再试。")
            elif status >= 500:
                await mai_cmd.finish(f"...水鱼服务器好像挂了（HTTP {status}）。过会儿再试。")
            else:
                await mai_cmd.finish(f"...请求出错了（HTTP {status}）。稍后再试。")
        except httpx.ConnectError:
            await mai_cmd.finish("...连不上水鱼服务器。检查一下网络？")
        except Exception as e:
            logger.error(f"[单曲查询] 出错: {e}")
            await mai_cmd.finish("查询出错了，稍后再试吧。")
        return

    # /mai 绑定 用户名 → 改为提示用新命令
    if content.startswith("绑定"):
        await mai_cmd.finish("...绑定命令已更新：\n/绑定 好友码 — 绑定好友码（查牌子用）\n/绑定水鱼 用户名 — 绑定水鱼账号（查B50用）")
        return

    # /mai 解绑 → 提示用新命令
    if content == "解绑":
        await mai_cmd.finish("...请直接发 /解绑")
        return

    # /mai b50 用户名 或 /mai b40 用户名
    is_b50 = False
    if content.lower().startswith("b50"):
        is_b50 = True
        username = content[3:].strip()
    elif content.lower().startswith("b40"):
        username = content[3:].strip()
    else:
        is_b50 = True
        username = content.strip()

    # 如果没给用户名，尝试用绑定的水鱼账号或token
    use_token = False
    if not username:
        user_id = str(event.user_id)
        binds = load_binds()
        bind_info = binds.get(user_id, {})
        # 兼容旧格式（字符串）和新格式（dict）
        if isinstance(bind_info, dict):
            df_token = bind_info.get("diving_fish_token", "")
            df_username = bind_info.get("diving_fish", "")
        elif isinstance(bind_info, str):
            df_token = ""
            df_username = bind_info
        else:
            df_token = ""
            df_username = ""
        # 优先用 token
        if df_token:
            use_token = True
        elif df_username:
            body_key = "username"
            username = df_username
        else:
            await mai_cmd.finish("...还没绑定。格式：/mai b50 用户名\n或 /绑定水鱼 用户名 /绑定token token")
            return
    else:
        body_key = "username"
        df_username = ""

    try:
        http_client = get_http_client()

        # 检查用户成绩缓存
        _cache_key = username or (str(event.user_id) if use_token else "")
        _cache_hit = False
        if _cache_key and _cache_key in _user_records_cache:
            _cached = _user_records_cache[_cache_key]
            if time.time() - _cached["time"] < _USER_RECORDS_TTL:
                data = _cached["data"]
                _convert_records_to_charts(data)
                _cache_hit = True
                logger.info(f"[mai] 用户成绩缓存命中: {_cache_key}")

        if not _cache_hit:
            if use_token:
                # 用 Import-Token 获取完整成绩（官方API：GET /player/records + Import-Token header）
                user_id = str(event.user_id)
                binds = load_binds()
                bind_info = binds.get(user_id, {})
                df_token = bind_info.get("diving_fish_token", "") if isinstance(bind_info, dict) else ""
                resp = await http_client.get(
                    "https://www.diving-fish.com/api/maimaidxprober/player/records",
                    headers={"Import-Token": df_token},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    logger.warning(f"[mai] Import-Token查分失败({resp.status_code}): {resp.text[:100]}")
            else:
                body = {body_key: username, "b50": "1"} if is_b50 else {body_key: username}
                resp = await http_client.post(MAIMAI_API, json=body, timeout=15.0)

                # 如果用用户名查分失败，尝试用QQ号
                if resp.status_code == 400:
                    user_id = str(event.user_id)
                    body2 = {"qq": user_id, "b50": "1"} if is_b50 else {"qq": user_id}
                    resp2 = await http_client.post(MAIMAI_API, json=body2, timeout=15.0)
                    if resp2.status_code == 200:
                        resp = resp2

            resp.raise_for_status()
            data = resp.json()

            # 如果是 /player/records 格式，转换为 charts.dx/sd
            _convert_records_to_charts(data)

            # 更新缓存
            if _cache_key and "error" not in data:
                _user_records_cache[_cache_key] = {"data": data, "time": time.time()}
                logger.info(f"[mai] 用户成绩已缓存: {_cache_key}")

        # 调试日志：打印返回数据的结构
        logger.debug(f"[mai] API返回数据 keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    logger.debug(f"[mai]   {k}: list[{len(v)}]")
                elif isinstance(v, dict):
                    logger.debug(f"[mai]   {k}: dict keys={list(v.keys())[:5]}")
                else:
                    logger.debug(f"[mai]   {k}: {str(v)[:100]}")

        if "error" in data and "charts" not in data:
            err_msg = data.get("error", data.get("message", "未知错误"))
            await mai_cmd.finish(f"查不到这个人。{err_msg}")
            return

        # 生成图片（异步，因为要下载封面）
        if _cache_hit:
            await mai_cmd.send("正在生成图片，请稍等...（数据可能有5分钟延迟）")
        else:
            await mai_cmd.send("正在生成图片，请稍等...")
        img = await generate_mai_image(data, is_b50)

        if img is None:
            await mai_cmd.finish("没有成绩数据。")
            return

        # 保存到内存并发送
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        await mai_cmd.finish(MessageSegment.image(buf))

    except httpx.TimeoutException:
        await mai_cmd.finish("...水鱼API超时了，网络可能不太稳定，稍后再试吧。")
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 429:
            await mai_cmd.finish("...请求太频繁了，水鱼限制了访问。等一会儿再试。")
        elif status >= 500:
            await mai_cmd.finish(f"...水鱼服务器好像挂了（HTTP {status}）。过会儿再试。")
        else:
            await mai_cmd.finish(f"...请求出错了（HTTP {status}）。稍后再试。")
    except httpx.ConnectError:
        await mai_cmd.finish("...连不上水鱼服务器。检查一下网络？")
    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"[B50查询] 出错: {e}")
        await mai_cmd.finish("查询出错了，稍后再试吧。")


# ========== 绑定系统（好友码 + 水鱼用户名） ==========

# 绑定数据结构：{qq号: {"friend_code": 好友码, "diving_fish": 水鱼用户名}}

mai_bind_cmd = on_command("绑定", priority=5)

@mai_bind_cmd.handle()
async def handle_mai_bind(event: MessageEvent):
    """绑定好友码：/绑定 好友码（仅私聊）"""
    if hasattr(event, 'group_id') and event.group_id:
        await mai_bind_cmd.finish("...绑定命令只能私聊使用。请私聊我发送。")
        return
    user_id = str(event.user_id)
    content = str(event.message).strip()
    for prefix in ["绑定"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        binds = load_binds()
        info = binds.get(user_id, {})
        fc = info.get("friend_code", "未绑定")
        df = info.get("diving_fish", "未绑定")
        await mai_bind_cmd.finish(f"当前绑定信息：\n好友码：{fc}\n水鱼账号：{df}")
        return

    # 验证好友码（纯数字，通常7-10位）
    try:
        friend_code = int(content)
        if friend_code < 1000000 or friend_code > 9999999999:
            raise ValueError
    except ValueError:
        await mai_bind_cmd.finish("...好友码格式不对。应该是7-10位纯数字。")
        return

    # 验证好友码是否有效（通过落雪API测试）
    try:
        http_client = get_http_client()
        test_url = f"https://maimai.lxns.net/api/v0/maimai/player/{friend_code}/plate/6101"
        resp = await http_client.get(test_url, timeout=10.0)
        if resp.status_code == 404:
            await mai_bind_cmd.finish("...找不到这个好友码对应的数据。检查一下？")
            return
    except httpx.TimeoutException:
        pass  # 超时不一定是好友码无效，继续绑定

    # 保存绑定
    binds = load_binds()
    if user_id not in binds:
        binds[user_id] = {}
    binds[user_id]["friend_code"] = friend_code
    save_binds(binds)
    await mai_bind_cmd.finish(f"[OK] 好友码 {friend_code} 绑定成功！\n现在可以直接发 /牌子 查询版本牌子了。")


# 绑定水鱼用户名（用于查分B50/B40）
mai_bind_df_cmd = on_command("绑定水鱼", priority=5)

@mai_bind_df_cmd.handle()
async def handle_mai_bind_df(event: MessageEvent):
    """绑定水鱼用户名：/绑定水鱼 用户名（仅私聊）"""
    if hasattr(event, 'group_id') and event.group_id:
        await mai_bind_df_cmd.finish("...绑定命令只能私聊使用。请私聊我发送。")
        return
    user_id = str(event.user_id)
    content = str(event.message).strip()
    for prefix in ["绑定水鱼"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await mai_bind_df_cmd.finish("...用户名呢。格式：/绑定水鱼 水鱼用户名")
        return

    binds = load_binds()
    if user_id not in binds:
        binds[user_id] = {}
    binds[user_id]["diving_fish"] = content
    save_binds(binds)
    await mai_bind_df_cmd.finish(f"[OK] 水鱼账号「{content}」绑定成功！\n现在可以直接发 /mai b50 查分了。")


# 解绑
mai_unbind_cmd = on_command("解绑", priority=5)

@mai_unbind_cmd.handle()
async def handle_mai_unbind(event: MessageEvent):
    """解绑：/解绑（仅私聊）"""
    if hasattr(event, 'group_id') and event.group_id:
        await mai_unbind_cmd.finish("...解绑只能私聊使用。请私聊我发送。")
        return
    user_id = str(event.user_id)
    binds = load_binds()
    if user_id in binds:
        old = binds.pop(user_id)
        save_binds(binds)
        fc = old.get("friend_code", "?")
        df = old.get("diving_fish", "?")
        await mai_unbind_cmd.finish(f"已解除绑定（好友码:{fc}，水鱼:{df}）。")
    else:
        await mai_unbind_cmd.finish("你本来就没绑定过。")


# 绑定水鱼Token（用于QQ号查分）
mai_bind_token_cmd = on_command("绑定token", priority=5)

@mai_bind_token_cmd.handle()
async def handle_mai_bind_token(event: MessageEvent):
    """绑定水鱼Token：/绑定token 你的token（仅私聊）"""
    if hasattr(event, 'group_id') and event.group_id:
        await mai_bind_token_cmd.finish("...绑定命令只能私聊使用。请私聊我发送。")
        return
    user_id = str(event.user_id)
    content = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["绑定token", "/绑定token"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    # 从内容中提取最长的十六进制字符串作为 token（支持换行）
    # 先去掉所有空白字符，再匹配
    content_clean = re.sub(r'\s+', '', content)
    hex_matches = re.findall(r'[0-9a-fA-F]{32,}', content_clean)
    if not hex_matches:
        await mai_bind_token_cmd.finish("...token呢。在水鱼官网→编辑个人资料→生成Token\n格式：/绑定token 你的token")
        return
    # 取最长的匹配（通常是真正的 token）
    token_clean = max(hex_matches, key=len)

    binds = load_binds()
    if user_id not in binds:
        binds[user_id] = {}
    binds[user_id]["diving_fish_token"] = token_clean
    save_binds(binds)
    logger.info(f"[绑定] Token已保存: user={user_id}, path={MAIMAI_BINDS_FILE}")
    await mai_bind_token_cmd.finish("[OK] 水鱼Token绑定成功！\n现在直接发 /mai b50 就能查分了。")


# ========== 版本牌子查询 ==========


mai_plate_cmd = on_command("牌子", priority=5)

@mai_plate_cmd.handle()
async def handle_mai_plate(event: MessageEvent):
    """查询版本牌子进度：/牌子（需要绑定水鱼Token）"""
    if not _check_group(event):
        return

    user_id = str(event.user_id)
    binds = load_binds()
    info = binds.get(user_id, {})
    df_token = info.get("diving_fish_token", "")
    df_username = info.get("diving_fish", "")

    if not df_token and not df_username:
        await mai_plate_cmd.finish("...还没绑定水鱼账号。私聊发 /绑定token 你的token 或 /绑定水鱼 用户名")
        return

    try:
        http_client = get_http_client()

        # 1. 获取用户完整成绩（带缓存）
        _plate_cache_key = f"plate_{user_id}"
        _plate_cache_hit = False
        if _plate_cache_key in _user_records_cache:
            _cached = _user_records_cache[_plate_cache_key]
            if time.time() - _cached["time"] < _USER_RECORDS_TTL:
                player_data = _cached["data"]
                _convert_records_to_charts(player_data)
                _plate_cache_hit = True
                logger.info(f"[牌子] 用户成绩缓存命中: {_plate_cache_key}")

        if not _plate_cache_hit:
            await mai_plate_cmd.send("正在获取成绩数据...")
            headers = {}
            if df_token:
                headers["Import-Token"] = df_token

            if df_token:
                # 用 Import-Token 获取完整成绩（GET 请求）
                resp = await http_client.get(
                    "https://www.diving-fish.com/api/maimaidxprober/player/records",
                    headers=headers,
                    timeout=15.0,
                )
            else:
                # 用用户名获取（POST 请求）
                resp = await http_client.post(
                    MAIMAI_API,
                    json={"username": df_username},
                    timeout=15.0,
                )

            if resp.status_code == 400:
                await mai_plate_cmd.finish("...获取成绩失败。可能是Token过期或用户设置了隐私保护。\n请重新绑定Token：/绑定token 新token")
                return
            resp.raise_for_status()
            player_data = resp.json()

            if "error" in player_data or "status" in player_data:
                err = player_data.get("error", player_data.get("message", "未知错误"))
                await mai_plate_cmd.finish(f"...查询失败：{err}")
                return

            # 如果是 /player/records 格式，转换为 charts.dx/sd
            _convert_records_to_charts(player_data)

            # 更新缓存
            _user_records_cache[_plate_cache_key] = {"data": player_data, "time": time.time()}
            logger.info(f"[牌子] 用户成绩已缓存: {_plate_cache_key}")
        else:
            await mai_plate_cmd.send("正在获取成绩数据...（数据可能有5分钟延迟）")

        # 2. 获取歌曲数据（版本信息）
        music_data = await get_music_data()
        if not music_data:
            await mai_plate_cmd.finish("...获取歌曲数据失败。稍后再试。")
            return

        # 构建歌曲版本映射
        song_version_map = _build_song_version_map(music_data)

        # 3. 提取用户所有成绩
        charts = player_data.get("charts", {})
        all_songs = charts.get("dx", []) + charts.get("sd", [])

        # 按版本分组，记录每首歌的最佳成绩
        # version_songs[version] = [(song_id, title, fc, fs, achievements)]
        version_songs = {}
        for s in all_songs:
            sid = int(s.get("song_id", 0))
            from_ver = song_version_map.get(sid, "") or song_version_map.get(sid % 10000, "")
            if not from_ver:
                continue
            if from_ver not in version_songs:
                version_songs[from_ver] = []
            version_songs[from_ver].append({
                "id": sid,
                "title": s.get("title", ""),
                "fc": str(s.get("fc", "")).lower().strip(),
                "fs": str(s.get("fs", "")).lower().strip(),
                "fdx": str(s.get("fdx", "")).lower().strip(),
                "achievements": s.get("achievements", 0),
            })

        # 4. 定义牌子检查函数
        def check_plate(songs, req_type):
            """检查一组歌曲是否满足牌子要求，返回 (完成数, 总数)"""
            if not songs:
                return 0, 0
            done = 0
            total = len(songs)
            for s in songs:
                fc = s["fc"]
                fs = s["fs"]
                fdx = s["fdx"]
                achiev = s["achievements"]
                if req_type == "FC":
                    if fc in ("fc", "fcp", "ap", "app"):
                        done += 1
                elif req_type == "AP":
                    if fc in ("ap", "app") or fdx in ("ap", "ap+"):
                        done += 1
                elif req_type == "FS":
                    if fs in ("fs", "fsp", "fsd", "fsdp") or fdx in ("fs", "fs+"):
                        done += 1
                elif req_type == "CLEAR":
                    if achiev > 0:
                        done += 1
                elif req_type == "SSS":
                    if achiev >= 100.0:
                        done += 1
            return done, total

        # 5. 定义版本牌子列表（简化版，只保留主要牌子）
        PLATE_DEFS = [
            # (版本名, 牌子类型, 显示名)
            ("maimai", "FC", "真極"), ("maimai", "AP", "真神"), ("maimai", "FS", "真舞舞"),
            ("maimai PLUS", "FC", "超極"), ("maimai PLUS", "SSS", "超将"),
            ("maimai PLUS", "AP", "超神"), ("maimai PLUS", "FS", "超舞舞"),
            ("GreeN", "FC", "橙極"), ("GreeN", "SSS", "橙将"),
            ("GreeN", "AP", "橙神"), ("GreeN", "FS", "橙舞舞"),
            ("GreeN PLUS", "FC", "暁極"), ("GreeN PLUS", "SSS", "暁将"),
            ("GreeN PLUS", "AP", "暁神"), ("GreeN PLUS", "FS", "暁舞舞"),
            ("ORANGE", "FC", "桃極"), ("ORANGE", "SSS", "桃将"),
            ("ORANGE", "AP", "桃神"), ("ORANGE", "FS", "桃舞舞"),
            ("ORANGE PLUS", "FC", "櫻極"), ("ORANGE PLUS", "SSS", "櫻将"),
            ("ORANGE PLUS", "AP", "櫻神"), ("ORANGE PLUS", "FS", "櫻舞舞"),
            ("MURASAKi", "FC", "紫極"), ("MURASAKi", "SSS", "紫将"),
            ("MURASAKi", "AP", "紫神"), ("MURASAKi", "FS", "紫舞舞"),
            ("MURASAKi PLUS", "FC", "菫極"), ("MURASAKi PLUS", "SSS", "菫将"),
            ("MURASAKi PLUS", "AP", "菫神"), ("MURASAKi PLUS", "FS", "菫舞舞"),
            ("MiLK", "FC", "白極"), ("MiLK", "SSS", "白将"),
            ("MiLK", "AP", "白神"), ("MiLK", "FS", "白舞舞"),
            ("MiLK PLUS", "FC", "雪極"), ("MiLK PLUS", "SSS", "雪将"),
            ("MiLK PLUS", "AP", "雪神"), ("MiLK PLUS", "FS", "雪舞舞"),
            ("FiNALE", "FC", "輝極"), ("FiNALE", "SSS", "輝将"),
            ("FiNALE", "AP", "輝神"), ("FiNALE", "FS", "輝舞舞"),
            ("DX", "FC", "熊極"), ("DX", "SSS", "熊将"),
            ("DX", "AP", "熊神"), ("DX", "FS", "熊舞舞"),
            ("DX 2021", "FC", "爽極"), ("DX 2021", "SSS", "爽将"),
            ("DX 2021", "AP", "爽神"), ("DX 2021", "FS", "爽舞舞"),
            ("DX 2022", "FC", "宙極"), ("DX 2022", "SSS", "宙将"),
            ("DX 2022", "AP", "宙神"), ("DX 2022", "FS", "宙舞舞"),
            ("DX 2023", "FC", "祭極"), ("DX 2023", "SSS", "祭将"),
            ("DX 2023", "AP", "祭神"), ("DX 2023", "FS", "祭舞舞"),
            ("DX 2024", "FC", "双極"), ("DX 2024", "SSS", "双将"),
            ("DX 2024", "AP", "双神"), ("DX 2024", "FS", "双舞舞"),
        ]

        # 全版本牌子
        ALL_PLATES = [
            ("全版本", "CLEAR", "覇者"), ("全版本", "FC", "舞極"),
            ("全版本", "SSS", "舞将"), ("全版本", "AP", "舞神"),
            ("全版本", "FS", "舞舞舞"),
        ]

        # 6. 按代分组计算牌子进度
        msg = "版本牌子进度\n━━━━━━━━━━━━━━\n"
        total_plates = len(PLATE_DEFS) + len(ALL_PLATES)
        done_plates = 0

        # 按版本分组显示
        from itertools import groupby
        sorted_plates = sorted(PLATE_DEFS, key=lambda x: x[0])
        for ver, group in groupby(sorted_plates, key=lambda x: x[0]):
            msg += f"【{ver}】\n"
            for _, req_type, plate_name in group:
                songs = version_songs.get(ver, [])
                done, total = check_plate(songs, req_type)
                if total == 0:
                    msg += f"  [-] {plate_name} 无数据\n"
                elif done >= total:
                    done_plates += 1
                    msg += f"  [✓] {plate_name} {done}/{total}\n"
                else:
                    msg += f"  [ ] {plate_name} {done}/{total}\n"

        # 全版本牌子
        all_song_list = []
        for ver_songs in version_songs.values():
            all_song_list.extend(ver_songs)

        msg += "━━━━━━━━━━━━━━\n【全版本】\n"
        for ver, req_type, plate_name in ALL_PLATES:
            done, total = check_plate(all_song_list, req_type)
            if total == 0:
                msg += f"  [-] {plate_name} 无数据\n"
            elif done >= total:
                done_plates += 1
                msg += f"  [✓] {plate_name} {done}/{total}\n"
            else:
                msg += f"  [ ] {plate_name} {done}/{total}\n"

        msg += f"━━━━━━━━━━━━━━\n进度：{done_plates}/{total_plates}"
        if done_plates == total_plates:
            msg += " 全制霸！"
        await mai_plate_cmd.finish(msg)

    except httpx.TimeoutException:
        await mai_plate_cmd.finish("...水鱼API超时了，稍后再试。")
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 400:
            await mai_plate_cmd.finish("...获取成绩失败。Token可能过期了，请重新绑定。")
        else:
            await mai_plate_cmd.finish(f"...请求出错（HTTP {status}）。")
    except Exception as e:
        logger.error(f"[牌子查询] 出错: {e}")
        await mai_plate_cmd.finish("...查询出错了，稍后再试。")
