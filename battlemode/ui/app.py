"""BattleMode main GUI — PyQt6."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QStringListModel
from PyQt6.QtGui import QFont, QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QDoubleSpinBox,
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
from battlemode.capture.device_capture import DeviceCapture, list_devices
from battlemode.capture.window_capture import WindowCapture, WindowInfo, list_windows
from battlemode.music import music_profiles as _music_profiles
from battlemode.music import track_settings as _track_settings
from battlemode.music.player import MusicPlayer, PlayerState
from battlemode.music.playlist import Playlist, Track
from battlemode.music.store import save as save_playlists, load as load_saved_playlists
from battlemode.music.youtube import download_audio, is_youtube_url
from battlemode.profiles.manager import ProfileManager
from battlemode.profiles.models import GameState
from battlemode.ui.debug_tab import DebugTabWidget, QtLogHandler
from battlemode.ui.detection_manager import DetectionManagerWidget
from battlemode.ui.ocr_live_view import OcrLiveViewWidget
from battlemode.ui import settings as _settings

log = _bm_logger.get("ui")

# Valid next states for streamline mode — only detect these from each current state
STREAMLINE_MAP: dict[GameState, set[GameState]] = {
    GameState.MENU:      {GameState.SELECTION},
    GameState.SELECTION: {GameState.BATTLE},
    GameState.BATTLE:    {GameState.WIN, GameState.LOSS},
    GameState.WIN:       {GameState.MENU, GameState.SELECTION},
    GameState.LOSS:      {GameState.MENU, GameState.SELECTION},
}

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


class _CapturePreviewWindow(QWidget):
    """Floating window that shows a just-captured screenshot."""

    def __init__(self, frame, path: str, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle(f"Capture — {Path(path).name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img)

        # Scale to fit within 1000×700 while keeping aspect ratio
        pixmap = pixmap.scaled(
            1000, 700,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        label = QLabel()
        label.setPixmap(pixmap)
        layout.addWidget(label)

        path_label = QLabel(path)
        path_label.setStyleSheet("color: #888; font-size: 10px;")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.adjustSize()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class _DeviceLivePreview(QWidget):
    """Floating live preview window for a V4L2 device."""

    _frame_ready = pyqtSignal(object)   # numpy BGR frame — cross-thread

    def __init__(self, device: str, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.device = device
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Preview — {device}")
        self._stop = threading.Event()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._label = QLabel("Connecting…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(640, 360)
        self._label.setStyleSheet("background: #111; color: #666;")
        layout.addWidget(self._label)

        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self._frame_ready.connect(self._update_frame)
        self.adjustSize()

        threading.Thread(target=self._capture_loop, daemon=True).start()

    def _capture_loop(self) -> None:
        try:
            cap = DeviceCapture(self.device)
        except Exception:
            return
        try:
            while not self._stop.is_set():
                try:
                    frame = cap.grab()
                except Exception:
                    break
                try:
                    self._frame_ready.emit(frame)
                except RuntimeError:
                    break  # Qt object already destroyed
                self._stop.wait(1 / 15)
        finally:
            cap.close()

    def _update_frame(self, frame) -> None:
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img).scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(pixmap)

    def closeEvent(self, event) -> None:
        self._stop.set()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class PlayerSignals(QObject):
    state_changed = pyqtSignal(str)   # GameState value
    track_changed = pyqtSignal(str)   # track title


class MainWindow(QMainWindow):
    # Cross-thread signal — detection loop emits this, main thread handles it
    _detected = pyqtSignal(object, object)   # (GameState, DetectionResult | None)
    _hotkey_triggered = pyqtSignal()          # global Ctrl+L → main thread
    _frame_ready = pyqtSignal(object, object) # (frame, DetectionResult | None) — live feed

    def __init__(self, player: MusicPlayer, profile_manager: ProfileManager) -> None:
        super().__init__()
        self.player = player
        self.profile_manager = profile_manager
        self.signals = PlayerSignals()
        self._current_state = GameState.UNKNOWN
        self._detection_active = False
        self._stop_event = threading.Event()

        self._capture_window: WindowInfo | None = None   # None = full screen
        self._capture_device: str | None = None           # V4L2 device path
        self._device_preview: _DeviceLivePreview | None = None
        self._detection_interval: float = 0.2            # seconds between frames
        self._streamline: bool = False
        self._ts_current_track: Track | None = None
        self._ts_current_state: GameState | None = None

        # Route cross-thread state updates safely to the main thread
        self._detected.connect(self._on_detected)
        self._hotkey_triggered.connect(self._quick_capture)

        self.setWindowTitle("BattleMode")
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._frame_ready.connect(self._ocr_live_view.push_detection_frame)
        self._frame_ready.connect(self._update_tmpl_status)
        _track_settings.load()
        self._load_playlists()

        # Install Qt log handler — routes battlemode.* logs into the Debug tab
        self._log_handler = QtLogHandler()
        self._log_handler.record.connect(self._debug_tab.append_log)
        logging.getLogger("battlemode").addHandler(self._log_handler)

        # Restore last source settings
        QTimer.singleShot(0, self._restore_source_settings)

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
        splitter.setSizes([560, 360])
        player_layout.addWidget(splitter)
        self._main_tabs.addTab(player_tab, "Player")

        # --- Detection Manager tab ---
        self._detection_manager = DetectionManagerWidget(self.profile_manager)
        self._detection_manager.profile_saved.connect(self._on_detection_profile_saved)
        self._main_tabs.addTab(self._detection_manager, "Detection Manager")

        # --- OCR Live View tab ---
        self._ocr_live_view = OcrLiveViewWidget(self.profile_manager)
        self._main_tabs.addTab(self._ocr_live_view, "OCR Live View")

        # --- Debug tab ---
        self._debug_tab = DebugTabWidget()
        self._main_tabs.addTab(self._debug_tab, "Debug")

        # Sync initial profile into the live view
        initial_profile = self._profile_combo.currentText()
        if initial_profile:
            self._ocr_live_view.load_profile(initial_profile)

        root.addWidget(self._main_tabs, stretch=1)

        # Bottom: transport controls + volume (always visible)
        root.addWidget(self._build_transport())

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")
        self._tmpl_status = QLabel("")
        self._tmpl_status.setStyleSheet("color: #aaa; font-size: 11px; padding-right: 6px;")
        self.statusBar().addPermanentWidget(self._tmpl_status)

        # Global Ctrl+L hotkey — fires even when app window is not focused
        self._start_global_hotkey()

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

        layout.addSpacing(8)

        # Profile selector + management
        layout.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(160)
        profiles = self.profile_manager.list_profiles()
        for name in profiles:
            self._profile_combo.addItem(name)
        last = _settings.get("last_profile")
        if last and last in profiles:
            self._profile_combo.setCurrentText(last)
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        layout.addWidget(self._profile_combo)

        new_profile_btn = QPushButton("New…")
        new_profile_btn.setFixedWidth(46)
        new_profile_btn.setToolTip("Create a new profile (cloned from current)")
        new_profile_btn.clicked.connect(self._new_profile)
        layout.addWidget(new_profile_btn)

        del_profile_btn = QPushButton("Delete")
        del_profile_btn.setFixedWidth(52)
        del_profile_btn.setToolTip("Delete the current profile")
        del_profile_btn.clicked.connect(self._delete_profile)
        layout.addWidget(del_profile_btn)

        layout.addSpacing(10)

        # Capture source
        layout.addWidget(QLabel("Source:"))
        self._source_mode_combo = QComboBox()
        self._source_mode_combo.addItem("Full Screen")
        self._source_mode_combo.addItem("Browser Window")
        self._source_mode_combo.addItem("OBS Window")
        self._source_mode_combo.addItem("V4L2 Device")
        self._source_mode_combo.setFixedWidth(130)
        self._source_mode_combo.currentIndexChanged.connect(self._on_source_mode_changed)
        layout.addWidget(self._source_mode_combo)

        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(200)
        self._window_combo.setEnabled(False)
        self._window_combo.setPlaceholderText("Pick a window…")
        layout.addWidget(self._window_combo)

        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(140)
        self._device_combo.setVisible(False)
        layout.addWidget(self._device_combo)

        self._device_preview_btn = QPushButton("Preview")
        self._device_preview_btn.setFixedWidth(60)
        self._device_preview_btn.setVisible(False)
        self._device_preview_btn.setToolTip("Open live preview for selected device")
        self._device_preview_btn.clicked.connect(self._open_device_preview)
        layout.addWidget(self._device_preview_btn)

        self._refresh_source_btn = QPushButton("↻")
        self._refresh_source_btn.setFixedWidth(28)
        self._refresh_source_btn.setToolTip("Refresh source list")
        self._refresh_source_btn.setEnabled(False)
        self._refresh_source_btn.clicked.connect(self._refresh_source_list)
        layout.addWidget(self._refresh_source_btn)

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

        # Detection interval
        layout.addWidget(QLabel("Interval:"))
        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setRange(0.05, 10.0)
        self._interval_spin.setSingleStep(0.05)
        self._interval_spin.setDecimals(1)
        self._interval_spin.setValue(self._detection_interval)
        self._interval_spin.setSuffix(" s")
        self._interval_spin.setFixedWidth(68)
        self._interval_spin.setToolTip("Seconds between detection frames")
        self._interval_spin.valueChanged.connect(
            lambda v: setattr(self, "_detection_interval", v)
        )
        layout.addWidget(self._interval_spin)

        layout.addSpacing(6)

        # Detection toggle
        self._detect_btn = QPushButton("Start Detection")
        self._detect_btn.setCheckable(True)
        self._detect_btn.setFixedWidth(140)
        self._detect_btn.clicked.connect(self._toggle_detection)
        layout.addWidget(self._detect_btn)

        return bar

    def _restore_source_settings(self) -> None:
        mode = _settings.get("source_mode")
        if not mode:
            return
        idx = self._source_mode_combo.findText(mode)
        if idx < 0:
            return
        self._source_mode_combo.setCurrentIndex(idx)
        # Device and window are restored after the list populates via _on_source_mode_changed,
        # but we need to re-select the saved entry since the list won't auto-match it.
        if mode == "V4L2 Device":
            saved_dev = _settings.get("source_device")
            if saved_dev:
                idx = self._device_combo.findText(saved_dev)
                if idx >= 0:
                    self._device_combo.setCurrentIndex(idx)
        elif mode in ("Browser Window", "OBS Window"):
            saved_title = _settings.get("source_window_title")
            if saved_title:
                idx = self._window_combo.findText(saved_title)
                if idx >= 0:
                    self._window_combo.setCurrentIndex(idx)

    def _on_source_mode_changed(self, index: int) -> None:
        mode = self._source_mode_combo.currentText()
        _settings.set("source_mode", mode)
        is_window_mode = index in (1, 2)   # Browser Window / OBS Window
        is_device_mode = index == 3        # V4L2 Device

        self._window_combo.setVisible(is_window_mode)
        self._device_combo.setVisible(is_device_mode)
        self._device_preview_btn.setVisible(is_device_mode)
        self._refresh_source_btn.setEnabled(is_window_mode or is_device_mode)

        if not is_device_mode:
            self._close_device_preview()

        self._capture_window = None
        self._capture_device = None
        self._detection_manager.set_capture_window(None)
        self._detection_manager.set_capture_device(None)
        self._ocr_live_view.set_capture_window(None)
        self._ocr_live_view.set_capture_device(None)

        if is_window_mode or is_device_mode:
            self._refresh_source_list()
        else:
            self.statusBar().showMessage("Capture source: Full Screen")

    def _refresh_source_list(self) -> None:
        mode = self._source_mode_combo.currentText()
        if mode == "V4L2 Device":
            self._refresh_device_list()
        else:
            self._refresh_window_list()

    def _refresh_window_list(self) -> None:
        mode = self._source_mode_combo.currentText()
        try:
            self._window_combo.currentIndexChanged.disconnect()
        except TypeError:
            pass
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
        self._on_window_selected(self._window_combo.currentIndex())

    def _on_window_selected(self, index: int) -> None:
        w = self._window_combo.itemData(index)
        if isinstance(w, WindowInfo):
            self._capture_window = w
            self._capture_device = None
            self._detection_manager.set_capture_window(w)
            self._ocr_live_view.set_capture_window(w)
            self.statusBar().showMessage(f"Capture source: {w.title} ({w.width}×{w.height})")
            _settings.set("source_window_title", w.title)

    def _refresh_device_list(self) -> None:
        try:
            self._device_combo.currentIndexChanged.disconnect()
        except TypeError:
            pass
        self._device_combo.clear()

        devices = list_devices()
        for dev in devices:
            self._device_combo.addItem(dev)

        if not devices:
            self._device_combo.addItem("(no devices found)")
        else:
            self.statusBar().showMessage(f"Found {len(devices)} V4L2 device(s)")

        self._device_combo.currentIndexChanged.connect(self._on_device_selected)
        self._on_device_selected(self._device_combo.currentIndex())

    def _on_device_selected(self, index: int) -> None:
        dev = self._device_combo.currentText()
        if dev and not dev.startswith("("):
            self._capture_device = dev
            self._capture_window = None
            self._detection_manager.set_capture_device(dev)
            self._ocr_live_view.set_capture_device(dev)
            self.statusBar().showMessage(f"Capture source: {dev}")
            self._close_device_preview()
            _settings.set("source_device", dev)

    def _open_device_preview(self) -> None:
        dev = self._capture_device
        if not dev:
            return
        self._close_device_preview()
        self._device_preview = _DeviceLivePreview(dev, self)
        # Clear our reference when the user closes the window manually
        self._device_preview.destroyed.connect(
            lambda: setattr(self, "_device_preview", None)
        )
        self._device_preview.show()

    def _close_device_preview(self) -> None:
        preview = self._device_preview
        self._device_preview = None
        if preview is not None:
            try:
                preview.close()
            except RuntimeError:
                pass  # already destroyed by Qt

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
            list_widget.itemChanged.connect(self._on_track_check_changed)
            list_widget.currentRowChanged.connect(
                lambda row, s=state: self._on_playlist_selection_changed(s, row)
            )
            self._playlist_lists[state] = list_widget
            layout.addWidget(list_widget)

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

            self._tabs.addTab(tab, STATE_LABELS[state])
            self._tabs.setTabVisible(self._tabs.indexOf(tab), True)

        # Clear track settings panel when switching phases
        self._tabs.currentChanged.connect(lambda _: self._show_track_settings(None, None))

        # Music profile corner widget (appears to the right of the LOSS tab)
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(4, 2, 4, 2)
        corner_layout.setSpacing(3)

        corner_layout.addWidget(QLabel("Music:"))
        self._music_profile_combo = QComboBox()
        self._music_profile_combo.setMinimumWidth(120)
        self._music_profile_combo.setToolTip("Active music profile (track lists + per-track settings)")
        profiles = _music_profiles.list_profiles()
        self._music_profile_combo.blockSignals(True)
        for name in profiles:
            self._music_profile_combo.addItem(name)
        self._music_profile_combo.blockSignals(False)
        corner_layout.addWidget(self._music_profile_combo)

        save_mp_btn = QPushButton("Save")
        save_mp_btn.setFixedWidth(42)
        save_mp_btn.setToolTip("Save current playlists to this music profile")
        save_mp_btn.clicked.connect(self._save_music_profile)
        corner_layout.addWidget(save_mp_btn)

        new_mp_btn = QPushButton("New…")
        new_mp_btn.setFixedWidth(46)
        new_mp_btn.setToolTip("Create a new music profile from current playlists")
        new_mp_btn.clicked.connect(self._new_music_profile)
        corner_layout.addWidget(new_mp_btn)

        del_mp_btn = QPushButton("Del")
        del_mp_btn.setFixedWidth(36)
        del_mp_btn.setToolTip("Delete this music profile")
        del_mp_btn.clicked.connect(self._delete_music_profile)
        corner_layout.addWidget(del_mp_btn)

        self._tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        self._music_profile_combo.currentTextChanged.connect(self._on_music_profile_changed)

        return self._tabs

    def _build_now_playing(self) -> QWidget:
        group = QGroupBox("Now Playing / Track Settings")
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        # --- Now Playing ---
        self._np_state = QLabel("—")
        self._np_state.setFont(QFont("Courier New", 10))
        self._np_state.setWordWrap(True)

        self._np_track = QLabel("No track playing")
        self._np_track.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._np_track.setWordWrap(True)

        layout.addWidget(QLabel("Current state:"))
        layout.addWidget(self._np_state)
        layout.addSpacing(4)
        layout.addWidget(QLabel("Playing:"))
        layout.addWidget(self._np_track)
        layout.addSpacing(4)
        layout.addWidget(QLabel("Last trigger:"))
        self._np_keywords = QLabel("—")
        self._np_keywords.setFont(QFont("Courier New", 9))
        self._np_keywords.setWordWrap(True)
        self._np_keywords.setStyleSheet("color: #aaa;")
        layout.addWidget(self._np_keywords)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        layout.addSpacing(6)
        layout.addWidget(sep)
        layout.addSpacing(4)

        # --- Track Settings (for selected playlist item) ---
        ts_header = QLabel("Track Settings")
        ts_header.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(ts_header)

        self._ts_track_label = QLabel("Select a track in the playlist")
        self._ts_track_label.setFont(QFont("Courier New", 9))
        self._ts_track_label.setStyleSheet("color: #888;")
        self._ts_track_label.setWordWrap(True)
        layout.addWidget(self._ts_track_label)

        # Container that gets enabled/disabled based on selection
        self._ts_panel = QWidget()
        ts_layout = QVBoxLayout(self._ts_panel)
        ts_layout.setContentsMargins(0, 4, 0, 0)
        ts_layout.setSpacing(4)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Vol (0–200):"))
        self._ts_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._ts_vol_slider.setRange(0, 200)
        self._ts_vol_slider.setValue(100)
        self._ts_vol_label = QLabel("100%")
        self._ts_vol_label.setFixedWidth(36)
        self._ts_vol_slider.valueChanged.connect(self._on_ts_vol_changed)
        vol_row.addWidget(self._ts_vol_slider)
        vol_row.addWidget(self._ts_vol_label)
        ts_layout.addLayout(vol_row)

        # Weight
        wt_row = QHBoxLayout()
        wt_row.addWidget(QLabel("Weight:"))
        self._ts_weight_spin = QDoubleSpinBox()
        self._ts_weight_spin.setRange(0.01, 100.0)
        self._ts_weight_spin.setSingleStep(0.25)
        self._ts_weight_spin.setDecimals(2)
        self._ts_weight_spin.setValue(1.0)
        self._ts_weight_spin.setFixedWidth(80)
        self._ts_weight_spin.setToolTip("Relative likelihood in weighted shuffle (1.0 = normal)")
        self._ts_weight_spin.valueChanged.connect(self._on_ts_weight_changed)
        wt_row.addWidget(self._ts_weight_spin)
        wt_row.addStretch()
        ts_layout.addLayout(wt_row)

        # Forced next
        self._ts_forced_cb = QCheckBox("Forced next enabled")
        self._ts_forced_cb.stateChanged.connect(self._on_ts_forced_enabled_changed)
        ts_layout.addWidget(self._ts_forced_cb)

        ts_layout.addWidget(QLabel("After this track, play:"))
        self._ts_forced_list = QListWidget()
        self._ts_forced_list.setFixedHeight(72)
        ts_layout.addWidget(self._ts_forced_list)

        add_row = QHBoxLayout()
        self._ts_add_input = QLineEdit()
        self._ts_add_input.setPlaceholderText("Type to search tracks…")
        self._ts_add_input.returnPressed.connect(self._ts_add_forced_next)
        self._ts_completer_map: dict[str, str] = {}
        self._ts_completer_model = QStringListModel(self)
        _completer = QCompleter(self._ts_completer_model, self._ts_add_input)
        _completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        _completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._ts_add_input.setCompleter(_completer)
        add_row.addWidget(self._ts_add_input)
        ts_add_btn = QPushButton("Add")
        ts_add_btn.setFixedWidth(40)
        ts_add_btn.clicked.connect(self._ts_add_forced_next)
        ts_rem_btn = QPushButton("−")
        ts_rem_btn.setFixedWidth(28)
        ts_rem_btn.setToolTip("Remove selected entry")
        ts_rem_btn.clicked.connect(self._ts_remove_forced_next)
        add_row.addWidget(ts_add_btn)
        add_row.addWidget(ts_rem_btn)
        ts_layout.addLayout(add_row)

        self._ts_panel.setEnabled(False)
        layout.addWidget(self._ts_panel)
        layout.addStretch()

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

        layout.addSpacing(16)

        # Playback toggles (moved here from Now Playing panel)
        self._repeat_cb = QCheckBox("Repeat")
        self._repeat_cb.setChecked(True)
        self._repeat_track_cb = QCheckBox("Repeat track")
        self._repeat_track_cb.setChecked(True)
        self._shuffle_cb = QCheckBox("Shuffle")
        self._shuffle_cb.setChecked(True)
        self._repeat_cb.stateChanged.connect(self._update_playback_flags)
        self._repeat_track_cb.stateChanged.connect(self._update_playback_flags)
        self._shuffle_cb.stateChanged.connect(self._update_playback_flags)
        layout.addWidget(self._repeat_cb)
        layout.addWidget(self._repeat_track_cb)
        layout.addWidget(self._shuffle_cb)

        layout.addSpacing(16)

        # Ignore forced transitions + Streamline mode
        self._ignore_forced_cb = QCheckBox("Ignore forced")
        self._ignore_forced_cb.setToolTip("Ignore per-track forced next transitions globally")
        self._ignore_forced_cb.stateChanged.connect(
            lambda s: setattr(self.player, "_ignore_forced_transitions", bool(s))
        )
        layout.addWidget(self._ignore_forced_cb)

        self._streamline_cb = QCheckBox("Streamline")
        self._streamline_cb.setToolTip(
            "Only detect states that are valid transitions from the current state"
        )
        self._streamline_cb.stateChanged.connect(
            lambda s: setattr(self, "_streamline", bool(s))
        )
        layout.addWidget(self._streamline_cb)

        layout.addStretch()

        # Manual state override
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
        _STATES = [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]

        for state in _STATES:
            self.player.set_playlist(state, Playlist(name=state.value))

        profiles = _music_profiles.list_profiles()
        last = _settings.get("last_music_profile", "")

        if profiles:
            target = last if last in profiles else profiles[0]
            _music_profiles.load(target, self.player._playlists)
            _settings.set("last_music_profile", target)
            if hasattr(self, "_music_profile_combo"):
                self._music_profile_combo.blockSignals(True)
                self._music_profile_combo.setCurrentText(target)
                self._music_profile_combo.blockSignals(False)
        else:
            # First run — scan filesystem, merge saved tracks, create Default profile
            for state in _STATES:
                folder = MUSIC_DIR / ("win_loss" if state in (GameState.WIN, GameState.LOSS) else state.value)
                if folder.exists():
                    self.player.get_playlist(state).add_directory(folder)
            load_saved_playlists(self.player._playlists)
            _music_profiles.save("Default", self.player._playlists)
            _settings.set("last_music_profile", "Default")
            if hasattr(self, "_music_profile_combo"):
                self._music_profile_combo.blockSignals(True)
                if self._music_profile_combo.count() == 0:
                    self._music_profile_combo.addItem("Default")
                self._music_profile_combo.setCurrentText("Default")
                self._music_profile_combo.blockSignals(False)

        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            self._refresh_list(state)

    def _save_playlists(self) -> None:
        save_playlists(self.player._playlists)

    def _refresh_list(self, state: GameState) -> None:
        list_widget = self._playlist_lists[state]
        list_widget.blockSignals(True)
        list_widget.clear()
        playlist = self.player.get_playlist(state)
        if playlist:
            for track in playlist.tracks():
                item = QListWidgetItem(track.title)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ts = _track_settings.get(str(track.path))
                item.setCheckState(
                    Qt.CheckState.Checked if ts.enabled else Qt.CheckState.Unchecked
                )
                item.setData(Qt.ItemDataRole.UserRole, str(track.path))
                list_widget.addItem(item)
        list_widget.blockSignals(False)

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

    def _on_track_check_changed(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            _track_settings.get(path).enabled = (
                item.checkState() == Qt.CheckState.Checked
            )

    # ------------------------------------------------------------------ #
    #  Inline track settings (right panel)                                 #
    # ------------------------------------------------------------------ #

    def _on_playlist_selection_changed(self, state: GameState, row: int) -> None:
        if row < 0:
            self._show_track_settings(None, None)
            return
        playlist = self.player.get_playlist(state)
        tracks = playlist.tracks() if playlist else []
        if row < len(tracks):
            self._show_track_settings(state, tracks[row])
        else:
            self._show_track_settings(None, None)

    def _show_track_settings(self, state: GameState | None, track: Track | None) -> None:
        self._ts_current_track = track
        self._ts_current_state = state
        self._ts_panel.setEnabled(track is not None)
        self._ts_add_input.clear()
        if track is None:
            self._ts_track_label.setText("Select a track in the playlist")
            self._refresh_ts_completer()
            return
        ts = _track_settings.get(str(track.path))
        self._ts_track_label.setText(track.title)
        for w in (self._ts_vol_slider, self._ts_weight_spin, self._ts_forced_cb):
            w.blockSignals(True)
        self._ts_vol_slider.setValue(ts.volume)
        self._ts_vol_label.setText(f"{ts.volume}%")
        self._ts_weight_spin.setValue(ts.weight)
        self._ts_forced_cb.setChecked(ts.forced_next_enabled)
        for w in (self._ts_vol_slider, self._ts_weight_spin, self._ts_forced_cb):
            w.blockSignals(False)
        self._ts_forced_list.blockSignals(True)
        self._ts_forced_list.clear()
        for path in ts.forced_next:
            item = QListWidgetItem(Path(path).stem)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._ts_forced_list.addItem(item)
        self._ts_forced_list.blockSignals(False)
        self._refresh_ts_completer()

    def _on_ts_vol_changed(self, value: int) -> None:
        self._ts_vol_label.setText(f"{value}%")
        if self._ts_current_track:
            _track_settings.get(str(self._ts_current_track.path)).volume = value

    def _on_ts_weight_changed(self, value: float) -> None:
        if self._ts_current_track:
            _track_settings.get(str(self._ts_current_track.path)).weight = value

    def _on_ts_forced_enabled_changed(self, state: int) -> None:
        if self._ts_current_track:
            _track_settings.get(str(self._ts_current_track.path)).forced_next_enabled = bool(state)

    def _ts_add_forced_next(self) -> None:
        if not self._ts_current_track:
            return
        text = self._ts_add_input.text().strip()
        if not text:
            return
        path = self._ts_completer_map.get(text)
        if not path:
            lower = text.lower()
            for k, v in self._ts_completer_map.items():
                if k.lower() == lower:
                    path = v
                    break
        if not path:
            return
        existing = {
            self._ts_forced_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._ts_forced_list.count())
        }
        if path not in existing:
            item = QListWidgetItem(Path(path).stem)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._ts_forced_list.addItem(item)
            self._commit_forced_next()
        self._ts_add_input.clear()
        self._refresh_ts_completer()

    def _ts_remove_forced_next(self) -> None:
        row = self._ts_forced_list.currentRow()
        if row >= 0:
            self._ts_forced_list.takeItem(row)
            self._commit_forced_next()
            self._refresh_ts_completer()

    def _commit_forced_next(self) -> None:
        if self._ts_current_track:
            ts = _track_settings.get(str(self._ts_current_track.path))
            ts.forced_next = [
                self._ts_forced_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._ts_forced_list.count())
            ]

    def _refresh_ts_completer(self) -> None:
        if self._ts_current_track is None or self._ts_current_state is None:
            self._ts_completer_map = {}
            self._ts_completer_model.setStringList([])
            return
        playlist = self.player.get_playlist(self._ts_current_state)
        if not playlist:
            return
        existing = {
            self._ts_forced_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._ts_forced_list.count())
        }
        self_path = str(self._ts_current_track.path)
        self._ts_completer_map = {}
        for t in playlist.tracks():
            path = str(t.path)
            if path == self_path or path in existing:
                continue
            display = t.title
            if display in self._ts_completer_map:
                display = f"{t.title} ({Path(path).name})"
            self._ts_completer_map[display] = path
        self._ts_completer_model.setStringList(sorted(self._ts_completer_map))

    # ------------------------------------------------------------------ #
    #  Music profile management                                            #
    # ------------------------------------------------------------------ #

    def _on_music_profile_changed(self, name: str) -> None:
        if not name:
            return
        _settings.set("last_music_profile", name)
        _music_profiles.load(name, self.player._playlists)
        for state in [GameState.MENU, GameState.SELECTION, GameState.BATTLE, GameState.WIN, GameState.LOSS]:
            self._refresh_list(state)
        self._show_track_settings(None, None)
        self.statusBar().showMessage(f"Music profile loaded: {name}")

    def _save_music_profile(self) -> None:
        name = self._music_profile_combo.currentText()
        if not name:
            return
        _music_profiles.save(name, self.player._playlists)
        self.statusBar().showMessage(f"Music profile '{name}' saved.", 3000)

    def _new_music_profile(self) -> None:
        dialog = QWidget(self, Qt.WindowType.Dialog)
        dialog.setWindowTitle("New Music Profile")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Profile name:"))
        name_input = QLineEdit()
        name_input.setMinimumWidth(220)
        layout.addWidget(name_input)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        cancel_btn.clicked.connect(dialog.close)

        def do_create():
            name = name_input.text().strip()
            if not name:
                return
            if name in _music_profiles.list_profiles():
                QMessageBox.warning(dialog, "Already exists", f"'{name}' already exists.")
                return
            _music_profiles.save(name, self.player._playlists)
            self._music_profile_combo.blockSignals(True)
            self._music_profile_combo.addItem(name)
            self._music_profile_combo.setCurrentText(name)
            self._music_profile_combo.blockSignals(False)
            _settings.set("last_music_profile", name)
            dialog.close()
            self.statusBar().showMessage(f"Music profile '{name}' created.", 3000)

        ok_btn.clicked.connect(do_create)
        dialog.show()

    def _delete_music_profile(self) -> None:
        name = self._music_profile_combo.currentText()
        if not name:
            return
        if self._music_profile_combo.count() <= 1:
            QMessageBox.warning(self, "Cannot delete", "You must have at least one music profile.")
            return
        reply = QMessageBox.question(
            self, "Delete music profile",
            f"Delete '{name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        _music_profiles.delete(name)
        idx = self._music_profile_combo.currentIndex()
        self._music_profile_combo.blockSignals(True)
        self._music_profile_combo.removeItem(idx)
        self._music_profile_combo.blockSignals(False)
        self.statusBar().showMessage(f"Music profile '{name}' deleted.", 3000)
        new_name = self._music_profile_combo.currentText()
        if new_name:
            self._on_music_profile_changed(new_name)

    def _play_from_list(self, state: GameState, item: QListWidgetItem) -> None:
        row = self._playlist_lists[state].row(item)
        self.player.play_direct(state, row)
        self._set_state(state)

    # ------------------------------------------------------------------ #
    #  State / detection                                                    #
    # ------------------------------------------------------------------ #

    def _set_state(self, state: GameState, result=None) -> None:
        self._current_state = state
        color = STATE_COLORS.get(state, "#888")
        self._state_label.setText(STATE_LABELS.get(state, "?"))
        self._state_label.setStyleSheet(f"background: {color}; color: white; border-radius: 6px;")
        self._np_state.setText(STATE_LABELS.get(state, "?"))

        if result is not None:
            kw_text = (
                f"{len(result.matched_keywords)}/{result.total_keywords} matched: "
                + ", ".join(result.matched_keywords)
            )
            self._np_keywords.setText(kw_text)
            self.statusBar().showMessage(
                f"→ {state.value.upper()}  |  {kw_text}"
            )

        # Sync checkboxes to the active playlist's settings
        playlist = self.player.get_playlist(state)
        if playlist:
            self._repeat_cb.blockSignals(True)
            self._shuffle_cb.blockSignals(True)
            self._repeat_track_cb.blockSignals(True)
            self._repeat_cb.setChecked(playlist.repeat)
            self._shuffle_cb.setChecked(playlist.shuffle)
            self._repeat_track_cb.setChecked(self.player._repeat_track)
            self._repeat_cb.blockSignals(False)
            self._shuffle_cb.blockSignals(False)
            self._repeat_track_cb.blockSignals(False)

    def _toggle_detection(self, checked: bool) -> None:
        if checked:
            self._detect_btn.setText("Stop Detection")
            self._detection_active = True
            self._mode_label.setText("DETECTION")
            self._mode_label.setStyleSheet("background: #c0392b; color: white; border-radius: 4px;")
            self.statusBar().showMessage("Detection running — force state to override a missed detection")
            self._ocr_live_view.set_detection_active(True)
            self._start_detection_thread()
        else:
            self._detect_btn.setText("Start Detection")
            self._detection_active = False
            self._stop_event.set()
            self._mode_label.setText("PREVIEW")
            self._mode_label.setStyleSheet("background: #444; color: #aaa; border-radius: 4px;")
            self.statusBar().showMessage("Preview mode — full control")
            self._ocr_live_view.set_detection_active(False)

    def _start_global_hotkey(self) -> None:
        """Register a global Ctrl+L listener via pynput (fires even when app is unfocused)."""
        try:
            from pynput import keyboard as _kb

            def _on_activate():
                self._hotkey_triggered.emit()

            listener = _kb.GlobalHotKeys({"<ctrl>+l": _on_activate})
            listener.daemon = True
            listener.start()
            log.info("Global hotkey Ctrl+L registered")
        except Exception as e:
            log.warning("Could not register global hotkey: %s", e)
            self.statusBar().showMessage(
                "Global hotkey unavailable — grant Accessibility permission in System Settings", 8000
            )

    def _quick_capture(self) -> None:
        """Ctrl+L — grab a screenshot, save to templates/, show in a floating preview."""
        import cv2
        from datetime import datetime

        try:
            with self._make_capture() as cap:
                frame = cap.grab()
        except Exception as e:
            self.statusBar().showMessage(f"Capture failed: {e}", 5000)
            return

        tmpl_dir = Path("user_data/templates")
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(tmpl_dir / f"capture_{ts}.png")
        cv2.imwrite(path, frame)
        self.statusBar().showMessage(f"Saved: {path}", 6000)

        # If Detection Manager has a rule selected, add to its template list
        dm = self._detection_manager
        if dm._selected_index >= 0:
            dm.add_template_path(path)

        # Show the capture in a floating preview window
        _CapturePreviewWindow(frame, path, self).show()

    def _start_detection_thread(self) -> None:
        """Lazy import to avoid loading CV/Tesseract until needed."""
        from battlemode.capture.screen_capture import ScreenCapture
        from battlemode.vision.state_detector import StateDetector, DetectionResult

        profile_id = self._profile_combo.currentText()
        try:
            profile = self.profile_manager.load(profile_id)
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Profile error", str(e))
            self._detect_btn.setChecked(False)
            return

        detector = StateDetector(profile)
        self._stop_event.clear()

        make_cap = self._make_capture

        def loop():
            source_label = (
                self._capture_device or
                (self._capture_window.title if self._capture_window else "full screen")
            )
            log.info("Detection loop started (source=%s)", source_label)
            last = GameState.UNKNOWN
            pending_state: GameState | None = None
            pending_since: float = 0.0

            try:
                with make_cap() as cap:
                    while not self._stop_event.is_set():
                        try:
                            frame = cap.grab()
                        except Exception:
                            log.exception("Frame capture failed")
                            self._stop_event.wait(2.0)
                            continue

                        try:
                            fs = STREAMLINE_MAP.get(last) if self._streamline else None
                            result = detector.detect_result(frame, fs)
                        except Exception:
                            log.exception("Detection failed")
                            self._stop_event.wait(2.0)
                            continue

                        self._frame_ready.emit(frame, result)

                        state = result.state if result else GameState.UNKNOWN
                        delay = result.trigger_delay if result else 0.0
                        now = time.time()

                        if state == GameState.UNKNOWN or state == last:
                            pending_state = None
                        elif state != pending_state:
                            log.debug("Pending state: %s (delay=%.1fs)", state.value, delay)
                            pending_state = state
                            pending_since = now
                        elif now - pending_since >= delay:
                            log.info("Triggered → %s", result.summary())
                            self.player.transition_to(state)
                            # Emit signal — Qt delivers this on the main thread
                            self._detected.emit(state, result)
                            last = state
                            pending_state = None

                        self._stop_event.wait(self._detection_interval)
            except Exception:
                log.exception("Detection loop crashed")
            finally:
                log.info("Detection loop stopped")

        threading.Thread(target=loop, daemon=True).start()

    def _on_detected(self, state: GameState, result) -> None:
        """Slot — always runs on main thread via Qt signal dispatch."""
        self._set_state(state, result)
        self._debug_tab.append_detection(state, result)
        # Return force combo to (auto) so it reflects detection is back in control
        self._force_combo.blockSignals(True)
        self._force_combo.setCurrentIndex(0)
        self._force_combo.blockSignals(False)

    def _update_tmpl_status(self, frame, result) -> None:
        """Update the permanent template-score label in the status bar each detection cycle."""
        if result and result.template_confidence > 0:
            matched = result.template_matched
            score = result.template_confidence
            threshold = result.rule.template_threshold
            icon = "✓" if matched else "✗"
            color = "#50c878" if matched else "#e05c5c"
            self._tmpl_status.setText(
                f'<span style="color:{color};">{icon} tmpl {score:.2f}</span>'
                f'<span style="color:#888;"> / {threshold:.2f}</span>'
            )
        else:
            self._tmpl_status.setText("")

    def _make_capture(self):
        """Return a context-manager capture object for the current source."""
        if self._capture_device:
            return DeviceCapture(self._capture_device)
        if self._capture_window:
            return WindowCapture(self._capture_window)
        from battlemode.capture.screen_capture import ScreenCapture
        return ScreenCapture()

    def _new_profile(self) -> None:
        current = self._profile_combo.currentText()
        if not current:
            return

        dialog = QWidget(self, Qt.WindowType.Dialog)
        dialog.setWindowTitle("New Profile")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)

        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel("Name:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g. Pokemon Champions — Ranked")
        name_input.setMinimumWidth(300)
        form_layout.addWidget(name_input)
        layout.addLayout(form_layout)

        hint = QLabel(f"Cloned from: {current}")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dialog.close)

        def do_create():
            new_name = name_input.text().strip()
            if not new_name:
                return
            new_id = new_name.lower().replace(" ", "_").replace("—", "").replace("-", "_")
            new_id = "".join(c for c in new_id if c.isalnum() or c == "_").strip("_")
            if not new_id:
                QMessageBox.warning(dialog, "Invalid name", "Could not generate a valid profile ID.")
                return
            if new_id in self.profile_manager.list_profiles():
                QMessageBox.warning(dialog, "Already exists", f"A profile named '{new_id}' already exists.")
                return
            try:
                self.profile_manager.duplicate(current, new_id, new_name)
            except Exception as e:
                QMessageBox.critical(dialog, "Error", str(e))
                return
            dialog.close()
            self._refresh_profile_combos(select=new_id)
            self.statusBar().showMessage(f"Created profile '{new_name}'")

        ok_btn.clicked.connect(do_create)
        dialog.show()

    def _delete_profile(self) -> None:
        current = self._profile_combo.currentText()
        if not current:
            return
        if self._profile_combo.count() <= 1:
            QMessageBox.warning(self, "Cannot delete", "You must have at least one profile.")
            return
        reply = QMessageBox.question(
            self, "Delete profile",
            f"Delete '{current}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.profile_manager.delete(current)
        self._refresh_profile_combos()
        self.statusBar().showMessage(f"Deleted profile '{current}'")

    def _refresh_profile_combos(self, select: str = "") -> None:
        profiles = self.profile_manager.list_profiles()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in profiles:
            self._profile_combo.addItem(p)
        if select and select in profiles:
            self._profile_combo.setCurrentText(select)
        self._profile_combo.blockSignals(False)
        current = self._profile_combo.currentText()
        self._detection_manager.refresh_profile_list(current)
        if current:
            self._on_profile_changed(current)

    def _on_profile_changed(self, name: str) -> None:
        if not name:
            return
        _settings.set("last_profile", name)
        self.statusBar().showMessage(f"Profile: {name}")
        self._detection_manager.load_profile(name)
        self._ocr_live_view.load_profile(name)

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
        self._close_device_preview()
        logging.getLogger("battlemode").removeHandler(self._log_handler)
        self.player.stop()
        _track_settings.save()
        mp_name = self._music_profile_combo.currentText() if hasattr(self, "_music_profile_combo") else ""
        if mp_name:
            _music_profiles.save(mp_name, self.player._playlists)
        event.accept()
