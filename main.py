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

# Allow imports from the src/ package (dev) or bundled src (PyInstaller)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _root = sys._MEIPASS
else:
    _root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_root, "src"))
sys.path.insert(0, _root)

from game import Game

if __name__ == "__main__":
    try:
        game = Game()
        game.run()
        sys.exit(0)  # clean exit (no launcher pause)
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
