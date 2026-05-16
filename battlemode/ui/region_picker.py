"""Region picker — click and drag on a live screenshot to select an OCR region."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    """Convert a BGR numpy frame to a QPixmap."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(img)


class _Canvas(QWidget):
    """Displays a screenshot and lets the user rubber-band a rectangle over it."""

    def __init__(self, pixmap: QPixmap, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._final: Optional[QRect] = None
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------ #

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            p.fillRect(rect, QColor(50, 150, 255, 50))
            pen = QPen(QColor(50, 150, 255), 2)
            p.setPen(pen)
            p.drawRect(rect)
            # size hint
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                rect.x() + 4, rect.y() + 14,
                f"{rect.width()} × {rect.height()}",
            )
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.pos()
            self._current = event.pos()
            self._final = None
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._current = event.pos()
            self._final = QRect(self._origin, self._current).normalized()
            self.update()

    def selection(self) -> Optional[QRect]:
        return self._final


class RegionPickerDialog(QDialog):
    """
    Show a live screenshot and let the user drag a rectangle.

    Call ``region()`` after ``exec()`` to get ``(x, y, w, h)`` in image pixels.
    Returns ``None`` if the user cancelled or drew nothing.
    """

    def __init__(self, frame: np.ndarray, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Region — drag a rectangle, then click OK")
        self.setModal(True)
        self._region: Optional[tuple[int, int, int, int]] = None

        h, w = frame.shape[:2]
        # Scale so the screenshot fits within ~85 % of a 1920×1080 screen
        max_w, max_h = 1600, 900
        self._scale = min(max_w / w, max_h / h, 1.0)
        scale = self._scale

        pixmap = _frame_to_pixmap(frame)
        scaled = pixmap.scaled(
            int(w * scale), int(h * scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        hint = QLabel(
            "Click and drag to select the region you want OCR to scan. "
            "The blue overlay shows your selection."
        )
        hint.setStyleSheet("color: #aaa; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._canvas = _Canvas(scaled)
        layout.addWidget(self._canvas)

        btn_row = QHBoxLayout()
        self._coord_label = QLabel("")
        self._coord_label.setStyleSheet("color: #888; font-size: 10px;")
        btn_row.addWidget(self._coord_label, stretch=1)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.clicked.connect(self._commit)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # Update coord label as the user drags
        self._canvas.mouseMoveEvent = self._intercept_move(self._canvas.mouseMoveEvent)
        self._canvas.mouseReleaseEvent = self._intercept_release(self._canvas.mouseReleaseEvent)

        self.adjustSize()

    # ------------------------------------------------------------------ #

    def _intercept_move(self, original):
        def handler(event):
            original(event)
            if self._canvas._origin:
                r = QRect(self._canvas._origin, event.pos()).normalized()
                ix = int(r.x() / self._scale)
                iy = int(r.y() / self._scale)
                iw = int(r.width() / self._scale)
                ih = int(r.height() / self._scale)
                self._coord_label.setText(f"x={ix}  y={iy}  w={iw}  h={ih}")
        return handler

    def _intercept_release(self, original):
        def handler(event):
            original(event)
            rect = self._canvas.selection()
            if rect:
                ix = int(rect.x() / self._scale)
                iy = int(rect.y() / self._scale)
                iw = int(rect.width() / self._scale)
                ih = int(rect.height() / self._scale)
                self._coord_label.setText(f"x={ix}  y={iy}  w={iw}  h={ih}  ✓")
        return handler

    def _commit(self) -> None:
        rect = self._canvas.selection()
        if rect and rect.width() > 2 and rect.height() > 2:
            s = self._scale
            self._region = (
                int(rect.x() / s),
                int(rect.y() / s),
                int(rect.width() / s),
                int(rect.height() / s),
            )
        self.accept()

    def region(self) -> Optional[tuple[int, int, int, int]]:
        return self._region
