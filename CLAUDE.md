# BattleMode — Project Scope

BattleMode is a music automation system for livestreamers. It captures a game window (via OBS or capture card), uses computer vision and OCR to detect the current game state, and automatically switches music playlists to match the gameplay context.

## Machines

| Name | OS | Hardware | Role |
|------|-----|---------|------|
| **DEFIANT** | macOS (Apple Silicon) | MacBook Air M4 | Primary dev machine, VSCode |
| **DREAMWEAVER** | Debian 13 Linux, KDE Plasma | Intel Core i7-10700K | Home machine, live testing |

Dev happens on DEFIANT. During development, testing uses VODs from Twitch/YouTube. Live testing (real capture card) happens on DREAMWEAVER.

## Game States → Music Categories

| Detected State | Music Category |
|---------------|---------------|
| Menu / Title screen | `menu` |
| Pokemon selection screen | `selection` |
| Active battle | `battle` |
| Win or Loss screen | `win_loss` |

## Music Sources

- Local files: `.mp3` (primary), video game formats (future — NSF, VGM, etc.)
- YouTube: URLs downloaded via `yt-dlp`
- Playlist controls: play, pause, skip, shuffle, repeat (per-phase), volume

## Profiles

Game detection logic is stored in profiles (JSON). Each profile defines:
- Visual/OCR patterns for each game state
- Which music categories are active
- Repeat and transition behavior

**Initial profile:** `pokemon_champions`
**Future:** Trainable profiles for other games

## Tech Stack

- **Language:** Python 3.11+
- **Screen capture:** OpenCV + mss (cross-platform)
- **OCR:** pytesseract (Tesseract backend)
- **Audio playback:** python-vlc (supports mp3, broad codec support)
- **YouTube:** yt-dlp
- **UI:** PyQt6
- **Config/Profiles:** JSON + pydantic

## Project Structure

```
BattleMode/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── battlemode/
│   ├── main.py              # Entry point
│   ├── capture/             # Screen capture
│   ├── vision/              # Game state detection (CV + OCR)
│   ├── music/               # Player and playlist management
│   ├── profiles/            # Profile loading/saving
│   └── ui/                  # PyQt6 GUI
├── profiles/
│   └── pokemon_champions.json
└── music/                   # Local music library (gitignored)
    ├── menu/
    ├── selection/
    ├── battle/
    └── win_loss/
```

## Cross-Platform Notes

- Use `pathlib.Path` everywhere — no hardcoded `/` or `\` paths
- Screen capture: `mss` works on both macOS and Linux
- Audio: VLC is available on both platforms
- Avoid macOS-only or Linux-only APIs unless wrapped in platform checks
