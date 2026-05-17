"""State Hotkeys tab — per-state global key bindings + HTTP server settings."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from battlemode.profiles.models import GameState
from battlemode.ui import settings as _settings

_STATES = [
    GameState.MENU,
    GameState.SELECTION,
    GameState.BATTLE,
    GameState.WIN,
    GameState.LOSS,
]
_STATE_LABELS = {
    GameState.MENU:      "Menu",
    GameState.SELECTION: "Selection",
    GameState.BATTLE:    "Battle",
    GameState.WIN:       "Win",
    GameState.LOSS:      "Loss",
}
_STATE_COLORS = {
    GameState.MENU:      "#5b8dd9",
    GameState.SELECTION: "#f0c040",
    GameState.BATTLE:    "#e05c5c",
    GameState.WIN:       "#50c878",
    GameState.LOSS:      "#9b59b6",
}


# ------------------------------------------------------------------ #
#  Key helpers                                                          #
# ------------------------------------------------------------------ #

def _qt_to_pynput(key: int, mods: Qt.KeyboardModifier) -> str:
    """Convert a Qt key event to a pynput hotkey string e.g. '<ctrl>+<f1>'."""
    parts: list[str] = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("<ctrl>")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("<shift>")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("<alt>")

    F1 = Qt.Key.Key_F1.value
    _special: dict[int, str] = {
        Qt.Key.Key_Return.value:   "<enter>",
        Qt.Key.Key_Enter.value:    "<enter>",
        Qt.Key.Key_Space.value:    "<space>",
        Qt.Key.Key_Tab.value:      "<tab>",
        Qt.Key.Key_Backspace.value:"<backspace>",
        Qt.Key.Key_Delete.value:   "<delete>",
        Qt.Key.Key_Insert.value:   "<insert>",
        Qt.Key.Key_Home.value:     "<home>",
        Qt.Key.Key_End.value:      "<end>",
        Qt.Key.Key_PageUp.value:   "<page_up>",
        Qt.Key.Key_PageDown.value: "<page_down>",
        Qt.Key.Key_Up.value:       "<up>",
        Qt.Key.Key_Down.value:     "<down>",
        Qt.Key.Key_Left.value:     "<left>",
        Qt.Key.Key_Right.value:    "<right>",
    }

    if F1 <= key <= F1 + 19:
        parts.append(f"<f{key - F1 + 1}>")
    elif key in _special:
        parts.append(_special[key])
    else:
        try:
            ch = chr(key).lower()
            if ch.isprintable() and not ch.isspace():
                parts.append(ch)
        except (ValueError, OverflowError):
            pass

    return "+".join(parts)


def _pynput_display(s: str) -> str:
    """Format a pynput key string for display: '<ctrl>+<f1>' → 'Ctrl+F1'."""
    if not s:
        return "—"

    def fmt(part: str) -> str:
        if not (part.startswith("<") and part.endswith(">")):
            return part.upper() if len(part) == 1 else part.title()
        inner = part[1:-1]
        if inner.startswith("f") and inner[1:].isdigit():
            return inner.upper()
        return inner.replace("_", " ").title()

    return "+".join(fmt(p) for p in s.split("+"))


# ------------------------------------------------------------------ #
#  Key capture dialog                                                   #
# ------------------------------------------------------------------ #

class _KeyCaptureDialog(QDialog):
    """Modal dialog that waits for a key press and records it."""

    def __init__(self, state_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Set hotkey — {state_name}")
        self.setModal(True)
        self.setFixedSize(340, 150)
        self._result: str = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel(f"Press a key combination for  <b>{state_name}</b>:"))

        self._display = QLabel("Waiting…")
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._display.setStyleSheet(
            "background: #1a1a1a; color: #5b8dd9; padding: 8px; border-radius: 4px;"
        )
        self._display.setMinimumHeight(40)
        layout.addWidget(self._display)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear binding")
        clear_btn.clicked.connect(self._on_clear)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_clear(self) -> None:
        self._result = ""
        self.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        _ignore = {
            Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
            Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
        }
        if key in _ignore:
            return
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        key_str = _qt_to_pynput(key, mods)
        if key_str:
            self._result = key_str
            self._display.setText(_pynput_display(key_str))
            QTimer.singleShot(350, self.accept)

    def result_key(self) -> str:
        return self._result


# ------------------------------------------------------------------ #
#  Main widget                                                          #
# ------------------------------------------------------------------ #

class StateHotkeysTab(QWidget):
    """State hotkey bindings + HTTP server configuration."""

    # Emitted (from pynput thread or main thread) when a hotkey fires.
    # Connected to MainWindow which routes to main thread via its own signal.
    force_state = pyqtSignal(object)   # GameState

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bindings: dict[GameState, str] = {}
        self._key_labels: dict[GameState, QLabel] = {}
        self._listener = None
        self._build_ui()
        self._load_bindings()
        self._register_hotkeys()

    # ------------------------------------------------------------------ #
    #  UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # --- Hotkey bindings ---
        hk_group = QGroupBox("State Hotkeys")
        hk_layout = QVBoxLayout(hk_group)
        hk_layout.setSpacing(6)

        hint = QLabel(
            "Bind a key combination to instantly force a game state. "
            "Hotkeys are global — they fire even when this window is not focused."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hk_layout.addWidget(hint)
        hk_layout.addSpacing(4)

        for state in _STATES:
            row = QHBoxLayout()

            name_lbl = QLabel(f"  {_STATE_LABELS[state]}")
            name_lbl.setFixedWidth(80)
            name_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            color = _STATE_COLORS.get(state, "#aaa")
            name_lbl.setStyleSheet(f"color: {color};")
            row.addWidget(name_lbl)

            key_lbl = QLabel("—")
            key_lbl.setFixedWidth(180)
            key_lbl.setFont(QFont("Courier New", 10))
            key_lbl.setStyleSheet("color: #ccc; background: #1c1c1c; padding: 2px 6px; border-radius: 3px;")
            self._key_labels[state] = key_lbl
            row.addWidget(key_lbl)

            set_btn = QPushButton("Set…")
            set_btn.setFixedWidth(56)
            set_btn.clicked.connect(lambda _, s=state: self._capture_key(s))
            row.addWidget(set_btn)

            clear_btn = QPushButton("Clear")
            clear_btn.setFixedWidth(50)
            clear_btn.clicked.connect(lambda _, s=state: self._clear_key(s))
            row.addWidget(clear_btn)

            copy_btn = QPushButton("Copy curl")
            copy_btn.setFixedWidth(76)
            copy_btn.setToolTip(f"Copy curl command for {_STATE_LABELS[state]} to clipboard")
            copy_btn.clicked.connect(lambda _, s=state, b=copy_btn: self._copy_curl(s, b))
            row.addWidget(copy_btn)

            row.addStretch()
            hk_layout.addLayout(row)

        root.addWidget(hk_group)

        # --- HTTP server settings ---
        http_group = QGroupBox("HTTP Control Server")
        http_layout = QVBoxLayout(http_group)
        http_layout.setSpacing(8)

        http_hint = QLabel(
            "Exposes a local HTTP API so external tools (Stream Deck, scripts) can "
            "control BattleMode. Use the <b>HTTP</b> button in the transport bar to start/stop it."
        )
        http_hint.setWordWrap(True)
        http_hint.setStyleSheet("color: #888; font-size: 11px;")
        http_layout.addWidget(http_hint)

        fields_row = QHBoxLayout()
        fields_row.addWidget(QLabel("Host:"))
        self._http_host = QLineEdit()
        self._http_host.setText(_settings.get("http_host", "127.0.0.1"))
        self._http_host.setFixedWidth(130)
        self._http_host.textChanged.connect(lambda t: _settings.set("http_host", t))
        fields_row.addWidget(self._http_host)
        fields_row.addSpacing(12)
        fields_row.addWidget(QLabel("Port:"))
        self._http_port = QSpinBox()
        self._http_port.setRange(1024, 65535)
        self._http_port.setValue(_settings.get("http_port", 9847))
        self._http_port.setFixedWidth(80)
        self._http_port.valueChanged.connect(lambda v: _settings.set("http_port", v))
        fields_row.addWidget(self._http_port)
        fields_row.addStretch()
        http_layout.addLayout(fields_row)

        endpoints = QLabel(
            "<b>Endpoints</b><br>"
            "<span style='color:#aaa; font-family:Courier New;'>"
            "GET  /state<br>"
            "POST /state/menu &nbsp;&nbsp; /state/selection &nbsp;&nbsp; "
            "/state/battle &nbsp;&nbsp; /state/win &nbsp;&nbsp; /state/loss<br>"
            "POST /skip &nbsp;&nbsp; /pause"
            "</span>"
        )
        endpoints.setStyleSheet("font-size: 11px; margin-top: 4px;")
        http_layout.addWidget(endpoints)

        example = QLabel(
            "Stream Deck example:<br>"
            "<span style='color:#5b8dd9; font-family:Courier New;'>"
            "curl -s -X POST http://127.0.0.1:9847/state/battle"
            "</span>"
        )
        example.setStyleSheet("font-size: 11px; margin-top: 2px;")
        http_layout.addWidget(example)

        root.addWidget(http_group)
        root.addStretch()

    # ------------------------------------------------------------------ #
    #  Hotkey capture                                                        #
    # ------------------------------------------------------------------ #

    def _copy_curl(self, state: GameState, btn: QPushButton) -> None:
        host = self._http_host.text().strip() or "127.0.0.1"
        port = self._http_port.value()
        cmd = f"curl -s -X POST http://{host}:{port}/state/{state.value}"
        QApplication.clipboard().setText(cmd)
        btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: btn.setText("Copy curl"))

    def _capture_key(self, state: GameState) -> None:
        dlg = _KeyCaptureDialog(_STATE_LABELS[state], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key_str = dlg.result_key()
            if key_str:
                self._bindings[state] = key_str
            else:
                self._bindings.pop(state, None)
            self._update_label(state)
            self._save_bindings()
            self._register_hotkeys()

    def _clear_key(self, state: GameState) -> None:
        self._bindings.pop(state, None)
        self._update_label(state)
        self._save_bindings()
        self._register_hotkeys()

    def _update_label(self, state: GameState) -> None:
        key_str = self._bindings.get(state, "")
        self._key_labels[state].setText(_pynput_display(key_str) if key_str else "—")

    # ------------------------------------------------------------------ #
    #  Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _save_bindings(self) -> None:
        _settings.set("state_hotkeys", {s.value: k for s, k in self._bindings.items() if k})

    def _load_bindings(self) -> None:
        data = _settings.get("state_hotkeys", {})
        by_value = {s.value: s for s in _STATES}
        for val, key_str in data.items():
            state = by_value.get(val)
            if state and key_str:
                self._bindings[state] = key_str
                self._update_label(state)

    # ------------------------------------------------------------------ #
    #  pynput registration                                                  #
    # ------------------------------------------------------------------ #

    def _register_hotkeys(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

        active = {key_str: state for state, key_str in self._bindings.items() if key_str}
        if not active:
            return

        try:
            from pynput import keyboard as _kb

            def _make_cb(s: GameState):
                def cb():
                    self.force_state.emit(s)
                return cb

            self._listener = _kb.GlobalHotKeys({k: _make_cb(s) for k, s in active.items()})
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            pass

    def stop_hotkeys(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    # ------------------------------------------------------------------ #
    #  Accessors (used by MainWindow to build the HTTP server)              #
    # ------------------------------------------------------------------ #

    def get_http_host(self) -> str:
        return self._http_host.text().strip() or "127.0.0.1"

    def get_http_port(self) -> int:
        return self._http_port.value()
