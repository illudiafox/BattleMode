"""Game state detection via OCR and (future) template matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

from battlemode.profiles.models import DetectionRule, GameProfile, GameState
from battlemode.logger import get as get_log

log = get_log("detector")


@dataclass
class DetectionResult:
    """Everything known about a single detection event."""
    rule: DetectionRule
    matched_keywords: list[str]
    total_keywords: int

    @property
    def state(self) -> GameState:
        return self.rule.state

    @property
    def trigger_delay(self) -> float:
        return self.rule.trigger_delay

    def summary(self) -> str:
        """Human-readable one-liner for logs and UI."""
        return (
            f"{self.state.value.upper()}  "
            f"[{len(self.matched_keywords)}/{self.total_keywords} keywords: "
            f"{', '.join(self.matched_keywords)}]"
        )


def _preprocess_for_ocr(frame: np.ndarray) -> Image.Image:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = 2
    gray = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                      interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary)


def _extract_text(frame: np.ndarray, region: Optional[tuple[int, int, int, int]] = None) -> str:
    if region:
        x, y, w, h = region
        frame = frame[y : y + h, x : x + w]
    img = _preprocess_for_ocr(frame)
    try:
        text = pytesseract.image_to_string(img, config="--psm 6")
    except Exception:
        log.exception("Tesseract OCR failed")
        return ""
    return text.lower()


class StateDetector:
    def __init__(self, profile: GameProfile) -> None:
        self.profile = profile
        self._rules: list[DetectionRule] = sorted(
            profile.detection_rules, key=lambda r: r.priority, reverse=True
        )

    def detect(self, frame: np.ndarray) -> GameState:
        result = self.detect_result(frame)
        return result.state if result else GameState.UNKNOWN

    def detect_rule(self, frame: np.ndarray) -> DetectionRule | None:
        result = self.detect_result(frame)
        return result.rule if result else None

    def detect_result(self, frame: np.ndarray) -> DetectionResult | None:
        """Return a full DetectionResult (rule + matched keywords) or None."""
        log.debug("Running detection against %d rules", len(self._rules))
        for rule in self._rules:
            result = self._match_result(frame, rule)
            if result:
                log.debug("Matched: %s", result.summary())
                return result
        log.debug("No rule matched → UNKNOWN")
        return None

    def _match_result(self, frame: np.ndarray, rule: DetectionRule) -> DetectionResult | None:
        if not rule.enabled:
            return None
        if rule.ocr_text:
            text = _extract_text(frame, rule.ocr_region)
            matched = [kw for kw in rule.ocr_text if kw in text]
            if len(matched) >= rule.min_keywords:
                return DetectionResult(
                    rule=rule,
                    matched_keywords=matched,
                    total_keywords=len(rule.ocr_text),
                )
        return None
