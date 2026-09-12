"""Runtime desktop / Android."""
import os
import sys

def is_android():
    return (
        "ANDROID_ARGUMENT" in os.environ
        or "ANDROID_PRIVATE" in os.environ
        or hasattr(sys, "getandroidapilevel")
        or sys.platform == "android"
    )

def is_web():
    return sys.platform in ("emscripten", "wasm")

def is_mobile_runtime():
    return is_android() or is_web()

def apply_sdl_mobile_hints():
    """Avant pygame.init() — pas de opengles2 (blit CPU + GLES = 5 fps)."""
    os.environ.setdefault("SDL_HINT_ORIENTATIONS", "LandscapeLeft LandscapeRight")
    os.environ.setdefault("SDL_ANDROID_TRAP_BACK_BUTTON", "1")
    os.environ.setdefault("SDL_HINT_RENDER_SCALE_QUALITY", "linear")
    os.environ.setdefault("SDL_RENDER_VSYNC", "0")
    os.environ.setdefault("SDL_HINT_RENDER_VSYNC", "0")

def writable_dir(fallback):
    path = fallback
    if is_android():
        for key in ("ANDROID_APP_PATH", "ANDROID_PRIVATE", "ANDROID_ARGUMENT"):
            raw = os.environ.get(key)
            if raw:
                path = raw if os.path.isdir(raw) else os.path.dirname(raw)
                break
        else:
            path = os.path.join(os.path.expanduser("~"), "phenix_rebirth")
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".w")
        open(probe, "w").write("ok")
        os.remove(probe)
    except Exception:
        path = fallback
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    return path


def leave_app():
    """Close the Android activity. pygame.quit() alone freezes the window."""
    if not is_android():
        return
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        try:
            act.finishAffinity()
        except Exception:
            act.finish()
    except Exception:
        pass
    os._exit(0)
