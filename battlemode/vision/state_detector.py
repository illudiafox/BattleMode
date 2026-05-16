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

# Module-level cache: path → grayscale numpy array.
# Loaded once per session; call invalidate_template_cache() when a template is replaced.
_template_cache: dict[str, np.ndarray] = {}


def invalidate_template_cache(path: str | None = None) -> None:
    """Remove one or all entries from the template image cache."""
    if path:
        _template_cache.pop(path, None)
    else:
        _template_cache.clear()


def _load_template_image(path: str) -> np.ndarray | None:
    if path in _template_cache:
        return _template_cache[path]
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        _template_cache[path] = img
    return img


@dataclass
class DetectionResult:
    """Everything known about a single detection event."""
    rule: DetectionRule
    matched_keywords: list[str]
    total_keywords: int
    template_matched: bool = False
    template_confidence: float = 0.0
    matched_template: str = ""   # path of the template that scored highest

    @property
    def state(self) -> GameState:
        return self.rule.state

    @property
    def trigger_delay(self) -> float:
        return self.rule.trigger_delay

    def summary(self) -> str:
        """Human-readable one-liner for logs and UI."""
        parts = [self.state.value.upper()]
        if self.matched_keywords:
            parts.append(
                f"[{len(self.matched_keywords)}/{self.total_keywords} keywords: "
                f"{', '.join(self.matched_keywords)}]"
            )
        if self.template_matched:
            parts.append(f"[template {self.template_confidence:.2f}]")
        return "  ".join(parts)


def _preprocess_for_ocr(frame: np.ndarray) -> Image.Image:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = 2
    gray = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                      interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary)


def _match_template(frame: np.ndarray, template_path: str, threshold: float) -> tuple[bool, float]:
    """Return (matched, confidence) using normalised cross-correlation."""
    from pathlib import Path as _Path
    template = _load_template_image(template_path)
    if template is None:
        log.warning("Template image not found: %s", template_path)
        return False, 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    th, tw = template.shape[:2]
    fh, fw = gray.shape[:2]
    if th > fh or tw > fw:
        log.warning(
            "Template '%s' (%dx%d) is larger than the capture frame (%dx%d). "
            "Recapture the template with the correct source selected.",
            _Path(template_path).name, tw, th, fw, fh,
        )
        return False, 0.0
    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    matched = max_val >= threshold
    log.debug(
        "Template '%s': conf=%.3f  threshold=%.2f → %s",
        _Path(template_path).name, max_val, threshold,
        "MATCH" if matched else "miss",
    )
    return matched, float(max_val)


def _extract_text(frame: np.ndarray, region: Optional[tuple[int, int, int, int]] = None) -> str:
    if region:
        x, y, w, h = region
        frame = frame[y : y + h, x : x + w]
    img = _preprocess_for_ocr(frame)
    # PSM 7 (single text line) is much faster for small region crops
    psm = 7 if region else 6
    try:
        text = pytesseract.image_to_string(img, config=f"--psm {psm} --oem 1")
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

    def detect_result(
        self,
        frame: np.ndarray,
        filter_states: set[GameState] | None = None,
    ) -> DetectionResult | None:
        """Return a full DetectionResult (rule + matched keywords) or None.

        filter_states: when provided (streamline mode), only rules whose target
        state is in this set are evaluated.  OCR results are cached by region
        key so each unique region is processed once per call.
        """
        log.debug("Running detection against %d rules", len(self._rules))
        ocr_cache: dict[tuple | None, str] = {}
        for rule in self._rules:
            if filter_states is not None and rule.state not in filter_states:
                continue
            result = self._match_result(frame, rule, ocr_cache)
            if result:
                log.debug("Matched: %s", result.summary())
                return result
        log.debug("No rule matched → UNKNOWN")
        return None

    def _match_result(
        self,
        frame: np.ndarray,
        rule: DetectionRule,
        ocr_cache: dict,
    ) -> DetectionResult | None:
        if not rule.enabled:
            return None

        # --- template check (fast, ~10 ms each) --- #
        # multi_template=True → check all paths, fire on any hit
        # multi_template=False → check only the first path
        paths_to_check = rule.template_paths if rule.multi_template else rule.template_paths[:1]
        tmpl_ok = False
        tmpl_conf = 0.0
        best_tmpl_path = ""
        for tpath in paths_to_check:
            ok, conf = _match_template(frame, tpath, rule.template_threshold)
            if conf > tmpl_conf:
                tmpl_conf = conf
                best_tmpl_path = tpath
            if ok:
                tmpl_ok = True
                break  # no need to check further once one matches

        # --- OCR check (slow, skip if template already matched) ---
        ocr_ok = False
        matched_keywords: list[str] = []
        if rule.ocr_text and not tmpl_ok:
            region_key = rule.ocr_region  # None or (x, y, w, h) — both hashable
            if region_key not in ocr_cache:
                ocr_cache[region_key] = _extract_text(frame, rule.ocr_region)
                log.debug(
                    "OCR (%s): %d chars extracted",
                    f"region {region_key}" if region_key else "full frame",
                    len(ocr_cache[region_key]),
                )
            text = ocr_cache[region_key]
            matched_keywords = [kw for kw in rule.ocr_text if kw in text]
            ocr_ok = len(matched_keywords) >= rule.min_keywords

        has_ocr = bool(rule.ocr_text)
        has_tmpl = bool(rule.template_paths)

        if has_ocr and has_tmpl:
            matched = ocr_ok or tmpl_ok
        elif has_ocr:
            matched = ocr_ok
        elif has_tmpl:
            matched = tmpl_ok
        else:
            matched = False

        if matched:
            return DetectionResult(
                rule=rule,
                matched_keywords=matched_keywords,
                total_keywords=len(rule.ocr_text) if rule.ocr_text else 0,
                template_matched=tmpl_ok,
                template_confidence=tmpl_conf,
                matched_template=best_tmpl_path,
            )
        return None
