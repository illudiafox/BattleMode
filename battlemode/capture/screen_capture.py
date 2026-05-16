"""Cross-platform screen capture using mss."""

from __future__ import annotations

from typing import Optional

import mss
import numpy as np


class ScreenCapture:
    """Captures frames from a monitor or a specific screen region."""

    def __init__(self, monitor_index: int = 1) -> None:
        """
        Args:
            monitor_index: mss monitor index (1 = primary, 0 = all monitors combined)
        """
        self.monitor_index = monitor_index
        self._sct = mss.mss()

    def get_monitor_info(self) -> list[dict]:
        return list(self._sct.monitors)

    def grab(self, region: Optional[tuple[int, int, int, int]] = None) -> np.ndarray:
        """Capture a frame.

        Args:
            region: (x, y, width, height) crop within the monitor, or None for full monitor.

        Returns:
            BGR numpy array (OpenCV-compatible).
        """
        monitor = self._sct.monitors[self.monitor_index]

        if region:
            x, y, w, h = region
            capture_region = {
                "left": monitor["left"] + x,
                "top": monitor["top"] + y,
                "width": w,
                "height": h,
            }
        else:
            capture_region = monitor

        raw = self._sct.grab(capture_region)
        # mss returns BGRA — drop alpha, keep BGR for OpenCV
        frame = np.array(raw)[:, :, :3]
        return frame

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *_) -> None:
        self.close()
