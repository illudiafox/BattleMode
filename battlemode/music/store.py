"""Persist playlist track lists to disk so they survive restarts."""

from __future__ import annotations

import json
from pathlib import Path

from battlemode.music.playlist import Playlist, Track
from battlemode.profiles.models import GameState

STORE_PATH = Path(__file__).parent.parent.parent / "user_data" / "playlists.json"


def save(playlists: dict[GameState, Playlist]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    for state, playlist in playlists.items():
        data[state.value] = [str(t.path) for t in playlist.tracks()]
    STORE_PATH.write_text(json.dumps(data, indent=2))


def load(playlists: dict[GameState, Playlist]) -> None:
    """Merge saved paths into existing playlists, skipping missing files."""
    if not STORE_PATH.exists():
        return
    try:
        data = json.loads(STORE_PATH.read_text())
    except Exception:
        return

    for state in GameState:
        if state == GameState.UNKNOWN:
            continue
        paths = data.get(state.value, [])
        playlist = playlists.get(state)
        if playlist is None:
            continue
        existing = {str(t.path) for t in playlist.tracks()}
        for path_str in paths:
            p = Path(path_str)
            if p.exists() and str(p) not in existing:
                playlist.add_track(Track(p))
