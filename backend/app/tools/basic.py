import ast
import operator
from datetime import datetime

import psutil

from app.tools.registry import Tool, register


def get_time() -> str:
    return datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


def get_system_info() -> str:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    cpu = psutil.cpu_percent(interval=0.5)
    return (
        f"RAM: {mem.used / 1e9:.1f} GB used of {mem.total / 1e9:.1f} GB ({mem.percent}%). "
        f"CPU: {cpu}%. "
        f"Disk C: {disk.used / 1e9:.0f} GB used of {disk.total / 1e9:.0f} GB ({disk.percent}%)."
    )


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Unsupported expression")


def calculate(expression: str) -> str:
    result = _eval(ast.parse(expression, mode="eval").body)
    return str(result)


register(Tool(
    name="get_time",
    description="Get the current local date and time. Use this whenever the user asks about the time or date.",
    parameters={"type": "object", "properties": {}},
    func=get_time,
))

register(Tool(
    name="get_system_info",
    description="Get real-time RAM, CPU and disk usage of this computer. Use this when the user asks about system resources or performance.",
    parameters={"type": "object", "properties": {}},
    func=get_system_info,
))

register(Tool(
    name="calculate",
    description="Evaluate a math expression exactly, e.g. '234 * 17 + 5'. Use this for any arithmetic instead of computing it yourself.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "The math expression, e.g. '12 * (3 + 4)'"}
        },
        "required": ["expression"],
    },
    func=calculate,
))
