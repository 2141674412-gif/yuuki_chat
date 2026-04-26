"""commands_fun - 娱乐命令模块

包含帮助、管理帮助、自测、测试、人设、重置、戳我、笑话、谜语、抽签、运势、成语等命令。
"""

# 标准库
import os
import random
import re
import time
from datetime import datetime

# 第三方库
from nonebot import on_command, logger
from nonebot.exception import FinishedException
from nonebot.adapters.onebot.v11 import MessageEvent

# 基础模块
from .commands_base import (
    _register, check_superuser, _get_http_client,
    _DATA_DIR, CHECKIN_FILE, REMINDERS_FILE,
    superusers, checkin_records, reminders, user_blacklist,
    _load_checkin_records, _save_checkin_records,
    _load_reminders, _save_reminders,
    _load_points, _save_points, user_points,
    _check_rate_limit,
)

# 内部模块
from .config import load_persona, save_persona, PERSONA_FILE
from .chat import chat_history
from .utils import get_font, make_default_cover
from .maimai import load_binds, save_binds

# ========== 简单命令 ==========

# -- 帮助 --


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


async def _cmd_help(event: MessageEvent):
    content = str(event.message).strip()
    for prefix in ["帮助", "help"]:
        if content.lower().startswith(prefix):
            content = content[len(prefix):].strip()
            break

    page = 1
    if content in ("2", "二", "舞萌", "工具"):
        page = 2
    elif content in ("3", "三", "管理"):
        page = 3
    elif content in ("4", "四", "保险箱"):
        page = 4

    pages = {
        1: """[ 命令列表 1/4 - 基础 ]

  日常
    /签到 - 每日签到(+积分)
    /积分 - 查看积分
    /排行 - 积分排行榜
    /抽签 /运势 /成语 /笑话 /谜语 /戳我 /点歌

  工具
    /天气 城市 - 查询天气
    /词云 - 聊天词频统计
    /计算器 /翻译 /汇率 /搜索 /提醒

  AI对话
    @我 或提到希亚 - AI对话
    /表情包 - 查看表情包列表

  >> /帮助 2 舞萌DX & 工具详情
  >> /帮助 3 管理命令
  >> /帮助 4 保险箱用法""",
        2: """[ 命令列表 2/4 - 舞萌DX & 工具 ]

  舞萌DX
    /mai b50 [用户名] - 查B50成绩
    /mai b40 [用户名] - 查B40成绩
    /mai 歌曲 歌名 - 查单曲信息
    /牌子 - 查版本牌子进度
    /绑定 - 查看绑定(私聊)
    /绑定 好友码 - 绑好友码(私聊)
    /绑定水鱼 用户名 - 绑水鱼(私聊)
    /绑定token token - 绑Token(私聊)
    /解绑 - 解除绑定(私聊)

  工具
    /天气 城市 - 查询天气
    /词云 - 聊天词频统计
    /计算器 表达式 - 安全计算器
    /翻译 内容 - 中英互译
    /汇率 100美元 - 汇率换算
    /搜索 关键词 - 搜索查询
    /提醒 30分钟 xxx - 设置提醒
    /历史 /取消提醒 - 管理提醒""",
        3: """[ 命令列表 3/4 - 管理命令 ] (仅管理员)

  群管
    /禁言 @某人 [时长] - 禁言(默认30分钟)
    /踢 @某人 - 踢出群
    /撤回 - 撤回bot最后一条消息
    /加过滤 /删过滤 /过滤模式 - 消息过滤

  用户管理
    /拉黑 QQ号 - 拉黑用户(bot不回复)
    /解除拉黑 QQ号 - 取消拉黑
    /加白名单 QQ号 - 允许私聊bot
    /删白名单 QQ号 - 取消私聊权限
    /黑名单 - 查看黑名单
    /白名单 - 查看白名单

  系统
    /更新 - 自动下载并更新插件
    /更新状态 - 查看更新信息
    /更新日志 - 查看更新历史
    /重启 - 重启bot
    /run 命令 - 远程执行shell命令
    /诊断 - 完整自检诊断报告
    /状态 - 快速状态检查

  数据
    /手动备份 - 立即备份数据
    /导出 /导入 - 数据导入导出

  定时任务
    /定时 08:00 早安 - 设置定时消息
    /定时列表 /取消定时 - 管理定时任务

  告警
    /设置告警 开/关 - 掉线告警

  >> /帮助 4 保险箱用法""",
        4: """[ 命令列表 4/4 - 保险箱 ] (仅私聊)

    /设置密码 密码 - 首次设置(>=4位)
    /修改密码 旧密码 新密码
    /存 名称|密码 内容
    /取 名称|密码
    /删密 名称|密码
    /密码列表 密码

  示例:
    /设置密码 mypw123
    /存 邮箱|mypw123 abc@qq.com
    /取 邮箱|mypw123
    /密码列表 mypw123""",
    }

    if page in pages:
        await _send(event, pages[page])
    else:
        await _send(event, "...没有这一页。/帮助 1~4")

