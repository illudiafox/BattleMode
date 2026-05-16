"""BattleMode entry point."""

from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

from battlemode.capture.screen_capture import ScreenCapture
from battlemode.profiles.manager import ProfileManager
from battlemode.profiles.models import GameState
from battlemode.vision.state_detector import StateDetector
from battlemode.music.player import MusicPlayer
from battlemode.music.playlist import Playlist


POLL_INTERVAL = 2.0  # seconds between screen captures / state checks
MUSIC_DIR = Path(__file__).parent.parent / "music"


def build_playlists(player: MusicPlayer) -> None:
    """Load all local music directories into playlists on the player."""
    for state in GameState:
        if state == GameState.UNKNOWN:
            continue
        # Both "win" and "loss" map to the win_loss directory
        if state in (GameState.WIN, GameState.LOSS):
            category_dir = MUSIC_DIR / "win_loss"
        else:
            category_dir = MUSIC_DIR / state.value

        playlist = Playlist(name=state.value)
        if category_dir.exists():
            playlist.add_directory(category_dir)
        player.set_playlist(state, playlist)


def detection_loop(detector: StateDetector, player: MusicPlayer, stop_event: threading.Event) -> None:
    """Background thread: capture screen → detect state → transition music."""
    last_state = GameState.UNKNOWN
    with ScreenCapture() as cap:
        while not stop_event.is_set():
            frame = cap.grab()
            state = detector.detect(frame)
            if state != last_state and state != GameState.UNKNOWN:
                print(f"[BattleMode] State: {last_state.value} → {state.value}")
                player.transition_to(state)
                last_state = state
            time.sleep(POLL_INTERVAL)


def run_cli(profile_id: str) -> None:
    """Minimal CLI runner — used during development / VOD testing."""
    manager = ProfileManager()
    profile = manager.load(profile_id)
    detector = StateDetector(profile)
    player = MusicPlayer()

    # Apply phase configs from profile
    for state, config in profile.phase_config.items():
        player.set_phase_config(state, config)

    build_playlists(player)

    stop_event = threading.Event()
    thread = threading.Thread(target=detection_loop, args=(detector, player, stop_event), daemon=True)
    thread.start()

    print(f"[BattleMode] Running with profile '{profile_id}'. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        player.stop()


def main() -> None:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else "pokemon_champions"
    run_cli(profile_id)


if __name__ == "__main__":
    main()
