from __future__ import annotations

import json
from typing import Any


def _format_record(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in record.items():
        if value in (None, ""):
            continue
        parts.append(f"{key}: {value}")
    return "\n".join(parts)


def extract_json_response(payload: Any) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return payload

    if isinstance(payload, dict) and "reply" in payload:
        payload = payload["reply"]

    if isinstance(payload, list):
        if not payload:
            return ""
        if all(isinstance(item, dict) for item in payload):
            return "\n\n".join(_format_record(item) for item in payload)
        return "\n".join(str(item) for item in payload)

    if isinstance(payload, dict):
        return _format_record(payload)

    return str(payload)