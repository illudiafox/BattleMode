"""Window-aware capture — Browser mode and OBS mode.

Uses CGWindowListCopyWindowInfo (Quartz) on macOS — no accessibility
permissions required, lists all apps including Firefox/Chrome.
Falls back to wmctrl on Linux.
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
    window_id: Optional[str] = None


def list_windows() -> list[WindowInfo]:
    system = platform.system()
    if system == "Darwin":
        return _list_windows_macos()
    elif system == "Linux":
        return _list_windows_linux()
    return []


# ------------------------------------------------------------------ #
#  macOS — Quartz CGWindowListCopyWindowInfo                           #
# ------------------------------------------------------------------ #

def _list_windows_macos() -> list[WindowInfo]:
    try:
        import Quartz
        raw = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        # Get our own PID so we can exclude BattleMode's window
        import os
        own_pid = os.getpid()

        windows: list[WindowInfo] = []
        for w in raw:
            owner = w.get("kCGWindowOwnerName", "") or ""
            name = w.get("kCGWindowName", "") or ""
            layer = w.get("kCGWindowLayer", 0)
            bounds = w.get("kCGWindowBounds", {})
            pid = w.get("kCGWindowOwnerPID", -1)

            # Skip menu bar, dock, overlays
            if layer != 0:
                continue
            # Skip our own process
            if pid == own_pid:
                continue

            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
            if width < 200 or height < 150:
                continue

            title = f"{owner} — {name}" if name else owner
            if not title.strip():
                continue

            windows.append(WindowInfo(
                title=title,
                x=int(bounds.get("X", 0)),
                y=int(bounds.get("Y", 0)),
                width=width,
                height=height,
                window_id=str(w.get("kCGWindowNumber", "")),
            ))

        # Sort by owner name for readability
        windows.sort(key=lambda w: w.title.lower())
        return windows

    except ImportError:
        return _list_windows_macos_applescript()


def _list_windows_macos_applescript() -> list[WindowInfo]:
    """Fallback if pyobjc-framework-Quartz is not installed."""
    SEP = "\x1c"   # ASCII file separator — safe delimiter
    ROW = "\x1d"   # ASCII group separator

    script = f"""
    tell application "System Events"
        set winList to ""
        repeat with proc in (every process whose visible is true)
            set procName to name of proc
            repeat with win in (every window of proc)
                try
                    set winTitle to title of win
                    set winPos to position of win
                    set winSize to size of win
                    set winList to winList & procName & "{SEP}" & winTitle & "{SEP}" & ¬
                        (item 1 of winPos as text) & "{SEP}" & ¬
                        (item 2 of winPos as text) & "{SEP}" & ¬
                        (item 1 of winSize as text) & "{SEP}" & ¬
                        (item 2 of winSize as text) & "{ROW}"
                end try
            end repeat
        end repeat
        return winList
    end tell
    """
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=8)
        windows = []
        for row in result.stdout.split(ROW):
            row = row.strip()
            if not row:
                continue
            parts = row.split(SEP)
            if len(parts) < 6:
                continue
            try:
                w = int(parts[4])
                h = int(parts[5])
                if w < 200 or h < 150:
                    continue
                windows.append(WindowInfo(
                    title=f"{parts[0]} — {parts[1]}" if parts[1] else parts[0],
                    x=int(parts[2]), y=int(parts[3]),
                    width=w, height=h,
                ))
            except (ValueError, IndexError):
                continue
        return windows
    except Exception:
        return []


# ------------------------------------------------------------------ #
#  Linux — wmctrl                                                      #
# ------------------------------------------------------------------ #

def _list_windows_linux() -> list[WindowInfo]:
    try:
        result = subprocess.run(["wmctrl", "-lG"],
                                capture_output=True, text=True, timeout=5)
        windows = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 8)
            if len(parts) < 8:
                continue
            try:
                w = int(parts[4])
                h = int(parts[5])
                if w < 200 or h < 150:
                    continue
                windows.append(WindowInfo(
                    title=parts[8] if len(parts) > 8 else "(untitled)",
                    x=int(parts[2]), y=int(parts[3]),
                    width=w, height=h,
                    window_id=parts[0],
                ))
            except (ValueError, IndexError):
                continue
        return windows
    except FileNotFoundError:
        return []


# ------------------------------------------------------------------ #
#  Capture                                                             #
# ------------------------------------------------------------------ #

class WindowCapture:
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
        return np.array(raw)[:, :, :3]

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "WindowCapture":
        return self

    def __exit__(self, *_) -> None:
        self.close()
