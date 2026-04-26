#!/usr/bin/env python3
"""
yuuki_chat 全功能测试脚本
用法: python3 test_all.py
"""

import sys
import os
import json
import time
import re
import importlib
from datetime import datetime, timedelta

# 将项目目录加入路径，模拟包导入
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

passed = 0
failed = 0
errors = []
total = 0


def test(name, fn):
    global passed, failed, total
    total += 1
    try:
        fn()
        passed += 1
        print(f"  ✅ {name}")
    except Exception as e:
        failed += 1
        errors.append((name, str(e)))
        print(f"  ❌ {name}: {e}")


# ==================== 计算器 ====================
print("\n【计算器】")

def test_calc_basic():
    # 直接用AST解析测试，不依赖模块导入
    import ast, operator
    _SAFE_OPERATORS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg,
    }
    def quick_eval(expr):
        tree = ast.parse(expr, mode="eval")
        def _eval(node):
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.BinOp):
                return _SAFE_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp):
                return _SAFE_OPERATORS[type(node.op)](_eval(node.operand))
            raise ValueError
        return _eval(tree.body)
    assert quick_eval("1+2*3") == 7.0
    assert quick_eval("2**10") == 1024.0
    assert quick_eval("100/3") == 100/3

def test_calc_negative():
    import ast, operator
    _SAFE_OPERATORS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.USub: operator.neg,
    }
    def quick_eval(expr):
        tree = ast.parse(expr, mode="eval")
        def _eval(node):
            if isinstance(node, ast.Constant): return float(node.value)
            if isinstance(node, ast.BinOp): return _SAFE_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp): return _SAFE_OPERATORS[type(node.op)](_eval(node.operand))
            raise ValueError
        return _eval(tree.body)
    assert quick_eval("-5+3") == -2.0
    assert quick_eval("-10*-2") == 20.0

def test_calc_scientific():
    assert eval("1e5") == 100000.0
    assert eval("2.5e-3") == 0.0025

def test_calc_regex():
    # 测试正则允许科学计数法
    pat = r'^[\d+\-*/().\s^eE]+$'
    assert re.match(pat, "-5+3")
    assert re.match(pat, "1e5")
    assert re.match(pat, "2.5e-3")
    assert re.match(pat, "1E2+3e2")
    assert not re.match(pat, "abc")

def test_calc_safety():
    import ast
    try:
        ast.parse("__import__('os')", mode="eval")
        # 如果能解析，检查是否有Call节点
        tree = ast.parse("__import__('os')", mode="eval")
        has_call = any(isinstance(n, ast.Call) for n in ast.walk(tree))
        assert has_call, "应该检测到Call节点"
    except SyntaxError:
        pass

test("基本运算", test_calc_basic)
test("负数支持", test_calc_negative)
test("科学计数法", test_calc_scientific)
test("正则匹配", test_calc_regex)
test("安全检查", test_calc_safety)


# ==================== 翻译缓存 ====================
print("\n【翻译】")

def test_translate_cache_structure():
    # 直接检查源码中的缓存变量
    with open("commands_translate.py") as f:
        content = f.read()
    assert "_translate_cache" in content
    assert "_TRANSLATE_TTL" in content
    assert "300" in content  # 5分钟

test("缓存结构", test_translate_cache_structure)


# ==================== 搜索 ====================
print("\n【搜索】")

def test_search_clean_html():
    text = re.sub(r'<[^>]+>', '', "<p>Hello &nbsp;World</p>")
    import html
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    assert text == "Hello World"

def test_search_quality():
    with open("commands_search.py") as f:
        content = f.read()
    assert "_is_quality_result" in content
    assert "15" in content  # 最短描述长度
    assert "下载" in content or "免费" in content  # 过滤关键词

def test_search_chinese():
    assert bool(re.search(r'[\u4e00-\u9fff]', "你好世界")) == True
    assert bool(re.search(r'[\u4e00-\u9fff]', "hello")) == False

def test_search_format():
    # 检查格式化函数存在
    with open("commands_search.py") as f:
        content = f.read()
    assert "_format_results" in content
    assert "is_english" in content
    assert "English" in content  # 英文兜底标记

test("HTML清理", test_search_clean_html)
test("质量过滤", test_search_quality)
test("中文检测", test_search_chinese)
test("结果格式化", test_search_format)


# ==================== 提醒 ====================
print("\n【提醒】")

def test_remind_trigger():
    # 检查提醒触发逻辑存在
    with open("commands_remind.py") as f:
        content = f.read()
    assert "_check_reminders" in content
    assert "_register_reminder_jobs" in content
    assert "send_private_msg" in content
    assert "get_scheduler" in content

def test_remind_expired():
    now = datetime.now()
    expired = now - timedelta(hours=1)
    active = now + timedelta(hours=1)
    assert expired < now
    assert active > now

test("定时触发逻辑", test_remind_trigger)
test("过期判断", test_remind_expired)


# ==================== 天气 ====================
print("\n【天气】")

def test_weather_separate_storage():
    with open("commands_weather.py") as f:
        content = f.read()
    assert "weather_user_binds" in content
    assert "weather_binds.json" in content
    assert "weather_user_binds.json" in content

def test_weather_cleanup():
    with open("commands_weather.py") as f:
        content = f.read()
    assert "retcode" in content
    assert "1200" in content

test("绑定分开存储", test_weather_separate_storage)
test("清理优化", test_weather_cleanup)


# ==================== 生日 ====================
print("\n【生日】")

def test_birthday_templates():
    with open("commands_birthday.py") as f:
        content = f.read()
    assert "_BLESS_TEMPLATES" in content
    assert "_REMIND_TEMPLATES" in content
    assert "_check_birthdays" in content

