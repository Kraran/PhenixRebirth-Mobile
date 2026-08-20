#!/usr/bin/env python3
"""
Phenix Rebirth — entry point.

Modern remake of the classic arcade shooter Phoenix (1978/1980).
Free to play, open source.

Run:
    python main.py
    or double-click lancer.bat on Windows
"""

import sys
import os

# Allow imports from the src/ package next to this file
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from game import Game

if __name__ == "__main__":
    try:
        game = Game()
        game.run()
        sys.exit(0)  # clean exit (no launcher pause)
    except SystemExit:
        raise
    except Exception:
        # Surface the traceback for bug reports, then non-zero exit
        import traceback
        traceback.print_exc()
        sys.exit(1)
