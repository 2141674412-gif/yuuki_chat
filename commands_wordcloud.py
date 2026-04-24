# ========== 词云统计 ==========

# 标准库
import re
import time
from collections import Counter

# 第三方库
from nonebot import logger
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

async def _cmd_wordcloud(event: MessageEvent):
    """词云统计：/词云 [天数] — 统计全群消息"""
    content = str(event.message).strip()
    for prefix in ["词云"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    group_id = str(getattr(event, 'group_id', 0))

    # 从群消息记录中读取数据
    try:
        from .chat import _group_chat_log
    except ImportError:
        _group_chat_log = {}

    group_messages = _group_chat_log.get(group_id, [])
    if not group_messages:
        await wordcloud_cmd.finish("...暂时没有群聊天记录可以统计。")
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
        await wordcloud_cmd.finish(f"...最近{days}天没有群聊天记录可以统计。")
        return

    # 分词
    words = []
    # 优先使用jieba分词（更准确）
    try:
        import jieba
        jieba.setLogLevel(jieba.logging.INFO)
        seg_list = jieba.cut_for_search(all_text)
        words = [w for w in seg_list if len(w) >= 2 and w not in _STOP_WORDS]
    except ImportError:
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
        await wordcloud_cmd.finish("...聊天内容太少，统计不出什么来。")
        return
    # 统计词频
    counter = Counter(words)
    top10 = counter.most_common(10)
    lines = [f"【词云 Top10（近{days}天）】"]
    for i, (word, count) in enumerate(top10, 1):
        lines.append(f"{i}. {word} ({count}次)")
    await wordcloud_cmd.finish("\n".join(lines))

wordcloud_cmd = _register("词云", _cmd_wordcloud)
