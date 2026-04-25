# 标准库
import asyncio
import base64
import os
import random
import re
import threading
import time
from io import BytesIO

# 第三方库
import numpy as np
from nonebot import get_bot, get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from openai import APIError, APITimeoutError, OpenAI
from PIL import Image
from qreader import QReader

# 本地模块
from .config import ALLOWED_GROUPS, COMMAND_NAMES, load_persona, DATA_DIR
from .commands_sticker import get_sticker_message

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

# 初始化 OpenAI 客户端（单例模式，支持断线重连）
_client = None
_client_lock = threading.Lock()

# ---- 全局 HTTP 客户端（连接池复用） ----
from .utils import get_shared_http_client as _get_http_client


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

# 对话历史时间戳，用于定期清理
_history_timestamps = {}
_HISTORY_TTL = 3600  # 1 小时过期时间（秒）


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

# ========== 艾特检测（睡觉模式） ==========

# 将命令列表转为集合，加速查找主人QQ号
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
]

_sleep_cmd = on_message(priority=0, block=False)

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
    plain = re.sub(r'\[at:qq=\d+\]', '', message).strip()
    if "希亚" in plain or "Noa" in plain.lower():
        return

    # 随机回复
    reply = random.choice(_SLEEP_REPLIES)
    await _sleep_cmd.finish(reply)


# 消息处理（优先级 1，block=False 让命令能继续传递）
chat = on_message(priority=1, block=False)

