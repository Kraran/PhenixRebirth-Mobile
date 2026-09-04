"""Chemins écrivables + profil runtime (desktop / Android / pygbag).

Ne pas importer pygame ici : ce module est chargé très tôt par settings.py.
"""
import os
import sys


def is_android():
    return (
        "ANDROID_ARGUMENT" in os.environ
        or "ANDROID_PRIVATE" in os.environ
        or "ANDROID_APP_PATH" in os.environ
        or sys.platform == "android"
        or hasattr(sys, "getandroidapilevel")
    )


def is_web():
    return sys.platform in ("emscripten", "wasm") or "pygbag" in sys.modules


def is_mobile_runtime():
    return is_android() or is_web()


def prefer_60hz():
    """Téléphone / WASM : on lock 60 jusqu'à preuve du contraire."""
    return is_mobile_runtime()


def mixer_buffer():
    return 512 if is_mobile_runtime() else 512  # mobile fork: latence basse partout


def apply_sdl_mobile_hints():
    """À appeler AVANT pygame.init()."""
    os.environ.setdefault("SDL_HINT_ORIENTATIONS", "LandscapeLeft LandscapeRight")
    os.environ.setdefault("SDL_ANDROID_TRAP_BACK_BUTTON", "1")


def writable_dir(fallback):
    """Dossier settings.json / highscores.json. Créé si besoin."""
    path = None
    if is_android():
        for key in ("ANDROID_APP_PATH", "ANDROID_PRIVATE", "ANDROID_ARGUMENT"):
            raw = os.environ.get(key)
            if raw:
                path = raw if os.path.isdir(raw) else os.path.dirname(raw)
                break
        if not path:
            home = os.path.expanduser("~")
            path = os.path.join(home, "phenix_rebirth")
    elif is_web():
        path = "/data"
    elif getattr(sys, "frozen", False):
        path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        path = fallback

    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except Exception:
        path = fallback
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    return path
