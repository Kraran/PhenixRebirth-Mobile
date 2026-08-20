"""
SFX and music manager (SDL_mixer via pygame).

SFX are WAV samples under assets/sounds/.
Music tracks are MP3 under assets/music/ with short cross-fades between
menu theme, game-over theme, and in-game silence.
"""
import pygame
import os

SOUND_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "sounds")
MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")

class SoundManager:
    FADE_MS = 350  # quick crossfade

    def __init__(self):
        self.enabled = False
        self.sounds = {}
        self._electric_channel = None
        self.master_volume = 0.8
        self.music_volume = 0.4
        self._base_volumes = {}
        self._current_music = None  # "menu" | "gameover" | None
        self._fading_out = False
        self._pending_music = None  # track to play after fade-out
        self._fade_timer = 0.0
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            for name, vol in [
                ("shoot", 0.45),
                ("explosion", 0.65),
                ("explosion_big", 0.85),
                ("electric", 0.35),
                ("enemy_shoot", 0.40),
                ("enemy_explosion", 0.55),
                ("1up", 1.0),
            ]:
                self._load(name, f"{name}.wav", vol)
            self.enabled = len(self.sounds) > 0
            self._apply_master()
            self._music_paths = {
                "menu": os.path.join(MUSIC_DIR, "Phenix-EternalDawn.mp3"),
                "gameover": os.path.join(MUSIC_DIR, "Phenix-EternalDawn-Game-Over.mp3"),
            }
        except Exception as e:
            print("Sound disabled:", e)
            self.enabled = False
            self._music_paths = {}

    def _load(self, name, filename, volume=0.55):
        path = os.path.join(SOUND_DIR, filename)
        if os.path.exists(path):
            snd = pygame.mixer.Sound(path)
            self.sounds[name] = snd
            self._base_volumes[name] = volume

    def _apply_master(self):
        for name, snd in self.sounds.items():
            base = self._base_volumes.get(name, 0.5)
            snd.set_volume(base * self.master_volume)

    def set_master_volume(self, vol):
        self.master_volume = max(0.0, min(1.0, vol))
        self._apply_master()

    def set_music_volume(self, vol):
        self.music_volume = max(0.0, min(1.0, vol))
        if not self._fading_out:
            try:
                pygame.mixer.music.set_volume(self.music_volume)
            except Exception:
                pass

    def play(self, name, volume=None):
        if not self.enabled or name not in self.sounds:
            return
        try:
            snd = self.sounds[name]
            if volume is not None:
                base = self._base_volumes.get(name, 0.5)
                snd.set_volume(base * self.master_volume * volume)
            snd.play()
        except Exception:
            pass

    def play_electric(self, active):
        if not self.enabled or "electric" not in self.sounds:
            return
        try:
            ch = self._electric_channel
            if active:
                if ch is None or not ch.get_busy():
                    self._electric_channel = self.sounds["electric"].play(loops=-1)
            else:
                if ch is not None and ch.get_busy():
                    ch.stop()
                    self._electric_channel = None
        except Exception:
            pass

    def play_music(self, key, loops=-1):
        """Request 'menu' or 'gameover'. Crossfades if switching tracks."""
        if key == self._current_music and not self._fading_out:
            return
        if self._fading_out and self._pending_music == key:
            return
        path = self._music_paths.get(key)
        if not path or not os.path.exists(path):
            return

        # Same track already requested after fade
        if self._current_music == key and not self._fading_out:
            return

        # If nothing playing, start immediately with fade-in
        if self._current_music is None and not self._fading_out:
            self._start_track(path, key, loops)
            return

        # Fade out current, then start new
        self._pending_music = key
        self._pending_loops = loops
        if not self._fading_out:
            self._fading_out = True
            self._fade_timer = self.FADE_MS / 1000.0
            try:
                pygame.mixer.music.fadeout(self.FADE_MS)
            except Exception:
                self._finish_fade()

    def stop_music(self):
        """Fade out to silence (e.g. entering gameplay)."""
        if self._current_music is None and not self._fading_out:
            return
        self._pending_music = None  # silence after fade
        if not self._fading_out:
            self._fading_out = True
            self._fade_timer = self.FADE_MS / 1000.0
            try:
                pygame.mixer.music.fadeout(self.FADE_MS)
            except Exception:
                self._finish_fade()

    def _start_track(self, path, key, loops=-1):
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(0.0)
            pygame.mixer.music.play(loops, fade_ms=self.FADE_MS)
            # Ramp to target volume (pygame fade_ms fades from 0)
            pygame.mixer.music.set_volume(self.music_volume)
            self._current_music = key
            self._fading_out = False
            self._pending_music = None
        except Exception as e:
            print("Music play failed:", e)
            self._current_music = None
            self._fading_out = False

    def _finish_fade(self):
        self._fading_out = False
        self._current_music = None
        pending = self._pending_music
        loops = getattr(self, "_pending_loops", -1)
        self._pending_music = None
        if pending:
            path = self._music_paths.get(pending)
            if path and os.path.exists(path):
                self._start_track(path, pending, loops)

    def update(self, dt):
        """Call each frame to complete fade transitions."""
        if not self._fading_out:
            return
        self._fade_timer -= dt
        # pygame fadeout is async; when timer done, start next or clear
        if self._fade_timer <= 0:
            try:
                if not pygame.mixer.music.get_busy():
                    self._finish_fade()
                else:
                    # force finish if still busy after fade window
                    pygame.mixer.music.stop()
                    self._finish_fade()
            except Exception:
                self._finish_fade()
