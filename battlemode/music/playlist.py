"""Playlist management — local files and YouTube URLs."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Iterator, Optional


SUPPORTED_EXTENSIONS = {".mp3", ".ogg", ".flac", ".wav", ".m4a"}


class Track:
    def __init__(self, path: str | Path, title: Optional[str] = None, youtube_url: Optional[str] = None) -> None:
        self.path = Path(path) if not isinstance(path, Path) else path
        self.title = title or self.path.stem
        self.youtube_url = youtube_url

    def __repr__(self) -> str:
        return f"Track({self.title!r})"


class Playlist:
    """An ordered collection of tracks with playback controls."""

    def __init__(self, name: str, repeat: bool = True, shuffle: bool = True) -> None:
        self.name = name
        self.repeat = repeat
        self.shuffle = shuffle
        self._tracks: list[Track] = []
        self._index: int = 0
        self._order: list[int] = []

    # --- Building ---

    def add_track(self, track: Track) -> None:
        self._tracks.append(track)
        self._rebuild_order()

    def add_directory(self, directory: Path) -> int:
        """Scan a directory for supported audio files and add them. Returns count added."""
        added = 0
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                self._tracks.append(Track(path))
                added += 1
        self._rebuild_order()
        return added

    def remove_track(self, index: int) -> None:
        if 0 <= index < len(self._tracks):
            self._tracks.pop(index)
            self._rebuild_order()

    def clear(self) -> None:
        self._tracks.clear()
        self._index = 0
        self._order = []

    # --- Playback navigation ---

    def current(self) -> Optional[Track]:
        if not self._order:
            return None
        return self._tracks[self._order[self._index]]

    def advance(self) -> Optional[Track]:
        """Move to next track. Returns None if playlist is exhausted and repeat is off."""
        if not self._order:
            return None
        self._index += 1
        if self._index >= len(self._order):
            if self.repeat:
                if self.shuffle:
                    self._rebuild_order()
                self._index = 0
            else:
                self._index = len(self._order) - 1
                return None
        return self.current()

    def previous(self) -> Optional[Track]:
        if not self._order:
            return None
        self._index = max(0, self._index - 1)
        return self.current()

    def skip_to(self, index: int) -> Optional[Track]:
        if 0 <= index < len(self._tracks):
            # Find position of that track in _order
            try:
                pos = self._order.index(index)
                self._index = pos
            except ValueError:
                self._index = 0
        return self.current()

    # --- Info ---

    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def __len__(self) -> int:
        return len(self._tracks)

    def is_empty(self) -> bool:
        return len(self._tracks) == 0

    # --- Internal ---

    def _rebuild_order(self) -> None:
        from battlemode.music import track_settings as _ts
        # Build (original_index, weight) for enabled tracks only
        candidates: list[tuple[int, float]] = []
        for i, track in enumerate(self._tracks):
            ts = _ts.get(str(track.path))
            if ts.enabled:
                candidates.append((i, max(ts.weight, 1e-9)))

        if not candidates:
            self._order = []
            self._index = 0
            return

        if self.shuffle:
            # Weighted shuffle via exponential keys (Efraimidis-Spirakis RSample)
            keyed = [(random.random() ** (1.0 / w), i) for i, w in candidates]
            keyed.sort(reverse=True)  # higher key → earlier in order
            indices = [i for _, i in keyed]
        else:
            indices = [i for i, _ in candidates]

        self._order = indices
        self._index = min(self._index, max(0, len(self._order) - 1))
