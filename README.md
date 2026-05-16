# BattleMode

Automatic music switching for livestreamers, driven by game state detection via computer vision.

Designed for **Pokemon Champions** on Twitch — reads visual cues from your OBS capture window and switches music playlists to match the current game state (menu, selection, battle, win/loss).

## Features

- **Automatic music switching** based on detected game state
- **4 music categories**: menu, selection, battle, win/loss
- **Local music** (mp3) and **YouTube** URL support
- **Full playlist controls**: play, pause, skip, shuffle, repeat per phase
- **Game profiles**: save and load detection settings per game
- **Cross-platform**: macOS and Linux

## Quick Start

```bash
pip install -r requirements.txt
python -m battlemode
```

## Requirements

- Python 3.11+
- Tesseract OCR (`brew install tesseract` / `apt install tesseract-ocr`)
- VLC (`brew install vlc` / `apt install vlc`)

## Development

See [CLAUDE.md](CLAUDE.md) for full project scope and architecture notes.
