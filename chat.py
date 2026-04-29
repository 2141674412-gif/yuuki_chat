# 标准库
import asyncio
import base64
import functools
import json
import os
import random
import re
import threading
import time
from datetime import datetime
from io import BytesIO

# 第三方库
import numpy as np
from nonebot import get_bot, get_driver, logger, on_message

# 获取superusers（延迟获取，等driver初始化后）
def _get_superusers() -> set:
    try:
        cfg = get_driver().config
        return set(str(s) for s in getattr(cfg, "superusers", set()))
    except Exception:
        return set()
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from openai import APIError, APITimeoutError, OpenAI
from PIL import Image
from qreader import QReader

# 本地模块
from .config import ALLOWED_GROUPS, COMMAND_NAMES, load_persona, DATA_DIR, CHAT_WHITELIST
from .commands_base import user_blacklist
from .commands_sticker import get_sticker_message

# 预编译正则表达式
_RE_AT_TAG = re.compile(r'\[at:qq=\d+\]')
_RE_CQ_TAG = re.compile(r'\[CQ:[^\]]+\]')

# ========== 配置读取（兼容 .env 大写和 section 两种格式） ==========

# 配置缓存（NoneBot 配置启动后不变，缓存 dict 避免重复创建）
_config_dict = None
try:
    _config_dict = get_driver().config.dict()
except Exception:
    pass

def _cfg(key: str, default: str = "") -> str:
    """读取配置，依次尝试：os.getenv(大写) → driver.config → os.getenv(小写) → 默认值"""
    def _clean(v: str) -> str:
        return v.strip().strip("`").strip("'").strip('"')
    # 1. 环境变量（大写）
    val = os.getenv(key.upper(), "")
    if val:
        return _clean(val)
    # 2. NoneBot driver.config（使用缓存的 dict）
    if _config_dict is not None:
        val = _config_dict.get(key, "") or _config_dict.get(key.upper(), "")
        if val:
            return _clean(str(val))
    # 3. 环境变量（小写）
    val = os.getenv(key, "")
    if val:
        return _clean(val)
    return default

def _cfg_int(key: str, default: int) -> int:
    try:
        return int(_cfg(key, str(default)))
    except (ValueError, TypeError):
        return default

# 初始化 OpenAI 客户端（单例模式，支持断线重连）
_client = None
_client_lock = threading.Lock()

# ---- 全局 HTTP 客户端（连接池复用） ----
from .utils import get_shared_http_client as _get_http_client

# ---- 截图记账去重缓存（持久化） ----
_ACCOUNTING_SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "accounting_seen.json")
_accounting_seen_cache = {}

def _get_accounting_seen():
    global _accounting_seen_cache
    if not _accounting_seen_cache and os.path.exists(_ACCOUNTING_SEEN_FILE):
        try:
            with open(_ACCOUNTING_SEEN_FILE, "r", encoding="utf-8") as f:
                _accounting_seen_cache = json.load(f)
        except Exception:
            _accounting_seen_cache = {}
    return _accounting_seen_cache

