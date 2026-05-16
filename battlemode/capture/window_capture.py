"""Window-aware capture — Browser mode and OBS mode.

Browser mode: enumerate visible windows, let user pick one, capture its bounds.
OBS mode:     capture the OBS virtual camera or a named window (e.g. "OBS Studio").

Uses platform-appropriate APIs wrapped behind a common interface.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import Optional

import mss
import numpy as np


@dataclass
class WindowInfo:
    title: str
    x: int
    y: int
    width: int
    height: int
    window_id: Optional[str] = None   # platform-specific handle


def list_windows() -> list[WindowInfo]:
    """Return all visible, named windows on the current platform."""
    system = platform.system()
    if system == "Darwin":
        return _list_windows_macos()
    elif system == "Linux":
        return _list_windows_linux()
    else:
        return []


# ------------------------------------------------------------------ #
#  macOS — uses AppleScript via osascript                              #
# ------------------------------------------------------------------ #

def _list_windows_macos() -> list[WindowInfo]:
    script = """
    tell application "System Events"
        set winList to {}
        repeat with proc in (every process whose visible is true)
            set procName to name of proc
            repeat with win in (every window of proc)
                set winTitle to title of win
                set winPos to position of win
                set winSize to size of win
                set end of winList to (procName & "|" & winTitle & "|" & ¬
                    (item 1 of winPos as text) & "|" & ¬
                    (item 2 of winPos as text) & "|" & ¬
                    (item 1 of winSize as text) & "|" & ¬
                    (item 2 of winSize as text))
            end repeat
        end repeat
        return winList
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        windows = []
        for line in result.stdout.strip().split(", "):
            line = line.strip()
            if not line or line.count("|") < 5:
                continue
            parts = line.split("|")
            try:
                windows.append(WindowInfo(
                    title=f"{parts[0]} — {parts[1]}",
                    x=int(parts[2]),
                    y=int(parts[3]),
                    width=int(parts[4]),
                    height=int(parts[5]),
                ))
            except (ValueError, IndexError):
                continue
        return windows
    except Exception:
        return []


# ------------------------------------------------------------------ #
#  Linux — uses wmctrl                                                 #
# ------------------------------------------------------------------ #

def _list_windows_linux() -> list[WindowInfo]:
    try:
        result = subprocess.run(
            ["wmctrl", "-lG"],
            capture_output=True, text=True, timeout=5
        )
        windows = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 8)
            if len(parts) < 8:
                continue
            try:
                windows.append(WindowInfo(
                    title=parts[8] if len(parts) > 8 else "(untitled)",
                    x=int(parts[2]),
                    y=int(parts[3]),
                    width=int(parts[4]),
                    height=int(parts[5]),
                    window_id=parts[0],
                ))
            except (ValueError, IndexError):
                continue
        return windows
    except FileNotFoundError:
        # wmctrl not installed
        return []


# ------------------------------------------------------------------ #
#  Capture from a WindowInfo                                           #
# ------------------------------------------------------------------ #

class WindowCapture:
    """
    Captures frames from a specific window region.

    In Browser mode: user picks a browser window — we capture its screen bounds.
    In OBS mode: user picks the OBS window (or a projector) — same mechanism.

    The capture is screen-coordinate based (mss), so it works for any window
    regardless of application. No special OBS integration needed for now.
    """

    def __init__(self, window: WindowInfo) -> None:
        self.window = window
        self._sct = mss.mss()

    def grab(self) -> np.ndarray:
        region = {
            "left": self.window.x,
            "top": self.window.y,
            "width": self.window.width,
            "height": self.window.height,
        }
        raw = self._sct.grab(region)
        return np.array(raw)[:, :, :3]   # BGRA → BGR

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "WindowCapture":
        return self

    def __exit__(self, *_) -> None:
        self.close()
