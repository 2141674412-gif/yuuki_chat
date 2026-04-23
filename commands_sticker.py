# ========== 表情包系统 ==========

import os
import random

from nonebot.adapters.onebot.v11 import MessageSegment

# 表情包目录
_STICKER_DIR = os.path.join(os.path.dirname(__file__), "assets", "stickers")

# 关键词 → 表情文件映射
_STICKER_MAP = {
    "害羞": "害羞.png",
    "脸红": "害羞.png",
    "紧张": "紧张.png",
    "汗": "汗颜.gif",
    "汗颜": "汗颜.gif",
    "尴尬": "汗颜.gif",
    "失落": "失落.png",
    "难过": "失落.png",
    "伤心": "失落.png",
    "吓": "吓.png",
    "害怕": "吓.png",
    "呆": "呆.gif",
    "呆住": "呆.gif",
    "瘫": "瘫.png",
    "无奈": "瘫.png",
    "抱头": "抱头.png",
    "？？？": "啊？？？.png",
    "哎嘿嘿": "哎嘿嘿.png",
    "嘿嘿": "哎嘿嘿.png",
    "哼": "哼哼.png",
    "哼哼": "哼哼.png",
    "魅惑": "魅惑.png",
    "自信": "自信.png",
    "元气": "元气.png",
    "加油": "元气.png",
    "耶": "耶比~.png",
    "耶比": "耶比~.png",
    "拜托": "拜托拜托.png",
    "求你": "拜托拜托.png",
    "消失": "给我消失.png",
    "拿来": "给我拿来.png",
    "制裁": "制裁！.png",
    "正义": "制裁！.png",
    "诸君": "诸君！！！.gif",
    "咖喱": "死亡咖喱.gif",
    "芭菲": "吃芭菲.png",
    "甜食": "吃芭菲.png",
    "猫": "neko.png",
    "喜欢": "suki.png",
    "工作": "workwork.png",
    "打工": "workwork.png",
}

# 触发概率
_TRIGGER_RATE = 0.35

# 模块加载时预计算：排序关键词 + 缓存有效文件路径
_SORTED_KEYWORDS = sorted(_STICKER_MAP.keys(), key=len, reverse=True)
_VALID_STICKERS = {}  # keyword → filepath（仅包含文件存在的）
for _kw in _SORTED_KEYWORDS:
    _fp = os.path.join(_STICKER_DIR, _STICKER_MAP[_kw])
    if os.path.exists(_fp) and os.path.getsize(_fp) > 0:
        _VALID_STICKERS[_kw] = _fp


def get_sticker_message(text: str):
    """根据文本内容匹配关键词，返回表情包MessageSegment或None"""
    for keyword in _SORTED_KEYWORDS:
        if keyword in text:
            if random.random() > _TRIGGER_RATE:
                return None
            filepath = _VALID_STICKERS.get(keyword)
            if filepath:
                return MessageSegment.image(f"file://{filepath}")
    return None


def list_stickers():
    """列出所有可用表情包"""
    result = []
    seen = set()
    for keyword, filename in _STICKER_MAP.items():
        if filename in seen:
            continue
        seen.add(filename)
        filepath = _VALID_STICKERS.get(keyword)
        exists = filepath is not None
        result.append(f"{'✓' if exists else '✗'} {filename} ← {keyword}")
    return result
