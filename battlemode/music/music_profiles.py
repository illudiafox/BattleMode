"""Named music configurations — per-phase track lists + track settings."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from battlemode.profiles.models import GameState

PROFILES_DIR = Path(__file__).parent.parent.parent / "user_data" / "music_profiles"

_PHASE_KEYS = {
    GameState.MENU:      "menu",
    GameState.SELECTION: "selection",
    GameState.BATTLE:    "battle",
    GameState.WIN:       "win",
    GameState.LOSS:      "loss",
}
_KEY_TO_STATE = {v: k for k, v in _PHASE_KEYS.items()}


def _profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.json"


def list_profiles() -> list[str]:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


def save(name: str, playlists: dict) -> None:
    from battlemode.music import track_settings as _ts
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tracks_data: dict[str, list[str]] = {}
    for state, key in _PHASE_KEYS.items():
        pl = playlists.get(state)
        tracks_data[key] = [str(t.path) for t in (pl.tracks() if pl else [])]

    all_paths = {p for paths in tracks_data.values() for p in paths}
    ts_data = {path: asdict(_ts.get(path)) for path in all_paths}

    _profile_path(name).write_text(
        json.dumps({"name": name, "tracks": tracks_data, "track_settings": ts_data}, indent=2)
    )


def load(name: str, playlists: dict) -> bool:
    p = _profile_path(name)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except Exception:
        return False

    from battlemode.music.playlist import Track
    from battlemode.music import track_settings as _ts
    from battlemode.music.track_settings import TrackSettings

    valid_fields = TrackSettings.__dataclass_fields__

    for path, ts_dict in data.get("track_settings", {}).items():
        ts = _ts.get(path)
        for k, v in ts_dict.items():
            if k in valid_fields:
                setattr(ts, k, v)

    for key, paths in data.get("tracks", {}).items():
        state = _KEY_TO_STATE.get(key)
        if state is None:
            continue
        pl = playlists.get(state)
        if pl is None:
            continue
        pl.clear()
        for path_str in paths:
            p_file = Path(path_str)
            if p_file.exists():
                pl.add_track(Track(p_file))

    return True


def delete(name: str) -> None:
    p = _profile_path(name)
    if p.exists():
        p.unlink()
