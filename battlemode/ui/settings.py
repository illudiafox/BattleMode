"""Persist lightweight UI settings (last profile, etc.) across sessions."""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent.parent / "user_data" / "settings.json"


def load() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}


def save(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)
