"""Independent FeimVoice configuration and persistence."""

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_VOICE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "stt": {
        "engine": "google",
        "language": "th-TH",
        "timeout": 5,
        "phrase_time_limit": 10,
        "ambient_noise_duration": 0.5,
        "pause_threshold": 0.8,
    },
    "tts": {
        "enabled": True,
        "engine": "sapi",
        "voice_id": "",
        "rate": 170,
        "volume": 0.8,
        "pitch": 0,
        "thai_model": "vachana",
        "thai_speaker": "th_f_1",
        "thai_rate": 1.0,
        "thai_pitch": 0.0,
        "thai_volume_db": 0.0,
    },
    "wake": {
        "enabled": False,
        "words": ["feim voice", "ฟีมวอยซ์"],
        "response": "มีอะไรให้ช่วยไหม",
        "command_timeout": 7,
        "phrase_time_limit": 3,
        "delay": 0.2,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_voice_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        return copy.deepcopy(DEFAULT_VOICE_CONFIG)
    with config_path.open("r", encoding="utf-8") as config_file:
        loaded = json.load(config_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"FeimVoice config must be a JSON object: {config_path}")
    return _merge(DEFAULT_VOICE_CONFIG, loaded)


def save_voice_config(path: str | Path, config: dict[str, Any]) -> None:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=2)
    temporary.replace(config_path)
