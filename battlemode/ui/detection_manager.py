"""Detection Manager — configure OCR rules and map them to game states."""

from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from battlemode.profiles.manager import ProfileManager
from battlemode.profiles.models import DetectionRule, GameProfile, GameState

STATE_LABELS = {
    GameState.MENU:      "Menu",
    GameState.SELECTION: "Selection",
    GameState.BATTLE:    "Battle",
    GameState.WIN:       "Win",
    GameState.LOSS:      "Loss",
    GameState.UNKNOWN:   "Unknown",
}
LABEL_TO_STATE = {v: k for k, v in STATE_LABELS.items()}


class DetectionManagerWidget(QWidget):
    """
    Full detection rule editor.

    Left panel  — list of all rules in the active profile
    Right panel — form to edit the selected rule
    Bottom      — test strip: run a single OCR capture and show raw text + matched state
    """

    profile_saved = pyqtSignal(str)   # emitted with profile game_id after save

    def __init__(self, profile_manager: ProfileManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.profile_manager = profile_manager
        self._profile: Optional[GameProfile] = None
        self._selected_index: int = -1
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Profile selector bar
        root.addWidget(self._build_profile_bar())

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_rule_list_panel())
        splitter.addWidget(self._build_edit_panel())
        splitter.setSizes([300, 500])
        root.addWidget(splitter, stretch=1)

        # OCR test strip
        root.addWidget(self._build_test_strip())

    def _build_profile_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        self._refresh_profile_combo()
        self._profile_combo.currentTextChanged.connect(self._load_profile)
        layout.addWidget(self._profile_combo)

        layout.addStretch()

        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self._save_profile)
        layout.addWidget(save_btn)

        return bar

    def _build_rule_list_panel(self) -> QWidget:
        group = QGroupBox("Detection Rules")
        layout = QVBoxLayout(group)

        self._rule_list = QListWidget()
        self._rule_list.currentRowChanged.connect(self._on_rule_selected)
        layout.addWidget(self._rule_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Rule")
        add_btn.clicked.connect(self._add_rule)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_rule)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)

        return group

    def _build_edit_panel(self) -> QWidget:
        group = QGroupBox("Edit Rule")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        # State
        self._state_combo = QComboBox()
        for label in STATE_LABELS.values():
            self._state_combo.addItem(label)
        form.addRow("Game State:", self._state_combo)

        # Priority
        self._priority_spin = QSpinBox()
        self._priority_spin.setRange(0, 100)
        self._priority_spin.setToolTip("Higher = checked first. Use to break ties between rules.")
        form.addRow("Priority:", self._priority_spin)

        # OCR keywords
        kw_hint = QLabel("One keyword per line. Detection triggers if ANY keyword is found in the OCR text.")
        kw_hint.setWordWrap(True)
        kw_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(kw_hint)

        self._keywords_edit = QTextEdit()
        self._keywords_edit.setPlaceholderText("fight\nbag\nuse\nhp\nrun")
        self._keywords_edit.setMaximumHeight(130)
        form.addRow("Keywords:", self._keywords_edit)

        # Region
        region_hint = QLabel("Leave all zeros to scan the full screen. Use x/y/w/h to limit to a region (pixels).")
        region_hint.setWordWrap(True)
        region_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(region_hint)

        self._use_region_cb = QCheckBox("Limit to screen region")
        self._use_region_cb.stateChanged.connect(self._toggle_region_fields)
        form.addRow(self._use_region_cb)

        region_row = QWidget()
        rl = QHBoxLayout(region_row)
        rl.setContentsMargins(0, 0, 0, 0)
        self._rx = QSpinBox(); self._rx.setRange(0, 9999); self._rx.setPrefix("x ")
        self._ry = QSpinBox(); self._ry.setRange(0, 9999); self._ry.setPrefix("y ")
        self._rw = QSpinBox(); self._rw.setRange(0, 9999); self._rw.setPrefix("w ")
        self._rh = QSpinBox(); self._rh.setRange(0, 9999); self._rh.setPrefix("h ")
        for spin in [self._rx, self._ry, self._rw, self._rh]:
            rl.addWidget(spin)
        self._region_row = region_row
        self._region_row.setEnabled(False)
        form.addRow("Region (px):", region_row)

        # Apply button
        apply_btn = QPushButton("Apply Changes to Rule")
        apply_btn.clicked.connect(self._apply_rule_edits)
        form.addRow(apply_btn)

        return group

    def _build_test_strip(self) -> QGroupBox:
        group = QGroupBox("Test Detection (single capture)")
        layout = QHBoxLayout(group)

        self._test_btn = QPushButton("Capture & Detect Now")
        self._test_btn.setFixedWidth(180)
        self._test_btn.clicked.connect(self._run_test)
        layout.addWidget(self._test_btn)

        layout.addWidget(QLabel("Detected state:"))
        self._test_state_label = QLabel("—")
        self._test_state_label.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self._test_state_label.setFixedWidth(110)
        layout.addWidget(self._test_state_label)

        layout.addWidget(QLabel("OCR text (truncated):"))
        self._test_ocr_label = QLabel("—")
        self._test_ocr_label.setFont(QFont("Courier New", 9))
        self._test_ocr_label.setWordWrap(True)
        layout.addWidget(self._test_ocr_label, stretch=1)

        return group

    # ------------------------------------------------------------------ #
    #  Profile loading                                                      #
    # ------------------------------------------------------------------ #

    def _refresh_profile_combo(self) -> None:
        self._profile_combo.blockSignals(True)
        current = self._profile_combo.currentText()
        self._profile_combo.clear()
        for name in self.profile_manager.list_profiles():
            self._profile_combo.addItem(name)
        if current:
            idx = self._profile_combo.findText(current)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.blockSignals(False)

    def _load_profile(self, game_id: str) -> None:
        if not game_id:
            return
        try:
            self._profile = self.profile_manager.load(game_id)
            self._refresh_rule_list()
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Profile not found", str(e))

    def load_profile(self, game_id: str) -> None:
        """Public — called by MainWindow when profile changes."""
        idx = self._profile_combo.findText(game_id)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        else:
            self._load_profile(game_id)

    # ------------------------------------------------------------------ #
    #  Rule list                                                            #
    # ------------------------------------------------------------------ #

    def _refresh_rule_list(self) -> None:
        self._rule_list.clear()
        if not self._profile:
            return
        for rule in sorted(self._profile.detection_rules, key=lambda r: -r.priority):
            label = self._rule_label(rule)
            self._rule_list.addItem(QListWidgetItem(label))

    def _rule_label(self, rule: DetectionRule) -> str:
        keywords = ", ".join(rule.ocr_text or [])[:50]
        region = "full screen" if not rule.ocr_region else f"region {rule.ocr_region}"
        return f"[{rule.state.value.upper()}] p{rule.priority}  |  {keywords}  ({region})"

    def _on_rule_selected(self, row: int) -> None:
        if not self._profile or row < 0:
            return
        self._selected_index = row
        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[row]
        self._populate_form(rule)

    def _populate_form(self, rule: DetectionRule) -> None:
        label = STATE_LABELS.get(rule.state, "Unknown")
        idx = self._state_combo.findText(label)
        if idx >= 0:
            self._state_combo.setCurrentIndex(idx)

        self._priority_spin.setValue(rule.priority)
        self._keywords_edit.setPlainText("\n".join(rule.ocr_text or []))

        if rule.ocr_region:
            self._use_region_cb.setChecked(True)
            self._rx.setValue(rule.ocr_region[0])
            self._ry.setValue(rule.ocr_region[1])
            self._rw.setValue(rule.ocr_region[2])
            self._rh.setValue(rule.ocr_region[3])
        else:
            self._use_region_cb.setChecked(False)
            for spin in [self._rx, self._ry, self._rw, self._rh]:
                spin.setValue(0)

    # ------------------------------------------------------------------ #
    #  Rule editing                                                         #
    # ------------------------------------------------------------------ #

    def _add_rule(self) -> None:
        if not self._profile:
            return
        new_rule = DetectionRule(state=GameState.UNKNOWN, priority=0, ocr_text=[])
        self._profile.detection_rules.append(new_rule)
        self._refresh_rule_list()
        self._rule_list.setCurrentRow(self._rule_list.count() - 1)

    def _delete_rule(self) -> None:
        if not self._profile or self._selected_index < 0:
            return
        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[self._selected_index]
        self._profile.detection_rules.remove(rule)
        self._refresh_rule_list()
        self._selected_index = -1

    def _apply_rule_edits(self) -> None:
        if not self._profile or self._selected_index < 0:
            QMessageBox.information(self, "No rule selected", "Select a rule from the list first.")
            return

        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[self._selected_index]

        state_label = self._state_combo.currentText()
        rule.state = LABEL_TO_STATE.get(state_label, GameState.UNKNOWN)
        rule.priority = self._priority_spin.value()

        raw = self._keywords_edit.toPlainText()
        rule.ocr_text = [kw.strip().lower() for kw in raw.splitlines() if kw.strip()]

        if self._use_region_cb.isChecked():
            rule.ocr_region = (
                self._rx.value(), self._ry.value(),
                self._rw.value(), self._rh.value(),
            )
        else:
            rule.ocr_region = None

        self._refresh_rule_list()
        self._rule_list.setCurrentRow(self._selected_index)

    def _toggle_region_fields(self, state: int) -> None:
        self._region_row.setEnabled(bool(state))

    # ------------------------------------------------------------------ #
    #  Save                                                                 #
    # ------------------------------------------------------------------ #

    def _save_profile(self) -> None:
        if not self._profile:
            return
        self.profile_manager.save(self._profile)
        self.profile_saved.emit(self._profile.game_id)
        QMessageBox.information(self, "Saved", f"Profile '{self._profile.name}' saved.")

    # ------------------------------------------------------------------ #
    #  Test detection                                                       #
    # ------------------------------------------------------------------ #

    def set_capture_window(self, window) -> None:
        """Called by MainWindow to pass the selected capture window (or None = full screen)."""
        self._capture_window = window

    def _run_test(self) -> None:
        if not self._profile:
            QMessageBox.warning(self, "No profile", "Load a profile first.")
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText("Capturing…")
        capture_window = getattr(self, "_capture_window", None)

        def worker():
            try:
                from battlemode.vision.state_detector import StateDetector, _extract_text

                detector = StateDetector(self._profile)

                if capture_window:
                    from battlemode.capture.window_capture import WindowCapture
                    cap = WindowCapture(capture_window)
                else:
                    from battlemode.capture.screen_capture import ScreenCapture
                    cap = ScreenCapture()

                with cap:
                    frame = cap.grab()

                state = detector.detect(frame)
                raw_text = _extract_text(frame)
                preview = raw_text.replace("\n", " ").strip()[:120]

                self._test_state_label.setText(state.value.upper())
                self._test_ocr_label.setText(preview or "(no text found)")
            except Exception as e:
                self._test_state_label.setText("ERROR")
                self._test_ocr_label.setText(str(e))
            finally:
                self._test_btn.setEnabled(True)
                self._test_btn.setText("Capture & Detect Now")

        threading.Thread(target=worker, daemon=True).start()
