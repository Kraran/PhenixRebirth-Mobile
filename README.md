# Phenix Rebirth

**Version 0.1.0**

A modern, ultra-responsive PC remake of the classic arcade shooter **Phoenix** (1978 / 1980).

Free to play · Open source · MIT License

> **Unofficial fan project.** *Phenix Rebirth* is inspired by the arcade game *Phoenix*.
> It is **not** an official port, sequel, or product of Amstar Electronics, Centuri, Taito,
> or any related rights holder.

---

## Features

- Faithful stage cycle inspired by the arcade original (birds → gargoyles → boss saucer)
- Infinite progression: stages loop with rising speed after each boss
- Smooth 60 / 120 Hz play with delta-time movement
- Keyboard & gamepad (hot-plug)
- Local high scores (top 15)
- 13 languages
- Attract mode (AI demo) + help screen
- Difficulty: Novice / Normal / Veteran

## Requirements

- Python **3.10+** (3.11 / 3.12 / 3.13 recommended)
- [Pygame](https://www.pygame.org/) 2.5+

## Install

```bash
git clone https://github.com/Kraran/PhenixRebirth.git
cd PhenixRebirth
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py
```

**Windows:** double-click `lancer.bat` (installs pygame if needed, then launches the game).

## Controls

| Action | Keyboard | Gamepad |
|--------|----------|---------|
| Move | Arrow keys / WASD | Left stick / D-Pad |
| Fire | Space / Up / W | A (or face buttons) |
| Pause | Esc | Start |
| Menus | Arrows + Enter | Stick / D-Pad + A · B = back |

One player shot on screen at a time (classic Phoenix rule).

## Stages (cycle 1–5, then faster loops)

| Stage | Enemies | Points (Normal) |
|-------|---------|-----------------|
| 1 | Dark birds | 10 |
| 2 | Green / khaki birds | 20 |
| 3 | Gargoyles | 30 (body only) |
| 4 | Violet gargoyles | 40 |
| 5 | Boss saucer + escort birds | Core 200 · cells 1 · decorations 50 |

Veteran: bird scores +10, boss core 300.  
Bonus lives at **1 337** and **8 086** points.

## Options

Persisted in `settings.json` (created at runtime, not shipped):

- Input mode, display (window / fullscreen / borderless)
- SFX & music volume
- Language
- FPS counter
- Reset high scores

## Project layout

```
PhenixRebirth/
├── main.py              # Entry point
├── lancer.bat           # Windows launcher
├── requirements.txt
├── LICENSE              # MIT
├── README.md
├── src/                 # Game code
│   ├── game.py          # Main loop, menus, combat
│   ├── player.py
│   ├── enemy.py
│   ├── boss.py
│   ├── starfield.py
│   ├── explosion.py
│   ├── sounds.py
│   ├── i18n.py
│   ├── highscores.py
│   └── settings.py
└── assets/
    ├── sprites/
    ├── logo/
    ├── sounds/
    └── music/
```

## Credits

**Development**  
Franck Fornasari (Kraran)

**Technical assistance & design**  
Grok — xAI

**Original game (inspiration only)**  
*Phoenix* (1978 / 1980) — Amstar Electronics / Centuri / Taito  

This repository contains **original code and newly created assets**. It does **not** include the original arcade ROM, board data, or copyrighted arcade graphics/audio from *Phoenix*. Gameplay structure is an homage; names and branding here (*Phenix Rebirth*) are distinct.

**Music**  
- Phenix — Eternal Dawn  
- Phenix — Eternal Dawn (Game Over)  

Generated with [Suno](https://suno.com/). Redistribution and commercial use of these tracks must comply with **Suno’s terms** for the account that created them. The MIT license on this repository covers the game code and non-Suno assets; it does **not** override Suno’s rules for the MP3 files under `assets/music/`.

**Visual assets**  
Player ship, enemies, boss, logo animation, starfield planets/nebulae, and UI art were created or adapted for this project (including AI-assisted generation). They are not rips from the original arcade game.

**Technology**  
Python 3 · Pygame 2 · SDL_mixer

## License

- **Code & original project assets** (except as noted below): [MIT License](LICENSE)  
- **Music (`assets/music/`)** : subject to [Suno Terms of Service](https://suno.com/terms) in addition to any rights you hold as the generator  
- **Arcade *Phoenix*** : trademark/copyright of their respective owners; no claim of ownership or endorsement

If you are a rights holder and believe something here infringes, open an issue and we will address it promptly.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned improvements (144 Hz, scanlines, packaging, etc.).

## Contributing

Issues and pull requests are welcome. Please keep changes focused and test **keyboard + gamepad** when touching input or menus.

Use the issue templates under `.github/ISSUE_TEMPLATE/` when reporting bugs or proposing features.
