#!/usr/bin/env python3
"""Phenix Rebirth Mobile 1.2 — GPU SCALED PC + tactile Android."""
import sys
import os
import asyncio

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _root = sys._MEIPASS
else:
    _root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_root, "src"))
sys.path.insert(0, _root)

os.environ.setdefault("SDL_HINT_RENDER_SCALE_QUALITY", "linear")
os.environ.setdefault("SDL_RENDER_VSYNC", "0")
os.environ.setdefault("SDL_HINT_RENDER_VSYNC", "0")

def _boot():
    try:
        from platform_io import apply_sdl_mobile_hints
        apply_sdl_mobile_hints()
    except Exception:
        pass
    from game import Game
    try:
        Game().run()
    finally:
        try:
            from platform_io import leave_app, is_android
            if is_android():
                leave_app()
        except Exception:
            pass

async def _amain():
    _boot()

if __name__ == "__main__":
    try:
        _boot()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
