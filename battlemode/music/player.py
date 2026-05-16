"""Audio player backed by python-vlc.

VLC is initialized lazily on first playback to avoid freezing on startup
if the VLC dylib takes time to load.
"""

from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Optional

from battlemode.profiles.models import GameState, PhaseConfig
from .playlist import Playlist, Track


class PlayerState(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


class MusicPlayer:
    """
    Manages per-phase playlists and VLC playback.
    Automatically switches playlists when the game state changes.
    """

    def __init__(self) -> None:
        self._vlc_instance = None       # created lazily
        self._media_player = None       # created lazily
        self._vlc_ok: bool | None = None  # None = not tried yet

        self._playlists: dict[GameState, Playlist] = {}
        self._active_state: Optional[GameState] = None
        self._phase_configs: dict[GameState, PhaseConfig] = {}
        self._state = PlayerState.STOPPED
        self._volume: int = 80
        self._repeat_track: bool = False
        self._lock = threading.Lock()

    # --- VLC lazy init ---

    def _ensure_vlc(self) -> bool:
        """Initialize VLC on first use. Returns False if unavailable."""
        if self._vlc_ok is not None:
            return self._vlc_ok
        try:
            import vlc
            self._vlc_instance = vlc.Instance("--no-xlib")
            self._media_player = self._vlc_instance.media_player_new()
            events = self._media_player.event_manager()
            events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_track_end)
            self._vlc_ok = True
        except Exception as e:
            print(f"[BattleMode] VLC unavailable: {e}")
            self._vlc_ok = False
        return self._vlc_ok

    # --- Playlist setup ---

    def set_playlist(self, state: GameState, playlist: Playlist) -> None:
        with self._lock:
            self._playlists[state] = playlist

    def set_phase_config(self, state: GameState, config: PhaseConfig) -> None:
        with self._lock:
            self._phase_configs[state] = config

    def get_playlist(self, state: GameState) -> Optional[Playlist]:
        return self._playlists.get(state)

    # --- State transitions ---

    def transition_to(self, state: GameState, fade_ms: Optional[int] = None) -> None:
        """Switch to the playlist for a new game state."""
        if state == self._active_state:
            # Same state — only restart if the player has stopped (playlist exhausted)
            if self._state != PlayerState.STOPPED:
                return

        config = self._phase_configs.get(state, PhaseConfig())
        playlist = self._playlists.get(state)
        if playlist is None or playlist.is_empty():
            self._active_state = state
            return  # No music for this state — silence

        self._active_state = state
        self._repeat_track = config.repeat_track
        playlist.repeat = config.repeat
        playlist.shuffle = config.shuffle

        track = playlist.current()
        if track:
            self._play_track(track)

    # --- Playback controls ---

    def play(self) -> None:
        if not self._ensure_vlc():
            return
        if self._state == PlayerState.PAUSED:
            self._media_player.play()
            self._state = PlayerState.PLAYING
        elif self._state == PlayerState.STOPPED:
            playlist = self._active_playlist()
            if playlist:
                track = playlist.current()
                if track:
                    self._play_track(track)

    def pause(self) -> None:
        if not self._ensure_vlc():
            return
        if self._state == PlayerState.PLAYING:
            self._media_player.pause()
            self._state = PlayerState.PAUSED

    def stop(self) -> None:
        if self._media_player:
            self._media_player.stop()
        self._state = PlayerState.STOPPED

    def skip(self) -> None:
        playlist = self._active_playlist()
        if playlist:
            track = playlist.advance()
            if track:
                self._play_track(track)
            else:
                self._state = PlayerState.STOPPED

    def previous(self) -> None:
        playlist = self._active_playlist()
        if playlist:
            track = playlist.previous()
            if track:
                self._play_track(track)

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int) -> None:
        self._volume = max(0, min(100, value))
        if self._media_player:
            self._media_player.audio_set_volume(self._volume)

    def current_track(self) -> Optional[Track]:
        playlist = self._active_playlist()
        return playlist.current() if playlist else None

    def player_state(self) -> PlayerState:
        return self._state

    def get_position(self) -> float:
        if self._media_player:
            return self._media_player.get_position()
        return 0.0

    def is_vlc_available(self) -> bool:
        return self._ensure_vlc()

    # --- Internal ---

    def _active_playlist(self) -> Optional[Playlist]:
        if self._active_state is None:
            return None
        return self._playlists.get(self._active_state)

    def _play_track(self, track: Track, fade_ms: int = 0) -> None:
        if not self._ensure_vlc():
            return
        import vlc
        media = self._vlc_instance.media_new(str(track.path))
        self._media_player.set_media(media)
        self._media_player.audio_set_volume(self._volume)
        self._media_player.play()
        self._state = PlayerState.PLAYING

    def _on_track_end(self, event) -> None:
        """Called by VLC event thread when current track finishes."""
        if self._repeat_track:
            playlist = self._active_playlist()
            if playlist:
                track = playlist.current()
                if track:
                    self._play_track(track)
            return

        playlist = self._active_playlist()
        if playlist:
            track = playlist.advance()
            if track:
                self._play_track(track)
            else:
                # Playlist exhausted — stop. Stay in current state but go silent.
                self._state = PlayerState.STOPPED

    def __del__(self) -> None:
        try:
            if self._media_player:
                self._media_player.stop()
                self._media_player.release()
            if self._vlc_instance:
                self._vlc_instance.release()
        except Exception:
            pass