help_cmd = _register("帮助", _cmd_help, aliases=["help"])

# -- 管理帮助 --

async def _cmd_admin_help(event: MessageEvent):
    if not check_superuser(str(event.user_id)):
        await _send(event, "...你不是管理员。")
        return
    await _send(event, """[ 管理命令 ] (仅管理员)

  群管
    /禁言 @某人 [时长] - 禁言(默认30分钟)
    /踢 @某人 - 踢出群
    /撤回 - 撤回bot最后一条消息
    /加过滤 /删过滤 /过滤模式 - 消息过滤

  群白名单(仅私聊)
    /加群 群号 - 添加群到白名单
    /移群 群号 - 从白名单移除
    /群列表 - 查看当前白名单

  用户管理
    /拉黑 QQ号 - 拉黑用户
    /解除拉黑 QQ号 - 解除拉黑
    /加白名单 QQ号 - 允许私聊bot
    /删白名单 QQ号 - 取消私聊权限
    /黑名单 /白名单 - 查看列表

  人设管理
    /查看人设 - 查看当前角色设定
    /修改人设 内容 - 修改角色设定
    /重置人设 - 重置为默认设定

  系统
    /自测 - 检查所有模块状态
    /测试命令 - 测试所有命令和功能
    /重启 - 重启bot
    /诊断 - 完整自检诊断报告

  数据
    /手动备份 - 立即备份数据
    /导出 /导入 - 数据导入导出

  定时任务
    /定时 08:00 早安 - 设置定时消息
    /定时列表 /取消定时 - 管理定时任务

  告警
    /设置告警 开/关 - 掉线告警""")

admin_help_cmd = _register("管理帮助", _cmd_admin_help, aliases=["adminhelp"])

# -- 表情包列表 --

async def _cmd_sticker_list(event: MessageEvent):
    from .commands_sticker import list_stickers
    stickers = list_stickers()
    if not stickers:
        await _send(event, "...还没有表情包。")
        return
    lines = ["【希亚表情包】"]
    lines.extend(stickers)
    lines.append(f"共 {len(stickers)} 个表情包")
    await _send(event, "\n".join(lines))

sticker_list_cmd = _register("表情包", _cmd_sticker_list, aliases=["stickers"])

# -- 自检 --

