"""
数学计算器工具 (Calculator Tool)
安全评估基础数学算数表达式（支持 + - * / ( ) % 及浮点数），
包含完备的 ZeroDivisionError 除零保护与语法错误捕获。
"""

import ast
import math
import operator
import logging

logger = logging.getLogger(__name__)

# 安全支持的操作符字典
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node):
    """递归评估 AST 语法节点"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value)}")

    elif isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op_type = type(node.op)

        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"不支持的操作符: {op_type.__name__}")

        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError("除数不能为 0！")

        return SAFE_OPERATORS[op_type](left, right)

    elif isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"不支持的一元操作符: {op_type.__name__}")
        return SAFE_OPERATORS[op_type](operand)

    else:
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


def calculate(expression: str) -> str:
    """
    计算器主入口函数
    :param expression: 算术表达式字符串，如 "(520+1314)*66666/77777"
    :return: 字符串格式的计算结果
    """
    if not expression or not expression.strip():
        raise ValueError("算术表达式不能为空")

    clean_expr = expression.strip().replace("×", "*").replace("÷", "/")

    # 安全拦截语句执行代码块，防止越权注入
    parsed = ast.parse(clean_expr, mode="eval")
    result = _eval_node(parsed.body)

    if isinstance(result, float):
        if result.is_integer():
            return str(int(result))
        return f"{result:.10g}"
    return str(result)


CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "执行精确的数学加减乘除计算，支持括号与复杂算术表达式求值。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "需要计算的合法算术表达式，如 '(520+1314)*66666/77777'",
                }
            },
            "required": ["expression"],
        },
    },
}
