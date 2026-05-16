"""V4L2 device capture — capture card or OBS virtual camera."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def list_devices() -> list[str]:
    """Return accessible /dev/video* paths, sorted."""
    return sorted(str(p) for p in Path("/dev").glob("video*"))


class DeviceCapture:
    """Read frames from a V4L2 device (Elgato HD60X, OBS virtual cam, etc.)."""

    def __init__(self, device: str = "/dev/video0") -> None:
        self.device = device
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open device {device}")

    def is_open(self) -> bool:
        return self._cap.isOpened()

    def grab(self) -> np.ndarray:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame from {self.device}")
        return frame  # BGR

    def close(self) -> None:
        self._cap.release()

    def __enter__(self) -> "DeviceCapture":
        return self

    def __exit__(self, *_) -> None:
        self.close()
