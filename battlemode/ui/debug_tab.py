"""Debug tab — live log viewer + detection history."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battlemode.profiles.models import GameState

STATE_COLORS = {
    GameState.MENU:      "#5b8dd9",
    GameState.SELECTION: "#f0c040",
    GameState.BATTLE:    "#e05c5c",
    GameState.WIN:       "#50c878",
    GameState.LOSS:      "#9b59b6",
    GameState.UNKNOWN:   "#888888",
}

LOG_LEVEL_COLORS = {
    logging.DEBUG:    "#777777",
    logging.INFO:     "#cccccc",
    logging.WARNING:  "#f0c040",
    logging.ERROR:    "#e05c5c",
    logging.CRITICAL: "#ff4444",
}

MAX_LOG_LINES = 500
MAX_HISTORY   = 100


class _LogSignal(QObject):
    record = pyqtSignal(str, int)   # (formatted message, levelno)


class QtLogHandler(logging.Handler):
    """Logging handler that routes records into a Qt signal (thread-safe)."""

    def __init__(self) -> None:
        super().__init__()
        self._signal = _LogSignal()
        self.record = self._signal.record  # shortcut for connect()
        self.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            self._signal.record.emit(msg, record.levelno)
        except RuntimeError:
            pass  # Qt object already destroyed


class DebugTabWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_level = logging.DEBUG
        self._line_count = 0
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def append_log(self, message: str, levelno: int) -> None:
        if levelno < self._min_level:
            return
        color = LOG_LEVEL_COLORS.get(levelno, "#cccccc")
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(message + "\n", fmt)

        self._line_count += 1
        if self._line_count > MAX_LOG_LINES:
            # Trim from the top
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down,
                                QTextCursor.MoveMode.KeepAnchor, 50)
            cursor.removeSelectedText()
            self._line_count -= 50

        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

    def append_detection(self, state: GameState, result=None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        label = state.value.upper()
        detail = ""
        if result and result.matched_keywords:
            detail = f"  [{', '.join(result.matched_keywords)}]"
        elif result and result.template_matched:
            detail = f"  [tmpl {result.template_confidence:.2f}]"

        item = QListWidgetItem(f"{ts}  →  {label}{detail}")
        color = STATE_COLORS.get(state, "#888888")
        item.setForeground(QColor(color))
        item.setFont(QFont("Courier New", 10))

        self._history_list.insertItem(0, item)  # newest on top
        if self._history_list.count() > MAX_HISTORY:
            self._history_list.takeItem(self._history_list.count() - 1)

    # ------------------------------------------------------------------ #
    #  UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, stretch=1)

        # --- Detection history ---
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(4)

        hist_header = QHBoxLayout()
        hist_label = QLabel("Detection History")
        hist_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        hist_header.addWidget(hist_label)
        hist_header.addStretch()
        clear_hist_btn = QPushButton("Clear")
        clear_hist_btn.setFixedWidth(52)
        clear_hist_btn.clicked.connect(self._history_list_clear)
        hist_header.addWidget(clear_hist_btn)
        history_layout.addLayout(hist_header)

        self._history_list = QListWidget()
        self._history_list.setFont(QFont("Courier New", 10))
        self._history_list.setAlternatingRowColors(True)
        history_layout.addWidget(self._history_list)
        splitter.addWidget(history_widget)

        # --- Log viewer ---
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_label = QLabel("Log")
        log_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        log_header.addWidget(log_label)
        log_header.addSpacing(12)
        log_header.addWidget(QLabel("Min level:"))
        self._level_combo = QComboBox()
        self._level_combo.addItem("DEBUG",   logging.DEBUG)
        self._level_combo.addItem("INFO",    logging.INFO)
        self._level_combo.addItem("WARNING", logging.WARNING)
        self._level_combo.addItem("ERROR",   logging.ERROR)
        self._level_combo.setCurrentIndex(1)  # INFO default
        self._min_level = logging.INFO
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        log_header.addWidget(self._level_combo)
        log_header.addStretch()
        clear_log_btn = QPushButton("Clear")
        clear_log_btn.setFixedWidth(52)
        clear_log_btn.clicked.connect(self._log_view_clear)
        log_header.addWidget(clear_log_btn)
        log_layout.addLayout(log_header)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Courier New", 9))
        self._log_view.setStyleSheet("background: #0d0d0d; color: #ccc;")
        log_layout.addWidget(self._log_view)
        splitter.addWidget(log_widget)

        splitter.setSizes([200, 300])

    def _history_list_clear(self) -> None:
        self._history_list.clear()

    def _log_view_clear(self) -> None:
        self._log_view.clear()
        self._line_count = 0

    def _on_level_changed(self, index: int) -> None:
        self._min_level = self._level_combo.itemData(index)
