"""Per-track settings — enabled, volume, weight, forced transitions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent.parent / "user_data" / "track_settings.json"

_cache: dict[str, "_TrackSettings"] = {}


@dataclass
class TrackSettings:
    enabled: bool = True
    volume: int = 100             # 0–200 relative to master (100 = same as master)
    weight: float = 1.0           # relative likelihood in weighted shuffle
    forced_next: list[str] = field(default_factory=list)   # paths to play after this track
    forced_next_enabled: bool = True


def get(path: str | Path) -> TrackSettings:
    key = str(path)
    if key not in _cache:
        _cache[key] = TrackSettings()
    return _cache[key]


def set_track(path: str | Path, settings: TrackSettings) -> None:
    _cache[str(path)] = settings


def save() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {k: asdict(v) for k, v in _cache.items()}
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def load() -> None:
    if not SETTINGS_PATH.exists():
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        for k, v in data.items():
            _cache[k] = TrackSettings(**{fk: fv for fk, fv in v.items()
                                         if fk in TrackSettings.__dataclass_fields__})
    except Exception:
        pass
