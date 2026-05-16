"""OCR Live View — standalone tab for testing detection in real time."""

from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battlemode.profiles.manager import ProfileManager
from battlemode.profiles.models import GameProfile


class OcrLiveViewWidget(QWidget):
    """Full-tab OCR viewer: capture, run detection, display raw text + highlights."""

    _test_done = pyqtSignal(object)   # dict — routes worker results to main thread

    def __init__(self, profile_manager: ProfileManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile_manager = profile_manager
        self._profile: Optional[GameProfile] = None
        self._capture_window = None
        self._last_frame = None   # most recent raw BGR frame (numpy array)
        self._test_done.connect(self._on_test_done)
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Public API — called by MainWindow                                   #
    # ------------------------------------------------------------------ #

    def set_detection_active(self, active: bool) -> None:
        """Called by MainWindow — pause live timer while detection loop is running."""
        if active:
            if self._live_timer.isActive():
                self._live_timer.stop()
                self._live_btn.setChecked(False)
                self._live_btn.setText("Live  ▶")
            self._live_btn.setEnabled(False)
            self._live_btn.setToolTip("Stop detection to use live view")
        else:
            self._live_btn.setEnabled(True)
            self._live_btn.setToolTip("")

    def push_detection_frame(self, frame, result) -> None:
        """Called from main thread each detection cycle — updates preview and labels.

        This keeps the view live during detection without triggering a second capture.
        """
        if frame is not None:
            self._last_frame = frame
            if self._preview_label.isVisible():
                self._update_preview(frame)

        if result:
            state_text = result.state.value.upper()
            if result.template_matched:
                state_text += f"  tmpl:{result.template_confidence:.2f}"
            elif result.template_confidence > 0:
                state_text += f"  tmpl(miss):{result.template_confidence:.2f}"
            self._state_label.setText(state_text)
            kw_info = (
                f"{len(result.matched_keywords)}/{result.total_keywords}: "
                + (", ".join(result.matched_keywords) or "—")
            )
            self._kw_label.setText(kw_info)
        else:
            self._state_label.setText("UNKNOWN")
            self._kw_label.setText("no rule matched")

    def set_capture_window(self, window) -> None:
        self._capture_window = window
        if hasattr(self, "_source_label"):
            if window:
                self._source_label.setText(f"Source: {window.title}")
            else:
                self._source_label.setText("Source: Full Screen")

    def load_profile(self, game_id: str) -> None:
        try:
            self._profile = self._profile_manager.load(game_id)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------ #
    #  UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Controls row
        ctrl = QHBoxLayout()

        self._test_btn = QPushButton("Capture Once")
        self._test_btn.setFixedWidth(120)
        self._test_btn.clicked.connect(self._run_test)
        ctrl.addWidget(self._test_btn)

        self._live_btn = QPushButton("Live  ▶")
        self._live_btn.setCheckable(True)
        self._live_btn.setFixedWidth(90)
        self._live_btn.clicked.connect(self._toggle_live)
        ctrl.addWidget(self._live_btn)

        self._source_label = QLabel("Source: Full Screen")
        self._source_label.setStyleSheet("color: #888; font-size: 10px;")
        ctrl.addWidget(self._source_label)

        ctrl.addSpacing(12)
        ctrl.addWidget(QLabel("Detected:"))
        self._state_label = QLabel("—")
        self._state_label.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._state_label.setFixedWidth(220)
        ctrl.addWidget(self._state_label)

        ctrl.addWidget(QLabel("Keywords:"))
        self._kw_label = QLabel("—")
        self._kw_label.setFont(QFont("Courier New", 10))
        self._kw_label.setWordWrap(True)
        ctrl.addWidget(self._kw_label, stretch=1)

        # Preview toggle
        self._preview_cb = QCheckBox("Show capture preview")
        self._preview_cb.setChecked(True)
        self._preview_cb.stateChanged.connect(self._toggle_preview)
        ctrl.addWidget(self._preview_cb)

        root.addLayout(ctrl)

        # Splitter: preview on top, OCR text below
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(self._splitter, stretch=1)

        # Capture preview label
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("background: #111; color: #666;")
        self._preview_label.setText("Capture preview will appear here after first grab")
        self._preview_label.setMinimumHeight(120)
        self._splitter.addWidget(self._preview_label)

        # Raw OCR output — matched keywords highlighted in yellow
        self._ocr_view = QTextEdit()
        self._ocr_view.setReadOnly(True)
        self._ocr_view.setFont(QFont("Courier New", 9))
        self._ocr_view.setPlaceholderText("OCR output will appear here after capture…")
        self._splitter.addWidget(self._ocr_view)

        self._splitter.setSizes([250, 200])

        # Live-refresh timer
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(2500)
        self._live_timer.timeout.connect(self._run_test)

    def _toggle_preview(self, state: int) -> None:
        visible = bool(state)
        self._preview_label.setVisible(visible)
        if not visible:
            self._splitter.setSizes([0, 1])

    def _toggle_live(self, checked: bool) -> None:
        if checked:
            self._live_btn.setText("Live  ⏹")
            self._live_timer.start()
            self._run_test()
        else:
            self._live_btn.setText("Live  ▶")
            self._live_timer.stop()

    # ------------------------------------------------------------------ #
    #  Capture + detection                                                  #
    # ------------------------------------------------------------------ #

    def _run_test(self) -> None:
        if not self._test_btn.isEnabled():
            return   # previous capture still in progress — skip this tick
        if not self._profile:
            self._state_label.setText("No profile loaded")
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText("Capturing…")
        capture_window = self._capture_window
        profile = self._profile   # snapshot

        def worker():
            try:
                from battlemode.vision.state_detector import StateDetector, _extract_text

                detector = StateDetector(profile)

                if capture_window:
                    from battlemode.capture.window_capture import WindowCapture
                    cap = WindowCapture(capture_window)
                else:
                    from battlemode.capture.screen_capture import ScreenCapture
                    cap = ScreenCapture()

                with cap:
                    frame = cap.grab()

                result = detector.detect_result(frame)
                raw_text = _extract_text(frame)

                all_keywords = [
                    kw
                    for rule in profile.detection_rules
                    if rule.enabled and rule.ocr_text
                    for kw in rule.ocr_text
                ]

                self._test_done.emit({
                    "result": result,
                    "raw_text": raw_text or "(no text returned)",
                    "all_keywords": all_keywords,
                    "frame": frame,
                    "error": None,
                })
            except Exception as e:
                self._test_done.emit({
                    "result": None,
                    "raw_text": "",
                    "all_keywords": [],
                    "frame": None,
                    "error": str(e),
                })

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, data: dict) -> None:
        """Slot — always called on the main thread via _test_done signal."""
        frame = data.get("frame")
        if frame is not None:
            self._last_frame = frame
            self._update_preview(frame)

        error = data.get("error")
        if error:
            self._state_label.setText("ERROR")
            self._kw_label.setText(error)
            self._ocr_view.setPlainText(error)
        else:
            result = data["result"]
            if result:
                state_text = result.state.value.upper()
                if result.template_matched:
                    state_text += f"  tmpl:{result.template_confidence:.2f}"
                self._state_label.setText(state_text)
                kw_info = (
                    f"{len(result.matched_keywords)}/{result.total_keywords}: "
                    + (", ".join(result.matched_keywords) or "—")
                )
                self._kw_label.setText(kw_info)
            else:
                self._state_label.setText("UNKNOWN")
                self._kw_label.setText("no rule matched")
            self._set_ocr_text(data["raw_text"], data["all_keywords"])

        self._test_btn.setEnabled(True)
        self._test_btn.setText("Capture Once")

    def _update_preview(self, frame) -> None:
        """Convert BGR numpy frame to a QPixmap and show it scaled to fit the label."""
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img)
        label_size = self._preview_label.size()
        scaled = pixmap.scaled(
            label_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._last_frame is not None and self._preview_label.isVisible():
            self._update_preview(self._last_frame)

    def _set_ocr_text(self, text: str, keywords: list[str]) -> None:
        """Populate the viewer, highlighting every keyword found in the text."""
        self._ocr_view.setPlainText(text)
        if not keywords:
            return

        highlight_fmt = QTextCharFormat()
        highlight_fmt.setBackground(QColor("#f0c040"))
        highlight_fmt.setForeground(QColor("#000000"))

        doc = self._ocr_view.document()
        cursor = QTextCursor(doc)

        for kw in set(keywords):
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            while True:
                cursor = doc.find(kw, cursor)
                if cursor.isNull():
                    break
                cursor.mergeCharFormat(highlight_fmt)
