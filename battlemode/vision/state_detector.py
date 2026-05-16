"""Game state detection via OCR and (future) template matching."""

from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

from battlemode.profiles.models import DetectionRule, GameProfile, GameState


def _preprocess_for_ocr(frame: np.ndarray) -> Image.Image:
    """Convert BGR frame to a high-contrast grayscale PIL image for Tesseract."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Upscale — Tesseract accuracy improves with larger text
    scale = 2
    gray = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    # Threshold to binary
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary)


def _extract_text(frame: np.ndarray, region: Optional[tuple[int, int, int, int]] = None) -> str:
    """Run Tesseract OCR on a frame (or cropped region) and return lower-cased text."""
    if region:
        x, y, w, h = region
        frame = frame[y : y + h, x : x + w]
    img = _preprocess_for_ocr(frame)
    text = pytesseract.image_to_string(img, config="--psm 6")
    return text.lower()


class StateDetector:
    """Detects the current game state from a captured frame using a loaded profile."""

    def __init__(self, profile: GameProfile) -> None:
        self.profile = profile
        # Sort rules by descending priority so high-priority rules are checked first
        self._rules: list[DetectionRule] = sorted(
            profile.detection_rules, key=lambda r: r.priority, reverse=True
        )

    def detect(self, frame: np.ndarray) -> GameState:
        """Return the detected GameState for a given frame."""
        for rule in self._rules:
            if self._matches(frame, rule):
                return rule.state
        return GameState.UNKNOWN

    def _matches(self, frame: np.ndarray, rule: DetectionRule) -> bool:
        if rule.ocr_text:
            text = _extract_text(frame, rule.ocr_region)
            if any(keyword in text for keyword in rule.ocr_text):
                return True
        # Template matching goes here in the future
        return False
