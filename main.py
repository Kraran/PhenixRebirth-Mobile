#!/usr/bin/env python3
"""Phenix Rebirth Mobile — PC + pygbag."""
import sys
import os
import asyncio

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _root = sys._MEIPASS
else:
    _root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_root, "src"))
sys.path.insert(0, _root)


async def main():
    print("[Phenix] main() platform=", sys.platform, flush=True)
    web = sys.platform in ("emscripten", "wasm") or hasattr(sys, "_emscripten_info")
    if web:
        for _ in range(8):
            await asyncio.sleep(0)
    from game import Game
    game = None
    last = None
    for attempt in range(3):
        try:
            game = Game()
            break
        except Exception as e:
            last = e
            print("[Phenix] boot", attempt + 1, e, flush=True)
            if not web:
                raise
            await asyncio.sleep(0.15)
    if game is None:
        raise last
    print("[Phenix] Game() ok", flush=True)
    await game.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        if sys.platform not in ("emscripten", "wasm"):
            sys.exit(1)
