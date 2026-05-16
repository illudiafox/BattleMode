"""Pydantic models for game profiles."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class GameState(str, Enum):
    UNKNOWN = "unknown"
    MENU = "menu"
    SELECTION = "selection"
    BATTLE = "battle"
    WIN = "win"
    LOSS = "loss"


class DetectionRule(BaseModel):
    """A single OCR or image-based detection rule for a game state."""

    state: GameState
    enabled: bool = True                          # disabled rules are never evaluated
    trigger_delay: float = 0.0                    # seconds state must be held before switching
    # OCR-based: look for text in a screen region
    ocr_text: Optional[list[str]] = None          # keywords to search for
    ocr_region: Optional[tuple[int, int, int, int]] = None  # (x, y, w, h) — None = full screen
    min_keywords: int = 1                         # how many keywords must match to trigger

    # Image template matching — match fires if ANY template exceeds the threshold
    template_paths: list[str] = Field(default_factory=list)
    template_threshold: float = 0.85

    @model_validator(mode="before")
    @classmethod
    def _migrate_single_template(cls, data):
        """Migrate old single template_path field to template_paths list."""
        if isinstance(data, dict) and "template_path" in data:
            old = data.pop("template_path")
            if old and not data.get("template_paths"):
                data["template_paths"] = [old]
        return data

    priority: int = 0  # higher = checked first


class PhaseConfig(BaseModel):
    """Music behavior config per game state."""

    repeat: bool = True               # loop playlist when exhausted
    repeat_track: bool = True         # repeat the current track
    shuffle: bool = True              # randomise playback order
    transition_fade_ms: int = 1500    # crossfade duration


class GameProfile(BaseModel):
    """Complete profile for one game."""

    name: str
    game_id: str                      # e.g. "pokemon_champions"
    description: str = ""
    version: str = "1.0"

    detection_rules: list[DetectionRule] = Field(default_factory=list)
    phase_config: dict[GameState, PhaseConfig] = Field(default_factory=dict)

    # Window/source to capture — None means user selects at runtime
    capture_source: Optional[str] = None

    def get_phase_config(self, state: GameState) -> PhaseConfig:
        return self.phase_config.get(state, PhaseConfig())
