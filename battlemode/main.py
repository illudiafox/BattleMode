"""BattleMode entry point."""

from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

from battlemode.profiles.manager import ProfileManager
from battlemode.music.player import MusicPlayer


def run_gui() -> None:
    from PyQt6.QtWidgets import QApplication
    from battlemode.ui.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("BattleMode")

    player = MusicPlayer()
    manager = ProfileManager()

    window = MainWindow(player, manager)
    window.show()
    sys.exit(app.exec())


def run_cli(profile_id: str) -> None:
    """Headless CLI runner — for VOD testing or debugging."""
    import time
    import threading
    from battlemode.capture.screen_capture import ScreenCapture
    from battlemode.profiles.models import GameState
    from battlemode.vision.state_detector import StateDetector
    from battlemode.music.playlist import Playlist

    MUSIC_DIR = Path(__file__).parent.parent / "music"

    manager = ProfileManager()
    profile = manager.load(profile_id)
    detector = StateDetector(profile)
    player = MusicPlayer()

    for state, config in profile.phase_config.items():
        player.set_phase_config(state, config)

    for state in GameState:
        if state == GameState.UNKNOWN:
            continue
        folder = MUSIC_DIR / ("win_loss" if state in (GameState.WIN, GameState.LOSS) else state.value)
        playlist = Playlist(name=state.value)
        if folder.exists():
            playlist.add_directory(folder)
        player.set_playlist(state, playlist)

    stop_event = threading.Event()

    def loop():
        last = GameState.UNKNOWN
        with ScreenCapture() as cap:
            while not stop_event.is_set():
                frame = cap.grab()
                state = detector.detect(frame)
                if state != last and state != GameState.UNKNOWN:
                    print(f"[BattleMode] {last.value} → {state.value}")
                    player.transition_to(state)
                    last = state
                time.sleep(2.0)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    print(f"[BattleMode] CLI mode — profile '{profile_id}'. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        player.stop()


def main() -> None:
    if "--cli" in sys.argv:
        profile_id = sys.argv[2] if len(sys.argv) > 2 else "pokemon_champions"
        run_cli(profile_id)
    else:
        run_gui()


if __name__ == "__main__":
    main()
