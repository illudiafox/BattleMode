"""Profile loading, saving, and management."""

from __future__ import annotations

import json
from pathlib import Path

from .models import GameProfile

PROFILES_DIR = Path(__file__).parent.parent.parent / "profiles"


class ProfileManager:
    def __init__(self, profiles_dir: Path = PROFILES_DIR) -> None:
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, GameProfile] = {}

    def list_profiles(self) -> list[str]:
        return [p.stem for p in self.profiles_dir.glob("*.json")]

    def load(self, game_id: str) -> GameProfile:
        if game_id in self._loaded:
            return self._loaded[game_id]

        path = self.profiles_dir / f"{game_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No profile found for '{game_id}' at {path}")

        profile = GameProfile.model_validate(json.loads(path.read_text()))
        self._loaded[game_id] = profile
        return profile

    def save(self, profile: GameProfile) -> None:
        path = self.profiles_dir / f"{profile.game_id}.json"
        path.write_text(profile.model_dump_json(indent=2))
        self._loaded[profile.game_id] = profile

    def duplicate(self, game_id: str, new_id: str, new_name: str) -> GameProfile:
        source = self.load(game_id)
        data = source.model_dump()
        data["game_id"] = new_id
        data["name"] = new_name
        new_profile = GameProfile.model_validate(data)
        self.save(new_profile)
        return new_profile

    def delete(self, game_id: str) -> None:
        path = self.profiles_dir / f"{game_id}.json"
        if path.exists():
            path.unlink()
        self._loaded.pop(game_id, None)

    def get_active(self) -> GameProfile | None:
        return next(iter(self._loaded.values()), None)
