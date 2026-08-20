"""
Phenix Rebirth — main game controller.

Owns the window, fixed-timestep loop, menus, combat, stage progression,
pause/options, high scores, attract-mode help, and credits.

Architecture notes:
- Logical resolution BASE_WIDTH x BASE_HEIGHT (see settings.py); scaled to display.
- State flags: started, game_over, paused, stage_transition, menu_screen, hs_phase.
- Stages cycle content 1–5 forever with rising speed (stage_speed_mult).
- Cheats typed on the menu high-score screen: LVL2–LVL5, LIVE (disables HS entry).

This file is intentionally large; split only if a future refactor needs it.
"""
import pygame
import math
import sys
import random
import os
import json
from settings import *
from settings import stage_content, stage_speed_mult
from player import Player
from enemy import EnemyFormation, BigBird, Enemy
from boss import BossSaucer
from explosion import Explosion
from starfield import Starfield
from sounds import SoundManager
from i18n import set_lang, get_lang, t, t_help, t_list, get_credits_lines, LANGS, LANG_CODES
from highscores import load_highscores, is_highscore, insert_score, reset_highscores

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "settings.json")

def load_user_settings():
    defaults = {
        "input_mode": None,  # None = auto
        "display_mode": "fullscreen",
        "sfx_volume": 0.8,
        "music_volume": 0.4,
        "language": "fr",
        "show_fps": False,
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults.update({k: data[k] for k in defaults if k in data})
    except Exception:
        pass
    return defaults

def save_user_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Could not save settings:", e)

class Game:
    """
    Top-level application object.

    Lifecycle: __init__ (load settings, build systems) → run() event/update/draw loop.
    Soft restart after a run re-enters __init__ while preserving user settings.
    """
    def __init__(self):
        pygame.init()
        
        flags = pygame.DOUBLEBUF | pygame.HWSURFACE
        if VSYNC:
            flags |= pygame.SCALED
            
        self.screen = pygame.display.set_mode((BASE_WIDTH, BASE_HEIGHT), flags)
        self.clock = pygame.time.Clock()
        
        # Detect 60 or 120 Hz after display is up (144 later)
        import settings as _settings
        self.fps_target = detect_refresh_rate()
        _settings.FPS_TARGET = self.fps_target
        pygame.display.set_caption(f"Phenix Rebirth  [{self.fps_target} Hz]")
        
        # Opaque game surface (faster blit than per-pixel alpha default)
        self.game_surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT)).convert()
        
        self.player = Player(BASE_WIDTH // 2, BASE_HEIGHT - 95)
        self.formation = EnemyFormation()
        self.explosions = []
        self.starfield = Starfield()
        
        self.running = True
        self.dt = 0.0
        self.score = 0
        self.game_over = False
        self.started = False
        self.stage = 1
        self.stage_transition = None  # None | "fly_up" | "arrive"
        self.transition_timer = 0.0
        self.boss_saucer = None
        self.boss_bird_timer = 0.0
        self.bosses_defeated = 0
        self.life_flash_timer = 0.0
        self.life_flash_index = -1
        self.life_thresholds = [(1337, False), (8086, False)]
        
        # High score flow: None | "enter" | "table"
        self.hs_phase = None
        self.hs_entries = load_highscores()
        self.hs_name = ["A", "A", "A"]
        self.hs_char_index = 0
        self.hs_submitted = False
        self._hs_joy_cooldown = 0.0
        self.cheat_buffer = ""
        self.cheat_msg_timer = 0.0
        self.cheat_msg = ""
        self.used_cheat = False
        self.paused = False
        self.pause_index = 0  # Reprendre
        self.pause_options = False  # options opened from pause
        self.quit_confirm = False
        self.quit_index = 1  # default Non
        self.menu_idle = 0.0
        self.help_timer = 0.0
        self.help_first_shown = False  # first attract uses longer delay
        self.attract_mode = False
        self.attract_timer = 0.0
        self.next_is_attract = True  # after first help, alternate attract/help
        self.ai_move_smooth = 0.0
        self.ai_dir_locked = 0
        self.ai_dir_timer = 0.0
        self.help_anim_t = 0.0
        # Built after display ready — icons filled in _build_help_icons
        self.help_icons = {}
        self.credits_scroll = 0.0
        
        # Fonts with broad Unicode coverage (Cyrillic, accents, etc.)
        _font_names = "dejavusans,segoe ui,arial,consolas,notosans"
        self.font = pygame.font.SysFont(_font_names, 28, bold=True)
        self.big_font = pygame.font.SysFont(_font_names, 64, bold=True)
        self.medium_font = pygame.font.SysFont(_font_names, 32, bold=True)

        # Animated title logo (frame sequence from LogoPhenix.mp4)
        self.logo_frames = []
        self.logo_timer = 0.0
        self.logo_index = 0
        self.logo_fps = 12.0
        logo_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "logo")
        if os.path.isdir(logo_dir):
            for name in sorted(os.listdir(logo_dir)):
                if name.endswith(".png"):
                    fp = os.path.join(logo_dir, name)
                    try:
                        img = pygame.image.load(fp).convert_alpha()
                        # Fit width ~720 max for menu
                        # Menu-friendly size (~560px wide)
                        max_w = 560
                        if img.get_width() != max_w:
                            scale = max_w / img.get_width()
                            img = pygame.transform.smoothscale(
                                img, (max_w, max(1, int(img.get_height() * scale)))
                            )
                        self.logo_frames.append(img)
                    except Exception:
                        pass

        self.shake_amount = 0.0
        self.title_timer = 0.0
        
        # Mini ship icon for lives display
        ship_full = pygame.image.load(
            os.path.join(os.path.dirname(__file__), "..", "assets", "sprites", "player_ship.png")
        ).convert_alpha()
        mini_h = 22
        scale = mini_h / ship_full.get_height()
        mini_w = max(1, int(ship_full.get_width() * scale))
        self.life_icon = pygame.transform.smoothscale(ship_full, (mini_w, mini_h)).convert_alpha()
        
        # --- Input / menu ---
        pygame.joystick.init()
        self.joystick = None
        self.gamepad_detected = False
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            self.gamepad_detected = True
        
        # Menu state: "main" | "options"
        self.menu_screen = "main"
        self.menu_index = 0
        self.difficulty = "normal"  # novice | normal | veteran — never persisted
        self.DIFFICULTIES = ["novice", "normal", "veteran"]
        self.DIFF_LABELS = {"novice": "Novice", "normal": "Normal", "veteran": "Veteran"}
        
        # Load persistent settings (or keep in-memory on soft restart)
        user = load_user_settings()
        if not hasattr(self, "input_mode"):
            if user["input_mode"] in ("keyboard", "gamepad"):
                self.input_mode = user["input_mode"]
                if self.input_mode == "gamepad" and not self.gamepad_detected:
                    self.input_mode = "keyboard"
            else:
                self.input_mode = "gamepad" if self.gamepad_detected else "keyboard"
        if not hasattr(self, "display_mode"):
            self.display_mode = user.get("display_mode", "fullscreen")
        if not hasattr(self, "sfx_volume"):
            self.sfx_volume = float(user.get("sfx_volume", 0.8))
        if not hasattr(self, "music_volume"):
            self.music_volume = float(user.get("music_volume", 0.4))
        if not hasattr(self, "language"):
            self.language = user.get("language", "fr")
            if self.language not in LANG_CODES:
                self.language = "fr"
            set_lang(self.language)
        if not hasattr(self, "show_fps"):
            self.show_fps = bool(user.get("show_fps", False))  # default off
        
        # Joystick menu navigation cooldown (anti spam)
        self._joy_menu_cooldown = 0.0
        self.input_grace = 0.0
        self._joy_axis_latch_x = 0
        self._joy_axis_latch_y = 0
        
        self.sounds = SoundManager()
        self.sounds.set_master_volume(self.sfx_volume)
        self.sounds.set_music_volume(self.music_volume)
        self._build_help_icons()
        self.player.sounds = self.sounds
        self.formation.sounds = self.sounds
        
        # Apply saved display mode (default fullscreen)
        self.apply_display_mode()

    # --- Audio state machine (menu / game-over / in-game silence) ---
    def _update_music(self):
        """Menu theme, high-score/game-over theme, silence in-game. Fades handled by SoundManager."""
        if self.game_over and self.hs_phase in ("enter", "table"):
            self.sounds.play_music("gameover")
        elif not self.started:
            if self.menu_screen == "highscores":
                self.sounds.play_music("gameover")
            else:
                self.sounds.play_music("menu")  # includes credits
        else:
            self.sounds.stop_music()

    # --- Difficulty & scoring helpers ---

    @staticmethod
    def format_score(n):
        """Thousand-separated score for display (spaces)."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        s = f"{n:,}".replace(",", " ")
        return s

    def _draw_hs_row(self, surface, y, rank, name, score, col, score_right_x=None):
        """Draw one high-score line: rank aligned on '.', score right-aligned."""
        if score_right_x is None:
            score_right_x = BASE_WIDTH // 2 + 160
        # Rank + dot (right-align rank digits against the dot)
        rank_s = f"{rank:>2}"
        dot = "."
        rank_surf = self.font.render(rank_s, True, col)
        dot_surf = self.font.render(dot, True, col)
        # Fixed column for the '.' so all ranks align
        dot_x = BASE_WIDTH // 2 - 120
        surface.blit(rank_surf, (dot_x - rank_surf.get_width(), y))
        surface.blit(dot_surf, (dot_x, y))
        # Name
        name_s = name if name else "---"
        name_surf = self.font.render(f" {name_s}", True, col)
        surface.blit(name_surf, (dot_x + dot_surf.get_width() + 6, y))
        # Score right-aligned (or dashes)
        if score is None:
            sc_s = "—"
        else:
            sc_s = self.format_score(score)
        sc_surf = self.font.render(sc_s, True, col)
        surface.blit(sc_surf, (score_right_x - sc_surf.get_width(), y))

    def difficulty_speed_mult(self):

        if self.difficulty == "novice":
            return 0.8
        if self.difficulty == "veteran":
            return 1.2
        return 1.0

    def _enemy_points(self, content_stage):
        """Points for killing a bird by content stage (1-4)."""
        base = {1: 10, 2: 20, 3: 30, 4: 40}.get(content_stage, 10)
        if self.difficulty == "veteran":
            return base + 10
        return base

    def _boss_points(self):
        return 300 if self.difficulty == "veteran" else 200

    def _apply_difficulty_start(self):
        """Lives and stage 1 setup when pressing JOUER."""
        if self.player.infinite_lives:
            self.player.lives = 99
            self.used_cheat = True
        elif self.difficulty == "novice":
            self.player.lives = 5
            self.used_cheat = False
        else:
            self.player.lives = 3
            self.used_cheat = False
        self.bosses_defeated = 0
        self.life_flash_timer = 0.0
        self.life_flash_index = -1
        self.stage = 1
        self._setup_stage(1)

    def _check_extra_lives(self):

        """Award a life when crossing score thresholds (once each)."""
        for i, (threshold, awarded) in enumerate(self.life_thresholds):
            if not awarded and self.score >= threshold:
                self.life_thresholds[i] = (threshold, True)
                if self.player.alive:
                    self.player.lives += 1
                    self.sounds.play("1up")
                    self.cheat_msg = t("one_up")
                    self.cheat_msg_timer = 4.0
                    self.life_flash_timer = 4.0
                    self.life_flash_index = max(0, self.player.lives - 1)

    # --- Stage setup (content cycle + speed tier) ---
    def _setup_stage(self, stage):
        """Load content for stage (1-5 cycle) with speed scaling + difficulty."""
        content = stage_content(stage)
        mult = stage_speed_mult(stage) * self.difficulty_speed_mult()
        self.formation.enemies = []
        self.formation.bullets = []
        self.boss_saucer = None
        if content == 5:
            self.boss_saucer = BossSaucer()
            # Scale boss descend/shoot lightly with mult
            self.boss_saucer.descend_speed *= mult
            self.boss_saucer.speed *= mult
            self.boss_bird_timer = 1.2
        else:
            self.formation.spawn_stage(content, speed_mult=mult)
            self.formation.sounds = self.sounds

    # --- Cheats (high-score menu keyboard buffer) ---
    def _start_at_stage(self, stage):

        """Cheat: jump straight into a stage from the menu."""
        self.started = True
        self.game_over = False
        self.hs_phase = None
        self.menu_screen = "main"
        self.stage = stage
        self.stage_transition = None
        self.player = Player(BASE_WIDTH // 2, BASE_HEIGHT - 95)
        self.player.sounds = self.sounds
        self.score = 0
        self.explosions = []
        self.life_thresholds = [(1337, False), (8086, False)]
        self.input_grace = 0.4
        self.cheat_buffer = ""
        self.cheat_msg = f"STAGE {stage}"
        self.cheat_msg_timer = 2.0
        self.used_cheat = True
        self.bosses_defeated = max(0, (stage - 1) // 5)
        self._setup_stage(stage)

    # --- High-score entry / table ---
    def _begin_highscore_flow(self):

        self.hs_entries = load_highscores()
        self.hs_submitted = False
        self.hs_name = ["A", "A", "A"]
        self.hs_char_index = 0
        self.shake_amount = 0.0
        self.explosions.clear()  # remove explosion remnants from HS screen
        # Novice / cheat: view table only, no name entry
        if self.difficulty == "novice" or getattr(self, "used_cheat", False):
            self.hs_phase = "table"
        elif is_highscore(self.score, self.hs_entries):
            self.hs_phase = "enter"
        else:
            self.hs_phase = "table"

    def _submit_highscore(self):
        if self.hs_submitted:
            return
        name = "".join(self.hs_name)
        self.hs_entries = insert_score(name, self.score)
        self.hs_submitted = True
        self.hs_phase = "table"

    def _hs_cycle_letter(self, direction):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        cur = self.hs_name[self.hs_char_index]
        idx = alphabet.find(cur)
        if idx < 0:
            idx = 0
        idx = (idx + direction) % len(alphabet)
        self.hs_name[self.hs_char_index] = alphabet[idx]

    def apply_display_mode(self):
        """Switch window / fullscreen / borderless."""
        flags = pygame.DOUBLEBUF | pygame.HWSURFACE
        size = (BASE_WIDTH, BASE_HEIGHT)
        if self.display_mode == "fullscreen":
            flags |= pygame.FULLSCREEN
            if VSYNC:
                flags |= pygame.SCALED
        elif self.display_mode == "borderless":
            flags |= pygame.NOFRAME
            if VSYNC:
                flags |= pygame.SCALED
        else:
            if VSYNC:
                flags |= pygame.SCALED
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(f"Phenix Rebirth  [{self.fps_target} Hz]")
        # Hide cursor in fullscreen / borderless
        pygame.mouse.set_visible(self.display_mode == "window")

    def _poll_gamepad(self):
        """Hot-plug detection while on menus (and soft recovery in-game)."""
        count = pygame.joystick.get_count()
        if count > 0:
            if self.joystick is None:
                try:
                    self.joystick = pygame.joystick.Joystick(0)
                    self.joystick.init()
                    self.gamepad_detected = True
                    # First detection on menus → default to gamepad if still on auto feel
                    if not self.started and not self.game_over:
                        # Newly plugged on menu → switch to gamepad
                        self.input_mode = "gamepad"
                        self.save_settings()
                except Exception:
                    self.joystick = None
                    self.gamepad_detected = False
            else:
                self.gamepad_detected = True
        else:
            self.joystick = None
            if self.gamepad_detected:
                self.gamepad_detected = False
                if self.input_mode == "gamepad":
                    self.input_mode = "keyboard"

    def save_settings(self):

        save_user_settings({
            "input_mode": self.input_mode,
            "display_mode": self.display_mode,
            "sfx_volume": self.sfx_volume,
            "music_volume": self.music_volume,
            "language": self.language,
            "show_fps": self.show_fps,
        })

    # --- Menu navigation ---
    def _menu_nav(self, direction):
        """direction: -1 up, +1 down"""
        if self.menu_screen == "main":
            n = 6  # Jouer, Difficulte, Options, High Scores, Credits, Quitter
        elif self.menu_screen == "reset_confirm":
            n = 2  # Oui, Non
        else:
            n = 8  # Controle, SFX, Music, Affichage, FPS, Language, Reset HS, Retour
        self.menu_index = (self.menu_index + direction) % n

    def _menu_adjust(self, direction):
        """direction: -1 left, +1 right — change current option value"""
        if self.menu_screen == "main":
            if self.menu_index == 1:
                idx = self.DIFFICULTIES.index(self.difficulty)
                self.difficulty = self.DIFFICULTIES[(idx + direction) % len(self.DIFFICULTIES)]
            return
        if self.menu_screen != "options":
            return
        i = self.menu_index
        if i == 0:  # controls
            self.input_mode = "keyboard" if self.input_mode == "gamepad" else "gamepad"
            if self.input_mode == "gamepad" and not self.gamepad_detected:
                self.input_mode = "keyboard"
            self.save_settings()
        elif i == 1:  # SFX volume
            self.sfx_volume = max(0.0, min(1.0, self.sfx_volume + direction * 0.1))
            self.sounds.set_master_volume(self.sfx_volume)
            self.sounds.play("shoot")
            self.save_settings()
        elif i == 2:  # Music volume
            self.music_volume = max(0.0, min(1.0, self.music_volume + direction * 0.1))
            self.sounds.set_music_volume(self.music_volume)
            self.save_settings()
        elif i == 3:  # display
            modes = ["window", "fullscreen", "borderless"]
            idx = modes.index(self.display_mode) if self.display_mode in modes else 0
            self.display_mode = modes[(idx + direction) % len(modes)]
            self.apply_display_mode()
            self.save_settings()
        elif i == 4:  # FPS counter
            self.show_fps = not self.show_fps
            self.save_settings()
        elif i == 5:  # Language
            idx = LANG_CODES.index(self.language) if self.language in LANG_CODES else 0
            self.language = LANG_CODES[(idx + direction) % len(LANG_CODES)]
            set_lang(self.language)
            self.save_settings()


    def _draw_logo(self, surface, center_x, top_y):
        """Draw current animated logo frame centered horizontally."""
        if not self.logo_frames:
            return False
        img = self.logo_frames[self.logo_index % len(self.logo_frames)]
        surface.blit(img, (center_x - img.get_width() // 2, top_y))
        return True

    def _draw_boss_flag(self, surface, x, y, big=False):

        """Victory flag next to stage number. big=True at 10+ bosses."""
        if big:
            pygame.draw.line(surface, (220, 220, 230), (x, y + 28), (x, y), 3)
            pygame.draw.polygon(surface, (220, 40, 50), [
                (x + 2, y), (x + 24, y + 8), (x + 2, y + 16)
            ])
            pygame.draw.polygon(surface, (255, 140, 100), [
                (x + 2, y + 2), (x + 18, y + 8), (x + 2, y + 12)
            ])
            # star mark
            pygame.draw.circle(surface, (255, 220, 80), (x + 8, y + 8), 3)
        else:
            pygame.draw.line(surface, (200, 200, 210), (x, y + 14), (x, y), 2)
            pygame.draw.polygon(surface, (220, 50, 60), [
                (x + 1, y), (x + 12, y + 4), (x + 1, y + 8)
            ])
            pygame.draw.polygon(surface, (255, 120, 100), [
                (x + 1, y + 1), (x + 9, y + 4), (x + 1, y + 6)
            ])

    # --- Help attract-mode icons ---
    def _build_help_icons(self):

        """Sprites for the help screen score table."""
        from enemy import Enemy, BigBird
        e1 = Enemy(0, 0, stage=1)
        e2 = Enemy(0, 0, stage=2)
        g3 = BigBird(0, 0, stage=3)
        g4 = BigBird(0, 0, stage=4)
        self.help_icons = {
            "bird1": e1.image,
            "bird2": e2.image,
            "garg3": g3,
            "garg4": g4,
        }
        core = pygame.Surface((36, 40), pygame.SRCALPHA)
        pygame.draw.ellipse(core, (200, 60, 160), (4, 8, 28, 28))
        pygame.draw.ellipse(core, (120, 20, 90), (8, 16, 20, 16))
        pygame.draw.ellipse(core, (200, 60, 160), (6, 2, 24, 20))
        pygame.draw.circle(core, (255, 240, 80), (13, 10), 3)
        pygame.draw.circle(core, (255, 240, 80), (23, 10), 3)
        self.help_icons["boss"] = core

    def _draw_help_gargoyle(self, surface, bird, x, y, scale=0.55):
        """Draw animated gargoyle icon centered at (x, y)."""
        wing_up = math.sin(self.help_anim_t * 10.0) > 0
        wing_src = bird.wing_up if wing_up else bird.wing_down
        flap_y = -2 if wing_up else 2
        body = pygame.transform.smoothscale(
            bird.body_img,
            (max(8, int(bird.body_img.get_width() * scale)),
             max(8, int(bird.body_img.get_height() * scale)))
        )
        wing = pygame.transform.smoothscale(
            wing_src,
            (max(8, int(wing_src.get_width() * scale)),
             max(8, int(wing_src.get_height() * scale)))
        )
        bw, bh = body.get_size()
        ww, wh = wing.get_size()
        surface.blit(wing, (int(x - ww - bw * 0.15), int(y - wh * 0.3 + flap_y)))
        surface.blit(pygame.transform.flip(wing, True, False),
                     (int(x + bw * 0.15), int(y - wh * 0.3 + flap_y)))
        surface.blit(body, (int(x - bw / 2), int(y - bh / 2)))



    def _attract_ai(self):
        """Reactive pilot with smoothed steering (avoids left/right jitter)."""
        px, py = self.player.x, self.player.y
        shoot = False

        danger_l = 0.0
        danger_r = 0.0

        def add_threat(bx, by, weight=1.0):
            nonlocal danger_l, danger_r
            if by < py - 520 or by > py + 30:
                return
            dx = bx - px
            if abs(dx) > 140:
                return
            dist_y = max(40.0, abs(by - py))
            w = weight * (220.0 / dist_y)
            if dx < -12:
                danger_l += w
            elif dx > 12:
                danger_r += w
            else:
                # Head-on: pick side with more room
                if px < BASE_WIDTH * 0.5:
                    danger_l += w * 0.8
                else:
                    danger_r += w * 0.8

        for b in getattr(self.formation, "bullets", []) or []:
            if isinstance(b, (list, tuple)):
                add_threat(b[0], b[1], 1.3)
            elif getattr(b, "alive", True):
                add_threat(getattr(b, "x", 0), getattr(b, "y", 0), 1.3)

        if self.boss_saucer is not None:
            for b in getattr(self.boss_saucer, "bullets", []) or []:
                if isinstance(b, (list, tuple)):
                    add_threat(b[0], b[1], 1.5)
                elif getattr(b, "alive", True):
                    add_threat(getattr(b, "x", 0), getattr(b, "y", 0), 1.5)

        # Desired aim X
        aim_x = None
        best = 1e9
        for e in getattr(self.formation, "enemies", []) or []:
            if not getattr(e, "alive", True):
                continue
            ex = getattr(e, "x", 0)
            ey = getattr(e, "y", 0)
            if ey > py - 40:
                if ex < px:
                    danger_l += 2.0
                else:
                    danger_r += 2.0
            d = abs(ex - px) + abs(ey - py) * 0.2
            if d < best:
                best = d
                aim_x = ex

        if self.boss_saucer is not None and not getattr(self.boss_saucer, "dead", False):
            core = getattr(self.boss_saucer, "core", None)
            if core is not None and getattr(core, "alive", True):
                aim_x = getattr(core, "x", self.boss_saucer.x)
            else:
                cells = [c for c in (getattr(self.boss_saucer, "cells", []) or []) if getattr(c, "alive", True)]
                if cells:
                    cells.sort(key=lambda c: abs(c.x - px))
                    aim_x = cells[0].x

        # Desired continuous steering in [-1, 1]
        desired = 0.0
        threat = danger_r - danger_l  # positive → dodge left
        if abs(threat) > 0.35:
            desired = -1.0 if threat > 0 else 1.0
        elif aim_x is not None:
            err = aim_x - px
            # Proportional aim, deadzone to stop micro-jitter
            if abs(err) > 18:
                desired = max(-1.0, min(1.0, err / 90.0))
            else:
                desired = 0.0

        # Edge soft push
        if px < 100:
            desired = max(desired, (100 - px) / 80.0)
        elif px > BASE_WIDTH - 100:
            desired = min(desired, -(px - (BASE_WIDTH - 100)) / 80.0)

        # Low-pass filter on steering (frame-rate independent-ish)
        # Higher alpha = more responsive; lower = smoother
        alpha = min(1.0, 4.5 * self.dt)
        self.ai_move_smooth += (desired - self.ai_move_smooth) * alpha

        # Hold direction at least ~0.12s when committed (hysteresis)
        self.ai_dir_timer = max(0.0, self.ai_dir_timer - self.dt)
        raw = self.ai_move_smooth
        if abs(raw) < 0.22:
            discrete = 0
        elif raw > 0:
            discrete = 1
        else:
            discrete = -1

        if discrete != 0 and discrete != self.ai_dir_locked:
            if self.ai_dir_timer <= 0:
                self.ai_dir_locked = discrete
                self.ai_dir_timer = 0.14
            else:
                discrete = self.ai_dir_locked
        elif discrete == 0 and abs(raw) < 0.12:
            self.ai_dir_locked = 0

        move = self.ai_dir_locked if self.ai_dir_timer > 0 and self.ai_dir_locked != 0 else discrete

        # Fire when stable and aligned
        if self.player.bullet is None and aim_x is not None:
            if abs(aim_x - px) < 40 and abs(self.ai_move_smooth) < 0.55:
                shoot = True

        return move, shoot


    def _start_attract(self):
        """Demo play — random stage 1–5, 30s, no high score."""
        self.attract_mode = True
        self.attract_timer = 30.0
        self.started = True
        self.game_over = False
        self.paused = False
        self.quit_confirm = False
        self.hs_phase = None
        self.stage_transition = None
        self.menu_screen = "main"
        self.stage = random.randint(1, 5)
        self.score = 0
        self.explosions = []
        self.life_thresholds = [(1337, False), (8086, False)]
        self.bosses_defeated = max(0, (self.stage - 1) // 5)
        self.used_cheat = True  # never write high score
        self.player = Player(BASE_WIDTH // 2, BASE_HEIGHT - 95)
        self.player.sounds = self.sounds
        self.player.lives = 5
        self.input_grace = 0.25
        self.shake_amount = 0.0
        self._setup_stage(self.stage)
        self.sounds.stop_music()
        self.cheat_msg = ""
        self.cheat_msg_timer = 0.0
        self.ai_move_smooth = 0.0
        self.ai_dir_locked = 0
        self.ai_dir_timer = 0.0

    def _end_attract(self):
        """Return to main menu from attract mode."""
        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
                 self.fps_target, self.show_fps, self.difficulty, self.language)
        first = self.help_first_shown
        nxt = self.next_is_attract
        self.__init__()
        (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
         self.fps_target, self.show_fps, self.difficulty, self.language) = saved
        set_lang(self.language)
        self.sounds.set_music_volume(self.music_volume)
        self.sounds.set_master_volume(self.sfx_volume)
        self.apply_display_mode()
        self.help_first_shown = first
        self.next_is_attract = nxt
        self.attract_mode = False
        self.started = False
        self.menu_idle = 0.0

    def _reset_menu_idle(self):
        self.menu_idle = 0.0
        if self.menu_screen == "help":
            self.menu_screen = "main"
            self.menu_index = 0
            self.help_timer = 0.0

    # --- Pause / quit-to-menu / app quit confirm ---
    def _toggle_pause(self):

        if not self.started or self.game_over or self.stage_transition is not None:
            return
        self.paused = not self.paused
        self.pause_index = 0
        self.pause_options = False
        if self.paused:
            self.sounds.play_electric(False)

    def _quit_to_menu(self):
        """Leave current run, return to main menu (keep settings)."""
        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
                 self.fps_target, self.show_fps, self.difficulty, self.language)
        inf = getattr(self.player, "infinite_lives", False)
        self.__init__()
        (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
         self.fps_target, self.show_fps, self.difficulty, self.language) = saved
        set_lang(self.language)
        self.sounds.set_music_volume(self.music_volume)
        self.sounds.set_master_volume(self.sfx_volume)
        self.apply_display_mode()
        self.paused = False
        self.quit_confirm = False
        self.player.infinite_lives = False

    def _menu_back(self):

        """B / Esc — return to previous menu screen."""
        if self.menu_screen == "main":
            return
        if self.menu_screen == "reset_confirm":
            self.menu_screen = "options"
            self.menu_index = 6  # Reset High Scores line
        elif self.menu_screen == "options":
            self.menu_screen = "main"
            self.menu_index = 2  # OPTIONS
        elif self.menu_screen == "highscores":
            self.menu_screen = "main"
            self.menu_index = 3
        elif self.menu_screen == "credits":
            self.menu_screen = "main"
            self.menu_index = 4
        else:
            self.menu_screen = "main"
            self.menu_index = 0

    def _menu_confirm(self):

        if self.menu_screen == "main":
            if self.menu_index == 0:
                self._apply_difficulty_start()
                self.started = True
                self.input_grace = 0.35
            elif self.menu_index == 1:
                # Cycle difficulty on confirm too
                idx = self.DIFFICULTIES.index(self.difficulty)
                self.difficulty = self.DIFFICULTIES[(idx + 1) % len(self.DIFFICULTIES)]
            elif self.menu_index == 2:
                self.menu_screen = "options"
                self.menu_index = 0
            elif self.menu_index == 3:
                self.hs_entries = load_highscores()
                self.menu_screen = "highscores"
                self.menu_index = 0
            elif self.menu_index == 4:
                self.menu_screen = "credits"
                self.credits_scroll = float(BASE_HEIGHT)
                self.menu_index = 0
            elif self.menu_index == 5:
                self.running = False
        elif self.menu_screen == "reset_confirm":
            if self.menu_index == 0:  # Oui
                self.hs_entries = reset_highscores()
                self.menu_screen = "options"
                self.menu_index = 6
            else:  # Non
                self.menu_screen = "options"
                self.menu_index = 6
        elif self.menu_screen == "options":
            if self.menu_index == 6:  # Reset high scores → confirmation
                self.menu_screen = "reset_confirm"
                self.menu_index = 1  # default on Non
            elif self.menu_index == 7:  # Retour
                if self.pause_options:
                    self.pause_options = False
                    self.menu_screen = "options"  # unused while pause_options False
                    self.menu_index = 0
                else:
                    self.menu_screen = "main"
                    self.menu_index = 2  # highlight OPTIONS
            # other options adjusted with left/right

    # --- Input ---
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type in (getattr(pygame, "JOYDEVICEADDED", -1), getattr(pygame, "JOYDEVICEREMOVED", -2)):
                self._poll_gamepad()
            elif event.type == pygame.KEYDOWN:
                if self.attract_mode:
                    self._end_attract()
                    continue
                if event.key == pygame.K_ESCAPE:
                    if self.started and not self.game_over:
                        if self.quit_confirm:
                            self.quit_confirm = False
                        else:
                            self._toggle_pause()
                    elif not self.started:
                        if self.menu_screen == "help":
                            self._reset_menu_idle()
                        elif self.quit_confirm:
                            self.quit_confirm = False
                        else:
                            self.quit_confirm = True
                            self.quit_index = 1
                # Pause menu (in-game)
                if self.paused and self.started and not self.game_over:
                    if self.pause_options:
                        if event.key in (pygame.K_UP, pygame.K_w):
                            self._menu_nav(-1)
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            self._menu_nav(1)
                        elif event.key in (pygame.K_LEFT, pygame.K_a):
                            self._menu_adjust(-1)
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            self._menu_adjust(1)
                        elif event.key == pygame.K_RETURN:
                            if self.menu_screen == "reset_confirm":
                                if self.menu_index == 0:
                                    self.hs_entries = reset_highscores()
                                self.menu_screen = "options"
                                self.menu_index = 6
                            elif self.menu_index == 7:
                                self.pause_options = False
                                self.menu_index = 0
                            elif self.menu_index == 6:
                                self.menu_screen = "reset_confirm"
                                self.menu_index = 1
                        elif event.key == pygame.K_ESCAPE:
                            if self.menu_screen == "reset_confirm":
                                self.menu_screen = "options"
                                self.menu_index = 6
                            else:
                                self.pause_options = False
                                self.menu_index = 0
                    else:
                        if event.key in (pygame.K_UP, pygame.K_w):
                            self.pause_index = (self.pause_index - 1) % 3
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            self.pause_index = (self.pause_index + 1) % 3
                        elif event.key == pygame.K_RETURN:
                            if self.pause_index == 0:  # Reprendre
                                self.paused = False
                            elif self.pause_index == 1:  # Options
                                self.pause_options = True
                                self.menu_screen = "options"
                                self.menu_index = 0
                            else:  # Quitter la partie
                                self._quit_to_menu()
                        elif event.key == pygame.K_ESCAPE:
                            self.paused = False
                            self.pause_options = False
                # Quit game confirm (menus) — ESC already toggled above
                elif self.quit_confirm and not self.started:
                    if event.key in (pygame.K_UP, pygame.K_w):
                        self.quit_index = (self.quit_index - 1) % 2
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        self.quit_index = (self.quit_index + 1) % 2
                    elif event.key == pygame.K_RETURN:
                        if self.quit_index == 0:
                            self.running = False
                        else:
                            self.quit_confirm = False

                
                if not self.started and not self.game_over and not self.quit_confirm:
                    if self.menu_screen == "help":
                        self._reset_menu_idle()
                    elif self.menu_screen == "credits":
                        self.menu_screen = "main"
                        self.menu_index = 0
                    elif self.menu_screen == "highscores":
                        # Invisible cheats: LVL2 / LVL3
                        if event.unicode and event.unicode.isalnum():
                            self.cheat_buffer = (self.cheat_buffer + event.unicode.upper())[-8:]
                            if "LVL2" in self.cheat_buffer:
                                self._start_at_stage(2)
                            elif "LVL3" in self.cheat_buffer:
                                self._start_at_stage(3)
                            elif "LVL4" in self.cheat_buffer:
                                self._start_at_stage(4)
                            elif "LVL5" in self.cheat_buffer:
                                self._start_at_stage(5)
                            elif "LIVE" in self.cheat_buffer:
                                self.used_cheat = True
                                self.player.infinite_lives = True
                                self.player.lives = 99
                                self.cheat_buffer = ""
                                self.cheat_msg = "INFINITE LIVES"
                                self.cheat_msg_timer = 2.0
                        else:
                            # Any non-alnum key (Enter, Esc already handled, Space, arrows...) returns
                            if event.key not in (pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_CAPSLOCK):
                                self.menu_screen = "main"
                                self.menu_index = 0
                                self.cheat_buffer = ""
                    elif event.key in (pygame.K_UP, pygame.K_w):
                        self._reset_menu_idle()
                        self._menu_nav(-1)
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        self._reset_menu_idle()
                        self._menu_nav(1)
                    elif event.key in (pygame.K_LEFT, pygame.K_a):
                        self._reset_menu_idle()
                        self._menu_adjust(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_d):
                        self._reset_menu_idle()
                        self._menu_adjust(1)
                    elif event.key == pygame.K_RETURN:
                        self._reset_menu_idle()
                        self._menu_confirm()
                
                if self.game_over:
                    if self.hs_phase == "enter":
                        if event.key == pygame.K_LEFT:
                            self.hs_char_index = (self.hs_char_index - 1) % 3
                        elif event.key == pygame.K_RIGHT:
                            self.hs_char_index = (self.hs_char_index + 1) % 3
                        elif event.key == pygame.K_UP:
                            self._hs_cycle_letter(1)
                        elif event.key == pygame.K_DOWN:
                            self._hs_cycle_letter(-1)
                        elif event.key == pygame.K_BACKSPACE:
                            self.hs_char_index = max(0, self.hs_char_index - 1)
                        elif event.key == pygame.K_RETURN:
                            self._submit_highscore()
                        elif event.unicode and event.unicode.isalnum():
                            self.hs_name[self.hs_char_index] = event.unicode.upper()
                            self.hs_char_index = min(2, self.hs_char_index + 1)
                            if self.hs_char_index == 2 and self.hs_name[2] != "A":
                                pass  # stay on last or auto-advance feel
                    elif self.hs_phase == "table" and event.key == pygame.K_RETURN:
                        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language)
                        self.__init__()
                        self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language = saved
                        set_lang(self.language)
                        self.sounds.set_music_volume(self.music_volume)
                        self.sounds.set_master_volume(self.sfx_volume)
                        self.apply_display_mode()
            
            elif event.type == pygame.JOYBUTTONDOWN:
                if self.attract_mode:
                    self._end_attract()
                    continue
                # Start button (7 Xbox / 9 some pads) — pause or quit confirm
                if event.button in (7, 9, 6):
                    if self.started and not self.game_over:
                        self._toggle_pause()
                    elif not self.started:
                        if self.menu_screen == "help":
                            self._reset_menu_idle()
                        elif self.quit_confirm:
                            self.quit_confirm = False
                        else:
                            self.quit_confirm = True
                            self.quit_index = 1
                elif self.paused and self.started and not self.game_over:
                    if self.pause_options:
                        if event.button == 0:
                            if self.menu_screen == "reset_confirm":
                                if self.menu_index == 0:
                                    self.hs_entries = reset_highscores()
                                self.menu_screen = "options"
                                self.menu_index = 6
                            elif self.menu_index == 7:
                                self.pause_options = False
                                self.menu_index = 0
                            elif self.menu_index == 6:
                                self.menu_screen = "reset_confirm"
                                self.menu_index = 1
                        elif event.button == 1:
                            if self.menu_screen == "reset_confirm":
                                self.menu_screen = "options"
                                self.menu_index = 6
                            else:
                                self.pause_options = False
                                self.menu_index = 0
                    else:
                        if event.button == 0:
                            if self.pause_index == 0:
                                self.paused = False
                            elif self.pause_index == 1:
                                self.pause_options = True
                                self.menu_screen = "options"
                                self.menu_index = 0
                            else:
                                self._quit_to_menu()
                        elif event.button == 1:
                            self.paused = False
                            self.pause_options = False
                elif self.quit_confirm and not self.started:
                    if event.button == 0:
                        if self.quit_index == 0:
                            self.running = False
                        else:
                            self.quit_confirm = False
                    elif event.button == 1:
                        self.quit_confirm = False
                elif not self.started and not self.game_over and not self.quit_confirm:
                    if self.menu_screen == "help":
                        self._reset_menu_idle()
                    elif event.button == 0:  # A — confirm / enter
                        self._reset_menu_idle()
                        if self.menu_screen in ("highscores", "credits"):
                            self._menu_back()
                        else:
                            self._menu_confirm()
                    elif event.button == 1:  # B — back
                        self._reset_menu_idle()
                        self._menu_back()
                elif self.game_over and self.hs_phase == "enter":
                    if event.button in (0, 1):
                        self._submit_highscore()
                elif self.game_over and self.hs_phase == "table":
                    if event.button in (0, 1):
                        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language)
                        self.__init__()
                        self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language = saved
                        set_lang(self.language)
                        self.sounds.set_music_volume(self.music_volume)
                        self.sounds.set_master_volume(self.sfx_volume)
                        self.apply_display_mode()
            elif event.type == pygame.JOYHATMOTION:
                hx, hy = event.value
                if not self.started and not self.game_over:
                    if self.menu_screen == "help":
                        self._reset_menu_idle()
                    elif self.menu_screen in ("highscores", "credits"):
                        self._menu_back()
                    else:
                        self._reset_menu_idle()
                        if hy > 0:
                            self._menu_nav(-1)
                        elif hy < 0:
                            self._menu_nav(1)
                        if hx != 0:
                            self._menu_adjust(1 if hx > 0 else -1)
                elif self.game_over and self.hs_phase == "enter":
                    if hx < 0:
                        self.hs_char_index = (self.hs_char_index - 1) % 3
                    elif hx > 0:
                        self.hs_char_index = (self.hs_char_index + 1) % 3
                    if hy > 0:
                        self._hs_cycle_letter(1)
                    elif hy < 0:
                        self._hs_cycle_letter(-1)
            elif event.type == pygame.JOYAXISMOTION:
                DEAD = 0.72
                if self.paused and self.started and not self.game_over:
                    if self.pause_options:
                        if event.axis == 1:
                            if abs(event.value) < 0.40:
                                self._joy_axis_latch_y = 0
                            elif self._joy_menu_cooldown <= 0:
                                if event.value < -DEAD and self._joy_axis_latch_y != -1:
                                    self._menu_nav(-1)
                                    self._joy_axis_latch_y = -1
                                    self._joy_menu_cooldown = 0.28
                                elif event.value > DEAD and self._joy_axis_latch_y != 1:
                                    self._menu_nav(1)
                                    self._joy_axis_latch_y = 1
                                    self._joy_menu_cooldown = 0.28
                        elif event.axis == 0:
                            if abs(event.value) < 0.40:
                                self._joy_axis_latch_x = 0
                            elif self._joy_menu_cooldown <= 0:
                                if event.value < -DEAD and self._joy_axis_latch_x != -1:
                                    self._menu_adjust(-1)
                                    self._joy_axis_latch_x = -1
                                    self._joy_menu_cooldown = 0.28
                                elif event.value > DEAD and self._joy_axis_latch_x != 1:
                                    self._menu_adjust(1)
                                    self._joy_axis_latch_x = 1
                                    self._joy_menu_cooldown = 0.28
                    elif event.axis == 1:
                        if abs(event.value) < 0.40:
                            self._joy_axis_latch_y = 0
                        elif self._joy_menu_cooldown <= 0:
                            if event.value < -DEAD and self._joy_axis_latch_y != -1:
                                self.pause_index = (self.pause_index - 1) % 3
                                self._joy_axis_latch_y = -1
                                self._joy_menu_cooldown = 0.28
                            elif event.value > DEAD and self._joy_axis_latch_y != 1:
                                self.pause_index = (self.pause_index + 1) % 3
                                self._joy_axis_latch_y = 1
                                self._joy_menu_cooldown = 0.28
                elif self.quit_confirm and not self.started:
                    if event.axis == 1:
                        if abs(event.value) < 0.40:
                            self._joy_axis_latch_y = 0
                        elif self._joy_menu_cooldown <= 0:
                            if event.value < -DEAD and self._joy_axis_latch_y != -1:
                                self.quit_index = (self.quit_index - 1) % 2
                                self._joy_axis_latch_y = -1
                                self._joy_menu_cooldown = 0.28
                            elif event.value > DEAD and self._joy_axis_latch_y != 1:
                                self.quit_index = (self.quit_index + 1) % 2
                                self._joy_axis_latch_y = 1
                                self._joy_menu_cooldown = 0.28
                elif not self.started and not self.game_over:
                    if self.menu_screen == "help":
                        if abs(event.value) > 0.55:
                            self._reset_menu_idle()
                    elif event.axis == 1:
                        if abs(event.value) < 0.40:
                            self._joy_axis_latch_y = 0
                        elif self._joy_menu_cooldown <= 0:
                            if event.value < -DEAD and self._joy_axis_latch_y != -1:
                                self._reset_menu_idle()
                                self._menu_nav(-1)
                                self._joy_axis_latch_y = -1
                                self._joy_menu_cooldown = 0.28
                            elif event.value > DEAD and self._joy_axis_latch_y != 1:
                                self._reset_menu_idle()
                                self._menu_nav(1)
                                self._joy_axis_latch_y = 1
                                self._joy_menu_cooldown = 0.28
                    elif event.axis == 0:
                        if abs(event.value) < 0.40:
                            self._joy_axis_latch_x = 0
                        elif self._joy_menu_cooldown <= 0:
                            if event.value < -DEAD and self._joy_axis_latch_x != -1:
                                self._reset_menu_idle()
                                self._menu_adjust(-1)
                                self._joy_axis_latch_x = -1
                                self._joy_menu_cooldown = 0.28
                            elif event.value > DEAD and self._joy_axis_latch_x != 1:
                                self._reset_menu_idle()
                                self._menu_adjust(1)
                                self._joy_axis_latch_x = 1
                                self._joy_menu_cooldown = 0.28

    # --- Simulation step ---
    def update(self):
        self.title_timer += self.dt
        self._update_music()
        self.sounds.update(self.dt)
        # Detect controller plugged after launch (especially on menus)
        if not self.started or self.game_over:
            self._poll_gamepad()
        if self._joy_menu_cooldown > 0:
            self._joy_menu_cooldown = max(0.0, self._joy_menu_cooldown - self.dt)
        if self.input_grace > 0:
            self.input_grace = max(0.0, self.input_grace - self.dt)
        if self.cheat_msg_timer > 0:
            self.cheat_msg_timer = max(0.0, self.cheat_msg_timer - self.dt)
        if self._hs_joy_cooldown > 0:
            self._hs_joy_cooldown = max(0.0, self._hs_joy_cooldown - self.dt)
        
        # Analog stick for initials entry
        if self.game_over and self.hs_phase == "enter" and self.joystick and self._hs_joy_cooldown <= 0:
            try:
                ax = self.joystick.get_axis(0) if self.joystick.get_numaxes() > 0 else 0
                ay = self.joystick.get_axis(1) if self.joystick.get_numaxes() > 1 else 0
                if abs(ax) > 0.7:
                    self.hs_char_index = (self.hs_char_index + (1 if ax > 0 else -1)) % 3
                    self._hs_joy_cooldown = 0.28
                elif abs(ay) > 0.7:
                    self._hs_cycle_letter(-1 if ay > 0 else 1)
                    self._hs_joy_cooldown = 0.22
            except Exception:
                pass
        
        if not self.started or self.game_over:
            # Still scroll stars on title/game over (no parallax)
            self.starfield.update(self.dt)
            self.sounds.play_electric(False)
            if self.logo_frames:
                self.logo_timer += self.dt
                if self.logo_timer >= 1.0 / self.logo_fps:
                    self.logo_timer -= 1.0 / self.logo_fps
                    self.logo_index = (self.logo_index + 1) % len(self.logo_frames)
            if not self.started and self.menu_screen == "credits":
                self.credits_scroll -= 42.0 * self.dt  # px/s, frame-locked via dt
            # Attract / help screen from main menu idle
            if not self.started and not self.quit_confirm:
                if self.menu_screen == "main":
                    self.menu_idle += self.dt
                    # First idle after launch: 10s help; then alternate help / attract every 5s
                    idle_need = 10.0 if not self.help_first_shown else 5.0
                    if self.menu_idle >= idle_need:
                        self.menu_idle = 0.0
                        if not self.help_first_shown:
                            self.help_first_shown = True
                            self.menu_screen = "help"
                            self.help_timer = 0.0
                            self.next_is_attract = True
                        elif self.next_is_attract:
                            self.next_is_attract = False
                            self._start_attract()
                        else:
                            self.next_is_attract = True
                            self.menu_screen = "help"
                            self.help_timer = 0.0
                elif self.menu_screen == "help":
                    self.help_timer += self.dt
                    self.help_anim_t += self.dt
                    if self.help_timer >= 10.0:
                        self.menu_screen = "main"
                        self.menu_index = 0
                        self.menu_idle = 0.0
                        self.help_timer = 0.0
                else:
                    self.menu_idle = 0.0
            return
        
        if self.paused:
            self.starfield.update(self.dt)
            self.sounds.play_electric(False)
            return
            
        keys = pygame.key.get_pressed()
        
        if self.stage_transition is None:
            ai_move = ai_shoot = None
            if self.attract_mode:
                ai_move, ai_shoot = self._attract_ai()
            edge_killed = self.player.update(
                self.dt, keys, self.input_mode, self.joystick,
                allow_shoot=(self.input_grace <= 0),
                ai_move=ai_move, ai_shoot=ai_shoot,
            )
        else:
            edge_killed = False
        # Electric crackle while edge lightning is active
        self.sounds.play_electric(self.player.edge_flash > 0.08 and not self.player.dying)
        if edge_killed:
            kind = "gameover" if self.player.dying else "edge"
            self.explosions.append(Explosion(self.player.x, self.player.y, kind=kind))
            self.shake_amount = 22.0 if self.player.dying else 14.0
            self.sounds.play("explosion_big" if self.player.dying else "explosion")
            self.sounds.play_electric(False)
        
        # Attract mode: 30s demo or death → back to menu (no high score)
        if self.attract_mode:
            self.attract_timer -= self.dt
            if self.attract_timer <= 0 or not self.player.alive:
                self._end_attract()
                return

        # Game over only after death disappearance finishes
        if not self.player.alive and not self.game_over and not self.attract_mode:
            self.game_over = True
            self._begin_highscore_flow()
        
        # Starfield with parallax based on player movement
        self.starfield.update(self.dt, self.player.x)
        
        # Stage transition: ship flies off top
        if self.stage_transition == "fly_up":
            self.player.y -= 420 * self.dt
            self.player.engine_intensity = 1.0
            self.starfield.update(self.dt, self.player.x)
            if self.player.y < -80:
                self.stage += 1
                self._setup_stage(self.stage)
                self.player.y = BASE_HEIGHT + 60
                self.player.x = BASE_WIDTH // 2
                self.stage_transition = "arrive"
                self.transition_timer = 0.0
            # still draw explosions etc lightly
            for exp in self.explosions[:]:
                exp.update(self.dt)
                if exp.is_finished():
                    self.explosions.remove(exp)
            return
        
        if self.stage_transition == "arrive":
            # Ship enters from bottom
            target_y = BASE_HEIGHT - 95
            self.player.y -= 380 * self.dt
            self.player.engine_intensity = 1.0
            self.starfield.update(self.dt, self.player.x)
            self.formation.update(self.dt, self.player.x)
            if self.player.y <= target_y:
                self.player.y = target_y
                self.stage_transition = None
                self.input_grace = 0.4
            for exp in self.explosions[:]:
                exp.update(self.dt)
                if exp.is_finished():
                    self.explosions.remove(exp)
            return
        
        self.formation.update(self.dt, self.player.x)
        self._check_extra_lives()
        if self.life_flash_timer > 0:
            self.life_flash_timer = max(0.0, self.life_flash_timer - self.dt)
        
        # --- Stage 5 boss ---
        if self.boss_saucer is not None and self.boss_saucer.alive:
            self.boss_saucer.update(self.dt, self.player.x)
            # Spawn birds more often — stage1 2x more likely than stage2, max 10
            self.boss_bird_timer -= self.dt
            if self.boss_bird_timer <= 0:
                self.boss_bird_timer = random.uniform(0.9, 1.8)
                alive_birds = len(self.formation.get_alive_enemies())
                if alive_birds < 6:
                    x = random.uniform(60, BASE_WIDTH - 60)
                    st = 1 if random.random() < 0.67 else 2
                    bird = Enemy(x, -30, formation_index=99, stage=st)
                    bird.speed_mult = stage_speed_mult(self.stage) * self.difficulty_speed_mult()
                    bird.state = "diving"
                    bird.dive_target_x = self.player.x
                    self.formation.enemies.append(bird)
        
        # Stage clear → fly to next stage (non-boss content)
        content = stage_content(self.stage)
        if (self.stage_transition is None and content != 5
                and self.formation.all_dead() and not self.player.dying
                and self.boss_saucer is None):
            self.stage_transition = "fly_up"
            self.player.destroy_bullet()
        
        # Boss killed → cataclysmic saucer explosion, kill all birds, then fly up
        if (self.boss_saucer is not None and not self.boss_saucer.alive
                and self.stage_transition is None and not self.game_over):
            # Cataclysm: explode many cells + boss area
            import random as _r
            living = [c for c in self.boss_saucer.cells if c.alive]
            for c in living:
                c.alive = False
                if _r.random() < 0.35:
                    self.explosions.append(Explosion(c.x, c.y, kind="enemy"))
            for d in self.boss_saucer.decorations:
                if d.alive:
                    d.alive = False
                    self.explosions.append(Explosion(d.x, d.y, kind="enemy"))
            bx = self.boss_saucer.boss.x
            by = self.boss_saucer.boss.y
            for _ in range(8):
                self.explosions.append(Explosion(
                    bx + _r.uniform(-120, 120),
                    by + _r.uniform(-40, 80),
                    kind="gameover" if _ < 3 else "collision"
                ))
            self.shake_amount = 30.0
            self.sounds.play("explosion_big")
            for e in self.formation.get_alive_enemies():
                e.kill()
            self.boss_saucer = None
            self.bosses_defeated += 1
            self.stage_transition = "boss_outro"
            self.transition_timer = 0.0
        
        if self.stage_transition == "boss_outro":
            self.transition_timer += self.dt
            self.starfield.update(self.dt, self.player.x)
            for exp in self.explosions[:]:
                exp.update(self.dt)
                if exp.is_finished():
                    self.explosions.remove(exp)
            # After spectacle, ship flies to next stage
            if self.transition_timer > 1.8:
                self.stage_transition = "fly_up"
                self.player.destroy_bullet()
            return
        
        # Player bullet vs Enemies / Boss
        bullet_rect = self.player.get_bullet_rect()
        if bullet_rect is not None:
            # Boss saucer armor / core
            if self.boss_saucer is not None and self.boss_saucer.alive:
                result = self.boss_saucer.hit_bullet(bullet_rect)
                if result is not None:
                    kind, target = result
                    self.player.destroy_bullet()
                    if kind == "cell":
                        self.explosions.append(Explosion(target.x, target.y, kind="enemy"))
                        self.shake_amount = 3.5
                        self.sounds.play("enemy_explosion", volume=0.4)
                        self.score += 1
                    elif kind == "deco":
                        self.explosions.append(Explosion(target.x, target.y, kind="enemy"))
                        self.shake_amount = 5.0
                        self.sounds.play("enemy_explosion")
                        self.score += 50
                    elif kind == "boss":
                        target.kill()
                        self.score += self._boss_points()
                        self.explosions.append(Explosion(target.x, target.y, kind="gameover"))
                        self.shake_amount = 20.0
                        self.sounds.play("explosion_big")
                    bullet_rect = None  # consumed
            
            if bullet_rect is not None:
              for enemy in self.formation.get_hittable_enemies():
                if isinstance(enemy, BigBird):
                    # Wings first (no points), then body (kill + 30)
                    if bullet_rect.colliderect(enemy.get_left_wing_hitbox()):
                        if enemy.hit_wing("left"):
                            self.player.destroy_bullet()
                            self.explosions.append(Explosion(enemy.x - 35, enemy.y, kind="enemy"))
                            self.shake_amount = 3.0
                            self.sounds.play("enemy_explosion", volume=0.5)
                        else:
                            self.player.destroy_bullet()
                        break
                    if bullet_rect.colliderect(enemy.get_right_wing_hitbox()):
                        if enemy.hit_wing("right"):
                            self.player.destroy_bullet()
                            self.explosions.append(Explosion(enemy.x + 35, enemy.y, kind="enemy"))
                            self.shake_amount = 3.0
                            self.sounds.play("enemy_explosion", volume=0.5)
                        else:
                            self.player.destroy_bullet()
                        break
                    if bullet_rect.colliderect(enemy.get_body_hitbox()):
                        enemy.kill()
                        self.player.destroy_bullet()
                        self.score += self._enemy_points(getattr(enemy, "stage", 3))
                        self.explosions.append(Explosion(enemy.x, enemy.y, kind="enemy"))
                        self.shake_amount = 7.0
                        self.sounds.play("enemy_explosion")
                        break
                else:
                    if bullet_rect.colliderect(enemy.get_hitbox()):
                        enemy.kill()
                        self.player.destroy_bullet()
                        self.score += self._enemy_points(getattr(enemy, "stage", 1))
                        self.explosions.append(Explosion(enemy.x, enemy.y, kind="enemy"))
                        self.shake_amount = 5.5
                        self.sounds.play("enemy_explosion")
                        break
        
        # Enemy attacks vs Player
        if self.player.alive and not self.player.dying:
            player_hitbox = self.player.get_hitbox()
            
            # Boss saucer hull contact → fatal
            if self.boss_saucer is not None and self.boss_saucer.alive:
                hull = self.boss_saucer.get_hull_hitbox()
                if hull.width > 0 and player_hitbox.colliderect(hull):
                    if not self.player.dying:
                        if self.player.infinite_lives:
                            # Bounce / damage without death
                            self.player.hit()
                            self.explosions.append(Explosion(self.player.x, self.player.y, kind="bullet"))
                            self.shake_amount = 14.0
                            self.sounds.play("explosion")
                            # Nudge player down away from hull
                            self.player.y = min(BASE_HEIGHT - 80, self.player.y + 40)
                        else:
                            self.player.lives = 0
                            self.player.dying = True
                            self.player.death_timer = 0.0
                            self.player.invulnerable = 0.0
                            self.explosions.append(Explosion(self.player.x, self.player.y, kind="gameover"))
                            self.shake_amount = 24.0
                            self.sounds.play("explosion_big")
                
                # Boss saucer bullets
                for b in self.boss_saucer.bullets[:]:
                    if b.alive and b.get_hitbox().colliderect(player_hitbox):
                        b.alive = False
                        if self.player.invulnerable <= 0 and self.player.alive and not self.player.dying:
                            self.player.hit()
                            kind = "gameover" if self.player.dying else "bullet"
                            self.explosions.append(Explosion(self.player.x, self.player.y, kind=kind))
                            self.shake_amount = 22.0 if self.player.dying else 12.0
                            self.sounds.play("explosion_big" if self.player.dying else "explosion")
                        break
            
            for bullet in self.formation.bullets[:]:
                if bullet.alive and bullet.get_hitbox().colliderect(player_hitbox):
                    bullet.alive = False
                    # Always play hit explosion if damage can be applied
                    if self.player.invulnerable <= 0 and self.player.alive and not self.player.dying:
                        self.player.hit()
                        kind = "gameover" if self.player.dying else "bullet"
                        self.explosions.append(Explosion(self.player.x, self.player.y, kind=kind))
                        self.shake_amount = 22.0 if self.player.dying else 12.0
                        self.sounds.play("explosion_big" if self.player.dying else "explosion")
                    break
            
            for enemy in self.formation.get_hittable_enemies():
                if enemy.diving and enemy.get_hitbox().colliderect(player_hitbox):
                    enemy.kill()
                    self.player.hit()
                    # Massive dual explosion — gameover if final life
                    self.explosions.append(Explosion(enemy.x, enemy.y, kind="collision"))
                    self.sounds.play("enemy_explosion")
                    pkind = "gameover" if self.player.dying else "collision"
                    self.explosions.append(Explosion(self.player.x, self.player.y, kind=pkind))
                    self.shake_amount = 26.0 if self.player.dying else 18.0
                    self.sounds.play("explosion_big")
                    break
        
        for exp in self.explosions[:]:
            exp.update(self.dt)
            if exp.is_finished():
                self.explosions.remove(exp)
        
        # Soft performance cap: keep newest explosions only
        if len(self.explosions) > 24:
            self.explosions = self.explosions[-24:]
        
        if self.shake_amount > 0:
            self.shake_amount = max(0.0, self.shake_amount - SCREEN_SHAKE_DECAY * self.dt)

    # --- Render (logical canvas, then present) ---
    def draw(self):
        self.game_surface.fill(COLOR_BG)
        
        # Starfield first (background)
        self.starfield.draw(self.game_surface)
        
        shake_x = shake_y = 0
        if self.shake_amount > 0 and self.started and not self.game_over:
            shake_x = random.randint(-int(self.shake_amount), int(self.shake_amount))
            shake_y = random.randint(-int(self.shake_amount), int(self.shake_amount))
        
        if self.started and not self.game_over:
            if self.boss_saucer:
                self.boss_saucer.draw(self.game_surface)
            self.formation.draw(self.game_surface)
            
            for exp in self.explosions:
                exp.draw(self.game_surface)
            
            self.player.draw(self.game_surface)
            
            # UI
            score_surf = self.font.render(self.format_score(self.score), True, (110, 255, 150))
            self.game_surface.blit(score_surf, (BASE_WIDTH // 2 - score_surf.get_width() // 2, 16))
            if self.attract_mode:
                demo = self.medium_font.render(t("demo"), True, (255, 180, 80))
                self.game_surface.blit(demo, (BASE_WIDTH // 2 - demo.get_width() // 2, 72))
                hint = self.font.render(t("press_any"), True, (180, 180, 200))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT - 36))
            if getattr(self, "used_cheat", False) and not self.attract_mode:
                ch = self.font.render(t("cheat_active"), True, (255, 60, 60))
                self.game_surface.blit(ch, (BASE_WIDTH // 2 - ch.get_width() // 2, 74))
            
            stage_surf = self.font.render(f"{t('stage')} {self.stage}", True, (180, 180, 220))
            self.game_surface.blit(stage_surf, (16, 16))
            # Flags for each boss defeated — at 10+, one big flag only
            if self.bosses_defeated >= 10:
                fx = 16 + stage_surf.get_width() + 12
                self._draw_boss_flag(self.game_surface, fx, 12, big=True)
            elif self.bosses_defeated > 0:
                fx = 16 + stage_surf.get_width() + 10
                fy = 18
                for i in range(self.bosses_defeated):
                    self._draw_boss_flag(self.game_surface, fx + i * 18, fy, big=False)
            
            if self.cheat_msg_timer > 0 and self.cheat_msg:
                # Pulsing glow for 1UP / stage messages
                pulse = 0.5 + 0.5 * abs(__import__("math").sin(self.cheat_msg_timer * 8.0))
                if self.cheat_msg.startswith("1UP"):
                    # bright blinking gold
                    blink = int(self.cheat_msg_timer * 6) % 2 == 0
                    col = (255, 255, 180) if blink else (255, 200, 60)
                    cm = self.big_font.render(self.cheat_msg, True, col)
                    # soft glow layers
                    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                        g = self.big_font.render(self.cheat_msg, True, (255, 220, 80))
                        g.set_alpha(int(60 + 80 * pulse))
                        self.game_surface.blit(g, (BASE_WIDTH // 2 - cm.get_width() // 2 + ox, 72 + oy))
                    self.game_surface.blit(cm, (BASE_WIDTH // 2 - cm.get_width() // 2, 72))
                else:
                    cm = self.medium_font.render(self.cheat_msg, True, (255, 220, 100))
                    self.game_surface.blit(cm, (BASE_WIDTH // 2 - cm.get_width() // 2, 80))
            
            # Lives as mini ships
            if self.player.infinite_lives:
                inf = self.font.render(t("lives_inf"), True, (110, 255, 150))
                self.game_surface.blit(inf, (BASE_WIDTH // 2 - inf.get_width() // 2, 44))
            n_lives = max(0, self.player.lives)
            if n_lives > 0 and not self.player.infinite_lives:
                gap = 6
                iw = self.life_icon.get_width()
                ih = self.life_icon.get_height()
                total_w = n_lives * iw + (n_lives - 1) * gap
                start_x = BASE_WIDTH // 2 - total_w // 2
                for i in range(n_lives):
                    lx = start_x + i * (iw + gap)
                    ly = 44
                    # Extra life flash/shine on the new icon
                    if self.life_flash_timer > 0 and i == self.life_flash_index:
                        blink = int(self.life_flash_timer * 8) % 2 == 0
                        if blink:
                            # bright glow under ship
                            glow = pygame.Surface((iw + 10, ih + 10), pygame.SRCALPHA)
                            pygame.draw.ellipse(glow, (255, 255, 120, 90), glow.get_rect())
                            self.game_surface.blit(glow, (lx - 5, ly - 5))
                            # white flash version
                            white = self.life_icon.copy()
                            white.fill((255, 255, 200, 0), special_flags=pygame.BLEND_RGBA_ADD)
                            self.game_surface.blit(white, (lx, ly))
                            self.game_surface.blit(self.life_icon, (lx, ly))
                    else:
                        self.game_surface.blit(self.life_icon, (lx, ly))
        
        # Title / Menu Screen
        if not self.started:
            if self.menu_screen in ("main",):
                # Animated fiery logo (fallback to text if frames missing)
                if not self._draw_logo(self.game_surface, BASE_WIDTH // 2, 8):
                    title = self.big_font.render("PHENIX REBIRTH", True, (255, 120, 255))
                    self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 80))
                
                # Subtitle below logo
                logo_h = self.logo_frames[0].get_height() if self.logo_frames else 100
                sub = self.font.render(t("subtitle"), True, (180, 160, 220))
                self.game_surface.blit(sub, (BASE_WIDTH // 2 - sub.get_width() // 2, 8 + logo_h - 4))
            
            if self.menu_screen == "help":
                import math as _math
                # Title
                title = self.big_font.render("PHENIX REBIRTH", True, (255, 120, 255))
                self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 28))
                sub = self.font.render(t("subtitle"), True, (180, 160, 220))
                self.game_surface.blit(sub, (BASE_WIDTH // 2 - sub.get_width() // 2, 82))
                
                # --- Left column: scenario + how to play ---
                col_l = 40
                y = 130
                def hdr(txt, yy):
                    s = self.medium_font.render(txt, True, (255, 200, 120))
                    self.game_surface.blit(s, (col_l, yy))
                    return yy + 36
                def body(txt, yy):
                    s = self.font.render(txt, True, (200, 200, 230))
                    self.game_surface.blit(s, (col_l, yy))
                    return yy + 26
                
                y = hdr(t_help("scenario_h"), y)
                for line in t_list("scenario"):
                    y = body(line, y)
                y += 12
                y = hdr(t_help("howto_h"), y)
                for line in t_list("howto"):
                    y = body(line, y)
                y += 12
                y = hdr(t_help("controls_h"), y)
                for line in t_list("controls"):
                    y = body(line, y)
                
                # --- Right column: scores with sprites ---
                col_r = BASE_WIDTH // 2 + 100
                y = 130
                y = hdr("POINTS", y) if False else y
                s = self.medium_font.render(t_help("points_h"), True, (255, 200, 120))
                self.game_surface.blit(s, (col_r, y))
                y += 44
                
                score_rows = [
                    ("bird1", t_help("enemy_s1"), "10"),
                    ("bird2", t_help("enemy_s2"), "20"),
                    ("garg3", t_help("enemy_s3"), "30"),
                    ("garg4", t_help("enemy_s4"), "40"),
                    ("boss", t_help("enemy_boss"), "200"),
                ]
                for key, label, pts in score_rows:
                    # icon
                    ix, iy = col_r + 28, y + 14
                    if key == "bird1" and "bird1" in self.help_icons:
                        img = self.help_icons["bird1"]
                        self.game_surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                    elif key == "bird2" and "bird2" in self.help_icons:
                        img = self.help_icons["bird2"]
                        self.game_surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                    elif key == "garg3" and "garg3" in self.help_icons:
                        self._draw_help_gargoyle(self.game_surface, self.help_icons["garg3"], ix, iy, 0.5)
                    elif key == "garg4" and "garg4" in self.help_icons:
                        self._draw_help_gargoyle(self.game_surface, self.help_icons["garg4"], ix, iy, 0.5)
                    elif key == "boss" and "boss" in self.help_icons:
                        img = self.help_icons["boss"]
                        self.game_surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                    # label + pts
                    ls = self.font.render(label, True, (200, 200, 230))
                    self.game_surface.blit(ls, (col_r + 60, y + 4))
                    ps = self.font.render(pts + " " + t_help("pts"), True, (110, 255, 150))
                    self.game_surface.blit(ps, (col_r + 60, y + 26))
                    y += 58
                
                note = self.font.render(t_help("vet_note"), True, (180, 160, 200))
                self.game_surface.blit(note, (col_r, y + 4))
                y += 30
                note2 = self.font.render(t_help("bonus_lives"), True, (180, 160, 220))
                self.game_surface.blit(note2, (col_r, y))
                
                hint = self.font.render(t("help_return"), True, (255, 220, 100))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT - 36))
            
            elif self.menu_screen == "main":
                diff_key = {"novice": "diff_novice", "normal": "diff_normal", "veteran": "diff_veteran"}.get(self.difficulty, "diff_normal")
                diff = t(diff_key)
                options = [
                    t("play"),
                    f"{t('difficulty')} :  <  {diff}  >",
                    t("options"),
                    t("high_scores"),
                    t("credits"),
                    t("quit"),
                ]
                # Under logo + subtitle, no overlap
                logo_h = self.logo_frames[0].get_height() if self.logo_frames else 100
                base_y = max(300, 12 + logo_h + 48)
                spacing = 34 if base_y + 6 * 34 < BASE_HEIGHT - 100 else 30
                for i, label in enumerate(options):
                    selected = (i == self.menu_index)
                    col = (255, 230, 120) if selected else (160, 160, 190)
                    prefix = "> " if selected else "  "
                    surf = self.medium_font.render(prefix + label, True, col)
                    self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, base_y + i * spacing))
                
                if self.gamepad_detected:
                    status = self.font.render(t("gamepad_detected"), True, (100, 200, 140))
                else:
                    status = self.font.render(t("gamepad_none"), True, (180, 140, 120))
                status_y = min(BASE_HEIGHT - 100, base_y + len(options) * spacing + 10)
                self.game_surface.blit(status, (BASE_WIDTH // 2 - status.get_width() // 2, status_y))
            
            elif self.menu_screen == "highscores":
                hdr = self.big_font.render(t("high_scores"), True, (255, 120, 255))
                self.game_surface.blit(hdr, (BASE_WIDTH // 2 - hdr.get_width() // 2, 50))
                entries = self.hs_entries if self.hs_entries else load_highscores()
                base_y = 140
                score_right = BASE_WIDTH // 2 + 170
                for i in range(15):
                    rank = i + 1
                    if i < len(entries):
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            entries[i]["name"], entries[i]["score"],
                            (200, 200, 230), score_right,
                        )
                    else:
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            "---", None, (100, 100, 120), score_right,
                        )
                back = self.font.render(t("press_any"), True, (255, 220, 100))
                self.game_surface.blit(back, (BASE_WIDTH // 2 - back.get_width() // 2, BASE_HEIGHT - 60))
            
            elif self.menu_screen == "credits":
                # Variable line heights; title uses animated logo
                logo_h = self.logo_frames[0].get_height() if self.logo_frames else 56
                heights = []
                credits_lines = get_credits_lines()
                for kind, _ in credits_lines:
                    if kind == "title":
                        heights.append(logo_h + 12)
                    elif kind == "header":
                        heights.append(42)
                    elif kind == "blank":
                        heights.append(28)
                    else:
                        heights.append(32)
                total_h = sum(heights)
                y0 = self.credits_scroll
                if y0 < -total_h:
                    self.credits_scroll = float(BASE_HEIGHT)
                    y0 = self.credits_scroll
                y = y0
                for i, (kind, line) in enumerate(credits_lines):
                    h = heights[i]
                    if -logo_h < y < BASE_HEIGHT + 20 and kind != "blank":
                        if kind == "title":
                            if self.logo_frames:
                                img = self.logo_frames[self.logo_index % len(self.logo_frames)]
                                self.game_surface.blit(
                                    img, (BASE_WIDTH // 2 - img.get_width() // 2, int(y))
                                )
                            else:
                                surf = self.big_font.render(line, True, (255, 120, 255))
                                self.game_surface.blit(
                                    surf, (BASE_WIDTH // 2 - surf.get_width() // 2, int(y))
                                )
                        elif kind == "header":
                            surf = self.medium_font.render(line, True, (255, 200, 120))
                            self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, int(y)))
                        elif kind == "sub":
                            surf = self.font.render(line, True, (180, 160, 220))
                            self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, int(y)))
                        else:
                            surf = self.font.render(line, True, (200, 200, 230))
                            self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, int(y)))
                    y += h
            
            elif self.menu_screen == "reset_confirm":
                hdr = self.medium_font.render(t("reset_hs_title"), True, (255, 120, 100))
                self.game_surface.blit(hdr, (BASE_WIDTH // 2 - hdr.get_width() // 2, 280))
                warn = self.font.render(t("reset_hs_warn"), True, (180, 160, 160))
                self.game_surface.blit(warn, (BASE_WIDTH // 2 - warn.get_width() // 2, 340))
                for i, label in enumerate([t("yes_u"), t("no_u")]):
                    selected = (i == self.menu_index)
                    col = (255, 230, 120) if selected else (160, 160, 190)
                    prefix = "> " if selected else "  "
                    surf = self.medium_font.render(prefix + label, True, col)
                    self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, 400 + i * 50))
            
            elif self.menu_screen == "options":
                # OPTIONS screen
                hdr = self.medium_font.render(t("options"), True, (255, 180, 255))
                self.game_surface.blit(hdr, (BASE_WIDTH // 2 - hdr.get_width() // 2, 100))
                
                mode_labels = {
                    "window": t("disp_window"),
                    "fullscreen": t("disp_fullscreen"),
                    "borderless": t("disp_borderless"),
                }
                ctrl = t("ctrl_pad") if self.input_mode == "gamepad" else t("ctrl_kb")
                vol_pct = int(round(self.sfx_volume * 100))
                disp = mode_labels.get(self.display_mode, self.display_mode)
                
                fps_label = t("yes") if self.show_fps else t("no")
                mus_pct = int(round(self.music_volume * 100))
                lang_label = next((n for c, n in LANGS if c == self.language), self.language)
                lines = [
                    f"{t('opt_control')} :  <  {ctrl}  >",
                    f"{t('opt_sfx')} :  <  {vol_pct}%  >",
                    f"{t('opt_music')} :  <  {mus_pct}%  >",
                    f"{t('opt_display')} :  <  {disp}  >",
                    f"{t('opt_fps')} :  <  {fps_label}  >",
                    f"{t('opt_language')} :  <  {lang_label}  >",
                    t("opt_reset_hs"),
                    t("opt_back"),
                ]
                base_y = 150
                for i, label in enumerate(lines):
                    selected = (i == self.menu_index)
                    col = (255, 230, 120) if selected else (160, 160, 190)
                    prefix = "> " if selected else "  "
                    surf = self.medium_font.render(prefix + label, True, col)
                    self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, base_y + i * 42))
                
                hint = self.font.render(t("opt_hint"), True, (120, 120, 150))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT - 70))
            
            if self.menu_screen == "main":
                if int(self.title_timer * 2.5) % 2 == 0:
                    press = self.font.render(t("press_confirm"), True, (255, 220, 100))
                    self.game_surface.blit(press, (BASE_WIDTH // 2 - press.get_width() // 2, BASE_HEIGHT - 70))
                
                if self.input_mode == "gamepad":
                    controls = self.font.render(t("controls_pad"), True, (140, 140, 180))
                else:
                    controls = self.font.render(t("controls_kb"), True, (140, 140, 180))
                self.game_surface.blit(controls, (BASE_WIDTH // 2 - controls.get_width() // 2, BASE_HEIGHT - 40))
            elif self.menu_screen == "options":
                if self.input_mode == "gamepad":
                    controls = self.font.render(t("controls_pad"), True, (140, 140, 180))
                else:
                    controls = self.font.render(t("controls_kb"), True, (140, 140, 180))
                self.game_surface.blit(controls, (BASE_WIDTH // 2 - controls.get_width() // 2, BASE_HEIGHT - 40))
        
        # High score / Game Over screens
        if self.game_over and self.hs_phase:
            overlay = pygame.Surface((BASE_WIDTH, BASE_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            self.game_surface.blit(overlay, (0, 0))
            
            if self.hs_phase == "enter":
                title = self.big_font.render(t("new_record"), True, (255, 220, 100))
                self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 100))
                
                sc = self.font.render(f"{t('score_label')} : {self.format_score(self.score)}", True, (200, 255, 180))
                self.game_surface.blit(sc, (BASE_WIDTH // 2 - sc.get_width() // 2, 180))
                
                hint = self.font.render(t("enter_initials_hint"), True, (180, 180, 220))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, 240))
                
                # Three letters
                letter_spacing = 70
                start_x = BASE_WIDTH // 2 - letter_spacing
                for i, ch in enumerate(self.hs_name):
                    col = (255, 255, 120) if i == self.hs_char_index else (220, 220, 255)
                    letter = self.big_font.render(ch, True, col)
                    lx = start_x + i * letter_spacing - letter.get_width() // 2
                    self.game_surface.blit(letter, (lx, 320))
                    if i == self.hs_char_index:
                        pygame.draw.line(
                            self.game_surface, (255, 220, 100),
                            (lx, 400), (lx + letter.get_width(), 400), 3
                        )
                
                controls = self.font.render(
                    t("hs_entry_controls"),
                    True, (140, 140, 180)
                )
                self.game_surface.blit(controls, (BASE_WIDTH // 2 - controls.get_width() // 2, 480))
                ok = self.font.render(t("press_confirm"), True, (255, 220, 100))
                self.game_surface.blit(ok, (BASE_WIDTH // 2 - ok.get_width() // 2, 540))
            
            elif self.hs_phase == "table":
                title = self.big_font.render(t("high_scores"), True, (255, 120, 255))
                self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 40))
                
                sc = self.font.render(f"{t('your_score')} : {self.format_score(self.score)}", True, (200, 255, 180))
                self.game_surface.blit(sc, (BASE_WIDTH // 2 - sc.get_width() // 2, 110))
                
                entries = self.hs_entries if self.hs_entries else []
                base_y = 160
                score_right = BASE_WIDTH // 2 + 170
                for i in range(15):
                    rank = i + 1
                    if i < len(entries):
                        name = entries[i]["name"]
                        score = entries[i]["score"]
                        highlight = (self.hs_submitted and score == self.score and name == "".join(self.hs_name))
                        col = (255, 230, 120) if highlight else (200, 200, 230)
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            name, score, col, score_right,
                        )
                    else:
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            "---", None, (100, 100, 120), score_right,
                        )
                
                restart = self.font.render(t("back_to_menu"), True, (255, 220, 100))
                self.game_surface.blit(restart, (BASE_WIDTH // 2 - restart.get_width() // 2, BASE_HEIGHT - 50))
        
        self.screen.fill((0, 0, 0))

        # Pause overlay
        if self.paused and self.started and not self.game_over:
            overlay = pygame.Surface((BASE_WIDTH, BASE_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            self.game_surface.blit(overlay, (0, 0))
            if self.pause_options:
                # Reuse options panel
                hdr = self.medium_font.render(t("options"), True, (255, 180, 255))
                self.game_surface.blit(hdr, (BASE_WIDTH // 2 - hdr.get_width() // 2, 100))
                mode_labels = {
                    "window": t("disp_window"),
                    "fullscreen": t("disp_fullscreen"),
                    "borderless": t("disp_borderless"),
                }
                ctrl = t("ctrl_pad") if self.input_mode == "gamepad" else t("ctrl_kb")
                vol_pct = int(round(self.sfx_volume * 100))
                mus_pct = int(round(self.music_volume * 100))
                disp = mode_labels.get(self.display_mode, self.display_mode)
                fps_label = t("yes") if self.show_fps else t("no")
                if self.menu_screen == "reset_confirm":
                    rh = self.medium_font.render(t("reset_hs_title"), True, (255, 120, 100))
                    self.game_surface.blit(rh, (BASE_WIDTH // 2 - rh.get_width() // 2, 280))
                    for i, label in enumerate([t("yes_u"), t("no_u")]):
                        selected = (i == self.menu_index)
                        col = (255, 230, 120) if selected else (160, 160, 190)
                        prefix = "> " if selected else "  "
                        surf = self.medium_font.render(prefix + label, True, col)
                        self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, 360 + i * 50))
                else:
                    lang_label = next((n for c, n in LANGS if c == self.language), self.language)
                    lines = [
                        f"{t('opt_control')} :  <  {ctrl}  >",
                        f"{t('opt_sfx')} :  <  {vol_pct}%  >",
                        f"{t('opt_music')} :  <  {mus_pct}%  >",
                        f"{t('opt_display')} :  <  {disp}  >",
                        f"{t('opt_fps')} :  <  {fps_label}  >",
                        f"{t('opt_language')} :  <  {lang_label}  >",
                        t("opt_reset_hs"),
                        t("opt_back"),
                    ]
                    base_y = 150
                    for i, label in enumerate(lines):
                        selected = (i == self.menu_index)
                        col = (255, 230, 120) if selected else (160, 160, 190)
                        prefix = "> " if selected else "  "
                        surf = self.medium_font.render(prefix + label, True, col)
                        self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, base_y + i * 42))
            else:
                title = self.big_font.render(t("pause"), True, (255, 220, 100))
                self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 200))
                for i, label in enumerate([t("resume"), t("options"), t("quit_run")]):
                    selected = (i == self.pause_index)
                    col = (255, 230, 120) if selected else (160, 160, 190)
                    prefix = "> " if selected else "  "
                    surf = self.medium_font.render(prefix + label, True, col)
                    self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, 300 + i * 55))
        
        # Quit game confirm (menus)
        if self.quit_confirm and not self.started:
            overlay = pygame.Surface((BASE_WIDTH, BASE_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            self.game_surface.blit(overlay, (0, 0))
            title = self.big_font.render(t("quit_game"), True, (255, 120, 100))
            self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, 220))
            q = self.medium_font.render(t("quit_game_q"), True, (220, 220, 240))
            self.game_surface.blit(q, (BASE_WIDTH // 2 - q.get_width() // 2, 300))
            for i, label in enumerate([t("yes_u"), t("no_u")]):
                selected = (i == self.quit_index)
                col = (255, 230, 120) if selected else (160, 160, 190)
                prefix = "> " if selected else "  "
                surf = self.medium_font.render(prefix + label, True, col)
                self.game_surface.blit(surf, (BASE_WIDTH // 2 - surf.get_width() // 2, 360 + i * 50))

        # FPS counter (top-right)
        if self.show_fps:
            fps_val = int(round(self.clock.get_fps()))
            fps_surf = self.font.render(f"{fps_val} FPS", True, (120, 220, 120))
            self.game_surface.blit(fps_surf, (BASE_WIDTH - fps_surf.get_width() - 16, 12))
        
        self.screen.blit(self.game_surface, (shake_x, shake_y))
        pygame.display.flip()

    # --- Main loop ---
    def run(self):
        while self.running:
            # Cap to 60 or 120 depending on detected display
            self.dt = self.clock.tick(self.fps_target) / 1000.0
            # Safety clamp (spiral of death protection)
            self.dt = min(self.dt, 0.05)
            
            self.handle_events()
            self.update()
            self.draw()
            
        pygame.quit()
        sys.exit(0)