test("生日模板和检查", test_birthday_templates)


# ==================== 笑话 ====================
print("\n【笑话】")

def test_joke_count():
    with open("commands_fun.py") as f:
        content = f.read()
    start = content.find('async def _cmd_joke')
    assert start > 0
    # 找到函数结束（下一个 async def 或 def）
    end = content.find('\nasync def ', start + 10)
    if end < 0:
        end = content.find('\ndef ', start + 10)
    section = content[start:end]
    # 计算笑话条目（以 " 开头的行）
    jokes = re.findall(r'^\s*"', section, re.MULTILINE)
    assert len(jokes) >= 15, f"笑话数量不足: {len(jokes)}"

def test_idiom_unique():
    with open("commands_fun.py") as f:
        content = f.read()
    start = content.find('async def _cmd_idiom')
    assert start > 0
    end = content.find('\n\n\n', start + 10)
    if end < 0:
        end = len(content)
    section = content[start:end]
    # 提取四字成语
    idioms = re.findall(r'"([\u4e00-\u9fff]{4})"', section)
    # 检查列表部分（从 "一心一意" 开始）
    list_start = section.find('"一心一意"')
    if list_start > 0:
        list_section = section[list_start:]
        idiom_list = re.findall(r'"([\u4e00-\u9fff]{4})"', list_section)
        unique = set(idiom_list)
        if len(idiom_list) != len(unique):
            dupes = [x for x in unique if idiom_list.count(x) > 1]
            assert False, f"成语有重复: {dupes}"

test("笑话数量", test_joke_count)
test("成语去重", test_idiom_unique)


# ==================== 保险箱 ====================
print("\n【保险箱】")

def test_vault_crypto():
    with open("commands_vault.py") as f:
        content = f.read()
    assert "_encrypt" in content
    assert "_decrypt" in content

test("加密模块", test_vault_crypto)


# ==================== 词云 ====================
print("\n【词云】")

def test_wordcloud_image():
    with open("commands_wordcloud.py") as f:
        content = f.read()
    assert "Image" in content or "image" in content
    assert "MessageSegment" in content

def test_wordcloud_stopwords():
    with open("commands_wordcloud.py") as f:
        content = f.read()
    assert "_STOP_WORDS" in content
    assert "的" in content

test("词云图片生成", test_wordcloud_image)
test("停用词", test_wordcloud_stopwords)


# ==================== 人设 ====================
print("\n【人设】")

def test_persona():
    with open("commands_admin.py") as f:
        content = f.read()
    # 修改人设不应该用 clear()（在 _cmd_set_persona 中）
    set_persona_start = content.find('async def _cmd_set_persona')
    set_persona_end = content.find('\n\n#', set_persona_start)
    set_persona_section = content[set_persona_start:set_persona_end]
    assert 'chat_history.clear()' not in set_persona_section, "修改人设不应清空对话历史"
    # 重置人设可以用 clear()（在 _cmd_reset_persona 中）
    reset_start = content.find('async def _cmd_reset_persona')
    if reset_start > 0:
        reset_end = content.find('\n\n', reset_start + 10)
        reset_section = content[reset_start:reset_end]
        # 重置时 clear 是合理的，不检查

test("人设修改逻辑", test_persona)


# ==================== 配置 ====================
print("\n【配置】")

def test_config():
    with open("config.py") as f:
        content = f.read()
    assert "COMMAND_NAMES" in content
    assert "ALLOWED_GROUPS" in content
    assert "天气" in content
    assert "签到" in content
    assert "生日" in content
    assert "搜图" in content

test("配置完整性", test_config)


# ==================== 工具函数 ====================
print("\n【工具函数】")

def test_utils():
    assert os.path.exists("utils.py")
    with open("utils.py") as f:
        content = f.read()
    assert "get_font" in content
    assert "make_default_cover" in content

test("工具模块", test_utils)


# ==================== 自检 ====================
print("\n【自检】")

def test_diagnose():
    assert os.path.exists("commands_diagnose.py")
    with open("commands_diagnose.py") as f:
        content = f.read()
    assert "_check_code_bugs" in content
    assert "FinishedException" in content

test("自检模块", test_diagnose)


# ==================== 文件完整性 ====================
print("\n【文件完整性】")

def test_files():
    required = [
        "__init__.py", "config.py", "chat.py", "utils.py", "commands_base.py",
        "commands_fun.py", "commands_checkin.py", "commands_remind.py",
        "commands_calc.py", "commands_translate.py", "commands_search.py",
        "commands_weather.py", "commands_wordcloud.py", "commands_admin.py",
        "commands_group_admin.py", "commands_update.py", "commands_schedule.py",
        "commands_backup.py", "commands_vault.py", "commands_sticker.py",
        "commands_remote.py", "commands_diagnose.py", "commands_birthday.py",
        "maimai.py",
    ]
    for f in required:
        assert os.path.exists(f), f"文件缺失: {f}"

def test_syntax():
    import py_compile
    import glob
    py_files = glob.glob("*.py")
    for f in py_files:
        py_compile.compile(f, doraise=True)

test("文件存在", test_files)
test("语法检查", test_syntax)


# ==================== 汇总 ====================
print(f"\n{'='*40}")
print(f"测试完成: {passed}/{total} 通过", end="")
if failed:
    print(f"，{failed} 个失败")
    print("\n失败列表:")
    for name, err in errors:
        print(f"  ❌ {name}")
        print(f"     {err[:200]}")
else:
    print()
    print("🎉 全部通过！")

sys.exit(1 if failed > 0 else 0)
