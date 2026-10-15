"""Separate FeimRemote configuration and persistence."""

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_REMOTE_CONFIG: dict[str, Any] = {
    "enabled": False,
    "model": "",
    "max_tool_steps": 4,
    "users": {},
    "tool_permissions": {
        "list": False,
        "read": False,
        "create": False,
        "edit": False,
        "delete": False,
        "shell": False,
        "web_search": False,
        "web_fetch": False,
        "image": False,
    },
    "history_file": "./data/feimremote_history.json",
    "max_history_messages": 40,
}


def merge_remote_config(override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(DEFAULT_REMOTE_CONFIG)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def load_remote_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        return copy.deepcopy(DEFAULT_REMOTE_CONFIG)
    with config_path.open("r", encoding="utf-8") as stream:
        loaded = json.load(stream)
    if not isinstance(loaded, dict):
        raise ValueError(f"FeimRemote config must be a JSON object: {config_path}")
    return merge_remote_config(loaded)


def save_remote_config(path: str | Path, config: dict[str, Any]) -> None:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
    temporary.replace(config_path)
