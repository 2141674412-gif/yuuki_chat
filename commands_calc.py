# 安全计算器模块

import ast
import operator
import re

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException

from .commands_base import _register


_SAFE_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}



async def _send(event, msg):
    """发送消息辅助函数"""
    from nonebot import get_bot
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)


def _safe_eval_node(node: ast.AST) -> float:
    """递归求值 AST 节点，仅允许数字常量和白名单运算符。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"不允许的运算符: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError("除数不能为零")
        if op_type is ast.Pow and abs(right) > 100:
            raise ValueError("幂运算指数过大")
        return _SAFE_OPERATORS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"不允许的一元运算符: {op_type.__name__}")
        return _SAFE_OPERATORS[op_type](_safe_eval_node(node.operand))
    raise ValueError("不支持的表达式")


def safe_eval(expr: str) -> float:
    """安全地计算数学表达式，仅支持基本算术运算。"""
    tree = ast.parse(expr, mode="eval")
    return _safe_eval_node(tree.body)


# -- 计算器 --

async def _cmd_calc(event: MessageEvent):
    expr = str(event.message).replace("计算器", "").strip()

    if not expr:
        await _send(event, "...算什么。你倒是给我算式啊。")

    if not re.match(r'^[\d+\-*/().\s^eE]+$', expr):
        await _send(event, "这个我算不了。太复杂了。")
        return

    try:
        result = safe_eval(expr)
        if isinstance(result, float) and result == int(result):
            result = int(result)
        await _send(event, f"{result}。这种程度的问题...不需要正义的伙伴吧。")
    except ZeroDivisionError:
        await _send(event, "...除以零了。你故意的吧。")
    except (ValueError, SyntaxError):
        await _send(event, "这个我算不了。太复杂了。")
    except FinishedException:
        raise
    except Exception:
        await _send(event, "...算错了。不怪我。")

calc_cmd = _register("计算器", _cmd_calc)
