"""Central logging setup for BattleMode.

Log file: logs/battlemode.log (rotating, max 2MB × 3 files)
Console:  WARNING and above only
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "battlemode.log"


def setup(level: int = logging.DEBUG) -> None:
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("battlemode")
    if root.handlers:
        return  # already configured

    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file — catches everything
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console — warnings+ only so the terminal isn't noisy
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def get(name: str) -> logging.Logger:
    """Return a child logger: battlemode.<name>"""
    return logging.getLogger(f"battlemode.{name}")
