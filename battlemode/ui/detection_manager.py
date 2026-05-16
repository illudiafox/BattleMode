"""Detection Manager — configure OCR rules and map them to game states."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
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

THUMB_SIZE = 280   # max width/height for gallery thumbnails


class _TemplateGalleryWindow(QWidget):
    """Floating window showing all template images for a rule as a scrollable grid."""

    def __init__(self, paths: list[str], title: str = "Templates", parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll, stretch=1)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(12)
        scroll.setWidget(container)

        COLS = 3
        for i, path in enumerate(paths):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(4, 4, 4, 4)
            cell_layout.setSpacing(4)

            img_label = QLabel()
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_label.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
            img_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)

            import cv2
            frame = cv2.imread(path)
            if frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qimg).scaled(
                    THUMB_SIZE, THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                img_label.setPixmap(pixmap)
            else:
                img_label.setText("(not found)")
                img_label.setStyleSheet("background: #1a1a1a; color: #666; border: 1px solid #333;")

            name_label = QLabel(Path(path).name)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet("color: #aaa; font-size: 10px;")
            name_label.setWordWrap(True)

            cell_layout.addWidget(img_label)
            cell_layout.addWidget(name_label)
            grid.addWidget(cell, i // COLS, i % COLS)

        close_btn = QPushButton("Close  [Esc]")
        close_btn.clicked.connect(self.close)
        root.addWidget(close_btn)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class DetectionManagerWidget(QWidget):
    """
    Full detection rule editor.

    Left panel  — list of all rules in the active profile
    Right panel — form to edit the selected rule
    Bottom      — test strip: run a single OCR capture and show raw text + matched state
    """

    profile_saved = pyqtSignal(str)   # emitted with profile game_id after save
    _burst_done = pyqtSignal(list)    # list[str] of saved paths — cross-thread

    def __init__(self, profile_manager: ProfileManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.profile_manager = profile_manager
        self._profile: Optional[GameProfile] = None
        self._selected_index: int = -1
        self._capture_window = None
        self._capture_device = None
        self._gallery_window: Optional[_TemplateGalleryWindow] = None
        self._burst_done.connect(self._on_burst_done)
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

        # Load initial profile now that all widgets exist
        if self._initial_profile:
            self._load_profile(self._initial_profile)

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
        self._initial_profile = self._profile_combo.currentText()

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
        root = QVBoxLayout(group)
        root.setSpacing(8)

        # --- Top: fields common to all rule types ---
        top_form = QFormLayout()
        top_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        top_form.setSpacing(8)

        self._enabled_cb = QCheckBox("Rule enabled")
        self._enabled_cb.setChecked(True)
        top_form.addRow(self._enabled_cb)

        self._state_combo = QComboBox()
        for label in STATE_LABELS.values():
            self._state_combo.addItem(label)
        top_form.addRow("Game State:", self._state_combo)

        self._priority_spin = QSpinBox()
        self._priority_spin.setRange(0, 100)
        self._priority_spin.setToolTip("Higher = checked first.")
        top_form.addRow("Priority:", self._priority_spin)

        delay_row = QWidget()
        dl = QHBoxLayout(delay_row)
        dl.setContentsMargins(0, 0, 0, 0)
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 60.0)
        self._delay_spin.setSingleStep(0.5)
        self._delay_spin.setDecimals(1)
        self._delay_spin.setFixedWidth(70)
        dl.addWidget(self._delay_spin)
        dl.addWidget(QLabel("s hold before switching"))
        dl.addStretch()
        top_form.addRow("Trigger delay:", delay_row)

        root.addLayout(top_form)

        # --- Tabs: OCR | Template ---
        tabs = QTabWidget()
        tabs.addTab(self._build_ocr_tab(), "OCR")
        tabs.addTab(self._build_template_tab(), "Template")
        root.addWidget(tabs, stretch=1)

        # --- Apply ---
        apply_btn = QPushButton("Apply Changes to Rule")
        apply_btn.clicked.connect(self._apply_rule_edits)
        root.addWidget(apply_btn)

        return group

    def _build_ocr_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(8, 8, 8, 8)

        hint = QLabel("One keyword per line. Triggers when ≥ N keywords found in OCR text.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(hint)

        self._keywords_edit = QTextEdit()
        self._keywords_edit.setPlaceholderText("fight\nbag\nuse\nhp\nrun")
        self._keywords_edit.setMaximumHeight(120)
        form.addRow("Keywords:", self._keywords_edit)

        min_kw_row = QWidget()
        mkl = QHBoxLayout(min_kw_row)
        mkl.setContentsMargins(0, 0, 0, 0)
        self._min_keywords_spin = QSpinBox()
        self._min_keywords_spin.setRange(1, 50)
        self._min_keywords_spin.setValue(1)
        self._min_keywords_spin.setFixedWidth(60)
        mkl.addWidget(self._min_keywords_spin)
        mkl.addWidget(QLabel("keyword(s) must match"))
        mkl.addStretch()
        form.addRow("Min matches:", min_kw_row)

        region_hint = QLabel("Leave blank for full screen, or pick a region to speed up OCR.")
        region_hint.setWordWrap(True)
        region_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(region_hint)

        use_region_row = QWidget()
        url = QHBoxLayout(use_region_row)
        url.setContentsMargins(0, 0, 0, 0)
        self._use_region_cb = QCheckBox("Limit to screen region")
        self._use_region_cb.stateChanged.connect(self._toggle_region_fields)
        url.addWidget(self._use_region_cb)
        pick_btn = QPushButton("Pick Region…")
        pick_btn.setFixedWidth(110)
        pick_btn.setToolTip("Capture the current frame and drag to select a region")
        pick_btn.clicked.connect(self._pick_region)
        url.addWidget(pick_btn)
        url.addStretch()
        form.addRow(use_region_row)

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

        return w

    def _build_template_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Multi-template toggle
        self._multi_tmpl_cb = QCheckBox("Multi-template mode — match fires if ANY image in the list hits")
        self._multi_tmpl_cb.setToolTip(
            "When enabled: all template images are checked; one match is enough to trigger.\n"
            "Also unlocks Capture Burst."
        )
        self._multi_tmpl_cb.stateChanged.connect(self._on_multi_tmpl_changed)
        layout.addWidget(self._multi_tmpl_cb)

        # List + inline preview side by side
        list_preview = QSplitter(Qt.Orientation.Horizontal)

        self._tmpl_list = QListWidget()
        self._tmpl_list.setToolTip("Click to preview · double-click to see full path")
        self._tmpl_list.currentItemChanged.connect(self._on_tmpl_selection_changed)
        list_preview.addWidget(self._tmpl_list)

        self._tmpl_preview = QLabel("Select a template\nto preview it here")
        self._tmpl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tmpl_preview.setStyleSheet("background: #111; color: #555; border: 1px solid #333;")
        self._tmpl_preview.setMinimumWidth(180)
        list_preview.addWidget(self._tmpl_preview)

        list_preview.setSizes([220, 200])
        layout.addWidget(list_preview, stretch=1)

        # Primary action row
        btn_row = QHBoxLayout()

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_template)
        btn_row.addWidget(browse_btn)

        capture_btn = QPushButton("Capture")
        capture_btn.setToolTip("Grab one screenshot now and add it as a template")
        capture_btn.clicked.connect(self._capture_template)
        btn_row.addWidget(capture_btn)

        self._burst_btn = QPushButton("Capture Burst")
        self._burst_btn.setToolTip("Grab 5 frames ~200 ms apart and add all as templates")
        self._burst_btn.setEnabled(False)
        self._burst_btn.clicked.connect(self._capture_burst)
        btn_row.addWidget(self._burst_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setToolTip("Remove selected template from this rule")
        remove_btn.clicked.connect(self._remove_template)
        btn_row.addWidget(remove_btn)

        view_btn = QPushButton("View All")
        view_btn.setToolTip("Open a gallery window showing all template images")
        view_btn.clicked.connect(self._view_templates)
        btn_row.addWidget(view_btn)

        layout.addLayout(btn_row)

        thresh_row = QWidget()
        tl = QHBoxLayout(thresh_row)
        tl.setContentsMargins(0, 0, 0, 0)
        self._tmpl_threshold_spin = QDoubleSpinBox()
        self._tmpl_threshold_spin.setRange(0.1, 1.0)
        self._tmpl_threshold_spin.setSingleStep(0.05)
        self._tmpl_threshold_spin.setDecimals(2)
        self._tmpl_threshold_spin.setValue(0.85)
        self._tmpl_threshold_spin.setFixedWidth(70)
        tl.addWidget(self._tmpl_threshold_spin)
        tl.addWidget(QLabel("confidence threshold (shared across all templates)"))
        tl.addStretch()
        layout.addWidget(thresh_row)

        return w

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
        region = "full screen" if not rule.ocr_region else "region"
        delay = f"  delay:{rule.trigger_delay}s" if rule.trigger_delay > 0 else ""
        status = "" if rule.enabled else "  [DISABLED]"
        return f"[{rule.state.value.upper()}] p{rule.priority}  min:{rule.min_keywords}{delay}  |  {keywords}  ({region}){status}"

    def _on_rule_selected(self, row: int) -> None:
        if not self._profile or row < 0:
            return
        self._selected_index = row
        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[row]
        self._populate_form(rule)

    def _populate_form(self, rule: DetectionRule) -> None:
        self._enabled_cb.setChecked(rule.enabled)

        label = STATE_LABELS.get(rule.state, "Unknown")
        idx = self._state_combo.findText(label)
        if idx >= 0:
            self._state_combo.setCurrentIndex(idx)

        self._priority_spin.setValue(rule.priority)
        self._delay_spin.setValue(rule.trigger_delay)
        self._min_keywords_spin.setValue(rule.min_keywords)
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

        self._multi_tmpl_cb.setChecked(rule.multi_template)
        self._burst_btn.setEnabled(rule.multi_template)
        self._tmpl_list.clear()
        self._tmpl_preview.setText("Select a template\nto preview it here")
        self._tmpl_preview.setPixmap(QPixmap())
        for path in rule.template_paths:
            self._tmpl_list_add(path)
        self._tmpl_threshold_spin.setValue(rule.template_threshold)

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

        rule.enabled = self._enabled_cb.isChecked()
        state_label = self._state_combo.currentText()
        rule.state = LABEL_TO_STATE.get(state_label, GameState.UNKNOWN)
        rule.priority = self._priority_spin.value()
        rule.trigger_delay = self._delay_spin.value()
        rule.min_keywords = self._min_keywords_spin.value()

        raw = self._keywords_edit.toPlainText()
        rule.ocr_text = [kw.strip().lower() for kw in raw.splitlines() if kw.strip()]

        if self._use_region_cb.isChecked():
            rule.ocr_region = (
                self._rx.value(), self._ry.value(),
                self._rw.value(), self._rh.value(),
            )
        else:
            rule.ocr_region = None

        rule.multi_template = self._multi_tmpl_cb.isChecked()
        rule.template_paths = [
            self._tmpl_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._tmpl_list.count())
        ]
        rule.template_threshold = self._tmpl_threshold_spin.value()

        # Invalidate cache for any paths in this rule so stale images are dropped
        from battlemode.vision.state_detector import invalidate_template_cache
        for p in rule.template_paths:
            invalidate_template_cache(p)

        self._refresh_rule_list()
        self._rule_list.setCurrentRow(self._selected_index)

    def _toggle_region_fields(self, state: int) -> None:
        self._region_row.setEnabled(bool(state))

    def _pick_region(self) -> None:
        """Capture a frame and open the visual region picker."""
        try:
            with self._make_capture() as cap:
                frame = cap.grab()
        except Exception as e:
            QMessageBox.critical(self, "Capture failed", str(e))
            return

        from battlemode.ui.region_picker import RegionPickerDialog
        dlg = RegionPickerDialog(frame, self)
        if dlg.exec():
            region = dlg.region()
            if region:
                x, y, w, h = region
                self._use_region_cb.setChecked(True)
                self._rx.setValue(x)
                self._ry.setValue(y)
                self._rw.setValue(w)
                self._rh.setValue(h)

    def _on_tmpl_selection_changed(self, current, previous) -> None:
        if current is None:
            self._tmpl_preview.setText("Select a template\nto preview it here")
            self._tmpl_preview.setPixmap(QPixmap())
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        import cv2
        frame = cv2.imread(path)
        if frame is None:
            self._tmpl_preview.setText(f"(file not found)\n{Path(path).name}")
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._tmpl_preview.width() - 4,
            self._tmpl_preview.height() - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._tmpl_preview.setPixmap(pixmap)

    def _on_multi_tmpl_changed(self, state: int) -> None:
        enabled = bool(state)
        self._burst_btn.setEnabled(enabled)
        if self._profile and self._selected_index >= 0:
            rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
            rules[self._selected_index].multi_template = enabled

    def _capture_burst(self) -> None:
        if not self._profile or self._selected_index < 0:
            QMessageBox.warning(self, "No rule selected", "Select a rule first.")
            return

        self._burst_btn.setEnabled(False)
        self._burst_btn.setText("Capturing…  0/5")

        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[self._selected_index]
        tmpl_dir = Path("user_data/templates")
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        profile_id = self._profile.game_id
        state_val = rule.state.value

        def worker():
            import cv2
            from datetime import datetime
            saved: list[str] = []
            for i in range(5):
                try:
                    with self._make_capture() as cap:
                        frame = cap.grab()
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:19]
                    path = str(tmpl_dir / f"{profile_id}_{state_val}_burst{i+1}_{ts}.png")
                    cv2.imwrite(path, frame)
                    saved.append(path)
                except Exception:
                    pass
                if i < 4:
                    import time
                    time.sleep(0.2)
            self._burst_done.emit(saved)

        threading.Thread(target=worker, daemon=True).start()

    def _on_burst_done(self, paths: list[str]) -> None:
        for p in paths:
            self._tmpl_list_add(p)
        self._burst_btn.setEnabled(True)
        self._burst_btn.setText("Capture Burst")
        QMessageBox.information(
            self, "Burst complete",
            f"Captured {len(paths)} image(s).\n\nClick 'Apply Changes to Rule' to attach them."
        )

    def _view_templates(self) -> None:
        paths = [
            self._tmpl_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._tmpl_list.count())
        ]
        if not paths:
            QMessageBox.information(self, "No templates", "Add at least one template image first.")
            return
        if self._gallery_window is not None:
            try:
                self._gallery_window.close()
            except RuntimeError:
                pass
        title = "Templates"
        if self._profile and self._selected_index >= 0:
            rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
            rule = rules[self._selected_index]
            title = f"Templates — {rule.state.value.upper()}"
        self._gallery_window = _TemplateGalleryWindow(paths, title, self)
        self._gallery_window.destroyed.connect(lambda: setattr(self, "_gallery_window", None))
        self._gallery_window.show()

    def _tmpl_list_add(self, path: str) -> None:
        """Add a path to the template list widget (deduplicates)."""
        existing = [
            self._tmpl_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._tmpl_list.count())
        ]
        if path in existing:
            return
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self._tmpl_list.addItem(item)

    def add_template_path(self, path: str) -> None:
        """Public — called by MainWindow after a Ctrl+L capture."""
        self._tmpl_list_add(path)

    def _browse_template(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Template Image(s)", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )
        for path in paths:
            self._tmpl_list_add(path)

    def _remove_template(self) -> None:
        row = self._tmpl_list.currentRow()
        if row >= 0:
            self._tmpl_list.takeItem(row)

    def _capture_template(self) -> None:
        """Grab a frame right now and add it to the template list."""
        if not self._profile or self._selected_index < 0:
            QMessageBox.warning(self, "No rule selected", "Select a rule first.")
            return

        try:
            with self._make_capture() as cap:
                frame = cap.grab()
        except Exception as e:
            QMessageBox.critical(self, "Capture failed", str(e))
            return

        import cv2
        rules = sorted(self._profile.detection_rules, key=lambda r: -r.priority)
        rule = rules[self._selected_index]

        tmpl_dir = Path("user_data/templates")
        tmpl_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self._profile.game_id}_{rule.state.value}_{ts}.png"
        path = str(tmpl_dir / filename)

        cv2.imwrite(path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        self._tmpl_list_add(path)
        QMessageBox.information(
            self, "Template saved",
            f"Saved {frame.shape[1]}×{frame.shape[0]} image.\n\nPath: {path}\n\n"
            "Click 'Apply Changes to Rule' to attach it."
        )

    # ------------------------------------------------------------------ #
    #  Save                                                                 #
    # ------------------------------------------------------------------ #

    def _save_profile(self) -> None:
        if not self._profile:
            return
        self.profile_manager.save(self._profile)
        self.profile_saved.emit(self._profile.game_id)
        QMessageBox.information(self, "Saved", f"Profile '{self._profile.name}' saved.")

    def _make_capture(self):
        if self._capture_device:
            from battlemode.capture.device_capture import DeviceCapture
            return DeviceCapture(self._capture_device)
        if self._capture_window:
            from battlemode.capture.window_capture import WindowCapture
            return WindowCapture(self._capture_window)
        from battlemode.capture.screen_capture import ScreenCapture
        return ScreenCapture()

    def set_capture_window(self, window) -> None:
        self._capture_window = window
        self._capture_device = None

    def set_capture_device(self, device) -> None:
        self._capture_device = device
        self._capture_window = None

    def refresh_profile_list(self, select: str = "") -> None:
        """Called by MainWindow after creating or deleting a profile."""
        self._refresh_profile_combo()
        if select:
            idx = self._profile_combo.findText(select)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)
