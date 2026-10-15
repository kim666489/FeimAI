"""Example FeimAI tool module. Enable it in Settings > Tools to use it."""

from datetime import datetime


TOOLS = [
    {
        "name": "get_current_time",
        "description": "Return the current local date and time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def run(tool_name, arguments, context):
    if tool_name != "get_current_time":
        raise ValueError(f"Unsupported tool: {tool_name}")
    return datetime.now().astimezone().isoformat(timespec="seconds")
