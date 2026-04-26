# 记账模块

import os
import re
from datetime import datetime, timedelta

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from .commands_base import _register, _load_json, _save_json, _DATA_DIR

# 数据文件
_ACCOUNTING_FILE = os.path.join(_DATA_DIR, "accounting.json")
# {user_id: [{"amount": float, "category": str, "note": str, "date": "YYYY-MM-DD HH:MM", "type": "expense/income"}]}

# 余额缓存（从chat.py截图记账写入）
try:
    from .chat import _accounting_balance
except ImportError:
    _accounting_balance = {}


async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _fmt_amount(amt):
    """格式化金额：整数不显示小数，小数显示2位"""
    if amt == int(amt):
        return f"{int(amt)}"
    return f"{amt:.2f}"
_CATEGORY_MAP = {
    # 餐饮
    "吃": "餐饮", "喝": "餐饮", "饭": "餐饮", "奶茶": "餐饮", "咖啡": "餐饮",
    "外卖": "餐饮", "零食": "餐饮", "水果": "餐饮", "饮料": "餐饮", "早餐": "餐饮",
    "午餐": "餐饮", "晚餐": "餐饮", "宵夜": "餐饮", "火锅": "餐饮", "烧烤": "餐饮",
    "蛋糕": "餐饮", "面包": "餐饮", "甜品": "餐饮", "啤酒": "餐饮", "酒": "餐饮",
    # 交通
    "车": "交通", "地铁": "交通", "公交": "交通", "打车": "交通", "油": "交通",
    "高铁": "交通", "火车": "交通", "飞机": "交通", "停车": "交通", "过路费": "交通",
    # 购物
    "买": "购物", "衣服": "购物", "鞋": "购物", "包": "购物", "手机": "购物",
    "电脑": "购物", "数码": "购物", "日用品": "购物", "超市": "购物", "淘宝": "购物",
    "京东": "购物", "拼多多": "购物",
    # 娱乐
    "玩": "娱乐", "游戏": "娱乐", "电影": "娱乐", "唱歌": "娱乐", "旅游": "娱乐",
    "门票": "娱乐", "演出": "娱乐", "音游": "娱乐", "舞萌": "娱乐", "maimai": "娱乐",
    # 住房
    "房租": "住房", "水电": "住房", "电费": "住房", "水费": "住房", "网费": "住房",
    "物业": "住房", "维修": "住房",
    # 学习
    "书": "学习", "课": "学习", "考试": "学习", "培训": "学习", "文具": "学习",
    # 医疗
    "药": "医疗", "医院": "医疗", "看病": "医疗", "体检": "医疗",
    # 收入
    "工资": "收入", "奖金": "收入", "红包": "收入", "转账": "收入", "报销": "收入",
    "零花钱": "收入", "兼职": "收入",
}

_DEFAULT_CATEGORY = "其他"


def _load_accounting() -> dict:
    return _load_json(_ACCOUNTING_FILE) or {}


def _save_accounting(data: dict):
    _save_json(_ACCOUNTING_FILE, data)


_accounting = _load_accounting()


def _parse_amount(text: str):
    """解析金额，支持各种格式"""
    text = text.strip()
    # 移除货币符号
    text = text.replace("¥", "").replace("￥", "").replace("$", "").replace("元", "").strip()

    # 匹配数字（支持小数）
    match = re.search(r'(\d+\.?\d*)', text)
    if not match:
        return None, text

    amount = float(match.group(1))
    remaining = text[:match.start()] + text[match.end():].strip()
    return amount, remaining


def _detect_category(text: str) -> str:
    """自动检测分类"""
    text_lower = text.lower()
    for keyword, category in _CATEGORY_MAP.items():
        if keyword in text_lower:
            return category
    return _DEFAULT_CATEGORY


