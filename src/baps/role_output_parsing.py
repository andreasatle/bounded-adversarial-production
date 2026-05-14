from __future__ import annotations

import json


def parse_json_object(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def get_non_empty_string(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def get_dict(data: dict, key: str) -> dict | None:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    return None