@chat.handle()
async def handle_chat(event: MessageEvent):
    user_id = str(event.user_id)
    message = str(event.message)

    # 提取纯文本（去掉 @ 标记和开头的 /）
    plain_text = re.sub(r'\[at:qq=\d+\]', '', message).strip()
    if plain_text.startswith("/"):
        plain_text = plain_text[1:].strip()

    # 如果是命令消息，不处理（使用集合加速查找）
    if plain_text in COMMAND_SET or any(plain_text.startswith(cmd + " ") for cmd in COMMAND_SET):
        return

    # 如果消息包含图片，跳过（交给识图handler处理）
    if any(seg.type == "image" for seg in event.message):
        return

    # 跳过合并转发消息（NapCat 不上报，但保险起见）
    if any(seg.type == "forward" for seg in event.message):
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

    # 被@但没有文字内容时，给一个默认提示
    if not plain_text:
        plain_text = "你在叫我吗？"

    message = plain_text

    # 加载当前人设
    system_prompt = load_persona()

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

        def _collect_stream():
            stream = client.chat.completions.create(
                model=_cfg("model_name", "qwen2.5:7b-instruct"),
                messages=messages,
                max_tokens=int(_cfg("max_tokens", "512")),
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
        ai_response = await asyncio.wait_for(
            loop.run_in_executor(None, _collect_stream),
            timeout=90.0
        )

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

        # 限制历史记录长度（只保留最近5轮对话）
        if len(chat_history[user_id]) > 11:  # system + 5轮(user+assistant) = 11条
            chat_history[user_id] = [chat_history[user_id][0]] + chat_history[user_id][-10:]

        # 检查是否需要附加表情包
        sticker_msg = get_sticker_message(ai_response)
        if sticker_msg:
            try:
                await chat.send(sticker_msg)
            except Exception:
                pass

        await chat.finish(ai_response)

    except FinishedException:
        raise
    except APITimeoutError:
        # API 超时，尝试重建客户端连接
        _reconnect_client()
        # 移除孤儿用户消息
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        fallback = "嗯...正义的伙伴好像走神了，再说一次？"
        await chat.finish(fallback)
    except APIError as e:
        # API 错误（如服务不可用、速率限制等）
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        fallback = "唔...脑袋好像有点转不过来，等一下再来吧。"
        await chat.finish(fallback)
    except Exception as e:
        # 其他未预期的错误
        if user_id in chat_history and chat_history[user_id] and chat_history[user_id][-1]["role"] == "user":
            chat_history[user_id].pop()
        fallback = [
            "嗯？怎么了。",
            "...有事就说。",
            "哼。",
            "正义的伙伴现在有点忙。",
            "...你继续说。",
            "怎么了，有什么事吗。",
        ]

        ai_response = random.choice(fallback)
        await chat.finish(ai_response)


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
- 不要每句话都加"..."，偶尔用就行"""

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

        response = await loop.run_in_executor(None, _do_api)
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

    message = str(event.message)

    # 跳过命令、CQ码、空消息
    for pattern in _SKIP_PATTERNS:
        if pattern.match(message):
            return

    # 跳过所有命令（带/或不带/，如"点歌 xxx"也是命令）
    msg_lower = message.lower().lstrip("/")
    if any(msg_lower == cmd or msg_lower.startswith(cmd + " ") for cmd in COMMAND_SET):
        return

    # 检测是否提到bot名字（希亚/Noa/正义的伙伴等）
    _BOT_NAMES = ["希亚", "noa", "结城", "正义的伙伴", "帕菲女王", "小希亚"]
    mentioned = any(name in msg_lower for name in _BOT_NAMES)

    if mentioned:
        # 提到bot名字时，高概率回复（80%）
        if random.random() > 0.8:
            return
        reply = await _ai_generate_reply(message, _MENTIONED_SYSTEM_PROMPT)
        if reply:
            await chatter.finish(reply)
        return

    # 计算插话概率：基础概率 + 话题关键词加成
    msg_lower = message.lower()
    max_prob = CHATTER_BASE_PROBABILITY
    for keyword, prob in _TOPIC_KEYWORDS.items():
        if keyword.lower() in msg_lower:
            max_prob = max(max_prob, prob)

    # 概率判断
    if random.random() > max_prob:
        return

    # 用AI生成回复，失败时用预设话题兜底
    reply = await _ai_generate_reply(message, _CHATTER_SYSTEM_PROMPT)
    if not reply:
        reply = random.choice(_FALLBACK_TOPICS)

    await chatter.finish(reply)


# ========== 自动识别二维码 ==========

_qrcode = on_message(priority=5, block=False)

_qr_detector = QReader()

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
                    # 如果是SGWCMAID开头的二维码，回复识别结果
                    if text.startswith("SGWCMAID"):
                        logger.debug(f"[二维码] 检测到SGWCMAID: {event.message_id}")
                        await _qrcode.finish(f"识别到机台二维码：\n{text}")
                        return
                    else:
                        await _qrcode.finish(f"识别到二维码：\n{text}")
            except FinishedException:
                raise
            except Exception as e:
                logger.warning(f"[二维码] 识别异常: {e}")


# ========== 图片理解 ==========

_img_chat = on_message(priority=4, block=False)

# 最大图片尺寸（像素），超过会压缩
_MAX_IMAGE_SIZE = 1024
# 最大图片文件大小（字节），超过会压缩
_MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
# 最大图片数量
_MAX_IMAGES = 5

_IMG_SYSTEM_PROMPT = """你是结城希亚，有人发了图片给你看。请仔细观察图片并给出自然的反应。

观察要点：
1. 图片主体是什么（人物、动物、物品、场景等）
2. 图片中的文字内容（如果有，请完整转述）
3. 图片的氛围和情感
4. 有趣或值得注意的细节

回复要求：
- 用2-3句话描述你看到的，像日常聊天一样自然
- 如果图片有文字，请把文字内容说出来
- 保持希亚的性格：傲娇、偶尔中二、喜欢甜食和猫
- 看到可爱的东西会不自觉开心，看到奇怪的会吐槽
- 不要用markdown格式"""


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

    # 群聊需要@bot才触发，私聊直接触发
    if gid:
        is_at_me = getattr(event, 'to_me', False) or "希亚" in str(event.message) or "Noa" in str(event.message)
        if not is_at_me:
            return

    # 检查消息是否包含图片
    has_image = any(seg.type == "image" for seg in event.message)
    if not has_image:
        return

    # 提取纯文本（去掉@标记）
    plain = re.sub(r'\[at:qq=\d+\]', '', str(event.message)).strip()

    # 收集所有图片URL（最多5张）
    img_urls = []
    for seg in event.message:
        if seg.type == "image":
            img_urls.append(seg.data.get("url", ""))
            if len(img_urls) >= _MAX_IMAGES:
                break

    if not img_urls:
        return

    try:
        # 下载并处理所有图片
        images_b64 = []
        for img_url in img_urls:
            resp = await _get_http_client().get(img_url, timeout=10.0)
            if resp.status_code != 200:
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

        if not images_b64:
            return

        # 使用视觉模型
        vision_model = _cfg("vision_model", "glm-4v-flash")
        client = _get_client()

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
            return client.chat.completions.create(
                model=vision_model,
                messages=[
                    {"role": "system", "content": _IMG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=int(_cfg("max_tokens", "256")),  # 多图需要更多token
                temperature=float(_cfg("temperature", "0.7")),
                timeout=30.0  # 多图需要更长超时
            )

        response = await loop.run_in_executor(None, _do_vision)
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
            await _img_chat.finish(reply)
    except Exception as e:
        # 模型不支持视觉或请求失败，静默忽略
        logger.debug(f"[图片理解] 失败: {type(e).__name__}: {str(e)[:100]}")


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

    # 主动发言的随机话题（给AI一些灵感）
    proactive_hints = [
        "群里现在很安静",
        "到了下午茶时间了",
        "今天好像没什么事",
        "有点无聊想找人聊天",
        "刚吃完东西",
        "在看窗外的风景",
        "在想接下来做什么",
        "突然想到了什么",
        "该做点什么好呢",
        "天气怎么样呢",
    ]

    while True:
        try:
            # 随机等待 30~60 分钟
            interval = random.randint(AUTO_CHAT_MIN_INTERVAL, AUTO_CHAT_MAX_INTERVAL)
            await asyncio.sleep(interval)

            if not _auto_chat_groups:
                continue

            # 随机选一个群
            group_id = random.choice(_auto_chat_groups)

            # 用AI生成发言
            hint = random.choice(proactive_hints)
            reply = await _ai_generate_reply(hint, _PROACTIVE_SYSTEM_PROMPT)
            if not reply:
                reply = random.choice(_FALLBACK_TOPICS)

            # 发送消息
            try:
                bot = get_bot()
                await bot.call_api(
                    "send_group_msg",
                    group_id=int(group_id),
                    message=reply
                )
                logger.info(f"[自动发言] 群{group_id}: {reply}")
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
    """bot 启动后启动自动发言任务 + 注册定时清理"""
    start_auto_chat()
    try:
        from .commands_schedule import _get_scheduler
        _get_scheduler().add_job(
            _cleanup_old_histories,
            "interval",
            hours=1,
            id="cleanup_chat_histories",
            replace_existing=True,
        )
        logger.info("[定时清理] 已注册 chat_history 定时清理任务（每小时一次）")
    except Exception as e:
        logger.warning(f"[定时清理] 注册失败（APScheduler 可能未安装）: {e}")