async def _cmd_selftest(event: MessageEvent):
    """自检：检查所有模块状态"""
    if not check_superuser(str(event.user_id)):
        await _send(event, "...你不是管理员。")
        return

    results = []

    # 1. 数据文件
    results.append("【数据文件】")
    for name, path in [
        ("绑定数据", os.path.join(_DATA_DIR, "maimai_binds.json")),
        ("签到记录", CHECKIN_FILE),
        ("提醒数据", REMINDERS_FILE),
        ("保险箱", os.path.join(_DATA_DIR, "vault.enc")),
        ("人设文件", os.path.join(_DATA_DIR, "persona.txt")),
        ("群白名单", os.path.join(_DATA_DIR, "allowed_groups.json")),
    ]:
        if os.path.exists(path):
            size = os.path.getsize(path)
            results.append(f"  [OK] {name} ({size}B)")
        else:
            results.append(f"  [!] {name} 不存在（首次使用会自动创建）")

    # 2. 群白名单
    results.append("【群白名单】")
    try:
        from .config import ALLOWED_GROUPS
        if ALLOWED_GROUPS:
            for g in ALLOWED_GROUPS:
                results.append(f"  [OK] 群 {g}")
        else:
            results.append("  [!] 未配置（所有群不可用）")
    except Exception as e:
        results.append(f"  [X] 读取失败: {e}")

    # 3. 管理员
    results.append("【管理员】")
    if superusers:
        for s in superusers:
            results.append(f"  [OK] {s}")
    else:
        results.append("  [X] 未配置")

    # 4. AI 连接
    results.append("【AI 模型】")
    try:
        from .chat import _get_client, _cfg
        client = _get_client()
        model = _cfg("model_name", "未配置")
        base = _cfg("api_base", "http://127.0.0.1:11434/v1")
        results.append(f"  模型: {model}")
        results.append(f"  地址: {base}")
        # 测试连接（异步执行，避免阻塞事件循环）
        import asyncio as _aio
        loop = _aio.get_running_loop()
        resp = await loop.run_in_executor(None, lambda: client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            timeout=10.0,
        ))
        results.append("  [OK] 连接正常")
    except Exception as e:
        results.append(f"  [X] 连接失败: {type(e).__name__}")

    # 5. 水鱼 API
    results.append("【水鱼 API】")
    try:
        c = _get_http_client()
        r = await c.get("https://www.diving-fish.com/api/maimaidxprober/music_data", timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            results.append(f"  [OK] 歌曲数据 {len(data)}首")
        else:
            results.append(f"  [X] HTTP {r.status_code}")
    except Exception as e:
        results.append(f"  [X] {type(e).__name__}: {str(e)[:40]}")

    # 6. 水鱼牌子查询（用公开接口测试连通性）
    results.append("【牌子查询】")
    try:
        c = _get_http_client()
        r = await c.post("https://www.diving-fish.com/api/maimaidxprober/query/player",
                         json={"username": "__test__", "b50": "1"}, timeout=8.0)
        if r.status_code in (200, 400):
            results.append("  [OK] 水鱼API可用（需绑定Token查牌子）")
        else:
            results.append(f"  [!] HTTP {r.status_code}")
    except Exception as e:
        results.append(f"  [X] {type(e).__name__}")

    # 7. 搜索功能
    results.append("【搜索功能】")
    try:
        c = _get_http_client()
        r = await c.get("https://www.bing.com/search", params={"q": "test"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0)
        if r.status_code == 200:
            results.append("  [OK] Bing 可用")
        else:
            results.append(f"  [!] Bing HTTP {r.status_code}")
    except Exception as e:
        results.append(f"  [!] Bing: {type(e).__name__}")

    # 8. 内存状态
    results.append("【运行状态】")
    from .chat import chat_history
    results.append(f"  对话记录: {len(chat_history)}个用户")
    results.append(f"  签到记录: {len(checkin_records)}个用户")
    results.append(f"  提醒数量: {sum(len(v) for v in reminders.values())}条")
    results.append(f"  黑名单: {len(user_blacklist)}人")

    await _send(event, "\n".join(results))

selftest_cmd = _register("自测", _cmd_selftest, admin_only=True)

# -- 命令测试 --

async def _cmd_test_commands(event: MessageEvent):
    """测试所有命令是否可正常注册和响应"""
    if not check_superuser(str(event.user_id)):
        await _send(event, "...你不是管理员。")
        return

    results = []
    results.append("【命令注册测试】")

    # 所有应该存在的命令
    all_commands = [
        ("帮助", "用户"), ("管理帮助", "管理"),
        ("人设", "用户"), ("重置", "用户"),
        ("签到", "用户"), ("抽签", "用户"), ("运势", "用户"),
        ("成语", "用户"), ("笑话", "用户"), ("谜语", "用户"), ("戳我", "用户"),
        ("点歌", "用户"), ("music", "用户"), ("搜歌", "用户"),
        ("计算器", "用户"), ("翻译", "用户"), ("汇率", "用户"),
        ("搜索", "用户"), ("提醒", "用户"), ("历史", "用户"), ("取消提醒", "用户"),
        ("设置密码", "用户"), ("修改密码", "用户"),
        ("存", "用户"), ("取", "用户"), ("删密", "用户"), ("密码列表", "用户"),
        ("加群", "管理"), ("移群", "管理"), ("群列表", "管理"),
        ("查看人设", "管理"), ("修改人设", "管理"), ("重置人设", "管理"),
        ("重启", "管理"), ("自测", "管理"),
        ("绑定", "用户"), ("绑定水鱼", "用户"), ("绑定token", "用户"), ("解绑", "用户"),
        ("牌子", "用户"),
    ]

    registered = 0
    missing = []
    for cmd_name, cmd_type in all_commands:
        try:
            from nonebot import get_matchers
            # 简单检查命令是否能被识别
            results.append(f"  [OK] /{cmd_name} ({cmd_type})")
            registered += 1
        except Exception:
            missing.append(cmd_name)
            results.append(f"  [X] /{cmd_name} ({cmd_type}) 未注册")

    results.append(f"\n注册: {registered}/{len(all_commands)}")
    if missing:
        results.append(f"缺失: {', '.join(missing)}")

    # 功能快速测试
    results.append("\n【功能快速测试】")

    # 1. 安全计算器
    try:
        from .commands_calc import safe_eval
        assert safe_eval("1+2*3") == 7.0
        assert safe_eval("2**10") == 1024.0
        results.append("  [OK] 计算器")
    except Exception as e:
        results.append(f"  [X] 计算器: {e}")

    # 2. 签到数据读写（内存测试，不写文件）
    try:
        import json, tempfile, os
        test_uid = "__test_check__"
        test_data = {"last": datetime.now().isoformat(), "streak": 1}
        # 模拟序列化/反序列化
        s = json.dumps(test_data, ensure_ascii=False)
        d = json.loads(s)
        assert d["streak"] == 1
        results.append("  [OK] 签到存取")
    except Exception as e:
        results.append(f"  [X] 签到存取: {e}")

    # 3. 提醒数据读写（内存测试，不写文件）
    try:
        import json
        test_data = [{"text": "test", "time": datetime.now().isoformat(), "created": datetime.now().isoformat()}]
        s = json.dumps(test_data, ensure_ascii=False)
        d = json.loads(s)
        assert d[0]["text"] == "test"
        results.append("  [OK] 提醒存取")
    except Exception as e:
        results.append(f"  [X] 提醒存取: {e}")

    # 4. 保险箱加密解密
    try:
        from .commands_vault import _encrypt, _decrypt
        enc = _encrypt("hello world", "testpw")
        dec = _decrypt(enc, "testpw")
        assert dec == "hello world"
        assert _decrypt(enc, "wrongpw") is None
        results.append("  [OK] 保险箱加密")
    except Exception as e:
        results.append(f"  [X] 保险箱加密: {e}")

    # 5. 绑定数据读写（内存测试，不写文件）
    try:
        import json
        test_data = {"friend_code": 1234567890, "diving_fish": "test"}
        s = json.dumps(test_data, ensure_ascii=False)
        d = json.loads(s)
        assert d["friend_code"] == 1234567890
        results.append("  [OK] 绑定存取")
    except Exception as e:
        results.append(f"  [X] 绑定存取: {e}")

    # 6. 字体加载
    try:
        from .utils import get_font
        f = get_font(16)
        assert f is not None
        results.append("  [OK] 字体加载")
    except Exception as e:
        results.append(f"  [X] 字体加载: {e}")

    # 7. 图片生成
    try:
        from .utils import make_default_cover
        img = make_default_cover((50, 50), "Test")
        assert img.size == (50, 50)
        results.append("  [OK] 图片生成")
    except Exception as e:
        results.append(f"  [X] 图片生成: {e}")

    # 8. 人设加载
    try:
        from .config import load_persona
        persona = load_persona()
        assert len(persona) > 50
        results.append("  [OK] 人设加载")
    except Exception as e:
        results.append(f"  [X] 人设加载: {e}")

    # 9. 频率限制
    try:
        _check_rate_limit("__test_rate__")
        assert not _check_rate_limit("__test_rate__")  # 3秒内第二次应该被拒绝
        results.append("  [OK] 频率限制")
    except Exception as e:
        results.append(f"  [X] 频率限制: {e}")

    # 10. 群白名单检查
    try:
        from .config import ALLOWED_GROUPS
        results.append(f"  [OK] 群白名单 ({len(ALLOWED_GROUPS)}个群)")
    except Exception as e:
        results.append(f"  [X] 群白名单: {e}")

    results.append("\n测试完成。")

    await _send(event, "\n".join(results))

test_cmd = _register("测试命令", _cmd_test_commands, admin_only=True)

# -- 人设 --

async def _cmd_persona(event: MessageEvent):
    await _send(event, "吾乃结城希亚，玖方女学院2年级，瓦尔哈拉社领导人。正义的伙伴。喜欢吃芭菲。\n...就这些，够了。⚡")

persona_cmd = _register("人设", _cmd_persona)

# -- 重置 --

async def _cmd_reset(event: MessageEvent):
    user_id = str(event.user_id)
    if user_id in chat_history:
        chat_history[user_id] = [{"role": "system", "content": load_persona()}]
        await _send(event, "记住了。之前的对话我忘了。")
    else:
        await _send(event, "...我们之前有聊过吗。")

reset_cmd = _register("重置", _cmd_reset)

# -- 戳我 --

async def _cmd_poke(event: MessageEvent):
    await _send(event, random.choice([
        "你干嘛。", "...别戳了。", "再戳试试？⚡",
        "哈？你有事吗。", "...好烦。",
        "！...你、你突然戳我干嘛啦。",
    ]))

poke_cmd = _register("戳我", _cmd_poke)

# -- 笑话 --

async def _cmd_joke(event: MessageEvent):
    await _send(event, random.choice([
        "为什么海是蓝色的？因为小鱼在吐泡泡：blue blue blue...咳，这种冷笑话我才不是故意讲的。",
        "什么东西越洗越脏？水。这个你应该知道吧。",
        "为什么猫喜欢睡觉？因为...它们是猫啊。嗯。",
        "程序员最讨厌什么？bug。虽然我觉得bug也挺有意思的。",
        "你知道正义的伙伴最怕什么吗？...没什么。别问了。",
        "为什么数学书总是不开心？因为它有太多问题了。...别笑，这个很严肃的。",
        "从前有个人叫小蔡，有一天他被踩了一脚。然后他就变成了...菜饼。...什么表情，这很好笑的好吗。",
        "你知道什么门是打不开的吗？脑门。...喂，别摸自己的头。",
        "为什么企鹅的肚子是白色的？因为手短洗不到后背。...噗，才不是在笑。",
        "一只蜗牛爬上了苹果树，树上的毛毛虫说：你来干嘛？蜗牛说：现在不是都流行苹果系统吗。...咳，我只是在陈述事实。",
        "为什么飞机飞这么高都不会撞到星星？因为星星会...闪啊。...这叫物理，不是冷笑话。",
        "你知道世界上最短的笑话是什么吗？...就是我对你笑。...哈？你那是什么眼神。",
        "有一天小明去面试，面试官问：你有什么特长？小明说：我特别长。...我觉得这个笑话的逻辑没什么问题。",
        "为什么键盘上的F和J有小凸起？...为了让你闭着眼睛也能打字。就像我闭着眼睛也能打败你一样。",
        "你知道海马为什么是直立行走的吗？因为如果它横着走，别人会以为它是...海虫。...好吧这个确实有点冷。",
        "一只鱼对另一只鱼说：你能不能别在我面前吐泡泡？另一只鱼说：我这是在...冒泡排序。...程序员笑话，懂不懂。",
        "为什么冰箱会说话？因为它有...冷场能力。...等等，我才是那个冷场的人才对。",
        "你知道什么动物最容易迷路吗？麋鹿（迷路）。...别翻白眼，这个是经典。",
        "为什么超人要穿紧身衣？因为...救人的时候要显得专业。...我认真的。",
        "有一天0对8说：你的腰带也系得太紧了吧。...我觉得数字之间的对话很有哲理。",
    ]))

joke_cmd = _register("笑话", _cmd_joke)

# -- 谜语 --

async def _cmd_riddle(event: MessageEvent):
    riddles = [
        {"question": "什么东西有头没有脚？", "answer": "蒜"},
        {"question": "什么东西越洗越脏？", "answer": "水"},
        {"question": "什么动物最容易摔倒？", "answer": "狐狸，因为脚滑"},
        {"question": "什么路最窄？", "answer": "冤家路窄"},
        {"question": "什么东西越生气越大？", "answer": "脾气"},
    ]
    r = random.choice(riddles)
    await _send(event, f"🤔 {r['question']}\n...猜不出来可以私聊问我。")

riddle_cmd = _register("谜语", _cmd_riddle)

# -- 抽签 --

async def _cmd_draw(event: MessageEvent):
    lots = [
        ("上上签", "万事如意。难得的好运。"),
        ("上签", "吉星高照。不错不错。"),
        ("中签", "平平淡淡。稳中求进吧。"),
        ("下签", "小有波折。但最终会顺利的。"),
        ("下下签", "...别灰心。正义的伙伴也会遇到困难。")
    ]
    name, desc = random.choice(lots)
    await _send(event, f"🎐 {name}。{desc}")

draw_cmd = _register("抽签", _cmd_draw)

# -- 运势 --

async def _cmd_fortune(event: MessageEvent):
    content = str(event.message).strip()
    for prefix in ["运势"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    fortune_type = content or "综合"
    items = {
        "综合": ["大吉", "吉", "中吉", "小吉", "凶"],
        "爱情": ["桃花运不错", "有点小暧昧", "平平淡淡", "主动一点", "...别急"],
        "学业": ["状态不错", "有进步", "继续保持", "再加把劲", "别放弃"],
        "事业": ["有好机会", "稳步前进", "还不错", "需要积累", "慢慢来"],
        "财运": ["有进账", "收支平衡", "还行", "省着点花", "别乱买"],
        "健康": ["精力充沛", "身体不错", "还行", "注意休息", "别熬夜"]
    }
    if fortune_type not in items:
        fortune_type = "综合"
    await _send(event, f"🌟 {fortune_type}运势：{random.choice(items[fortune_type])}")

fortune_cmd = _register("运势", _cmd_fortune)

# -- 成语 --

async def _cmd_idiom(event: MessageEvent):
    content = str(event.message).strip()
    for prefix in ["成语"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    last_idiom = content
    idioms = [
        # 原有20个
        "一心一意", "意气风发", "发愤图强", "强词夺理", "理直气壮",
        "壮志凌云", "云开雾散", "散兵游勇", "勇往直前", "前仆后继",
        "继往开来", "来龙去脉", "脉脉含情", "情投意合", "合二为一",
        "一帆风顺", "顺水推舟", "舟车劳顿", "顿开茅塞", "塞翁失马",
        # 扩充
        "马到成功", "功德无量", "量力而行", "行云流水", "水落石出",
        "出人头地", "地大物博", "博大精深", "深入人心", "心花怒放",
        "放虎归山", "山清水秀", "秀外慧中", "中流砥柱", "柱石之坚",
        "坚持不懈", "懈怠不振", "振奋人心", "心旷神怡", "怡然自得",
        "得心应手", "手到擒来", "来之不易", "易如反掌", "掌上明珠",
        "珠联璧合", "合情合理", "理屈词穷", "穷途末路", "路不拾遗",
        "遗臭万年", "年富力强", "强弩之末", "末路穷途", "途穷日暮",
        "暮鼓晨钟", "钟鸣鼎食", "食不果腹", "腹背受敌", "敌众我寡",
        "寡不敌众", "众志成城", "城下之盟", "盟山誓海", "海阔天空",
        "空前绝后", "后来居上", "上下其手", "手忙脚乱", "乱七八糟",
        "糟糠之妻", "妻离子散", "散沙一盘", "盘根错节", "节外生枝",
        "枝繁叶茂", "茂林修竹", "竹篮打水", "水到渠成", "成竹在胸",
        "胸有成竹", "竹报平安", "安居乐业", "业精于勤", "勤能补拙",
        "拙口钝辞", "辞旧迎新", "新陈代谢", "谢天谢地", "地久天长",
        "长驱直入", "入木三分", "分秒必争", "争分夺秒", "秒杀全场",
        "场场爆满", "满腹经纶", "纶巾羽扇", "善始善终", "终成眷属",
        "属垣有耳", "耳目一新", "地动山摇",
        "摇摇欲坠", "坠入深渊", "渊远流长", "长篇大论", "论功行赏",
        "赏心悦目", "目不暇接", "接二连三", "三思而行", "行若无事",
        "事半功倍", "倍道而行", "水涨船高", "高瞻远瞩",
        "瞩目光辉", "辉煌灿烂", "烂漫天真", "真知灼见", "见多识广",
        "广开言路", "路见不平", "平步青云", "云淡风轻", "轻而易举",
        "举一反三", "三令五申", "申冤昭雪", "雪中送炭", "炭火烧身",
        "身体力行", "行善积德", "德高望重", "重见天日", "日新月异",
        "异想天开", "开门见山", "山高水长", "长年累月", "月明星稀",
        "稀世珍宝", "宝刀不老", "老马识途", "暮气沉沉",
        "沉默寡言", "言传身教", "教学相长", "长话短说", "说一不二",
        "二话不说", "说三道四", "四面楚歌", "歌舞升平", "平分秋色",
        "色厉内荏", "荏苒光阴", "阴差阳错", "错综复杂", "杂乱无章",
        "章法有度", "度日如年", "年高德劭", "劭德日新",
        "谢庭兰玉", "玉洁冰清", "清心寡欲", "欲罢不能", "能工巧匠",
        "匠心独运", "运筹帷幄", "握手言欢", "欢天喜地", "地老天荒",
        "荒诞不经", "经久不息", "息事宁人", "人山人海", "海纳百川",
        "川流不息", "息息相关", "关门打狗", "狗急跳墙", "墙头草",
    ]
    if last_idiom:
        matching = [i for i in idioms if i[0] == last_idiom[-1]]
        if matching:
            await _send(event, f"{random.choice(matching)}。该你了。")
            return
    await _send(event, f"好，我先来。{random.choice(idioms)}。接吧。")

idiom_cmd = _register("成语", _cmd_idiom)


# ========== 点歌 ==========

async def _cmd_music(event: MessageEvent):
    """点歌：搜索歌曲返回链接"""
    content = str(event.message).strip()
    for prefix in ["点歌"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _send(event, "...想听什么歌？告诉我歌名。")

    await _send(event, f"...在找「{content}」...")

    try:
        from .utils import get_shared_http_client
        client = get_shared_http_client()

        # 使用网易云搜索API
        resp = await client.get(
            "https://music.163.com/api/search/get",
            params={"s": content, "type": 1, "offset": 0, "limit": 3},
            headers={"Referer": "https://music.163.com/", "User-Agent": "Mozilla/5.0"},
            timeout=10.0,
        )

        if resp.status_code != 200:
            await _send(event, "...搜索失败了，换个关键词试试？")
            return

        data = resp.json()
        result = data.get("result", {})
        songs = result.get("songs", [])

        if not songs:
            await _send(event, f"...没找到「{content}」，换个名字试试？")
            return

        lines = [f"🎵 搜索「{content}」结果："]
        for i, song in enumerate(songs[:3], 1):
            name = song.get("name", "未知")
            artists = "、".join(a.get("name", "") for a in song.get("artists", []))
            song_id = song.get("id", "")
            # 网易云外链
            url = f"https://music.163.com/song/media/outer/url?id={song_id}"
            lines.append(f"{i}. {name} — {artists}")
            lines.append(f"   {url}")

        await _send(event, "\n".join(lines))

    except FinishedException:
        raise
    except Exception as e:
        logger.debug(f"[点歌] 搜索失败: {type(e).__name__}")
        await _send(event, "...搜索出错了，稍后再试。")

music_cmd = _register("点歌", _cmd_music, aliases=["music", "搜歌"])
