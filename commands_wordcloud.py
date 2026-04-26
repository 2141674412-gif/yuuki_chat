# ========== 词云统计 ==========

# 标准库
import re
import time
from collections import Counter

# 第三方库
from nonebot import logger
from nonebot.exception import FinishedException
from nonebot.adapters.onebot.v11 import MessageEvent

# 从子模块导入
from .commands_base import _register


# 中文停用词集合
_STOP_WORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 里 为 什么 吗 吧 啊 呢 嗯 哦 哈 嘿 呀 哇 哟 唉 哼 嘛 "
    "么 啦 呗 咯 呐 哩 诶 噢 嗨 嘞 嗯哼 哼唧 啧 哎 哟呵 哈哈 嘻嘻 嘿嘿 呼呼 嘎 "
    "这个 那个 什么 怎么 怎么样 哪里 谁 多少 多大 几个 哪个 为什么 可以 吗 "
    "不是 没 没有 还 还是 又 或者 但是 而且 因为 所以 如果 虽然 不过 然后 一下 "
    "一些 一种 一样 一个 的话 起来 出来 过来 回来 下来 上来 进去 出去 回去 "
    "知道 觉得 认为 认为 想 看 说 做 去 来 给 让 被 把 对 比 从 到 在 向 往 "
    "以 按 据 将 被 把 与 及 等 中 内 外 前 后 左 右 上 下 大 小 多 少 高 低 "
    "长 短 好 坏 新 旧 快 慢 冷 热 远 近 早 晚 真 假 对 错 美 丑 强 弱 "
    "but the a an is are was were be been being have has had do does did "
    "will would shall should can could may might must need to of in on at "
    "by for with from and or not no so if then than too very just about "
    "that this it its i me my we our you your he him his she her they them "
    "their what which who when where how why all each every both few more "
    "most other some such only own same also as into through during before "
    "after above below between out off over under again further then once "
    "here there when where why how all any both each few more most other "
    "some such no nor not only own same so than too very s t m re ve ll d"
)


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


async def _cmd_wordcloud(event: MessageEvent):
    """词云统计：/词云 [天数] — 统计全群消息"""
    content = str(event.message).strip()
    for prefix in ["词云"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    group_id = getattr(event, 'group_id', 0)

    # 从群消息记录中读取数据
    try:
        from .chat import _group_chat_log
    except ImportError:
        _group_chat_log = {}

    group_messages = _group_chat_log.get(group_id, [])
    if not group_messages:
        await _send(event, "...暂时没有群聊天记录可以统计。")
        return

    # 可选：按天数过滤（默认7天）
    days = 7
    if content and content.isdigit():
        days = int(content)
        days = max(1, min(days, 30))  # 限制1-30天

    cutoff = time.time() - days * 24 * 3600
    all_text = ""
    for ts, uid, text in group_messages:
        if ts >= cutoff:
            all_text += text + " "

    if not all_text.strip():
        await _send(event, f"...最近{days}天没有群聊天记录可以统计。")
        return

    # 分词
    words = []
    # 优先使用jieba分词（更准确）
    try:
        import jieba
        import logging
        jieba.setLogLevel(logging.INFO)
        seg_list = jieba.cut_for_search(all_text)
        words = [w for w in seg_list if len(w) >= 2 and w not in _STOP_WORDS]
    except Exception:
        # jieba未安装，回退到简单2-gram
        zh_chunks = re.findall(r'[\u4e00-\u9fff]{2,}', all_text)
        for chunk in zh_chunks:
            for i in range(len(chunk) - 1):
                words.append(chunk[i:i+2])
        en_chunks = re.findall(r'[a-zA-Z]{2,}', all_text)
        for chunk in en_chunks:
            words.append(chunk.lower())
        words = [w for w in words if w not in _STOP_WORDS]
    if not words:
        await _send(event, "...聊天内容太少，统计不出什么来。")
        return
    # 统计词频
    counter = Counter(words)
    top10 = counter.most_common(10)
    top20 = counter.most_common(20)

    # 尝试用PIL生成词云图片
    try:
        from PIL import Image, ImageDraw, ImageFont
        from .utils import get_font

        img_width, img_height = 800, 400
        img = Image.new("RGB", (img_width, img_height), "#1a1a2e")
        draw = ImageDraw.Draw(img)

        # 预定义一些好看的颜色
        _colors = [
            "#e94560", "#0f3460", "#16213e", "#e94560",
            "#533483", "#0f3460", "#e94560", "#16213e",
            "#533483", "#e94560", "#0f3460", "#533483",
            "#e94560", "#16213e", "#0f3460", "#533483",
            "#e94560", "#0f3460", "#16213e", "#533483",
        ]

        # 按词频从大到小排列，字号从大到小
        if top20:
            max_count = top20[0][1]
            min_count = top20[-1][1]
            count_range = max_count - min_count if max_count != min_count else 1

        import random
        random.seed(42)

        # 简单的贪心放置，避免重叠
        _placed = []  # [(x, y, w, h), ...]

        def _try_place(text_w, text_h):
            """尝试找一个不重叠的位置"""
            for _ in range(200):
                x = random.randint(10, max(10, img_width - text_w - 10))
                y = random.randint(10, max(10, img_height - text_h - 10))
                box = (x - 4, y - 4, x + text_w + 4, y + text_h + 4)
                overlap = False
                for px, py, pw, ph in _placed:
                    if not (box[2] < px or box[0] > px + pw or box[3] < py or box[1] > py + ph):
                        overlap = True
                        break
                if not overlap:
                    return x, y
            return None

        for i, (word, count) in enumerate(top20):
            # 字号：最大60，最小16
            ratio = (count - min_count) / count_range if count_range else 1
            font_size = int(16 + ratio * 44)
            try:
                font = get_font(font_size, bold=(ratio > 0.5))
            except Exception:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), word, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            pos = _try_place(text_w, text_h)
            if pos:
                x, y = pos
                color = _colors[i % len(_colors)]
                draw.text((x, y), word, fill=color, font=font)
                _placed.append((x, y, text_w, text_h))

        # 保存到临时文件
        import tempfile
        import os
        tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_wordcloud")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"wordcloud_{int(time.time())}.png")
        img.save(tmp_path, "PNG")

        from nonebot.adapters.onebot.v11 import MessageSegment
        lines = [f"【词云 Top10（近{days}天）】"]
        for i, (word, count) in enumerate(top10, 1):
            lines.append(f"{i}. {word} ({count}次)")
        await _send(event, "\n".join(lines) + "\n[词云图片]" + MessageSegment.image(f"file://{tmp_path}"))
    except FinishedException:
        raise
    except Exception as e:
        logger.debug(f"[词云] 生成图片失败，回退到文字列表：{e}")
        lines = [f"【词云 Top10（近{days}天）】"]
        for i, (word, count) in enumerate(top10, 1):
            lines.append(f"{i}. {word} ({count}次)")
        await _send(event, "\n".join(lines))

wordcloud_cmd = _register("词云", _cmd_wordcloud)
