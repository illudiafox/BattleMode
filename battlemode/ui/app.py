"""BattleMode main GUI — PyQt6."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QMessageBox,
)

import battlemode.logger as _bm_logger
from battlemode.capture.window_capture import WindowCapture, WindowInfo, list_windows
from battlemode.music.player import MusicPlayer, PlayerState
from battlemode.music.playlist import Playlist, Track
from battlemode.music.store import save as save_playlists, load as load_saved_playlists
from battlemode.music.youtube import download_audio, is_youtube_url
from battlemode.profiles.manager import ProfileManager
from battlemode.profiles.models import GameState
from battlemode.ui.detection_manager import DetectionManagerWidget

log = _bm_logger.get("ui")

MUSIC_DIR = Path(__file__).parent.parent.parent / "music"
STATE_COLORS = {
    GameState.MENU:      "#5b8dd9",
    GameState.SELECTION: "#f0c040",
    GameState.BATTLE:    "#e05c5c",
    GameState.WIN:       "#50c878",
    GameState.LOSS:      "#9b59b6",
    GameState.UNKNOWN:   "#888888",
}
STATE_LABELS = {
    GameState.MENU:      "MENU",
    GameState.SELECTION: "SELECTION",
    GameState.BATTLE:    "BATTLE",
    GameState.WIN:       "WIN",
    GameState.LOSS:      "LOSS",
    GameState.UNKNOWN:   "UNKNOWN",
}


class PlayerSignals(QObject):
    state_changed = pyqtSignal(str)   # GameState value
    track_changed = pyqtSignal(str)   # track title


class MainWindow(QMainWindow):
    def __init__(self, player: MusicPlayer, profile_manager: ProfileManager) -> None:
        super().__init__()
        self.player = player
        self.profile_manager = profile_manager
        self.signals = PlayerSignals()
        self._current_state = GameState.UNKNOWN
        self._detection_active = False
        self._stop_event = threading.Event()

        self._capture_window: WindowInfo | None = None   # None = full screen

        self.setWindowTitle("BattleMode")
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._load_playlists()

        # Poll player for track changes
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_player)
        self._poll_timer.start(500)

        # Warn if VLC isn't available (checked lazily so this is non-blocking)
        QTimer.singleShot(500, self._check_vlc)

    # ------------------------------------------------------------------ #
    #  UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # Top bar: state indicator + profile selector + detection toggle
        root.addWidget(self._build_top_bar())

        # Main tabs: Player | Detection Manager
        self._main_tabs = QTabWidget()

        # --- Player tab ---
        player_tab = QWidget()
        player_layout = QVBoxLayout(player_tab)
        player_layout.setContentsMargins(0, 6, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_playlist_tabs())
        splitter.addWidget(self._build_now_playing())
        splitter.setSizes([600, 300])
        player_layout.addWidget(splitter)
        self._main_tabs.addTab(player_tab, "Player")

        # --- Detection Manager tab ---
        self._detection_manager = DetectionManagerWidget(self.profile_manager)
        self._detection_manager.profile_saved.connect(self._on_detection_profile_saved)
        self._main_tabs.addTab(self._detection_manager, "Detection Manager")

        root.addWidget(self._main_tabs, stretch=1)

        # Bottom: transport controls + volume (always visible)
        root.addWidget(self._build_transport())

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        # State badge
        self._state_label = QLabel("UNKNOWN")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_label.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._state_label.setFixedWidth(130)
        self._state_label.setFixedHeight(36)
        self._state_label.setStyleSheet("background: #888; color: white; border-radius: 6px;")
        layout.addWidget(self._state_label)

        layout.addSpacing(12)

        # Profile selector
        layout.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(160)
        for name in self.profile_manager.list_profiles():
            self._profile_combo.addItem(name)
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        layout.addWidget(self._profile_combo)

        layout.addSpacing(16)

        # Capture source
        layout.addWidget(QLabel("Source:"))
        self._source_mode_combo = QComboBox()
        self._source_mode_combo.addItem("Full Screen")
        self._source_mode_combo.addItem("Browser Window")
        self._source_mode_combo.addItem("OBS Window")
        self._source_mode_combo.setFixedWidth(130)
        self._source_mode_combo.currentIndexChanged.connect(self._on_source_mode_changed)
        layout.addWidget(self._source_mode_combo)

        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(220)
        self._window_combo.setEnabled(False)
        self._window_combo.setPlaceholderText("Pick a window…")
        layout.addWidget(self._window_combo)

        self._refresh_windows_btn = QPushButton("↻")
        self._refresh_windows_btn.setFixedWidth(28)
        self._refresh_windows_btn.setToolTip("Refresh window list")
        self._refresh_windows_btn.setEnabled(False)
        self._refresh_windows_btn.clicked.connect(self._refresh_window_list)
        layout.addWidget(self._refresh_windows_btn)

        layout.addStretch()

        # Mode badge
        self._mode_label = QLabel("PREVIEW")
        self._mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_label.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._mode_label.setFixedWidth(90)
        self._mode_label.setFixedHeight(28)
        self._mode_label.setStyleSheet("background: #444; color: #aaa; border-radius: 4px;")
        layout.addWidget(self._mode_label)

        layout.addSpacing(6)

        # Detection toggle
        self._detect_btn = QPushButton("Start Detection")
        self._detect_btn.setCheckable(True)
        self._detect_btn.setFixedWidth(140)
        self._detect_btn.clicked.connect(self._toggle_detection)
        layout.addWidget(self._detect_btn)

        return bar

    def _on_source_mode_changed(self, index: int) -> None:
        is_window_mode = index > 0   # 0 = Full Screen
        self._window_combo.setEnabled(is_window_mode)
        self._refresh_windows_btn.setEnabled(is_window_mode)
        if is_window_mode:
            self._refresh_window_list()
        else:
            self._capture_window = None
            self.statusBar().showMessage("Capture source: Full Screen")

    def _refresh_window_list(self) -> None:
        mode = self._source_mode_combo.currentText()
        try:
            self._window_combo.currentIndexChanged.disconnect()
        except TypeError:
            pass  # no connections yet on first call
        self._window_combo.clear()

        all_windows = list_windows()
        filter_term = "obs" if "OBS" in mode else None

        for w in all_windows:
            if filter_term and filter_term not in w.title.lower():
                continue
            self._window_combo.addItem(w.title, w)

        if self._window_combo.count() == 0:
            self._window_combo.addItem("(no windows found)")
        else:
            self.statusBar().showMessage(f"Found {self._window_combo.count()} window(s)")

        self._window_combo.currentIndexChanged.connect(self._on_window_selected)

    def _on_window_selected(self, index: int) -> None:
        w = self._window_combo.itemData(index)
        if isinstance(w, WindowInfo):
            self._capture_window = w
            self._detection_manager.set_capture_window(w)
            self.statusBar().showMessage(f"Capture source: {w.title} ({w.width}×{w.height})")

    def _build_playlist_tabs(self) -> QWidget:
        self._tabs = QTabWidget()
        self._playlist_lists: dict[GameState, QListWidget] = {}

        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            tab = QWidget()
            layout = QVBoxLayout(tab)

            list_widget = QListWidget()
            list_widget.setAlternatingRowColors(True)
            list_widget.itemDoubleClicked.connect(
                lambda item, s=state: self._play_from_list(s, item)
            )
            self._playlist_lists[state] = list_widget
            layout.addWidget(list_widget)

            # Buttons row
            btn_row = QHBoxLayout()
            add_file_btn = QPushButton("+ Add Files")
            add_file_btn.clicked.connect(lambda _, s=state: self._add_files(s))
            add_yt_btn = QPushButton("+ YouTube URL")
            add_yt_btn.clicked.connect(lambda _, s=state: self._add_youtube(s))
            rescan_btn = QPushButton("↻ Rescan Folder")
            rescan_btn.setToolTip("Re-scan the music folder for this category")
            rescan_btn.clicked.connect(lambda _, s=state: self._rescan_folder(s))
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _, s=state: self._remove_selected(s))
            btn_row.addWidget(add_file_btn)
            btn_row.addWidget(add_yt_btn)
            btn_row.addWidget(rescan_btn)
            btn_row.addWidget(remove_btn)
            layout.addLayout(btn_row)

            color = STATE_COLORS[state]
            self._tabs.addTab(tab, STATE_LABELS[state])
            self._tabs.setTabVisible(self._tabs.indexOf(tab), True)

        return self._tabs

    def _build_now_playing(self) -> QWidget:
        group = QGroupBox("Now Playing")
        layout = QVBoxLayout(group)

        self._np_state = QLabel("—")
        self._np_state.setFont(QFont("Courier New", 10))
        self._np_state.setWordWrap(True)

        self._np_track = QLabel("No track playing")
        self._np_track.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._np_track.setWordWrap(True)

        layout.addWidget(QLabel("Current state:"))
        layout.addWidget(self._np_state)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Track:"))
        layout.addWidget(self._np_track)
        layout.addStretch()

        # Repeat / shuffle toggles for active phase
        self._repeat_cb = QCheckBox("Repeat playlist")
        self._repeat_track_cb = QCheckBox("Repeat track")
        self._shuffle_cb = QCheckBox("Shuffle")
        self._repeat_cb.stateChanged.connect(self._update_playback_flags)
        self._repeat_track_cb.stateChanged.connect(self._update_playback_flags)
        self._shuffle_cb.stateChanged.connect(self._update_playback_flags)

        layout.addWidget(self._repeat_cb)
        layout.addWidget(self._repeat_track_cb)
        layout.addWidget(self._shuffle_cb)

        return group

    def _build_transport(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        self._prev_btn = QPushButton("⏮")
        self._play_btn = QPushButton("▶")
        self._pause_btn = QPushButton("⏸")
        self._stop_btn = QPushButton("⏹")
        self._skip_btn = QPushButton("⏭")

        for btn in [self._prev_btn, self._play_btn, self._pause_btn, self._stop_btn, self._skip_btn]:
            btn.setFixedSize(44, 36)
            layout.addWidget(btn)

        self._prev_btn.clicked.connect(self.player.previous)
        self._play_btn.clicked.connect(self.player.play)
        self._pause_btn.clicked.connect(self.player.pause)
        self._stop_btn.clicked.connect(self.player.stop)
        self._skip_btn.clicked.connect(self.player.skip)

        layout.addSpacing(16)

        # Volume
        layout.addWidget(QLabel("Vol:"))
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(self.player.volume)
        self._vol_slider.setFixedWidth(120)
        self._vol_slider.valueChanged.connect(lambda v: setattr(self.player, "volume", v))
        layout.addWidget(self._vol_slider)

        layout.addStretch()

        # Manual state override (useful for testing without detection)
        layout.addWidget(QLabel("Force state:"))
        self._force_combo = QComboBox()
        self._force_combo.addItem("(auto)")
        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            self._force_combo.addItem(STATE_LABELS[state], state)
        self._force_combo.currentIndexChanged.connect(self._on_force_state)
        layout.addWidget(self._force_combo)

        return bar

    # ------------------------------------------------------------------ #
    #  Playlist management                                                  #
    # ------------------------------------------------------------------ #

    def _load_playlists(self) -> None:
        """Scan music/ directories, then merge any saved tracks on top."""
        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            folder = MUSIC_DIR / ("win_loss" if state in (GameState.WIN, GameState.LOSS) else state.value)
            playlist = Playlist(name=state.value)
            if folder.exists():
                playlist.add_directory(folder)
            self.player.set_playlist(state, playlist)

        # Restore any tracks added manually in previous sessions
        load_saved_playlists(self.player._playlists)

        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            self._refresh_list(state)

    def _save_playlists(self) -> None:
        save_playlists(self.player._playlists)

    def _refresh_list(self, state: GameState) -> None:
        list_widget = self._playlist_lists[state]
        list_widget.clear()
        playlist = self.player.get_playlist(state)
        if playlist:
            for track in playlist.tracks():
                list_widget.addItem(QListWidgetItem(track.title))

    def _add_files(self, state: GameState) -> None:
        start_dir = MUSIC_DIR / ("win_loss" if state in (GameState.WIN, GameState.LOSS) else state.value)
        start_dir.mkdir(parents=True, exist_ok=True)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add audio files", str(start_dir),
            "Audio Files (*.mp3 *.ogg *.flac *.wav *.m4a)"
        )
        if not paths:
            return
        playlist = self.player.get_playlist(state)
        if playlist is None:
            QMessageBox.warning(self, "Playlist error", f"No playlist initialised for {state.value}. Restart the app.")
            return
        for path in paths:
            playlist.add_track(Track(path))
        self._refresh_list(state)
        self._save_playlists()
        self.statusBar().showMessage(f"Added {len(paths)} file(s) to {STATE_LABELS[state]}")

    def _rescan_folder(self, state: GameState) -> None:
        folder = MUSIC_DIR / ("win_loss" if state in (GameState.WIN, GameState.LOSS) else state.value)
        folder.mkdir(parents=True, exist_ok=True)
        playlist = self.player.get_playlist(state)
        if playlist is None:
            return
        playlist.clear()
        added = playlist.add_directory(folder)
        self._refresh_list(state)
        self._save_playlists()
        self.statusBar().showMessage(f"Rescanned {folder.name}: {added} file(s) found")

    def _add_youtube(self, state: GameState) -> None:
        dialog = QWidget(self, Qt.WindowType.Dialog)
        dialog.setWindowTitle("Add YouTube URL")
        layout = QVBoxLayout(dialog)
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        url_input.setMinimumWidth(420)
        btn = QPushButton("Download & Add")
        layout.addWidget(QLabel(f"YouTube URL → {state.value} playlist"))
        layout.addWidget(url_input)
        layout.addWidget(btn)
        dialog.setLayout(layout)

        def do_download():
            url = url_input.text().strip()
            if not is_youtube_url(url):
                QMessageBox.warning(dialog, "Invalid URL", "That doesn't look like a YouTube URL.")
                return
            btn.setEnabled(False)
            btn.setText("Downloading…")

            def worker():
                try:
                    path = download_audio(url)
                    playlist = self.player.get_playlist(state)
                    if playlist:
                        playlist.add_track(Track(path))
                    self._refresh_list(state)
                    self._save_playlists()
                    self.statusBar().showMessage(f"Downloaded: {path.name}")
                except Exception as e:
                    QMessageBox.critical(dialog, "Download failed", str(e))
                finally:
                    btn.setEnabled(True)
                    btn.setText("Download & Add")
                    dialog.close()

            threading.Thread(target=worker, daemon=True).start()

        btn.clicked.connect(do_download)
        dialog.show()

    def _remove_selected(self, state: GameState) -> None:
        list_widget = self._playlist_lists[state]
        row = list_widget.currentRow()
        if row < 0:
            return
        playlist = self.player.get_playlist(state)
        if playlist:
            playlist.remove_track(row)
        self._refresh_list(state)
        self._save_playlists()

    def _play_from_list(self, state: GameState, item: QListWidgetItem) -> None:
        list_widget = self._playlist_lists[state]
        row = list_widget.row(item)
        playlist = self.player.get_playlist(state)
        if playlist:
            playlist.skip_to(row)
        self.player.transition_to(state)
        self._set_state(state)

    # ------------------------------------------------------------------ #
    #  State / detection                                                    #
    # ------------------------------------------------------------------ #

    def _set_state(self, state: GameState) -> None:
        self._current_state = state
        color = STATE_COLORS.get(state, "#888")
        self._state_label.setText(STATE_LABELS.get(state, "?"))
        self._state_label.setStyleSheet(f"background: {color}; color: white; border-radius: 6px;")
        self._np_state.setText(STATE_LABELS.get(state, "?"))

        # Sync checkboxes to the active playlist's settings
        playlist = self.player.get_playlist(state)
        if playlist:
            self._repeat_cb.blockSignals(True)
            self._shuffle_cb.blockSignals(True)
            self._repeat_cb.setChecked(playlist.repeat)
            self._shuffle_cb.setChecked(playlist.shuffle)
            self._repeat_cb.blockSignals(False)
            self._shuffle_cb.blockSignals(False)

    def _toggle_detection(self, checked: bool) -> None:
        if checked:
            self._detect_btn.setText("Stop Detection")
            self._detection_active = True
            # Lock: cannot manually force state while detection is running
            self._force_combo.setEnabled(False)
            self._force_combo.setCurrentIndex(0)
            self._mode_label.setText("DETECTION")
            self._mode_label.setStyleSheet("background: #c0392b; color: white; border-radius: 4px;")
            self.statusBar().showMessage("Detection running — state forcing disabled")
            self._start_detection_thread()
        else:
            self._detect_btn.setText("Start Detection")
            self._detection_active = False
            self._stop_event.set()
            # Unlock: preview mode
            self._force_combo.setEnabled(True)
            self._mode_label.setText("PREVIEW")
            self._mode_label.setStyleSheet("background: #444; color: #aaa; border-radius: 4px;")
            self.statusBar().showMessage("Preview mode — full control")

    def _start_detection_thread(self) -> None:
        """Lazy import to avoid loading CV/Tesseract until needed."""
        from battlemode.capture.screen_capture import ScreenCapture
        from battlemode.vision.state_detector import StateDetector

        profile_id = self._profile_combo.currentText()
        try:
            profile = self.profile_manager.load(profile_id)
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Profile error", str(e))
            self._detect_btn.setChecked(False)
            return

        detector = StateDetector(profile)
        self._stop_event.clear()

        capture_window = self._capture_window

        def loop():
            log.info("Detection loop started (source=%s)",
                     capture_window.title if capture_window else "full screen")
            last = GameState.UNKNOWN
            pending_state: GameState | None = None
            pending_since: float = 0.0

            if capture_window:
                cap = WindowCapture(capture_window)
            else:
                from battlemode.capture.screen_capture import ScreenCapture
                cap = ScreenCapture()

            try:
                with cap:
                    while not self._stop_event.is_set():
                        try:
                            frame = cap.grab()
                        except Exception:
                            log.exception("Frame capture failed")
                            time.sleep(2.0)
                            continue

                        try:
                            rule = detector.detect_rule(frame)
                        except Exception:
                            log.exception("Detection failed")
                            time.sleep(2.0)
                            continue

                        state = rule.state if rule else GameState.UNKNOWN
                        delay = rule.trigger_delay if rule else 0.0
                        now = time.time()

                        if state == GameState.UNKNOWN or state == last:
                            pending_state = None
                        elif state != pending_state:
                            log.debug("Pending state: %s (delay=%.1fs)", state.value, delay)
                            pending_state = state
                            pending_since = now
                        elif now - pending_since >= delay:
                            log.info("Committing transition → %s (held %.1fs)",
                                     state.value, now - pending_since)
                            self.player.transition_to(state)
                            self._set_state(state)
                            last = state
                            pending_state = None

                        time.sleep(2.0)
            except Exception:
                log.exception("Detection loop crashed")
            finally:
                log.info("Detection loop stopped")

        threading.Thread(target=loop, daemon=True).start()

    def _on_profile_changed(self, name: str) -> None:
        self.statusBar().showMessage(f"Profile: {name}")
        self._detection_manager.load_profile(name)

    def _on_detection_profile_saved(self, game_id: str) -> None:
        self.statusBar().showMessage(f"Profile '{game_id}' saved.")

    def _on_force_state(self, index: int) -> None:
        if index == 0:
            return
        state: GameState = self._force_combo.itemData(index)
        self.player.transition_to(state)
        self._set_state(state)
        self.statusBar().showMessage(f"Forced state: {state.value}")

    def _update_playback_flags(self) -> None:
        playlist = self.player.get_playlist(self._current_state)
        if playlist:
            playlist.repeat = self._repeat_cb.isChecked()
            playlist.shuffle = self._shuffle_cb.isChecked()
        self.player._repeat_track = self._repeat_track_cb.isChecked()

    def _check_vlc(self) -> None:
        if not self.player.is_vlc_available():
            QMessageBox.warning(
                self, "VLC not found",
                "Could not initialize VLC. Music playback will be disabled.\n\n"
                "Install VLC: brew install vlc  (or download from videolan.org)"
            )

    def _poll_player(self) -> None:
        track = self.player.current_track()
        self._np_track.setText(track.title if track else "No track playing")

    def closeEvent(self, event) -> None:
        self._stop_event.set()
        self.player.stop()
        event.accept()