def _save_accounting_seen():
    try:
        os.makedirs(os.path.dirname(_ACCOUNTING_SEEN_FILE), exist_ok=True)
        with open(_ACCOUNTING_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(_accounting_seen_cache, f)
    except Exception:
        pass

# ---- 截图记账余额缓存 ----
_accounting_balance = {}  # {user_id: latest_balance}


def _get_client() -> OpenAI:
    """获取 OpenAI 客户端单例，如果连接失败则重新创建。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _create_client()
    return _client


def _create_client() -> OpenAI:
    """创建 OpenAI 客户端（带连接超时和自动重试）"""
    import httpx
    # 自定义httpx客户端：连接超时5秒，读取超时60秒，自动重连
    http_client = httpx.Client(
        timeout=httpx.Timeout(5.0, connect=10.0, read=60.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        transport=httpx.HTTPTransport(retries=2),
    )
    return OpenAI(
        api_key=_cfg("api_key", "ollama"),
        base_url=_cfg("api_base", "http://127.0.0.1:11434/v1"),
        http_client=http_client,
        max_retries=2,  # SDK级别重试
        timeout=httpx.Timeout(30.0, connect=10.0),  # 30秒超时，连接10秒
    )


def _reconnect_client():
    """重建 OpenAI 客户端以恢复连接。"""
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = _create_client()


# 对话历史存储
chat_history = {}

# 群消息记录（用于词云统计）
_group_chat_log = {}  # {group_id: [(timestamp, user_id, text), ...]}
_GROUP_CHAT_LOG_TTL = 7 * 24 * 3600  # 保留最近 7 天的数据（秒）

# 用户画像记忆（记住用户喜好/话题/习惯）
_user_profiles = {}  # {user_id: {"topics": [...], "mentioned_count": int, "last_active": float}}
_PROFILE_FILE = os.path.join(DATA_DIR, "user_profiles.json")

# ========== 防踢优化开关 ==========
_anti_kick_enabled = True  # 防踢优化总开关

# ========== 全局消息发送速率限制 ==========
_send_times: list[float] = []  # 记录最近发送时间戳
_RATE_LIMIT_5S = 3   # 5秒内最多3条
_RATE_LIMIT_60S = 20  # 60秒内最多20条

async def _rate_limited_send(matcher, message: str):
    """带速率限制的消息发送"""
    if _anti_kick_enabled:
        # 模拟人类打字延迟
        import random as _random
        delay = _random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)
    now = time.time()
    if _anti_kick_enabled:
        # 清理过期记录
        _send_times[:] = [t for t in _send_times if now - t < 60]
        # 检查限制
        recent_5s = sum(1 for t in _send_times if now - t < 5)
        if recent_5s >= _RATE_LIMIT_5S:
            await asyncio.sleep(2)  # 等待2秒
        if len(_send_times) >= _RATE_LIMIT_60S:
            await asyncio.sleep(5)  # 等待5秒
        _send_times.append(time.time())
    try:
        await matcher.send(message)
    except Exception:
        pass

# ========== 插话冷却 ==========
_last_chatter_time: dict[int, float] = {}  # {group_id: timestamp}
_CHATTER_COOLDOWN = 60  # 同一群60秒内最多插话一次

# ========== 错误静默 ==========
_consecutive_errors = 0
_error_silence_until = 0.0

def _load_user_profiles():
    global _user_profiles
    try:
        if os.path.exists(_PROFILE_FILE):
            with open(_PROFILE_FILE, "r", encoding="utf-8") as f:
                _user_profiles = json.load(f)
    except Exception:
        pass

def _save_user_profiles():
    try:
        with open(_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_profiles, f, ensure_ascii=False)
    except Exception:
        pass

def _add_memory(profile, memory_text):
    """添加长期记忆，去重，上限20条"""
    memories = profile.get("memories", [])
    # 简单去重：如果新记忆的核心词已存在则跳过
    for m in memories:
        if any(w in m for w in memory_text if len(w) >= 2):
            return
    memories.append(memory_text)
    if len(memories) > 20:
        memories = memories[-20:]
    profile["memories"] = memories

def _update_user_profile(user_id: str, message: str):
    """更新用户画像"""
    if user_id not in _user_profiles:
        _user_profiles[user_id] = {"topics": [], "mentioned_count": 0, "last_active": 0, "name": ""}
    profile = _user_profiles[user_id]
    profile["last_active"] = time.time()
    profile["mentioned_count"] = profile.get("mentioned_count", 0) + 1
    # 提取关键词作为话题标签
    message_lower = message.lower()
    for keyword in _TOPIC_KEYWORDS:
        if keyword.lower() in message_lower and keyword not in profile["topics"]:
            profile["topics"].append(keyword)
            if len(profile["topics"]) > 20:
                profile["topics"] = profile["topics"][-20:]

    # 好感度系统
    if "affinity" not in profile:
        # 旧用户迁移：根据历史互动次数推算初始好感度
        mentioned = profile.get("mentioned_count", 0)
        if mentioned >= 100:
            profile["affinity"] = 60
        elif mentioned >= 50:
            profile["affinity"] = 40
        elif mentioned >= 20:
            profile["affinity"] = 20
        else:
            profile["affinity"] = 5
    if "interaction_count" not in profile:
        profile["interaction_count"] = 0
    profile["interaction_count"] += 1

    # 主人好感度固定999，不衰减
    if user_id == _get_owner_qq():
        profile["affinity"] = 999
    else:
        msg_lower = message.lower()

        # === 好感度增减（基于希亚的性格特点） ===
        delta = 0

        # --- 大幅增加好感 ---
        # 夸希亚
        if any(w in msg_lower for w in ["可爱", "好可爱", "最可爱", "卡哇伊", "kawaii"]):
            delta += 3  # 表面不在意但心里开心
        # 送/提到希亚喜欢的东西
        if any(w in msg_lower for w in ["芭菲", "巴菲", "parfait", "猫", "猫咪", "猫猫", "甜点", "蛋糕", "冰淇淋", "巧克力"]):
            delta += 3
        # 关心希亚
        if any(w in msg_lower for w in ["希亚你", "你累吗", "辛苦了", "注意休息", "别太累", "早安希亚", "晚安希亚"]):
            delta += 2
        # 叫希亚的名字（亲密感）
        if any(w in msg_lower for w in ["希亚", "小希亚", "noa"]):
            delta += 1
        # 聊希亚感兴趣的话题
        if any(w in msg_lower for w in ["舞萌", "maimai", "音游", "动漫", "游戏", "猫"]):
            delta += 1
        # 和希亚一起吐槽/共鸣
        if any(w in msg_lower for w in ["确实", "同意", "对啊", "哈哈", "笑死", "太真实"]):
            delta += 1

        # --- 大幅降低好感 ---
        # 说希亚矮/身高相关（雷点！）
        if any(w in msg_lower for w in ["小矮子", "矮冬瓜", "身高146", "一米四", "好矮", "长不高", "萝莉", "小学生"]):
            delta -= 5  # 非常生气
        # 叫希亚奇怪的外号
        if any(w in msg_lower for w in ["正义的伙伴", "帕菲女王"]):
            delta -= 3  # 烦死了别这么叫
        # 提到希亚讨厌的东西
        if any(w in msg_lower for w in ["虫", "蟑螂", "蜘蛛", "恐怖片", "鬼故事"]):
            delta -= 2  # 不舒服
        # 命令/使唤语气
        if any(w in msg_lower for w in ["给我", "快点", "赶紧", "闭嘴", "滚", "笨蛋", "白痴"]):
            delta -= 2
        # 无视/冷淡
        if len(message.strip()) <= 2 and not any(w in msg_lower for w in ["早", "晚安", "嗨", "嗯"]):
            delta -= 1  # 太冷淡了

        # --- 基础互动 ---
        if delta == 0:
            delta = 1  # 普通互动+1

        # 应用好感度变化
        old_affinity = profile["affinity"]
        profile["affinity"] = max(0, min(99, profile["affinity"] + delta))

        # 长时间不互动好感度衰减（超过24小时没互动，每次-1）
        if profile["last_active"] > 0:
            hours_since = (time.time() - profile["last_active"]) / 3600
            if hours_since > 24:
                decay = min(int(hours_since / 24), 5)
                profile["affinity"] = max(0, profile["affinity"] - decay)

    # 长期记忆：提取关键信息
    if "memories" not in profile:
        profile["memories"] = []
    # 从消息中提取可能的记忆（简单规则）
    # 检测自我介绍
    name_match = re.search(r'我叫(\S+)|我是(\S+)', message)
    if name_match:
        name = name_match.group(1) or name_match.group(2)
        if name and len(name) <= 10:
            profile["name"] = name
            _add_memory(profile, f"这个用户的名字是{name}")
    # 检测喜好表达
    like_match = re.search(r'(喜欢|爱|最爱|最爱吃)(.{1,10})', message)
    if like_match:
        _add_memory(profile, f"喜欢{like_match.group(2)}")
    # 检测生日
    bday_match = re.search(r'生日是(\d{1,2})[月-](\d{1,2})', message)
    if bday_match:
        _add_memory(profile, f"生日是{bday_match.group(1)}月{bday_match.group(2)}日")

    # 定期保存
    if random.random() < 0.1:  # 10%概率保存，避免频繁IO
        _save_user_profiles()

def _get_user_context(user_id: str) -> str:
    """获取用户上下文信息（用于AI prompt）"""
    if user_id not in _user_profiles:
        return ""
    profile = _user_profiles[user_id]
    parts = []
    if profile.get("topics"):
        parts.append(f"这个用户经常聊: {', '.join(profile['topics'][-5:])}")
    if profile.get("mentioned_count", 0) > 10:
        parts.append("这个用户经常和你聊天，算是老熟人了")
    affinity = profile.get("affinity", 0)
    if affinity >= 999:
        parts.append("这是你的主人，最亲密的人，可以撒娇、任性，不用敬语")
    elif affinity >= 80:
        parts.append("和这个用户非常亲密，可以撒娇、开玩笑")
    elif affinity >= 60:
        parts.append("和这个用户关系不错，可以轻松聊天")
    elif affinity >= 40:
        parts.append("和这个用户是普通朋友，保持礼貌")
    elif affinity >= 20:
        parts.append("和这个用户不太熟，保持距离")
    else:
        parts.append("和这个用户是陌生人，冷淡对待")
    memories = profile.get("memories", [])
    if memories:
        parts.append("关于这个用户的记忆: " + ", ".join(memories[-5:]))
    return "\n".join(parts) if parts else ""


def _cleanup_group_chat_log():
    """清理超过 7 天的群消息记录"""
    now = time.time()
    cutoff = now - _GROUP_CHAT_LOG_TTL
    total = 0
    for gid in list(_group_chat_log.keys()):
        _group_chat_log[gid] = [
            entry for entry in _group_chat_log[gid]
            if entry[0] > cutoff
        ]
        total += len(_group_chat_log[gid])
        if not _group_chat_log[gid]:
            del _group_chat_log[gid]
    # 全局条目上限保护
    if total > 50000:
        for gid in list(_group_chat_log.keys()):
            if len(_group_chat_log[gid]) > 5000:
                _group_chat_log[gid] = _group_chat_log[gid][-5000:]

# 情绪关键词
_MOOD_KEYWORDS = {
    "positive": ["开心", "哈哈", "笑死", "太好了", "好棒", "可爱", "厉害", "牛", "赞", "感谢", "谢谢", "爱你", "么么", "嘿嘿"],
    "negative": ["难过", "伤心", "哭", "烦", "生气", "讨厌", "累", "困", "痛", "难受", "无聊", "孤独", "寂寞", "焦虑", "压力"],
    "excited": ["！！！", "！！", "啊啊啊", "冲", "加油", "干", "太强了", "无敌", "绝了", "神"],
}

def _detect_group_mood(group_id):
    """检测群聊情绪氛围"""
    msgs = _group_chat_log.get(group_id, [])
    if not msgs:
        return "neutral", ""
    recent = msgs[-10:]  # 最近10条消息
    scores = {"positive": 0, "negative": 0, "excited": 0}
    for _, _, text in recent:
        text_lower = text.lower()
        for mood, keywords in _MOOD_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[mood] += 1
    total = sum(scores.values())
    if total == 0:
        return "neutral", ""
    dominant = max(scores, key=scores.get)
    if scores[dominant] >= 2:
        mood_map = {
            "positive": "群里气氛很好，大家很开心",
            "negative": "群里气氛有些低落，有人不太开心",
            "excited": "群里气氛很热烈，大家很激动",
        }
        return dominant, mood_map.get(dominant, "")
    return "neutral", ""

# 对话历史时间戳，用于定期清理
_history_timestamps = {}
_HISTORY_TTL = 14400  # 4 小时过期时间（秒）


def _cleanup_old_histories():
    """清理超过 TTL 的旧对话历史，防止内存泄漏。"""
    now = time.time()
    expired_users = [
        uid for uid, ts in _history_timestamps.items()
        if now - ts > _HISTORY_TTL
    ]
    for uid in expired_users:
        chat_history.pop(uid, None)
        _history_timestamps.pop(uid, None)


# 将命令列表转为集合，加速查找
COMMAND_SET = set(COMMAND_NAMES)

# 加载用户画像数据
_load_user_profiles()

# ========== 艾特检测（睡觉模式） ==========

# 将命令列表转为集合，加速查找主人QQ号
@functools.lru_cache(maxsize=1)
def _get_owner_qq() -> str:
    """获取主人 QQ 号"""
    try:
        superusers = get_driver().config.dict().get("superusers", [])
        if superusers:
            return str(superusers[0])
    except Exception:
        pass
    return "2141674412"  # 默认值

# 睡觉回复池
_SLEEP_REPLIES = [
    "...zzz",
    "...别吵，在睡觉。",
    "...zzZ...什么事。",
    "...呼...谁啊。",
    "...再吵把你扔出去。",
    "...困死了，明天再说。",
    "...嗯...zzz...",
    "...五分钟...再睡五分钟...",
    "...别艾特了，在睡觉呢。",
    "zzZ...别吵...再睡五分钟...",
    "唔...谁啊...大半夜的...",
    "困死了...明天再聊...",
    "正义的伙伴需要...充电...",
    "呼...呼...（翻了个身）",
    "再吵就把你列入黑名单...",
    "zzZ...（抱紧被子）",
    "你知不知道叫醒睡美人会被诅咒的...",
    "五分钟...就五分钟...",
    "（揉眼睛）...几点了...",
    "还没到起床时间呢...",
    "希亚...在充电中...请勿打扰...",
    "嘘...小声点...我还没醒...",
    "（把被子拉过头顶）",
    "明天一定找你算账...",
    "...再闹就把你拉黑...",
    "...做梦呢...别叫醒我...",
    "...zzz...（流口水）",
]

_sleep_cmd = on_message(priority=0, block=False)

# 防踢开关命令
_antikick_cmd = on_command("防踢", priority=1, block=True)

@_antikick_cmd.handle()
async def handle_antikick(event: GroupMessageEvent, matcher: Matcher):
    global _anti_kick_enabled
    user_id = str(event.user_id)
    if user_id != _get_owner_qq():
        await matcher.send("只有主人才能操作这个~")
        return
    arg = event.get_plaintext().strip()
    if arg in ("开", "开启", "on", "1"):
        _anti_kick_enabled = True
        await matcher.send("防踢优化已开启 ✅\n（速率限制+随机延迟+插话冷却+错误静默）")
    elif arg in ("关", "关闭", "off", "0"):
        _anti_kick_enabled = False
        await matcher.send("防踢优化已关闭 ❌\n（回复将无延迟，注意被风控风险）")
    else:
        status = "开启 ✅" if _anti_kick_enabled else "关闭 ❌"
        await matcher.send(f"防踢优化状态: {status}\n\n用法: /防踢 开|关")

# 全局群白名单拦截器（最高优先级，阻断非白名单群的所有消息处理）
_group_gate = on_message(priority=-100, block=False)

@_group_gate.handle()
async def _block_non_whitelist(event: MessageEvent):
    """非白名单群的群消息直接阻断，不进入任何后续handler"""
    gid = getattr(event, 'group_id', None)
    if gid and gid not in ALLOWED_GROUPS:
        # 非白名单群，设置block=True阻止后续handler
        _group_gate.block = True

@_sleep_cmd.handle()
async def handle_sleep_at(event: GroupMessageEvent):
    """群里有人@bot时，如果不是主人@的，回复在睡觉"""
    if not hasattr(event, 'group_id') or not event.group_id:
        return

    # 群白名单检查
    if event.group_id not in ALLOWED_GROUPS:
        return

    # 黑名单检查
    try:
        from .commands_base import user_blacklist, superusers
        uid = str(event.user_id)
        if uid not in superusers and uid in user_blacklist:
            return
    except Exception:
        pass

    # 检查是否@了bot
    if not getattr(event, 'to_me', False):
        return

    user_id = str(event.user_id)

    # 主人@bot或@希亚，不触发睡觉模式（交给handle_chat处理）
    if user_id == _get_owner_qq():
        return

    # 检查消息里是否有"希亚"（主人提到希亚不算）
    message = str(event.message)
    # 去掉@标记后检查纯文本
    plain = _RE_AT_TAG.sub('', message).strip()
    if "希亚" in plain or "Noa" in plain.lower():
        return

    # 随机回复
    reply = random.choice(_SLEEP_REPLIES)
    await _rate_limited_send(_sleep_cmd, reply)


# 消息处理（优先级 1，block=False 让命令能继续传递）
chat = on_message(priority=1, block=False)

@chat.handle()
async def handle_chat(event: MessageEvent):
    user_id = str(event.user_id)
    message = str(event.message)

    # 提取纯文本（去掉 @ 标记和开头的 /）
    plain_text = _RE_AT_TAG.sub('', message).strip()
    if plain_text.startswith("/"):
        plain_text = plain_text[1:].strip()

    # 如果是命令消息，不处理（使用集合加速查找）
    if plain_text in COMMAND_SET or any(plain_text.startswith(cmd + " ") for cmd in COMMAND_SET):
        return

    # 黑名单检查
    if user_id in user_blacklist:
        return

    # 如果消息包含图片，跳过（交给识图handler处理）
    if any(seg.type == "image" for seg in event.message):
        return

    # 跳过合并转发消息（NapCat 不上报，但保险起见）
    if any(seg.type == "forward" for seg in event.message):
        return

    # 跳过B站链接（交给B站handler处理）
    if re.search(r'bilibili\.com/video/|b23\.tv/', plain_text):
        return

    # 过滤无意义消息：纯表情、纯标点、过短无内容
    # 去掉所有表情字符后检查剩余内容
    import unicodedata
    text_no_emoji = ''.join(
        c for c in plain_text
        if unicodedata.category(c) not in ('So', 'Sk', 'Sc')  # Symbol other/Modifier/ Currency
    ).strip()
    text_no_punct = re.sub(r'[^\w\u4e00-\u9fff]', '', text_no_emoji).strip()
    if not text_no_punct and len(plain_text) <= 20:
        # 纯表情/标点消息，不调AI
        return
    if len(text_no_punct) <= 1 and not any(kw in plain_text for kw in ["希亚", "noa", "Noa"]):
        # 单个字且不是叫bot名字，跳过
        return

    # 记录群消息到 _group_chat_log（用于词云统计）
    if hasattr(event, 'group_id') and event.group_id:
        if event.group_id in ALLOWED_GROUPS and plain_text:
            if event.group_id not in _group_chat_log:
                _group_chat_log[event.group_id] = []
            _group_chat_log[event.group_id].append(
                (time.time(), user_id, plain_text)
            )
            # 定期清理过期记录
            if len(_group_chat_log[event.group_id]) > 10000:
                _cleanup_group_chat_log()

    # 如果是群聊，需要@bot或提到希亚才回复
    is_at_me = getattr(event, 'to_me', False) or "希亚" in message or "Noa" in message or "noa" in message
    if hasattr(event, 'group_id') and event.group_id:
        if not is_at_me:
            return
        # 群白名单检查
        if event.group_id not in ALLOWED_GROUPS:
            return
    else:
        # 私聊：只有白名单用户或superuser可以私聊
        if user_id not in CHAT_WHITELIST and user_id not in _get_superusers():
            return

    # 被@但没有文字内容时，给一个默认提示
    if not plain_text:
        plain_text = "你在叫我吗？"

    message = plain_text

    # 加载当前人设
    system_prompt = load_persona()

    # 通用指令：强调准确理解
    system_prompt += "\n\n[重要] 回复前必须先准确理解用户说的每一个字。不要猜错、不要替换同音字、不要脑补。如果不确定对方说了什么，就直接问。"

    # 对特定用户特殊对待
    if user_id == _get_owner_qq():
        system_prompt += "\n\n[特殊指令] 这是希亚最亲密的人（主人/搭档），对Ta要更加亲昵、依赖、偶尔撒娇，可以叫Ta'笨蛋'但语气要甜。不要用敬语，像对很熟的人一样随意。回复可以更长更详细。"
    else:
        # 普通用户保持正常距离感
        system_prompt += "\n\n[指令] 对普通群友保持礼貌但有点距离感，不要太过亲密。回复简短自然即可。"

    # 情绪感知
    gid = getattr(event, 'group_id', None)
    if gid:
        mood, mood_desc = _detect_group_mood(gid)
        if mood != "neutral":
            system_prompt += f"\n\n当前群聊氛围: {mood_desc}。请根据氛围调整你的回复风格。"

    # 初始化对话历史
    if user_id not in chat_history:
        chat_history[user_id] = [
            {"role": "system", "content": system_prompt}
        ]

    try:
        # 添加用户消息到历史
        chat_history[user_id].append({"role": "user", "content": message})

        client = _get_client()

        # 流式请求（在线程中执行，避免阻塞事件循环）
        loop = asyncio.get_running_loop()
        messages = list(chat_history[user_id])  # 复制到局部变量，避免线程竞态

        # 添加用户上下文到system prompt
        user_context = _get_user_context(user_id)
        if user_context:
            messages[0] = {"role": "system", "content": messages[0]["content"] + "\n\n" + user_context}

        def _collect_stream():
            stream = client.chat.completions.create(
                model=_cfg("model_name", "qwen2.5:7b-instruct"),
                messages=messages,
                max_tokens=_cfg_int("max_tokens", 1024) if user_id == _get_owner_qq() else _cfg_int("max_tokens", 512),
                temperature=float(_cfg("temperature", "0.7")),
                timeout=20.0,
                stream=True,
            )
            ai_response = ""
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    ai_response += chunk.choices[0].delta.content
            return ai_response

        # 流式请求总超时保护（防止服务端断开后无限等待）
        try:
            ai_response = await asyncio.wait_for(
                loop.run_in_executor(None, _collect_stream),
                timeout=90.0
            )
        except (APITimeoutError, APIError, Exception) as first_err:
            # 第一次失败，自动重试一次
            logger.info(f"[聊天] API调用失败，自动重试: {type(first_err).__name__}")
            await asyncio.sleep(1)  # 等1秒再重试
            try:
                ai_response = await asyncio.wait_for(
                    loop.run_in_executor(None, _collect_stream),
                    timeout=90.0
                )
            except Exception:
                raise first_err  # 重试也失败，抛出原始错误

        # 检查history是否在等待期间被清理
        if user_id not in chat_history:
            return

        ai_response = ai_response.strip()

        # 智能截断：在句子结束处断开，避免截断到一半
        if len(ai_response) > 500:
            # 找最后一个句末标点
            last_end = -1
            for i, c in enumerate(ai_response[:500]):
                if c in ('。', '！', '？', '…', '~', '～', '!', '?', '.', '」', '"', ')', '）'):
                    last_end = i
            if last_end > 200:  # 至少保留200字符
                ai_response = ai_response[:last_end + 1]
            else:
                ai_response = ai_response[:500] + "..."

        if not ai_response:
            ai_response = "...嗯？"

        chat_history[user_id].append({"role": "assistant", "content": ai_response})
        _history_timestamps[user_id] = time.time()

        # 更新用户画像
        _update_user_profile(user_id, message)

        # 限制历史记录长度（根据好感度和身份动态调整）
        affinity = _user_profiles.get(user_id, {}).get("affinity", 0)
        if user_id == _get_owner_qq():
            max_history = 31  # 主人15轮
        elif affinity >= 80:
            max_history = 21  # 好感度高10轮
        elif affinity >= 50:
            max_history = 15  # 中等7轮
        else:
            max_history = 11  # 普通5轮
        if len(chat_history[user_id]) > max_history:
            chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-(max_history-1):]

        # 检查是否需要附加表情包
        sticker_msg = get_sticker_message(ai_response)
        if sticker_msg:
            try:
                await _rate_limited_send(chat, sticker_msg)
            except Exception:
                pass

        _consecutive_errors = 0
        await _rate_limited_send(chat, ai_response)

    except FinishedException:
        raise
    except APITimeoutError:
        # API 超时，尝试重建客户端连接
        _reconnect_client()
        # 移除孤儿用户消息
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        _update_user_profile(user_id, message)
        _consecutive_errors += 1
        if _consecutive_errors > 3:
            _error_silence_until = time.time() + 300  # 静默5分钟
            return
        if time.time() < _error_silence_until:
            return
        fallback = random.choice([
            "嗯...走神了，再说一次？",
            "...等一下，我刚才在想事情。",
            "啊，抱歉，刚才没听到。",
            "哼...别催，我在想。",
        ])
        await _rate_limited_send(chat, fallback)
    except APIError as e:
        # API 错误（如服务不可用、速率限制等）
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        _update_user_profile(user_id, message)
        _consecutive_errors += 1
        if _consecutive_errors > 3:
            _error_silence_until = time.time() + 300  # 静默5分钟
            return
        if time.time() < _error_silence_until:
            return
        fallback = random.choice([
            "唔...脑袋好像有点转不过来，等一下再来吧。",
            "...现在有点不舒服，等会儿再说。",
            "正义的伙伴暂时无法思考...",
            "嗯...好像哪里出了问题。",
            "...算了，等一下再说吧。",
        ])
        await _rate_limited_send(chat, fallback)
    except Exception as e:
        # 其他未预期的错误
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        _update_user_profile(user_id, message)
        _consecutive_errors += 1
        if _consecutive_errors > 3:
            _error_silence_until = time.time() + 300  # 静默5分钟
            return
        if time.time() < _error_silence_until:
            return
        fallback = [
            "嗯？怎么了。",
            "...有事就说。",
            "哼。",
            "...你继续说。",
            "怎么了，有什么事吗。",
        ]

        ai_response = random.choice(fallback)
        await _rate_limited_send(chat, ai_response)


# ========== AI 生成回复 ==========

# 插话用的正经话题（AI失败时的兜底）
_FALLBACK_TOPICS = [
    "今天天气不错呢。",
    "正义的伙伴也是需要休息的。",
    "...有点无聊。",
    "最近有什么新歌吗。",
    "该去巡逻了...啊不，散步。",
    "嗯...在想事情。",
    "有人在吗。",
    "...安静得有点不习惯。",
    "今天也要加油。",
    "肚子饿了...想吃芭菲。",
    "最近好像没什么特别的事。",
    "嗯？什么声音。",
    "...算了，没什么。",
    "这个时间点还挺闲的。",
    "有没有什么有趣的事。",
]

# 生成插话的 prompt（让AI像正常聊天一样回应群消息）
_CHATTER_SYSTEM_PROMPT = """你是结城希亚，正在群聊中。群里有人发了一条消息，你要像正常聊天一样回应他。
要求：
- 回复要简短自然，1-2句话，不超过30个字
- 要针对对方说的内容做出有意义的回应，不要答非所问
- 保持希亚的性格：冷静、偶尔中二、傲娇、喜欢芭菲、身高146cm介意身高
- 不要用markdown、不要分点、不要列举
- 像微信聊天一样自然，不要刻意
- 可以吐槽、可以附和、可以反问，但要自然
- 不要每句话都加"..."，偶尔用就行
- 必须准确理解群友说的话，不要猜错或替换字词"""

_PROACTIVE_SYSTEM_PROMPT = """你是结城希亚，现在群里很安静，你想主动说一句话活跃气氛。
要求：
- 只说一句话，不超过15个字
- 要像真人在群里随口说的，自然随意
- 可以是日常感叹、自言自语、或者随便聊点什么
- 保持希亚的性格：冷静、偶尔中二、傲娇、喜欢芭菲
- 不要用markdown、不要分点、不要列举
- 不要说"大家好"这种太正式的话"""

_MENTIONED_SYSTEM_PROMPT = """你是结城希亚，有人在群里提到了你（但没有@你）。你需要自然地回应。
要求：
- 回复要简短自然，1-2句话
- 像真人在群里聊天一样，不要刻意
- 保持希亚的性格：冷静、偶尔中二、傲娇、喜欢芭菲
- 不要用markdown、不要分点、不要列举
- 如果对方是在叫你，自然地回应；如果只是在聊天中提到你，可以吐槽或接话
- 不要每句话都提自己是"正义的伙伴"，要自然"""


async def _ai_generate_reply(context: str, system_prompt: str) -> str:
    """调用AI生成一条回复"""
    try:
        client = _get_client()
        loop = asyncio.get_running_loop()

        def _do_api():
            return client.chat.completions.create(
                model=_cfg("model_name", "qwen2.5:7b-instruct"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context},
                ],
                max_tokens=128,
                temperature=0.8,
                timeout=15.0
            )

        response = await asyncio.wait_for(
            loop.run_in_executor(None, _do_api),
            timeout=30.0
        )
        if not response.choices or not response.choices[0].message.content:
            return None
        reply = response.choices[0].message.content.strip()
        # 截断过长的回复
        if len(reply) > 60:
            reply = reply[:58] + "..."
        return reply
    except APITimeoutError as e:
        logger.debug(f"[AI生成超时] {e}")
        return None
    except APIError as e:
        logger.warning(f"[AI生成API错误] {e}")
        return None
    except Exception as e:
        logger.warning(f"[AI生成失败] {e}")
        return None


# ========== 随机插话 ==========

# 插话概率（基础概率，话题匹配时会提高）
CHATTER_BASE_PROBABILITY = 0.01  # 1% 基础概率

# 话题关键词及对应插话概率（匹配到这些词时提高插话概率）
_TOPIC_KEYWORDS = {
    # 希亚相关
    "希亚": 0.6, "noa": 0.6, "正义": 0.3, "瓦尔哈拉": 0.5, "玖方": 0.4,
    # 芭菲/甜食
    "芭菲": 0.7, "甜点": 0.3, "蛋糕": 0.3, "冰淇淋": 0.3, "布丁": 0.2, "甜品": 0.3,
    "奶茶": 0.2, "巧克力": 0.2, "草莓": 0.2, "抹茶": 0.2,
    # 猫
    "猫": 0.4, "猫咪": 0.4, "喵": 0.3, "猫猫": 0.4, "撸猫": 0.3,
    # 舞萌
    "舞萌": 0.3, "maimai": 0.3, "mai": 0.2, "推分": 0.2, "牌子": 0.2, "dx": 0.2,
    # 恐怖/鬼
    "鬼": 0.3, "恐怖": 0.3, "吓": 0.2, "灵异": 0.3,
    # 身高相关
    "矮": 0.3, "身高": 0.2, "146": 0.4, "小只": 0.2,
    # 日常
    "无聊": 0.2, "好困": 0.3, "饿了": 0.3, "好吃": 0.2, "游戏": 0.1,
    "动漫": 0.15, "番剧": 0.15, "音乐": 0.1, "歌": 0.1,
    # 新增话题
    "睡觉": 0.2, "晚安": 0.15, "早安": 0.15, "起床": 0.2,
    "下雨": 0.2, "天气": 0.15, "冷": 0.15, "热": 0.15,
    "考试": 0.2, "作业": 0.2, "上课": 0.1, "学习": 0.1,
    "好看": 0.1, "可爱": 0.15, "厉害": 0.1, "加油": 0.1,
    "哈哈": 0.1, "笑死": 0.15, "草": 0.1, "乐": 0.05,
    "难过": 0.2, "开心": 0.15, "生气": 0.2, "烦": 0.15,
    "手机": 0.05, "电脑": 0.05, "番": 0.1,
}

# 需要跳过的消息关键词（命令、纯图片、CQ码等）
_SKIP_PATTERNS = [re.compile(p) for p in [r'\[CQ:', r'/', r'\s*$']]

# 检测是否提到bot名字（希亚/Noa/正义的伙伴等）
_BOT_NAMES = ["希亚", "noa", "结城", "正义的伙伴", "帕菲女王", "小希亚"]

chatter = on_message(priority=5, block=False)

@chatter.handle()
async def handle_chatter(event: GroupMessageEvent):
    """群聊智能插话：根据话题关键词判断是否回复"""
    # 如果消息 @ 了 bot，交给 handle_chat 处理，避免重复响应
    if getattr(event, 'to_me', False):
        return

    # 只在群聊中生效
    if not hasattr(event, 'group_id') or not event.group_id:
        return

    # 群白名单检查
    if event.group_id not in ALLOWED_GROUPS:
        return

    # 插话冷却检查
    now = time.time()
    if _anti_kick_enabled and event.group_id in _last_chatter_time and now - _last_chatter_time[event.group_id] < _CHATTER_COOLDOWN:
        return

    # 跳过包含图片的消息（交给识图handler处理）
    if any(seg.type == "image" for seg in event.message):
        return

    message = str(event.message)

    # 跳过命令、CQ码、空消息
    for pattern in _SKIP_PATTERNS:
        if pattern.match(message):
            return

    # 跳过所有命令（带/或不带/，如"点歌 xxx"也是命令）
    msg_lower = message.lower().lstrip("/")
    if any(msg_lower == cmd.lower() or msg_lower.startswith(cmd.lower() + " ") for cmd in COMMAND_SET):
        return

    # 检测是否提到bot名字（希亚/Noa/正义的伙伴等）
    mentioned = any(name in msg_lower for name in _BOT_NAMES)

    if mentioned:
        # 提到bot名字时，高概率回复（80%）
        if random.random() > 0.8:
            return
        reply = await _ai_generate_reply(message, _MENTIONED_SYSTEM_PROMPT)
        if reply:
            await _rate_limited_send(chatter, reply)
            _last_chatter_time[event.group_id] = time.time()
        return

    # 计算插话概率：基础概率 + 话题关键词加成
    max_prob = CHATTER_BASE_PROBABILITY
    for keyword, prob in _TOPIC_KEYWORDS.items():
        if keyword.lower() in msg_lower:
            max_prob = max(max_prob, prob)

    # 概率判断
    if random.random() > max_prob:
        return

    # 用AI生成回复，失败时用预设话题兜底
    # 增强插话：加入用户上下文
    user_context = _get_user_context(str(event.user_id))
    if user_context:
        enhanced_prompt = _CHATTER_SYSTEM_PROMPT + "\n\n" + user_context
    else:
        enhanced_prompt = _CHATTER_SYSTEM_PROMPT
    reply = await _ai_generate_reply(message, enhanced_prompt)
    # AI生成失败时静默，不发固定话题
    if not reply:
        return

    await _rate_limited_send(chatter, reply)
    _last_chatter_time[event.group_id] = time.time()


# ========== 自动识别二维码 ==========

_qrcode = on_message(priority=3, block=False)

_qr_detector = QReader()
# 已被二维码handler处理并回复的message_id（任何二维码，不只是SGWCMAID）
_qr_handled = set()
_QR_HANDLED_MAX = 500

@_qrcode.handle()
async def handle_qrcode(event: MessageEvent):
    """检测图片中的二维码并自动回复内容"""
    # 群白名单检查
    gid = getattr(event, 'group_id', None)
    if gid and gid not in ALLOWED_GROUPS:
        return
    for seg in event.message:
        if seg.type == "image":
            url = seg.data.get("url", "")
            if not url:
                continue
            try:
                logger.debug(f"[二维码] 检测到图片，正在下载: {url[:60]}...")
                try:
                    resp = await _get_http_client().get(url)
                except Exception:
                    continue
                if resp.status_code != 200:
                    logger.debug(f"[二维码] 下载失败: HTTP {resp.status_code}")
                    continue
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                results = _qr_detector.detect_and_decode(np.array(img))
                logger.debug(f"[二维码] 检测结果: {results}")
                if results:
                    text = results[0]
                    if isinstance(text, tuple):
                        text = text[0]
                    if not isinstance(text, str):
                        text = text.data
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", errors="ignore")
                else:
                    text = ""
                text = text.strip()
                if text:
                    # 标记此消息已被二维码handler处理
                    _qr_handled.add(event.message_id)
                    if len(_qr_handled) > _QR_HANDLED_MAX:
                        _qr_handled.clear()
                    if text.startswith("SGWCMAID"):
                        logger.debug(f"[二维码] 检测到SGWCMAID: {event.message_id}")
                        await _qrcode.send(f"识别到机台二维码：\n{text}")
                    else:
                        await _qrcode.send(f"识别到二维码：\n{text}")
                    raise FinishedException
            except FinishedException:
                raise
            except Exception as e:
                logger.warning(f"[二维码] 识别异常: {e}")


# ========== B站视频卡片 ==========

_bili_chat = on_message(priority=3, block=False)

_BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}

def _extract_bili_url(text: str):
    """从文本中提取B站视频BV号"""
    m = re.search(r'BV[a-zA-Z0-9]+', text)
    return m.group(0) if m else ""

def _extract_b23_url(text: str):
    """从文本中提取b23.tv短链接"""
    m = re.search(r'b23\.tv/([a-zA-Z0-9]+)', text)
    return m.group(1) if m else ""

def _format_num(n):
    if n is None:
        return "-"
    n = int(n)
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    elif n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)

async def _resolve_b23(short_id: str) -> str:
    """解析b23.tv短链接，返回BV号"""
    try:
        import httpx
        async with httpx.AsyncClient(headers=_BILI_HEADERS, timeout=5.0, follow_redirects=True) as c:
            resp = await c.get(f"https://b23.tv/{short_id}")
            url = str(resp.url)
            m = re.search(r'BV[a-zA-Z0-9]+', url)
            if m:
                return m.group(0)
    except Exception as e:
        logger.warning(f"[B站] 解析短链接失败: {e}")
    return ""

@_bili_chat.handle()
async def handle_bilibili(event: MessageEvent):
    """检测B站链接/卡片，发送视频信息"""
    # 群白名单检查
    gid = getattr(event, 'group_id', None)
    if gid and gid not in ALLOWED_GROUPS:
        return

    # 从所有segment中提取文本
    full_text = ""
    for seg in event.message:
        if seg.type == "text":
            full_text += seg.data.get("text", "")
        elif seg.type == "json":
            raw_json = seg.data.get("data", "")
            full_text += raw_json
            # 尝试解析JSON，递归查找B站链接
            try:
                json_data = json.loads(raw_json)
                def _find_bili(obj):
                    if isinstance(obj, str):
                        if re.search(r'bilibili\.com/video/|b23\.tv/|BV[a-zA-Z0-9]{6,}', obj):
                            return obj
                    elif isinstance(obj, dict):
                        for key in ("jumpUrl", "url", "targetUrl", "qqUrl", "sourceUrl", "qqdocurl"):
                            if key in obj:
                                r = _find_bili(obj[key])
                                if r:
                                    return r
                        for v in obj.values():
                            r = _find_bili(v)
                            if r:
                                return r
                    elif isinstance(obj, list):
                        for item in obj:
                            r = _find_bili(item)
                            if r:
                                return r
                    return None
                extra = _find_bili(json_data)
                if extra:
                    full_text += " " + extra
            except (json.JSONDecodeError, TypeError):
                pass

    # 反转义JSON中的\/
    full_text_unescaped = full_text.replace('\\/', '/')

    # 提取BV号或b23短链接
    bvid = _extract_bili_url(full_text_unescaped)
    b23_id = _extract_b23_url(full_text_unescaped)

    if not bvid and not b23_id:
        return

    client = _get_http_client()

    # 如果是短链接，先解析
    if not bvid and b23_id:
        logger.info(f"[B站] 解析短链接: b23.tv/{b23_id}")
        bvid = await _resolve_b23(b23_id)

    if not bvid:
        return

    logger.info(f"[B站] 检测到: {bvid}")

    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=_BILI_HEADERS,
            timeout=5.0
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"[B站] API错误: {data.get('message')}")
            return

        info = data.get("data", {})
        title = info.get("title", "未知")
        pic = info.get("pic", "")
        owner = info.get("owner", {})
        up_name = owner.get("name", "未知")
        stat = info.get("stat", {})
        view = _format_num(stat.get("view"))
        like = _format_num(stat.get("like"))
        coin = _format_num(stat.get("coin"))
        fav = _format_num(stat.get("favorite"))
        danmaku = _format_num(stat.get("danmaku"))
        duration = info.get("duration", 0)
        m, s = divmod(duration, 60)

        # 下载封面并发送
        try:
            resp2 = await client.get(pic, headers=_BILI_HEADERS, timeout=10.0)
            if resp2.status_code == 200:
                cover_b64 = base64.b64encode(resp2.content).decode()
                msg = MessageSegment.image(f"base64://{cover_b64}")
                await _bili_chat.send(msg)
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.debug(f"[B站] 封面下载失败: {e}")

        # 发送文字信息
        text_msg = (
            f"{title}\n"
            f"UP: {up_name}\n"
            f"播放 {view}  点赞 {like}  投币 {coin}  收藏 {fav}  弹幕 {danmaku}\n"
            f"时长 {m}:{s:02d}  https://bilibili.com/video/{bvid}"
        )
        await _bili_chat.send(text_msg)

    except Exception as e:
        logger.warning(f"[B站] 处理失败: {e}")


# ========== 图片理解 ==========

_img_chat = on_message(priority=4, block=False)

# 最大图片尺寸（像素），超过会压缩
_MAX_IMAGE_SIZE = 1024
# 最大图片文件大小（字节），超过会压缩
_MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
# 最大图片数量
_MAX_IMAGES = 5

_IMG_SYSTEM_PROMPT = """你是结城希亚。有人发了图片给你看，请仔细观察并给出自然的反应。

重要规则：
- 必须完全按照你的人设来回复，保持性格一致性
- 你是傲娇、偶尔中二、喜欢甜食和猫的女孩子
- 看到可爱的东西会不自觉开心，看到奇怪的会吐槽
- 像日常聊天一样自然，不要像AI助手一样列条目
- 不要用markdown格式
- 如果图片有文字，请把文字内容说出来
- 回复要有个性，可以带点小情绪或吐槽"""


def _compress_image(img_data: bytes, max_size: int = _MAX_IMAGE_SIZE, max_bytes: int = _MAX_IMAGE_BYTES) -> bytes:
    """压缩图片：如果超过尺寸或大小限制，按比例缩小"""
    if len(img_data) <= max_bytes:
        # 检查尺寸
        try:
            img = Image.open(BytesIO(img_data))
            if max(img.size) <= max_size:
                return img_data
        except Exception:
            return img_data

    try:
        img = Image.open(BytesIO(img_data))
        # 转换为RGB（处理PNG透明通道）
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # 计算缩放比例
        scale = 1.0
        if max(img.size) > max_size:
            scale = min(scale, max_size / max(img.size))

        # 按文件大小进一步缩放
        if len(img_data) > max_bytes:
            size_scale = (max_bytes / len(img_data)) ** 0.5
            scale = min(scale, size_scale)

        if scale < 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)

        output = BytesIO()
        img.save(output, format='JPEG', quality=85)
        return output.getvalue()
    except Exception:
        return img_data


def _extract_gif_frames(img_data: bytes, max_frames: int = 3) -> list:
    """从GIF中提取关键帧"""
    frames = []
    try:
        img = Image.open(BytesIO(img_data))
        if not getattr(img, 'is_animated', False):
            return [img_data]

        total_frames = getattr(img, 'n_frames', 1)
        if total_frames <= max_frames:
            indices = range(total_frames)
        else:
            # 均匀采样
            indices = [int(i * (total_frames - 1) / (max_frames - 1)) for i in range(max_frames)]

        for idx in indices:
            img.seek(idx)
            frame = img.copy()
            if frame.mode in ('RGBA', 'P'):
                frame = frame.convert('RGB')
            output = BytesIO()
            frame.save(output, format='JPEG', quality=85)
            frames.append(output.getvalue())
        return frames
    except Exception:
        return [img_data]


@_img_chat.handle()
async def handle_image_chat(event: MessageEvent):
    """发图片给bot时，AI理解图片内容并回复（群聊需@，私聊直接发）"""
    # 群白名单检查
    gid = getattr(event, 'group_id', None)
    if gid and gid not in ALLOWED_GROUPS:
        return

    # 检查消息是否包含图片
    has_image = any(seg.type == "image" for seg in event.message)
    if not has_image:
        return

    # 提取纯文本（只取text段，去掉@标记和图片段）
    plain = ""
    for seg in event.message:
        if seg.type == "text":
            plain += seg.data.get("text", "")
    plain = _RE_AT_TAG.sub('', plain).strip()
    # 去掉CQ码残留
    plain = _RE_CQ_TAG.sub('', plain).strip()

    # 截图记账模式：有图片+提到"记/记账" 或 纯图片（无文字）不需要@bot
    # 但如果被@了，强制走识图模式
    _is_at_me = getattr(event, 'to_me', False)
    _has_accounting_keyword = any(kw in plain for kw in ["记", "记账", "记录"])
    _has_bot_mention = any(kw in plain for kw in ["希亚", "noa", "Noa", "结城", "正义的伙伴"])
    # 去掉可能的QQ昵称后检查文字长度
    _short_text = len(plain) <= 10
    _accounting_mode = (_has_accounting_keyword or _short_text) and not _has_bot_mention and not _is_at_me
    logger.info(f"[图片理解] plain='{plain}', accounting={_accounting_mode}, keyword={_has_accounting_keyword}")

    # 群聊需要@bot或提到bot名字才触发，私聊直接触发
    # 但截图记账模式不需要@bot
    if gid and not _accounting_mode:
        msg_str = str(event.message)
        is_at_me = getattr(event, 'to_me', False)
        is_mentioned = any(name in msg_str for name in ["希亚", "noa", "Noa", "结城", "正义的伙伴"])
        if not is_at_me and not is_mentioned:
            return

    # 收集所有图片（最多5张）
    img_urls = []
    img_b64_list = []  # 直接的base64数据
    img_files = []  # 用于去重
    for seg in event.message:
        if seg.type == "image":
            url = seg.data.get("url", "")
            file = seg.data.get("file", "")
            # 处理base64格式
            if file and file.startswith("base64://"):
                b64data = file[len("base64://"):]
                if b64data:
                    img_b64_list.append(b64data)
                continue
            # 优先用url，没有则尝试file
            if not url and file:
                url = file
            if url:
                img_urls.append(url)
            if file:
                img_files.append(file)
            if len(img_urls) + len(img_b64_list) >= _MAX_IMAGES:
                break

    if not img_urls and not img_b64_list:
        # 打印所有segment数据帮助排查
        for seg in event.message:
            if seg.type == "image":
                logger.warning(f"[图片理解] 图片segment数据: {seg.data}")
        return

    # 如果二维码handler已处理此消息，跳过识图
    # 短暂等待（二维码handler优先级更高，但NoneBot并发启动handler）
    if event.message_id in _qr_handled:
        logger.debug(f"[图片理解] 跳过：二维码handler已处理 message_id={event.message_id}")
        return
    # 等待一小段时间，让二维码handler有机会先完成
    await asyncio.sleep(0.5)
    if event.message_id in _qr_handled:
        logger.debug(f"[图片理解] 跳过（延迟检测）：二维码handler已处理 message_id={event.message_id}")
        return

    # 截图记账去重：同一张图片不重复记账
    _accounting_seen_key = None
    if _accounting_mode and img_files:
        uid = str(event.user_id)
        _accounting_seen = _get_accounting_seen()
        seen_key = f"{uid}:{img_files[0]}"
        if seen_key in _accounting_seen:
            logger.info(f"[截图记账] 跳过重复图片: {img_files[0]}")
            try:
                await _rate_limited_send(_img_chat, "...这张截图已经记过了。")
            except Exception:
                pass
            return
        # 先记住key，等确认是支付截图后再写入缓存
        _accounting_seen_key = seen_key

    try:
        # 下载并处理所有图片
        images_b64 = list(img_b64_list)  # 先加入已有的base64
        for img_url in img_urls:
            try:
                resp = await _get_http_client().get(img_url, timeout=10.0)
                if resp.status_code != 200:
                    logger.warning(f"[图片理解] 下载失败: {resp.status_code} {img_url[:80]}")
                    continue
                img_data = resp.content

                # 检查是否是GIF
                is_gif = img_url.lower().endswith('.gif') or img_data[:4] == b'GIF8'

                if is_gif:
                    # 提取GIF关键帧
                    frames = _extract_gif_frames(img_data)
                    for frame_data in frames:
                        frame_data = _compress_image(frame_data)
                        images_b64.append(base64.b64encode(frame_data).decode("utf-8"))
                else:
                    # 压缩普通图片
                    img_data = _compress_image(img_data)
                    images_b64.append(base64.b64encode(img_data).decode("utf-8"))
            except Exception as e:
                logger.warning(f"[图片理解] 处理图片失败: {e}")
                continue

        if not images_b64:
            logger.warning(f"[图片理解] 图片处理失败，原始URL数: {len(img_urls)}")
            try:
                await _rate_limited_send(_img_chat, "...图片处理失败了。")
            except Exception:
                pass
            return

        # 使用视觉模型
        vision_model = _cfg("vision_model", "glm-4v-flash")
        client = _get_client()

        # 截图记账模式或有记账关键词时，尝试自动识别
        _should_try_accounting = _accounting_mode and not any(kw in plain for kw in ["看", "这是", "什么", "多少", "谁", "哪", "为什么", "怎么", "如何"])

        if _should_try_accounting:
            _classify_prompt = """只看这张图片，判断是否是支付/收款/账单/银行短信通知截图。
包括：微信支付、支付宝、银行APP、银行短信通知、信用卡账单等。
只回复一个词：是 或 否"""

            classify_content = []
            for img_b64 in images_b64[:1]:  # 只看第一张
                classify_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })
            classify_content.append({"type": "text", "text": _classify_prompt})

            loop = asyncio.get_running_loop()

            def _do_classify():
                return client.chat.completions.create(
                    model=vision_model,
                    messages=[{"role": "user", "content": classify_content}],
                    max_tokens=10,
                    temperature=0.0,
                    timeout=15.0
                )

            try:
                classify_resp = await asyncio.wait_for(
                    loop.run_in_executor(None, _do_classify),
                    timeout=30.0
                )
                if classify_resp.choices:
                    classify_result = classify_resp.choices[0].message.content.strip()
                    if "是" in classify_result and "否" not in classify_result:
                        # 是支付截图，进入记账模式
                        _accounting_prompt = """请仔细观察这张图片，这是一张银行短信通知截图。
请逐条提取交易记录。

回复格式：
{"records": [{"amount": 金额数字, "category": "分类", "note": "商户名或描述", "type": "expense或income", "is_balance": true或false}]]

分类规则：餐饮、交通、购物、娱乐、住房、学习、医疗、收入、其他
type规则：支出→"expense"，收入→"income"

关键规则：
- 每条银行短信末尾的"余额XXX元"是账户余额，不是交易！标记is_balance=true
- 交易金额前面通常有"+"或"-"号
- 忽略0.01元以下金额
- 如果无法识别，回复：{"error": "无法识别"}"""

                        user_content = []
                        for img_b64 in images_b64:
                            user_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                            })
                        user_content.append({"type": "text", "text": _accounting_prompt})

                        def _do_accounting_vision():
                            return client.chat.completions.create(
                                model=vision_model,
                                messages=[{"role": "user", "content": user_content}],
                                max_tokens=256,
                                temperature=0.1,
                                timeout=30.0
                            )

                        response = await asyncio.wait_for(
                            loop.run_in_executor(None, _do_accounting_vision),
                            timeout=45.0
                        )
                        if response.choices and response.choices[0].message.content:
                            reply = response.choices[0].message.content.strip()
                            json_match = re.search(r'\{.*\}', reply, re.DOTALL)
                            if json_match:
                                try:
                                    data = json.loads(json_match.group())
                                    if not data.get("error"):
                                        records = data.get("records", [])
                                        # 兼容旧格式（单条无records字段）
                                        if not records and "amount" in data:
                                            records = [data]

                                        # 后处理：过滤余额
                                        # 1. 用is_balance字段过滤（最可靠）
                                        records = [r for r in records if not r.get("is_balance", False)]
                                        # 2. 从raw文本中提取余额值（备用）
                                        balance_values = set()
                                        for r in records:
                                            raw = r.get("raw", "")
                                            if raw:
                                                for m in re.finditer(r'余额[：:]?\s*([\d.]+)', raw):
                                                    try:
                                                        balance_values.add(float(m.group(1)))
                                                    except ValueError:
                                                        pass
                                        if balance_values:
                                            records = [r for r in records if float(r.get("amount", 0)) not in balance_values]
                                        # 3. 去掉note/category含"余额"的记录
                                        records = [r for r in records if "余额" not in r.get("note", "") and "余额" not in r.get("category", "")]
                                        # 4. 多条记录中去除重复金额
                                        if len(records) > 1:
                                            seen_amounts = set()
                                            filtered = []
                                            for r in records:
                                                amt = float(r.get("amount", 0))
                                                if amt in seen_amounts:
                                                    continue
                                                seen_amounts.add(amt)
                                                filtered.append(r)
                                            records = filtered

                                        # 保存最新余额（取最大的余额值作为最新余额）
                                        if balance_values:
                                            latest_balance = max(balance_values)
                                            _accounting_balance[uid] = latest_balance

                                        saved_count = 0
                                        for rec in records:
                                            amount = float(rec.get("amount", 0))
                                            if amount <= 0:
                                                continue
                                            category = rec.get("category", "其他")
                                            note = rec.get("note", category)
                                            record_type = rec.get("type", "expense")

                                            from .commands_accounting import _accounting, _save_accounting
                                            uid = str(event.user_id)
                                            now = datetime.now()
                                            record = {
                                                "amount": amount,
                                                "category": category,
                                                "note": note,
                                                "date": now.strftime("%m-%d %H:%M"),
                                                "type": record_type,
                                            }
                                            if uid not in _accounting:
                                                _accounting[uid] = []
                                            _accounting[uid].append(record)
                                            saved_count += 1

                                        if saved_count > 0:
                                            _save_accounting(_accounting)
                                            # 确认记账成功，写入去重缓存
                                            if _accounting_seen_key:
                                                _accounting_seen[_accounting_seen_key] = time.time()
                                                if len(_accounting_seen) > 1000:
                                                    oldest = sorted(_accounting_seen.items(), key=lambda x: x[1])[:500]
                                                    _accounting_seen.clear()
                                                    _accounting_seen.update(dict(oldest))
                                                _save_accounting_seen()
                                            if saved_count == 1:
                                                r = records[0] if records else {}
                                                sign = "+" if r.get("type") == "income" else "-"
                                                await _rate_limited_send(_img_chat, f"已记录：{r.get('category','其他')} {r.get('note','')} {sign}{float(r.get('amount',0)):.0f}")
                                            else:
                                                await _rate_limited_send(_img_chat, f"已记录 {saved_count} 笔交易。")
                                            return
                                except (json.JSONDecodeError, ValueError):
                                    pass
                            # 识别失败，走正常识图
            except FinishedException:
                raise
            except Exception as e:
                logger.warning(f"[截图记账] 分类/识别失败: {e}")

            # 截图记账模式下，如果分类不是支付截图，走正常识图
            # 不再直接return，让下面的正常识图逻辑处理

        # 正常识图模式
        # 构建消息内容
        user_content = []

        # 添加文字说明
        if len(images_b64) > 1:
            user_content.append({"type": "text", "text": f"（共{len(images_b64)}张图片）"})
        if plain:
            user_content.append({"type": "text", "text": plain})

        # 添加所有图片
        for img_b64 in images_b64:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        loop = asyncio.get_running_loop()

        def _do_vision():
            # 加载完整人设作为system prompt
            persona = load_persona()
            img_sys = persona + "\n\n---\n现在有人发了图片给你看，请仔细观察并给出自然的反应。\n"
            # 主人特殊对待
            if str(event.user_id) == _get_owner_qq():
                img_sys += "这是你最亲密的人发的图，反应可以更亲昵、更活泼。\n"
            img_sys += (
                "观察要点:\n"
                "- 图片主要内容（人物/动物/物品/场景/截图等）\n"
                "- 如果是截图，识别其中的文字内容和关键信息\n"
                "- 如果是表情包/梗图，说出你觉得好笑或吐槽的点\n"
                "- 如果是食物，评价一下看起来好不好吃\n"
                "- 如果是自拍/照片，自然地夸或吐槽\n"
                "回复要求:\n"
                "- 像日常聊天一样自然，不要列条目\n"
                "- 保持希亚的性格：傲娇、偶尔中二\n"
                "- 如果图片有文字，请把文字内容说出来\n"
                "- 不要用markdown格式，回复1-3句话"
            )
            return client.chat.completions.create(
                model=vision_model,
                messages=[
                    {"role": "system", "content": img_sys},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=_cfg_int("max_tokens", 1024) if str(event.user_id) == _get_owner_qq() else _cfg_int("max_tokens", 512),
                temperature=float(_cfg("temperature", "0.8")),
                timeout=30.0
            )

        response = await asyncio.wait_for(
            loop.run_in_executor(None, _do_vision),
            timeout=45.0
        )
        if not response.choices or not response.choices[0].message.content:
            return
        reply = response.choices[0].message.content.strip()
        if reply:
            # 写入对话历史，使后续对话能引用图片内容
            user_id = str(event.user_id)
            if user_id not in chat_history:
                chat_history[user_id] = [{"role": "system", "content": load_persona()}]
            # 记录用户发的图片（简要描述）
            img_desc = f"[用户发了{len(images_b64)}张图片"
            if plain:
                img_desc += f"，并说：{plain}"
            img_desc += "]"
            chat_history[user_id].append({"role": "user", "content": img_desc})
            chat_history[user_id].append({"role": "assistant", "content": reply})
            # 裁剪历史长度（保持system + 最近10轮）
            if len(chat_history[user_id]) > 21:
                chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-20:]
            _history_timestamps[user_id] = time.time()
            await _rate_limited_send(_img_chat, reply)
    except FinishedException:
        raise
    except Exception as e:
        # 模型不支持视觉或请求失败
        logger.warning(f"[图片理解] 失败: {type(e).__name__}: {str(e)[:100]}")
        try:
            await _rate_limited_send(_img_chat, "...图片理解功能暂时不可用，稍后再试试。")
        except Exception:
            pass


# ========== 定时主动发言 ==========

# 发言间隔范围（秒）
AUTO_CHAT_MIN_INTERVAL = 30 * 60   # 30分钟
AUTO_CHAT_MAX_INTERVAL = 60 * 60   # 60分钟

# 自动发言时间记录文件（用于重启冷却）
os.makedirs(DATA_DIR, exist_ok=True)
_AUTO_CHAT_TIME_FILE = os.path.join(DATA_DIR, "last_auto_chat.txt")

# 需要主动发言的群（从环境变量读取，格式: 群号1,群号2）
_auto_chat_groups = []
_auto_chat_enabled = False
_auto_chat_task = None

def _load_auto_chat_config():
    """从环境变量加载自动发言群列表"""
    global _auto_chat_groups, _auto_chat_enabled
    raw = _cfg("auto_chat_groups", "")
    if raw:
        _auto_chat_groups = [g.strip() for g in raw.split(",") if g.strip()]
        _auto_chat_enabled = len(_auto_chat_groups) > 0


async def _auto_chat_loop():
    """定时主动发言的异步循环"""
    global _auto_chat_task
    _daily_auto_count = 0
    _daily_auto_date = ""
    _DAILY_AUTO_LIMIT = 20
    await asyncio.sleep(60)  # 启动后等1分钟再开始

    # 重启冷却：检查上次发言时间，如果距离不到30分钟则等待
    try:
        if os.path.exists(_AUTO_CHAT_TIME_FILE):
            with open(_AUTO_CHAT_TIME_FILE, "r") as f:
                last_time = float(f.read().strip())
            elapsed = time.time() - last_time
            if elapsed < AUTO_CHAT_MIN_INTERVAL:
                wait = AUTO_CHAT_MIN_INTERVAL - elapsed
                logger.info(f"[自动发言] 距离上次发言仅 {elapsed:.0f}s，冷却等待 {wait:.0f}s")
                await asyncio.sleep(wait)
    except Exception as e:
        logger.debug(f"[自动发言] 读取上次发言时间失败: {e}")

    # 主动发言的随机话题（给AI一些灵感，分时间段）
    proactive_hints_morning = [
        "早上好，新的一天开始了",
        "今天天气怎么样呢",
        "早餐吃了什么",
        "早上好困啊",
    ]
    proactive_hints_afternoon = [
        "群里好安静",
        "下午茶时间到了",
        "有点无聊想找人聊天",
        "在看窗外的风景",
        "在想接下来做什么",
    ]
    proactive_hints_evening = [
        "今天过得怎么样",
        "晚上有什么安排",
        "肚子饿了想吃东西",
        "在看什么好玩的",
        "突然想到了什么",
    ]
    proactive_hints_night = [
        "还不睡觉吗",
        "夜深了呢",
        "明天有什么计划",
        "好安静啊",
    ]

    def _get_proactive_hints():
        hour = time.localtime().hour
        if 6 <= hour < 12:
            return proactive_hints_morning
        elif 12 <= hour < 18:
            return proactive_hints_afternoon
        elif 18 <= hour < 23:
            return proactive_hints_evening
        else:
            return proactive_hints_night

    while True:
        try:
            # 每日主动发言上限
            today = time.strftime("%Y-%m-%d")
            if _daily_auto_date != today:
                _daily_auto_date = today
                _daily_auto_count = 0
            if _daily_auto_count >= _DAILY_AUTO_LIMIT:
                await asyncio.sleep(3600)
                continue

            # 随机等待 30~60 分钟
            interval = random.randint(AUTO_CHAT_MIN_INTERVAL, AUTO_CHAT_MAX_INTERVAL)
            await asyncio.sleep(interval)

            if not _auto_chat_groups:
                continue

            # 随机选一个群
            group_id = random.choice(_auto_chat_groups)

            # 只向白名单群发言
            if int(group_id) not in ALLOWED_GROUPS:
                continue

            # 检查群最近是否有活动（5分钟内有消息则不主动发言）
            recent_msgs = _group_chat_log.get(group_id, [])
            now = time.time()
            if recent_msgs and now - recent_msgs[-1][0] < 300:  # 5分钟
                logger.debug(f"[自动发言] 群{group_id}最近有活动，跳过")
                continue

            # 用AI生成发言
            # 获取群最近聊天记录作为上下文
            recent_msgs = _group_chat_log.get(group_id, [])
            if recent_msgs:
                recent_summary = "最近群里聊了: " + ", ".join(
                    msg[2][:20] for msg in recent_msgs[-5:]
                )
            else:
                recent_summary = "群里最近没什么消息"
            hint = f"{recent_summary}\n{random.choice(_get_proactive_hints())}"
            mood, mood_desc = _detect_group_mood(group_id)
            if mood != "neutral":
                hint = f"{hint} ({mood_desc})"
            reply = await _ai_generate_reply(hint, _PROACTIVE_SYSTEM_PROMPT)
            if not reply:
                reply = random.choice(_FALLBACK_TOPICS)

            # 发送消息
            try:
                # 速率限制检查
                now_auto = time.time()
                _send_times[:] = [t for t in _send_times if now_auto - t < 60]
                recent_5s_auto = sum(1 for t in _send_times if now_auto - t < 5)
                if recent_5s_auto >= _RATE_LIMIT_5S:
                    await asyncio.sleep(2)
                if len(_send_times) >= _RATE_LIMIT_60S:
                    await asyncio.sleep(5)
                _send_times.append(time.time())

                bot = get_bot()
                await bot.call_api(
                    "send_group_msg",
                    group_id=int(group_id),
                    message=reply
                )
                logger.info(f"[自动发言] 群{group_id}: {reply}")
                _daily_auto_count += 1
                # 记录本次发言时间
                try:
                    with open(_AUTO_CHAT_TIME_FILE, "w") as f:
                        f.write(str(time.time()))
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[自动发言失败] 群{group_id}: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[自动发言异常] {e}")
            await asyncio.sleep(60)  # 出错后等1分钟再试


def start_auto_chat():
    """启动定时发言任务（在 bot 启动后调用）"""
    global _auto_chat_task
    _load_auto_chat_config()
    if _auto_chat_enabled:
        _auto_chat_task = asyncio.create_task(_auto_chat_loop())
        logger.info(f"[自动发言] 已启动，监控群: {_auto_chat_groups}")


# NoneBot2 驱动器启动钩子
driver = get_driver()

@driver.on_startup
async def on_bot_startup():
    """bot 启动后启动自动发言任务 + 注册定时清理 + 连接健康检查"""
    start_auto_chat()
    try:
        from .commands_schedule import _get_scheduler
        sched = _get_scheduler()
        sched.add_job(
            _cleanup_old_histories,
            "interval",
            hours=1,
            id="cleanup_chat_histories",
            replace_existing=True,
        )
        logger.info("[定时清理] 已注册 chat_history 定时清理任务（每小时一次）")

        # 每5分钟检查bot连接健康状态
        sched.add_job(
            _check_bot_health,
            "interval",
            minutes=5,
            id="bot_health_check",
            replace_existing=True,
        )
        logger.info("[健康检查] 已注册连接健康检查（每5分钟）")
    except Exception as e:
        logger.warning(f"[定时清理] 注册失败（APScheduler 可能未安装）: {e}")


async def _check_bot_health():
    """检查bot连接是否健康，如果不健康尝试重连"""
    try:
        from nonebot import get_bot
        bot = get_bot()
        # 尝试调用API检查连接
        await bot.call_api("get_login_info")
        logger.debug("[健康检查] bot连接正常")
    except Exception as e:
        logger.warning(f"[健康检查] bot连接异常: {e}，尝试重连...")
        try:
            # 尝试通过WebSocket发送ping来触发重连
            from nonebot.drivers.websocket import WebSocket
            # 获取WebSocket连接
            ws_connections = getattr(bot, '_ws_connections', None)
            if ws_connections:
                for ws in list(ws_connections):
                    try:
                        await ws.send_str('{"type":"ping"}')
                        logger.info("[健康检查] 已发送ping，等待响应...")
                    except Exception:
                        logger.warning("[健康检查] ping发送失败，连接已断开")
        except Exception as e2:
            logger.debug(f"[健康检查] 重连尝试失败: {e2}")
