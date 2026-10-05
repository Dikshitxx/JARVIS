import ast
import operator
from datetime import datetime
import json
from urllib.parse import urlencode
from urllib.request import urlopen

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


def get_weather(location: str = "") -> str:
    if not location.strip():
        return "I need a city or location to check the current weather."
    try:
        query = urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
        with urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{query}", timeout=10) as response:
            places = json.load(response).get("results") or []
        if not places:
            return f"I couldn't find a weather location matching '{location}'."
        place = places[0]
        query = urlencode({
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "timezone": "auto",
        })
        with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=10) as response:
            current = json.load(response).get("current") or {}
        return (
            f"Current weather in {place['name']}: {current.get('temperature_2m')}°C, "
            f"feels like {current.get('apparent_temperature')}°C, "
            f"humidity {current.get('relative_humidity_2m')}%, "
            f"wind {current.get('wind_speed_10m')} km/h."
        )
    except Exception as exc:
        return f"Weather service failed for '{location}': {exc}"


register(Tool(
    name="get_time",
    description="Get the local date and time. Use this whenever the user asks about the time or date.",
    parameters={"type": "object", "properties": {}},
    func=get_time,
    keywords=("time", "date", "day"),
    parallel_safe=True,
))

register(Tool(
    name="get_system_info",
    description="Get real-time RAM, CPU and disk usage of this computer. Use this when the user asks about system resources or performance.",
    parameters={"type": "object", "properties": {}},
    func=get_system_info,
    keywords=("ram", "memory use", "cpu", "disk", "system status", "performance", "telemetry"),
    parallel_safe=True,
    metadata={"direct_information": True, "offline_summary": "check this computer's system status"},
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
    keywords=("calculate", "compute", "arithmetic", "math", "sum", "product"),
    parallel_safe=True,
))

register(Tool(
    name="get_weather",
    description="Get current weather for a city or location. Use this for current weather questions, not web search.",
    parameters={
        "type": "object",
        "properties": {"location": {"type": "string", "description": "City or location to check"}},
        "required": ["location"],
    },
    func=get_weather,
    keywords=("weather", "temperature", "forecast", "wind", "humidity"),
    parallel_safe=True,
))
