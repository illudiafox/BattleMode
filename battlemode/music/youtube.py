"""YouTube audio download via yt-dlp."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent.parent / ".cache" / "yt"


def download_audio(url: str, output_dir: Optional[Path] = None, title: Optional[str] = None) -> Path:
    """Download audio from a YouTube URL using yt-dlp.

    Args:
        url: YouTube video/playlist URL.
        output_dir: Directory to save the file. Defaults to .cache/yt/.
        title: Override filename (without extension).

    Returns:
        Path to the downloaded audio file.
    """
    out_dir = output_dir or CACHE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    template = str(out_dir / (f"{title}.%(ext)s" if title else "%(title)s.%(ext)s"))

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--output", template,
        "--no-playlist",
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

    # Find what was actually written
    # yt-dlp prints "Destination: <path>" in stdout
    for line in result.stdout.splitlines():
        if line.startswith("[ExtractAudio] Destination:"):
            return Path(line.split("Destination:", 1)[1].strip())

    # Fallback: search for the newest mp3 in the output dir
    mp3s = sorted(out_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if mp3s:
        return mp3s[0]

    raise FileNotFoundError(f"yt-dlp ran successfully but output file not found in {out_dir}")


def is_youtube_url(text: str) -> bool:
    pattern = r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/"
    return bool(re.match(pattern, text.strip()))