def _detect_type(text: str) -> str:
    """检测是收入还是支出"""
    income_keywords = ["收入", "收到", "工资", "奖金", "红包", "报销", "赚", "到账", "+", "加"]
    for kw in income_keywords:
        if kw in text:
            return "income"
    return "expense"


async def _cmd_record(event: MessageEvent):
    """记账：/记 午饭 25 /记 +100 工资"""
    content = str(event.message).strip()
    for prefix in ["记", "记账", "记录"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        uid = str(event.user_id)
        records = _accounting.get(uid, [])
        if not records:
            await _send(event, "...记什么。格式：/记 午饭 25\n或：/记 +100 工资")
            return
        # 显示最近5条
        lines = ["[最近记账]\n"]
        for r in records[-5:]:
            sign = "+" if r["type"] == "income" else "-"
            lines.append(f"{sign} {r['date']} {r['category']} {r['note']} {sign}{r['amount']:.0f}")
        lines.append(f"\n共 {len(records)} 条记录")
        await _send(event, "\n".join(lines))
        return

    uid = str(event.user_id)
    amount, remaining = _parse_amount(content)

    if amount is None:
        await _send(event, "...金额呢。格式：/记 午饭 25")
        return

    record_type = _detect_type(content)
    category = _detect_category(remaining)
    note = remaining.replace(category, "").strip() if category != _DEFAULT_CATEGORY else remaining.strip()
    # 清理note中的数字
    note = re.sub(r'\d+\.?\d*', '', note).strip()
    if not note:
        note = category

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
    _save_accounting(_accounting)

    sign = "+" if record_type == "income" else "-"
    await _send(event, f"已记录：{category} {note} {sign}{_fmt_amount(amount)}")


async def _cmd_bill(event: MessageEvent):
    """账单：/账单 /账单 今天 /账单 本月"""
    content = str(event.message).strip()
    for prefix in ["账单", "账目", "明细"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    uid = str(event.user_id)
    records = _accounting.get(uid, [])
    if not records:
        await _send(event, "...还没有记账记录。")
        return

    now = datetime.now()
    today_str = now.strftime("%m-%d")

    # 过滤记录
    filtered = records
    if "今天" in content or "今日" in content:
        filtered = [r for r in records if r["date"].startswith(today_str)]
    elif "昨天" in content or "昨日" in content:
        yesterday = (now - timedelta(days=1)).strftime("%m-%d")
        filtered = [r for r in records if r["date"].startswith(yesterday)]
    elif "本月" in content or "这个月" in content:
        month_prefix = now.strftime("%m-")
        filtered = [r for r in records if r["date"].startswith(month_prefix)]

    if not filtered:
        await _send(event, "...这个时间段没有记录。")
        return

    # 按分类汇总
    expense_by_cat = {}
    income_by_cat = {}
    income_total = 0
    expense_total = 0

    for r in filtered:
        if r["type"] == "income":
            income_total += r["amount"]
            cat = r.get("category", "收入")
            income_by_cat[cat] = income_by_cat.get(cat, 0) + r["amount"]
        else:
            expense_total += r["amount"]
            cat = r["category"]
            expense_by_cat[cat] = expense_by_cat.get(cat, 0) + r["amount"]

    lines = []
    if "今天" in content or "今日" in content:
        title = f"今日账单 ({len(filtered)}笔)"
    elif "昨天" in content or "昨日" in content:
        title = f"昨日账单 ({len(filtered)}笔)"
    elif "本月" in content or "这个月" in content:
        title = f"本月账单 ({len(filtered)}笔)"
    else:
        title = f"账单 ({len(filtered)}笔)"

    lines.append(title)

    # 总支出/总收入
    lines.append(f"支出 {_fmt_amount(expense_total)}  收入 +{_fmt_amount(income_total)}")

    # 支出分类
    if expense_by_cat:
        sorted_cats = sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True)
        cat_str = "  ".join(f"{cat} {_fmt_amount(amount)}" for cat, amount in sorted_cats)
        lines.append(f"支出明细: {cat_str}")

    # 收入分类
    if income_by_cat:
        sorted_income = sorted(income_by_cat.items(), key=lambda x: x[1], reverse=True)
        inc_str = "  ".join(f"{cat} +{_fmt_amount(amount)}" for cat, amount in sorted_income)
        lines.append(f"收入明细: {inc_str}")

    # 结余
    net = income_total - expense_total
    if net >= 0:
        lines.append(f"结余 +{net:.0f}")
    else:
        lines.append(f"结余 {net:.0f}")

    # 显示余额（来自截图记账提取）
    balance = _accounting_balance.get(uid)
    if balance is not None:
        lines.append(f"余额 {balance:.2f}")

    # 明细：只有带"明细"关键词才显示
    if "明细" in content or "详细" in content:
        lines.append("-" * 12)
        for r in reversed(filtered):
            sign = "+" if r["type"] == "income" else "-"
            lines.append(f"{r['date']} {sign}{r['note']} {sign}{r['amount']:.0f}")

    await _send(event, "\n".join(lines))


async def _cmd_stats(event: MessageEvent):
    """统计：/统计 /统计 本月"""
    content = str(event.message).strip()
    for prefix in ["统计", "汇总"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    uid = str(event.user_id)
    records = _accounting.get(uid, [])
    if not records:
        await _send(event, "...还没有记账记录。")
        return

    now = datetime.now()
    # 过滤本月
    month_prefix = now.strftime("%m-")
    if "本月" in content or "这个月" in content:
        filtered = [r for r in records if r["date"].startswith(month_prefix)]
    else:
        filtered = records

    if not filtered:
        await _send(event, "...这个月还没有记录。")
        return

    # 计算日均
    total_expense = sum(r["amount"] for r in filtered if r["type"] == "expense")
    total_income = sum(r["amount"] for r in filtered if r["type"] == "income")

    # 计算天数
    dates = set()
    for r in filtered:
        dates.add(r["date"].split(" ")[0])
    days = max(len(dates), 1)

    # 最大单笔支出
    expenses = [r for r in filtered if r["type"] == "expense"]
    max_expense = max(expenses, key=lambda x: x["amount"]) if expenses else None

    # 最常消费分类
    cat_count = {}
    for r in expenses:
        cat_count[r["category"]] = cat_count.get(r["category"], 0) + 1
    top_cat = max(cat_count, key=cat_count.get) if cat_count else "无"

    lines = []
    if "本月" in content or "这个月" in content:
        lines.append("[本月消费统计]")
    else:
        lines.append("[消费统计]")
    lines.append("-" * 20)
    lines.append(f"总支出: -{total_expense:.0f}")
    lines.append(f"总收入: +{total_income:.0f}")
    lines.append(f"日均支出: -{total_expense/days:.0f}")
    lines.append(f"记账天数: {days}天")
    lines.append(f"总笔数: {len(filtered)}笔")
    if max_expense:
        lines.append(f"最大单笔: {max_expense['category']} {max_expense['note']} -{max_expense['amount']:.0f}")
    lines.append(f"最常消费: {top_cat}（{cat_count.get(top_cat, 0)}笔）")

    await _send(event, "\n".join(lines))


async def _cmd_clear_records(event: MessageEvent):
    """清空记账：/清空记账"""
    uid = str(event.user_id)
    if uid in _accounting and _accounting[uid]:
        count = len(_accounting[uid])
        del _accounting[uid]
        _save_accounting(_accounting)
        await _send(event, f"...已清空 {count} 条记账记录。")
    else:
        await _send(event, "...你本来就没有记录。")


record_cmd = _register("记", _cmd_record, aliases=["记账", "记录"])
bill_cmd = _register("账单", _cmd_bill, aliases=["账目", "明细"])
stats_cmd = _register("统计", _cmd_stats, aliases=["汇总"])
clear_cmd = _register("清空记账", _cmd_clear_records, aliases=["清除记账"])
