"""
Phenix Rebirth — main game controller.

Owns the window, fixed-timestep loop, menus, combat, stage progression,
pause/options, high scores, attract-mode help, and credits.

Play modes: solo, hot-seat (alternating), coop (simultaneous). Options cover
controls, autofire, volumes, rumble, display, bezels, FPS counter, CRT
scanlines and language. Cheats on the high-score menu: LVL2–LVL5, LIVE, PHEN.

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
from datetime import datetime
from settings import *
from settings import stage_content, stage_speed_mult
from player import Player
from enemy import EnemyFormation, BigBird, Enemy
from boss import BossSaucer
from explosion import Explosion, TeslaCoilFx
from starfield import Starfield
from sounds import SoundManager
from i18n import set_lang, get_lang, t, t_help, t_list, get_credits_lines, LANGS, LANG_CODES
from highscores import load_highscores, is_highscore, insert_score, reset_highscores
from input_state import InputState
from touch_controls import TouchControls

from settings import user_data_dir, asset_path
SETTINGS_FILE = os.path.join(user_data_dir(), "settings.json")

def load_user_settings():
    defaults = {
        "input_mode": None,  # None = auto
        "display_mode": "fullscreen",
        "sfx_volume": 0.8,
        "music_volume": 0.4,
        "rumble_level": 3,  # 0=off … 3=normal … 5=max
        "autofire": True,  # hold fire key to shoot again when the shot leaves
        "language": "fr",
        "show_fps": False,
        "scanlines": 0,  # 0=off, 1/2/3 intensity
        "bezel_style": "off",  # mobile: no ultrawide bezels
        "monitor_index": 0,
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

class TextCache:
    """Cache font.render results — rebuild only when (font, text, color) changes."""
    __slots__ = ("_data",)

    def __init__(self):
        self._data = {}

    def get(self, font, text, color):
        key = (id(font), text, color)
        surf = self._data.get(key)
        if surf is None:
            if len(self._data) > 400:
                self._data.clear()
            surf = font.render(str(text), True, color)
            self._data[key] = surf
        return surf

    def clear(self):
        self._data.clear()


class Game:
    """
    Top-level application object.

    Lifecycle: __init__ (load settings, build systems) → run() event/update/draw loop.
    Soft restart after a run re-enters __init__ while preserving user settings.
    """
    def __init__(self, soft=False):
        """soft=True: reset session state without recreating the window (no desktop flash)."""
        if not soft:
            try:
                from platform_io import apply_sdl_mobile_hints
                apply_sdl_mobile_hints()
            except Exception:
                pass
            pygame.init()
            # Load display prefs early so the FIRST (and only) window is correct
            try:
                early = load_user_settings()
                self.monitor_index = int(early.get("monitor_index", 0) or 0)
                if self.monitor_index < 0:
                    self.monitor_index = 0
                self.display_mode = early.get("display_mode", "fullscreen") or "fullscreen"
                if self.display_mode not in ("window", "fullscreen", "borderless"):
                    self.display_mode = "fullscreen"
                self.bezel_style = "off"
            except Exception:
                self.monitor_index = 0
                self.display_mode = "fullscreen"
                self.bezel_style = "phoenix"
            self.clock = pygame.time.Clock()
            self.view_rect = pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT)
            self.bezel_active = False
            self._bezel_stars = []
            self.bezel_left_img = None
            self.bezel_right_img = None
            self._bezel_blit_left = None
            self._bezel_blit_right = None
            self._bezel_cache_key = None
            self._present_size = None
            self._scaled_game_buf = None
            # ONE set_mode only — double set_mode crashes some Intel/SDL multi-monitor setups
            self._prepare_monitor_env()
            self._open_display()
            self._display_ready = True
            try:
                self.game_surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT)).convert()
            except Exception:
                self.game_surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT))
            import settings as _settings
            self.fps_target = 60
            _settings.FPS_TARGET = 60
            try:
                pygame.display.set_caption(f"Phenix Rebirth  [{self.fps_target} Hz]")
            except Exception:
                pass
        
        self.player = Player(BASE_WIDTH // 2, BASE_HEIGHT - 95)
        if not hasattr(self, "touch"):
            self.touch = TouchControls(BASE_WIDTH, BASE_HEIGHT)
        self.touch_enabled = True
        self._ts = None
        self._app_suspended = False
        self.formation = EnemyFormation()
        self.explosions = []
        self.tesla_fx = None
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
        self.cheat_kind = ""
        self.used_cheat = False
        self.phenix_cheat = False
        self.paused = False
        self.pause_index = 0  # Reprendre
        self.pause_options = False  # options opened from pause
        self.quit_confirm = False
        self.quit_index = 1  # default Non
        self.menu_idle = 0.0
        self.help_timer = 0.0
        self.help_page = 0  # 0 = scenario/points, 1 = PHENIX
        self.help_scroll = 0.0  # transition offset in pixels
        self.help_transitioning = False
        self.HELP_PAGE_SEC = 10.0
        self.HELP_SCROLL_SEC = 0.42
        self.help_first_shown = False  # first attract uses longer delay
        self.attract_mode = False
        self.attract_timer = 0.0
        # Hot-seat 2P: each player has a fully independent run (stage/score/lives/world)
        self.hotseat = False
        self.play_mode = "solo"
        self.PLAY_MODES = ["solo"]
        self.player2 = None
        self.joysticks = []
        self.lives_shared = 5
        self.current_p = 0
        self.slots = [None, None]
        self.hotseat_wait = False
        self.hotseat_next = 0
        self.hotseat_hold = 0.0
        self.hotseat_pending = None  # None | "switch" | "eliminated" | "gameover"
        self.HOTSEAT_HOLD_LIFE = 1.25   # mid-life explosion
        self.HOTSEAT_HOLD_FINAL = 1.95  # last life / game over (covers Tesla climb)
        self.hs_queue = []
        self.hs_slot_label = 1
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
        self.text_cache = TextCache()
        self._fps_display = 0
        self._fps_timer = 0.0

        # Animated title logo (frame sequence from LogoPhenix.mp4)
        self.logo_frames = []
        self.logo_timer = 0.0
        self.logo_index = 0
        self.logo_fps = 12.0
        logo_dir = asset_path("logo")
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
            asset_path("sprites", "player_ship.png")
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
        # Difficulty is session-only (not in settings.json) but must survive soft resets
        if not hasattr(self, "difficulty"):
            self.difficulty = "normal"  # novice | normal | veteran
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
        if not hasattr(self, "rumble_level"):
            try:
                self.rumble_level = int(user.get("rumble_level", 3))
            except Exception:
                self.rumble_level = 3
            self.rumble_level = max(0, min(5, self.rumble_level))
        if not hasattr(self, "autofire"):
            self.autofire = bool(user.get("autofire", True))
        if not hasattr(self, "language"):
            self.language = user.get("language", "fr")
            if self.language not in LANG_CODES:
                self.language = "fr"
            set_lang(self.language)
        if not hasattr(self, "show_fps"):
            self.show_fps = bool(user.get("show_fps", False))  # default off
        if not hasattr(self, "scanlines"):
            raw = user.get("scanlines", 0)
            # Migrate old bool settings
            if isinstance(raw, bool):
                self.scanlines = 1 if raw else 0
            else:
                try:
                    self.scanlines = max(0, min(3, int(raw)))
                except Exception:
                    self.scanlines = 0
        self._scanline_surf = None
        self._scanline_level_cached = None
        if not hasattr(self, "bezel_style"):
            self.bezel_style = "off"
        if not hasattr(self, "monitor_index"):
            self.monitor_index = int(user.get("monitor_index", 0) or 0)
        # Registry of available bezels (id → i18n key)
        self.BEZEL_STYLES = [
            ("off", "bezel_off"),
            ("phoenix", "bezel_phoenix"),
            ("tesla", "bezel_tesla"),
            ("blue", "bezel_blue"),
            ("fire", "bezel_fire"),
        ]
        valid = {s[0] for s in self.BEZEL_STYLES}
        if getattr(self, "bezel_style", "phoenix") not in valid:
            self.bezel_style = "phoenix"
        
        # Joystick menu navigation cooldown (anti spam)
        self._joy_menu_cooldown = 0.0
        self.input_grace = 0.0
        self._joy_axis_latch_x = 0
        self._joy_axis_latch_y = 0
        
        if not soft or not getattr(self, "sounds", None):
            self.sounds = SoundManager()
        self.sounds.set_master_volume(self.sfx_volume)
        self.sounds.set_music_volume(self.music_volume)
        if not soft or not getattr(self, "help_icons", None):
            self._build_help_icons()
        if not soft or not getattr(self, "bezel_left_img", None):
            self._load_bezel_images()
        self.player.sounds = self.sounds
        self.formation.sounds = self.sounds
        
        # Display already opened once in boot (_open_display). Only layout/bezel finalize.
        if not soft:
            try:
                self._layout_viewport()
                if getattr(self, "bezel_active", False):
                    self._ensure_bezel_cache()
            except Exception as e:
                print("post-boot layout failed:", e)

    # --- Audio state machine (menu / game-over / in-game silence) ---
    def _update_music(self):
        """Menu theme, high-score/game-over theme, silence in-game. Fades handled by SoundManager."""
        if self.game_over and self.hs_phase in ("enter", "table"):
            self.sounds.play_music("gameover")
        elif not self.started:
            if self.menu_screen == "highscores":
                self.sounds.play_music("gameover")
            elif self.menu_screen == "credits":
                self.sounds.play_music("credits")
            else:
                self.sounds.play_music("menu")
        else:
            self.sounds.stop_music()

    # --- Difficulty & scoring helpers ---


    def _activate_phenix_from_input(self, ship=None):
        """Toggle Phenix: activate if ready, or cancel early (keep remaining gauge)."""
        if not self.started or self.paused or self.game_over or self.attract_mode:
            return
        if self.stage_transition is not None:
            return
        ships = [ship] if ship is not None else self._ships()
        for s in ships:
            if not s or not s.alive:
                continue
            if s.is_phenix:
                if s.cancel_phenix():
                    self.shake_amount = max(self.shake_amount, 3.0)
                return
            if s.try_activate_phenix():
                self.shake_amount = max(self.shake_amount, 4.0)
                return


    def _draw_cheat_message(self):
        """Centered, large, readable cheat / stage / 1UP banner."""
        if self.cheat_msg_timer <= 0 or not self.cheat_msg:
            return
        pulse = 0.55 + 0.45 * abs(math.sin(self.cheat_msg_timer * 5.0))
        msg = self.cheat_msg
        # Color by type (kind is language-agnostic)
        kind = getattr(self, "cheat_kind", "")
        if kind == "1up" or "1UP" in msg.upper():
            blink = int(self.cheat_msg_timer * 5) % 2 == 0
            col = (255, 255, 180) if blink else (255, 200, 60)
        elif kind == "phen" or "PHENIX" in msg.upper():
            col = (255, int(140 + 80 * pulse), 40)
        elif kind == "live":
            col = (120, 255, 160)
        elif kind == "stage":
            col = (180, 200, 255)
        else:
            col = (255, 220, 100)

        cm = self.big_font.render(msg, True, col)
        cx = BASE_WIDTH // 2
        cy = BASE_HEIGHT // 2
        # Dark plate behind for readability
        pad_x, pad_y = 28, 16
        plate = pygame.Surface((cm.get_width() + pad_x * 2, cm.get_height() + pad_y * 2), pygame.SRCALPHA)
        pygame.draw.rect(plate, (0, 0, 0, 160), plate.get_rect(), border_radius=8)
        self.game_surface.blit(plate, (cx - plate.get_width() // 2, cy - plate.get_height() // 2))
        # Glow
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1)):
            g = self.big_font.render(msg, True, col)
            g.set_alpha(int(50 + 60 * pulse))
            self.game_surface.blit(g, (cx - cm.get_width() // 2 + ox, cy - cm.get_height() // 2 + oy))
        self.game_surface.blit(cm, (cx - cm.get_width() // 2, cy - cm.get_height() // 2))

    def _add_score(self, ship, pts):
        pts = int(pts)
        if ship is not None:
            ship.score = getattr(ship, "score", 0) + pts
        if getattr(self, "play_mode", "solo") == "coop":
            self.score = sum(getattr(s, "score", 0) for s in self._ships())
        else:
            self.score += pts

    def _draw_phenix_gauge(self, ship=None, gx=18, gy=100, align="left"):
        """HUD: 10-segment Phenix gauge + fire around label from level 3."""
        if ship is None:
            ship = getattr(self, "player", None)
        if ship is None:
            return
        gauge = float(getattr(ship, "phenix_gauge", 0))
        level = int(gauge)  # for label threshold
        blue = getattr(ship, "palette", "red") == "blue"
        seg_w, seg_h, gap = 14, 10, 3
        total_h = 10 * (seg_h + gap)
        pygame.draw.rect(self.game_surface, (20, 20, 35), (gx - 3, gy - 3, seg_w + 6, total_h + 3), border_radius=3)
        active = getattr(ship, "is_phenix", False)
        for i in range(10):
            y = gy + (9 - i) * (seg_h + gap)
            # How much of this segment is filled (supports fractional drain)
            seg_fill = max(0.0, min(1.0, gauge - i))
            if seg_fill > 0:
                t = (i + 1) / 10.0
                if blue:
                    if active:
                        col = (int(40 + 20 * t), int(140 + 80 * t), 255)
                    else:
                        col = (
                            int(40 * (1.0 - t)),
                            int(80 + 100 * t),
                            int(255 * min(1.0, 0.5 + t * 0.5)),
                        )
                elif active:
                    col = (255, int(140 + 80 * t), int(30 + 20 * t))
                else:
                    col = (
                        int(255 * min(1.0, 0.5 + t * 0.5)),
                        int(80 + 100 * t),
                        int(40 * (1.0 - t)),
                    )
                fh = max(1, int(seg_h * seg_fill))
                pygame.draw.rect(
                    self.game_surface, col,
                    (gx, y + (seg_h - fh), seg_w, fh),
                    border_radius=2,
                )
            else:
                pygame.draw.rect(self.game_surface, (40, 40, 55), (gx, y, seg_w, seg_h), border_radius=2)

        lab_y = gy + total_h + 6
        tc = self.text_cache
        right = align == "right" or gx > BASE_WIDTH // 2
        if level >= 3:
            ticks = pygame.time.get_ticks() * 0.001
            pulse = 0.75 + 0.25 * abs(math.sin(ticks * 4.0))
            power = (level - 3) / 7.0
            if blue:
                g_q = int((180 + 50 * power * pulse) // 8) * 8
                lab = tc.get(self.font, "PHENIX", (140, g_q, 255))
                glow = tc.get(self.font, "PHENIX", (80, 180, 255))
            else:
                g_q = int((140 + 80 * power * pulse) // 8) * 8
                b_q = int((40 + 40 * power) // 8) * 8
                lab = tc.get(self.font, "PHENIX", (255, g_q, b_q))
                glow_g = int((100 + 60 * power) // 8) * 8
                glow = tc.get(self.font, "PHENIX", (255, glow_g, 20))
            lab_x = (gx + seg_w - lab.get_width()) if right else (gx - 2)
            alpha = int(50 + 40 * power * pulse)
            glow.set_alpha(alpha)
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                self.game_surface.blit(glow, (lab_x + ox, lab_y + oy))
            self.game_surface.blit(lab, (lab_x, lab_y))
        else:
            lab = tc.get(self.font, "PHENIX", (100, 140, 180) if blue else (120, 110, 100))
            lab_x = (gx + seg_w - lab.get_width()) if right else (gx - 2)
            self.game_surface.blit(lab, (lab_x, lab_y))

        num_col = ((180, 230, 255) if blue else (255, 220, 160)) if level >= 3 or active else (140, 140, 150)
        num = tc.get(self.font, str(int(round(gauge))), num_col)
        self.game_surface.blit(num, (gx + seg_w // 2 - num.get_width() // 2, gy - 18))





    @staticmethod
    def format_score(n):
        """Thousand-separated score for display (spaces)."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        s = f"{n:,}".replace(",", " ")
        return s

    def _coop_icon_surf(self):
        """Lazy-load the two-player HUD pictogram."""
        icon = getattr(self, "_coop_icon", None)
        if icon is None:
            path = asset_path("sprites", "icon_coop.png")
            try:
                icon = pygame.image.load(path).convert_alpha()
            except Exception:
                icon = pygame.Surface((22, 28), pygame.SRCALPHA)
            self._coop_icon = icon
        return icon

    def _draw_coop_mark(self, surface, x, y, col=(170, 185, 210)):
        """Two-player mark, vertically centered on the score row."""
        icon = self._coop_icon_surf()
        surface.blit(icon, (x, y))

    def _draw_hs_row(self, surface, y, rank, name, score, col, score_right_x=None, coop=False):
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
        if coop:
            icon = self._coop_icon_surf()
            # Column just right of the score, vertically centered on the line
            ix = score_right_x + 12
            iy = y + (self.font.get_height() - icon.get_height()) // 2
            self._draw_coop_mark(surface, ix, iy)

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
        if self.difficulty == "novice":
            self.player.phenix_sec_per_point = 1.0
            self.player.phenix_min_gauge = 1
            self.player.phenix_gauge = 1
        else:
            self.player.phenix_sec_per_point = 0.6
            self.player.phenix_min_gauge = 0
        if self.phenix_cheat:
            self.player.phenix_auto_refill = True
            self.player.phenix_gauge = 10
        if self.player.infinite_lives:
            self.player.lives = 99
        elif self.difficulty == "novice":
            self.player.lives = 5
        else:
            self.player.lives = 3
        # Any active cheat (LVL / LIVE / PHEN) blocks high scores + shows banner
        self.used_cheat = bool(
            self.phenix_cheat
            or getattr(self.player, "infinite_lives", False)
            or getattr(self.player, "phenix_auto_refill", False)
        )
        self.bosses_defeated = 0
        self.life_flash_timer = 0.0
        self.life_flash_index = -1
        self.stage = 1
        self._setup_stage(1)

    def _capture_slot(self):
        """Snapshot the active run so another player can take over."""
        return {
            "player": self.player,
            "formation": self.formation,
            "boss_saucer": self.boss_saucer,
            "score": self.score,
            "stage": self.stage,
            "bosses_defeated": self.bosses_defeated,
            "life_thresholds": list(self.life_thresholds),
            "boss_bird_timer": getattr(self, "boss_bird_timer", 0.0),
            "eliminated": bool(getattr(self.player, "alive", True) is False),
        }

    def _apply_slot(self, slot):
        """Restore a player's independent world."""
        if not slot:
            return
        self.player = slot["player"]
        self.formation = slot["formation"]
        self.boss_saucer = slot["boss_saucer"]
        self.score = slot["score"]
        self.stage = slot["stage"]
        self.bosses_defeated = slot["bosses_defeated"]
        self.life_thresholds = list(slot["life_thresholds"])
        self.boss_bird_timer = slot.get("boss_bird_timer", 1.2)
        self.stage_transition = None
        self.transition_timer = 0.0
        self.explosions = []
        self.shake_amount = 0.0
        # Fresh ship placement; keep gauge / lives / phenix flags on the Player object
        self.player.x = BASE_WIDTH // 2
        self.player.y = BASE_HEIGHT - 95
        self.player.destroy_bullet()
        self.player.dying = False
        if self.player.lives > 0 or getattr(self.player, "infinite_lives", False):
            self.player.alive = True
        self.player.invulnerable = 1.1
        self.player.just_lost_life = False
        self.player.clear_wall_status()
        self.tesla_fx = None
        self.sounds.play_electric(False)
        if getattr(self.player, "is_phenix", False):
            try:
                self.player.end_phenix(grant_invuln=True, keep_gauge=True)
            except Exception:
                pass

    def _save_current_slot(self):
        if not self.hotseat:
            return
        cap = self._capture_slot()
        if self.slots[self.current_p]:
            cap["eliminated"] = self.slots[self.current_p].get("eliminated", False)
        self.slots[self.current_p] = cap

    def _init_hotseat_slots(self):
        """Build two independent stage-1 runs (same difficulty / cheat flags)."""
        self.slots = []
        for i in range(2):
            self.player = Player(BASE_WIDTH // 2, BASE_HEIGHT - 95)
            self.player.sounds = self.sounds
            self.player.pid = i + 1
            if i == 1:
                self.player.apply_blue_palette()
            self.formation = EnemyFormation()
            self.boss_saucer = None
            self.score = 0
            self.stage = 1
            self.explosions = []
            self.life_thresholds = [(1337, False), (8086, False)]
            self._apply_difficulty_start()
            slot = self._capture_slot()
            slot["eliminated"] = False
            self.slots.append(slot)

    def _other_p(self):
        return 1 - self.current_p

    def _slot_still_playing(self, idx):
        sl = self.slots[idx] if 0 <= idx < 2 else None
        if not sl or sl.get("eliminated"):
            return False
        p = sl.get("player")
        if p is None:
            return False
        return bool(getattr(p, "infinite_lives", False) or getattr(p, "lives", 0) > 0 or p.alive)

    def _hotseat_begin_wait(self, next_idx):
        """Interstitial: wait for any key before loading the other player's world."""
        self._save_current_slot()
        if self.player:
            self.player.clear_wall_status()
        outgoing = self.slots[self.current_p] if self.slots[self.current_p] else None
        if outgoing and outgoing.get("player"):
            outgoing["player"].clear_wall_status()
        self.hotseat_wait = True
        self.hotseat_next = next_idx
        self.input_grace = 0.28
        self.paused = False
        self.tesla_fx = None
        self.sounds.play_electric(False)

    def _hotseat_resume(self):
        if not self.hotseat_wait:
            return
        self.hotseat_wait = False
        self.current_p = self.hotseat_next
        self._apply_slot(self.slots[self.current_p])
        self.input_grace = 0.35
        self.game_over = False

    def _hotseat_arm_hold(self, pending, duration):
        """Wait so the ship explosion is visible before overlay / game over."""
        if self.hotseat_hold > 0:
            return
        self.hotseat_hold = duration
        self.hotseat_pending = pending
        if self.player:
            self.player.just_lost_life = False

    def _hotseat_finish_hold(self):
        pending = self.hotseat_pending
        self.hotseat_pending = None
        self.hotseat_hold = 0.0
        if pending == "switch":
            self._hotseat_try_switch()
        elif pending == "eliminated":
            self._hotseat_player_eliminated()
        elif pending == "gameover":
            self.game_over = True
            self._begin_highscore_flow()

    def _hotseat_try_switch(self):
        """After a lost life (ship still has lives): other player takes their own run."""
        other = self._other_p()
        if self._slot_still_playing(other):
            self._hotseat_begin_wait(other)
        # else keep playing — opponent already eliminated

    def _hotseat_player_eliminated(self):
        """Current player has no lives left."""
        self._save_current_slot()
        if self.slots[self.current_p]:
            self.slots[self.current_p]["eliminated"] = True
        other = self._other_p()
        if self._slot_still_playing(other):
            self._hotseat_begin_wait(other)
        else:
            self.game_over = True
            self._begin_highscore_flow()

    def _ships(self):
        """Active ships this frame (1 in solo/hotseat, 2 in coop)."""
        out = []
        if self.player:
            out.append(self.player)
        if getattr(self, "play_mode", "solo") == "coop" and getattr(self, "player2", None):
            out.append(self.player2)
        return out

    def _living_ships(self):
        return [p for p in self._ships() if p.alive and not p.dying]

    def _coop_bindings(self):
        """Assign kb/pad for coop: 2 pads, or kb+pad, or split keyboard."""
        joys = []
        try:
            pygame.joystick.init()
            for i in range(pygame.joystick.get_count()):
                j = pygame.joystick.Joystick(i)
                j.init()
                joys.append(j)
        except Exception:
            joys = []
        self.joysticks = joys
        if len(joys) >= 2:
            return ("pad", joys[0]), ("pad", joys[1])
        if len(joys) == 1:
            # P1 pad, P2 same keyboard layout as 1-player
            return ("pad", joys[0]), ("solo", None)
        return ("kb1", None), ("kb2", None)

    def _start_coop(self):
        self.play_mode = "coop"
        self.hotseat = False
        self.player2 = Player(BASE_WIDTH // 2 + 70, BASE_HEIGHT - 95)
        self.player = Player(BASE_WIDTH // 2 - 70, BASE_HEIGHT - 95)
        self.player.pid = 1
        self.player2.pid = 2
        self.player.sounds = self.sounds
        self.player2.sounds = self.sounds
        self.player2.apply_blue_palette()
        self.player.use_shared_lives = True
        self.player2.use_shared_lives = True
        b1, b2 = self._coop_bindings()
        self.player.input_scheme = b1[0]
        self.player2.input_scheme = b2[0]
        self.player._joy = b1[1]
        self.player2._joy = b2[1]
        if b1[0] == "pad":
            self.joystick = b1[1]
        elif b2[0] == "pad":
            self.joystick = b2[1]
        self.lives_shared = 5
        self._apply_difficulty_start()
        # Shared pool overrides per-difficulty lives
        self.lives_shared = 5
        self.player.lives = 5
        self.player2.lives = 5
        self.player.use_shared_lives = True
        self.player2.use_shared_lives = True
        self.player2.phenix_sec_per_point = self.player.phenix_sec_per_point
        self.player2.phenix_min_gauge = self.player.phenix_min_gauge
        self.player.score = 0
        self.player2.score = 0
        self.player.life_flags = [False, False]
        self.player2.life_flags = [False, False]
        self.player2.sounds = self.sounds
        self.started = True
        self.input_grace = 0.35

    def _on_coop_life_lost(self, ship):
        if getattr(self, "play_mode", "") != "coop":
            return
        self.lives_shared = max(0, self.lives_shared - 1)
        for p in self._ships():
            p.lives = self.lives_shared
        if self.lives_shared <= 0 and not ship.dying:
            ship.lives = 0
            ship.dying = True
            ship.death_timer = 0.0
            ship.invulnerable = 0.0
            ship.rumble(1.0, 1.0, 640)

    def _check_extra_lives(self):

        """Award a life when crossing score thresholds (once each)."""
        if self.play_mode == "coop":
            for ship in self._ships():
                flags = getattr(ship, "life_flags", None)
                if not flags or len(flags) < len(self.life_thresholds):
                    ship.life_flags = [False] * len(self.life_thresholds)
                    flags = ship.life_flags
                for i, (threshold, _) in enumerate(self.life_thresholds):
                    if not flags[i] and getattr(ship, "score", 0) >= threshold:
                        flags[i] = True
                        self.lives_shared += 1
                        for s in self._ships():
                            s.lives = self.lives_shared
                        self.sounds.play("1up")
                        self.cheat_msg = t("one_up")
                        self.cheat_kind = "1up"
                        self.cheat_msg_timer = 5.0
                        self.life_flash_timer = 4.0
                        self.life_flash_index = max(0, self.lives_shared - 1)
            return
        for i, (threshold, awarded) in enumerate(self.life_thresholds):
            if not awarded and self.score >= threshold:
                self.life_thresholds[i] = (threshold, True)
                if self.player.alive:
                    self.player.lives += 1
                    self.sounds.play("1up")
                    self.cheat_msg = t("one_up")
                    self.cheat_kind = "1up"
                    self.cheat_msg_timer = 5.0
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
        self.cheat_msg = t("cheat_stage").format(n=stage)
        self.cheat_kind = "stage"
        self.cheat_msg_timer = 5.0
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
        self.hs_queue = []
        self.hs_slot_label = 1
        block = (self.difficulty == "novice"
                 or getattr(self, "used_cheat", False)
                 or getattr(self, "phenix_cheat", False))
        if self.hotseat and self.slots[0] and self.slots[1]:
            # Show last player's score as default; queue every qualifying run
            self.score = max(self.slots[0]["score"], self.slots[1]["score"])
            if not block:
                for i, sl in enumerate(self.slots):
                    if sl and is_highscore(sl["score"], self.hs_entries):
                        self.hs_queue.append(i)
            if self.hs_queue:
                self._hs_prepare_entry(self.hs_queue.pop(0))
            else:
                self.hs_phase = "table"
            return
        # Novice / cheat: view table only, no name entry
        if block:
            self.hs_phase = "table"
        elif is_highscore(self.score, self.hs_entries):
            self.hs_phase = "enter"
        else:
            self.hs_phase = "table"

    def _hs_prepare_entry(self, slot_idx):
        sl = self.slots[slot_idx]
        self.score = sl["score"]
        self.hs_slot_label = slot_idx + 1
        self.hs_name = ["A", "A", "A"]
        self.hs_char_index = 0
        self.hs_submitted = False
        self.hs_phase = "enter"

    def _submit_highscore(self):
        if self.hs_submitted:
            return
        name = "".join(self.hs_name)
        self.hs_entries = insert_score(
            name, self.score, coop=(getattr(self, "play_mode", "solo") == "coop")
        )
        self.hs_submitted = True
        if self.hs_queue:
            self._hs_prepare_entry(self.hs_queue.pop(0))
        else:
            self.hs_phase = "table"

    def _hs_cycle_letter(self, direction):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        cur = self.hs_name[self.hs_char_index]
        idx = alphabet.find(cur)
        if idx < 0:
            idx = 0
        idx = (idx + direction) % len(alphabet)
        self.hs_name[self.hs_char_index] = alphabet[idx]



    def _bezel_asset_names(self, style=None):
        """Return (left_file, right_file) for a bezel style id."""
        style = style if style is not None else getattr(self, "bezel_style", "phoenix")
        mapping = {
            "phoenix": ("bezel_left.png", "bezel_right.png"),
            "tesla": ("bezel_tesla_left.png", "bezel_tesla_right.png"),
            "blue": ("bezel_blue_left.png", "bezel_blue_right.png"),
            "fire": ("bezel_fire_left.png", "bezel_fire_right.png"),
        }
        return mapping.get(style, (None, None))

    def _load_bezel_images(self):
        """Load left/right arcade bezel artwork for the current style."""
        self.bezel_left_img = None
        self.bezel_right_img = None
        style = getattr(self, "bezel_style", "phoenix")
        if style in (None, "", "off"):
            self._invalidate_present_cache()
            return
        left_name, right_name = self._bezel_asset_names(style)
        try:
            if left_name:
                lp = asset_path("sprites", left_name)
                if os.path.exists(lp):
                    self.bezel_left_img = pygame.image.load(lp).convert()
            if right_name:
                rp = asset_path("sprites", right_name)
                if os.path.exists(rp):
                    self.bezel_right_img = pygame.image.load(rp).convert()
            self._invalidate_present_cache()
        except Exception as e:
            print("Bezel images not loaded:", e)

    def _layout_viewport(self):
        """Center the 16:9 game area in the real window.

        Bezel art only in fullscreen on displays wider than 16:9.
        Windowed and borderless: never bezel (letterbox black only if needed).
        """
        if not getattr(self, "screen", None):
            return
        mode = getattr(self, "display_mode", "window")
        sw, sh = self.screen.get_size()
        if mode == "window" or sh <= 0 or sw <= 0:
            self.view_rect = pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT)
            self.bezel_active = False
            return

        scale = min(sw / float(BASE_WIDTH), sh / float(BASE_HEIGHT))
        gw = max(1, int(BASE_WIDTH * scale))
        gh = max(1, int(BASE_HEIGHT * scale))
        target_aspect = BASE_WIDTH / float(BASE_HEIGHT)
        if gw / float(max(1, gh)) > target_aspect:
            gw = max(1, int(gh * target_aspect))
        else:
            gh = max(1, int(gw / target_aspect))
        gx = max(0, (sw - gw) // 2)
        gy = max(0, (sh - gh) // 2)
        self.view_rect = pygame.Rect(gx, gy, gw, gh)

        aspect = sw / float(sh)
        style = getattr(self, "bezel_style", "phoenix")
        self.bezel_active = False

    def _init_bezel_stars(self):
        """Starfield particles for left/right bezel panels."""
        import random as _r
        self._bezel_stars = []
        if not getattr(self, "screen", None):
            return
        sw, sh = self.screen.get_size()
        for _ in range(120):
            self._bezel_stars.append({
                "x": _r.uniform(0, sw),
                "y": _r.uniform(0, sh),
                "s": _r.uniform(0.4, 2.2),
                "v": _r.uniform(12, 55),
                "a": _r.randint(80, 220),
            })

    def _update_bezel_stars(self, dt):
        if not self._bezel_stars:
            return
        sh = self.screen.get_height()
        for st in self._bezel_stars:
            st["y"] += st["v"] * dt
            if st["y"] > sh:
                st["y"] = -2
                st["x"] = __import__("random").uniform(0, self.screen.get_width())

    def _invalidate_present_cache(self):
        """Call when display mode / bezel style / window size changes."""
        self._bezel_blit_left = None
        self._bezel_blit_right = None
        self._bezel_cache_key = None
        self._present_size = None

    def _ensure_bezel_cache(self):
        """Scale bezel art once per panel size (not every frame)."""
        if not self.bezel_active:
            self._bezel_blit_left = None
            self._bezel_blit_right = None
            self._bezel_cache_key = None
            return
        sw, sh = self.screen.get_size()
        vr = self.view_rect
        left_w = max(0, vr.x)
        right_w = max(0, sw - vr.right)
        key = (left_w, right_w, sh, getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0))
        if key == getattr(self, "_bezel_cache_key", None):
            return
        self._bezel_cache_key = key
        self._bezel_blit_left = None
        self._bezel_blit_right = None

        def cover(img, panel_w, panel_h, align_right):
            if img is None or panel_w < 8 or panel_h < 8:
                return None
            iw, ih = img.get_width(), img.get_height()
            scale = max(panel_w / float(iw), panel_h / float(ih))
            tw = max(1, int(iw * scale))
            th = max(1, int(ih * scale))
            # Fast scale once; convert for faster blit
            scaled = pygame.transform.scale(img, (tw, th)).convert()
            # Same pixel format as the display → blit without conversion
            try:
                if getattr(self, "screen", None) is not None:
                    surf = pygame.Surface((panel_w, panel_h), 0, self.screen)
                else:
                    surf = pygame.Surface((panel_w, panel_h)).convert()
            except Exception:
                surf = pygame.Surface((panel_w, panel_h))
            if align_right:
                x = panel_w - tw
            else:
                x = 0
            y = (panel_h - th) // 2
            surf.blit(scaled, (x, y))
            return surf

        self._bezel_blit_left = cover(
            getattr(self, "bezel_left_img", None), left_w, sh, True
        )
        self._bezel_blit_right = cover(
            getattr(self, "bezel_right_img", None), right_w, sh, False
        )

    def _draw_arcade_bezels(self):
        """Blit cached left/right bezel panels (no per-frame scaling)."""
        if not self.bezel_active:
            return
        self._ensure_bezel_cache()
        vr = self.view_rect
        if self._bezel_blit_left is not None:
            self.screen.blit(self._bezel_blit_left, (0, 0))
        if self._bezel_blit_right is not None:
            self.screen.blit(self._bezel_blit_right, (vr.right, 0))

    def _present_game_scaled(self, vr, dest_x, dest_y):
        """Scale logical canvas into the window game band."""
        if vr.width == BASE_WIDTH and vr.height == BASE_HEIGHT:
            self.screen.blit(self.game_surface, (dest_x, dest_y))
            return
        key = (vr.width, vr.height)
        buf = getattr(self, "_scaled_game_buf", None)
        if buf is None or buf.get_size() != key:
            try:
                if self.screen is not None:
                    self._scaled_game_buf = pygame.Surface(key, 0, self.screen)
                else:
                    self._scaled_game_buf = pygame.Surface(key).convert()
            except Exception:
                self._scaled_game_buf = pygame.Surface(key)
            buf = self._scaled_game_buf
        pygame.transform.scale(self.game_surface, key, buf)
        self.screen.blit(buf, (dest_x, dest_y))

    def _prepare_monitor_env(self):
        """Set SDL window position for the selected monitor before set_mode."""
        try:
            import os
            mons = self._list_monitors()
            idx = int(getattr(self, "monitor_index", 0) or 0)
            if idx < 0 or idx >= len(mons):
                idx = 0
            m = mons[idx]
            mon_w, mon_h = int(m[1]), int(m[2])
            mon_x = int(m[3]) if len(m) >= 5 else 0
            mon_y = int(m[4]) if len(m) >= 5 else 0
            mode = getattr(self, "display_mode", "fullscreen")
            if mode == "window":
                x = mon_x + max(0, (mon_w - BASE_WIDTH) // 2)
                y = mon_y + max(0, (mon_h - BASE_HEIGHT) // 2)
            else:
                x, y = mon_x, mon_y
            os.environ["SDL_VIDEO_WINDOW_POS"] = f"{x},{y}"
            os.environ["SDL_VIDEO_CENTERED"] = "0"
        except Exception as e:
            print("prepare monitor env:", e)

    def _list_monitors(self):
        """List monitors as (index, w, h, x, y).

        Index 0 is always the primary monitor (Windows) / first desktop size.
        User-facing "Moniteur 1" = index 0.
        """
        raw = self._query_monitors_raw()
        if not raw:
            info = pygame.display.Info()
            w = int(getattr(info, "current_w", BASE_WIDTH) or BASE_WIDTH)
            h = int(getattr(info, "current_h", BASE_HEIGHT) or BASE_HEIGHT)
            raw = [(max(BASE_WIDTH, w), max(BASE_HEIGHT, h), 0, 0, True)]
        # Primary first, then left-to-right
        raw.sort(key=lambda m: (0 if m[4] else 1, m[2], m[3]))
        out = []
        for i, (w, h, x, y, _prim) in enumerate(raw):
            out.append((i, int(w), int(h), int(x), int(y)))
        return out

    def _query_monitors_raw(self):
        """Return list of (w, h, x, y, is_primary)."""
        # Prefer Win32 for accurate primary + origins
        try:
            import sys
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", RECT),
                        ("rcWork", RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                MONITORINFOF_PRIMARY = 1
                rects = []
                MONITORENUMPROC = ctypes.WINFUNCTYPE(
                    ctypes.c_int,
                    wintypes.HMONITOR,
                    wintypes.HDC,
                    ctypes.POINTER(RECT),
                    wintypes.LPARAM,
                )

                def _cb(hmon, hdc, lprect, lparam):
                    try:
                        mi = MONITORINFO()
                        mi.cbSize = ctypes.sizeof(MONITORINFO)
                        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                            r = mi.rcMonitor
                            w = int(r.right - r.left)
                            h = int(r.bottom - r.top)
                            x, y = int(r.left), int(r.top)
                            prim = bool(mi.dwFlags & MONITORINFOF_PRIMARY)
                            rects.append((w, h, x, y, prim))
                    except Exception:
                        pass
                    return 1

                cb = MONITORENUMPROC(_cb)
                self._mon_enum_cb = cb
                ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, 0)
                if rects:
                    return rects
        except Exception as e:
            print("Win32 monitor query:", e)

        # Fallback: pygame sizes only (primary = index 0)
        try:
            sizes = list(pygame.display.get_desktop_sizes())
        except Exception:
            sizes = []
        out = []
        for i, (w, h) in enumerate(sizes):
            out.append((int(w), int(h), 0, 0, i == 0))
        return out

    def _monitor_origins(self, count):
        """Compat helper — origins from _list_monitors order."""
        mons = self._list_monitors()
        origins = [(m[3], m[4]) for m in mons]
        while len(origins) < count:
            origins.append((0, 0))
        return origins[:count]

    def _pick_monitor(self):
        """Return (index, width, height, x, y). Default = monitor 1 (index 0, primary)."""
        mons = self._list_monitors()
        idx = int(getattr(self, "monitor_index", 0) or 0)
        if idx < 0 or idx >= len(mons):
            self.monitor_index = 0
            return mons[0]
        return mons[idx]

    def _pick_monitor_size(self):
        m = self._pick_monitor()
        return m[1], m[2]

    def _open_display(self):
        """Create the display surface once (or recreate on Options change)."""
        try:
            mon = self._pick_monitor()
            mon_i = int(mon[0])
            mon_w, mon_h = int(mon[1]), int(mon[2])
            mon_x = int(mon[3]) if len(mon) >= 5 else 0
            mon_y = int(mon[4]) if len(mon) >= 5 else 0
        except Exception as e:
            print("pick monitor failed:", e)
            mon_i, mon_w, mon_h, mon_x, mon_y = 0, BASE_WIDTH, BASE_HEIGHT, 0, 0

        base_flags = pygame.DOUBLEBUF | pygame.HWSURFACE
        mode = getattr(self, "display_mode", "fullscreen")

        def _set(size, flags, display=None):
            try:
                if display is not None:
                    return pygame.display.set_mode(size, flags, display=int(display))
            except TypeError:
                pass
            except pygame.error as e:
                print("set_mode(display=) failed:", e)
            return pygame.display.set_mode(size, flags)

        # Position hint for the next window
        try:
            import os
            if mode == "window":
                px = mon_x + max(0, (mon_w - BASE_WIDTH) // 2)
                py = mon_y + max(0, (mon_h - BASE_HEIGHT) // 2)
            else:
                px, py = mon_x, mon_y
            os.environ["SDL_VIDEO_WINDOW_POS"] = f"{px},{py}"
            os.environ["SDL_VIDEO_CENTERED"] = "0"
        except Exception:
            pass

        try:
            if mode == "window":
                self.screen = _set((BASE_WIDTH, BASE_HEIGHT), base_flags, mon_i)
            elif mode == "borderless":
                self.screen = _set((mon_w, mon_h), base_flags | pygame.NOFRAME, mon_i)
            else:
                try:
                    self.screen = _set(
                        (mon_w, mon_h), base_flags | pygame.FULLSCREEN, mon_i
                    )
                except pygame.error:
                    try:
                        self.screen = _set(
                            (0, 0), base_flags | pygame.FULLSCREEN, mon_i
                        )
                    except pygame.error:
                        # Last resort: windowed (never leave screen unset)
                        self.display_mode = "window"
                        self.screen = _set((BASE_WIDTH, BASE_HEIGHT), base_flags, mon_i)
        except Exception as e:
            print("open display failed, windowed fallback:", e)
            import traceback
            traceback.print_exc()
            self.display_mode = "window"
            self.screen = pygame.display.set_mode(
                (BASE_WIDTH, BASE_HEIGHT), base_flags
            )

        try:
            pygame.mouse.set_visible(self.display_mode == "window")
        except Exception:
            pass

    def apply_display_mode(self):
        """Apply window/fullscreen/borderless from Options (safe recreate)."""
        try:
            self._prepare_monitor_env()
            self._open_display()
        except Exception as e:
            print("apply_display_mode failed:", e)
            import traceback
            traceback.print_exc()
            try:
                self.display_mode = "window"
                self.screen = pygame.display.set_mode(
                    (BASE_WIDTH, BASE_HEIGHT), pygame.DOUBLEBUF | pygame.HWSURFACE
                )
            except Exception as e2:
                print("windowed fallback failed:", e2)
                return

        try:
            pygame.display.set_caption(f"Phenix Rebirth  [{getattr(self, 'fps_target', 60)} Hz]")
            pygame.mouse.set_visible(self.display_mode == "window")
        except Exception:
            pass

        self._scaled_cache = None
        self._scaled_cache_size = None
        self._scaled_game_buf = None
        self._present_size = None
        try:
            self._invalidate_present_cache()
        except Exception:
            pass
        try:
            self._layout_viewport()
        except Exception as e:
            print("layout failed:", e)
        try:
            if getattr(self, "game_surface", None) is not None:
                self.game_surface = self.game_surface.convert()
        except Exception:
            pass
        try:
            if getattr(self, "bezel_active", False):
                self._ensure_bezel_cache()
        except Exception as e:
            print("bezel rebuild failed:", e)
        self._bezel_stars = []

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
            "bezel_style": getattr(self, "bezel_style", "phoenix"),
            "monitor_index": int(getattr(self, "monitor_index", 0) or 0),
            "sfx_volume": self.sfx_volume,
            "music_volume": self.music_volume,
            "rumble_level": int(getattr(self, "rumble_level", 3)),
            "autofire": bool(getattr(self, "autofire", True)),
            "language": self.language,
            "show_fps": self.show_fps,
            "scanlines": int(getattr(self, "scanlines", 0) or 0),
        })

    # --- Menu navigation ---
    def _is_menu_up(self, key):
        # W = QWERTY, Z = AZERTY (ZQSD)
        return key in (pygame.K_UP, pygame.K_w, pygame.K_z)

    def _is_menu_down(self, key):
        return key in (pygame.K_DOWN, pygame.K_s)

    def _is_menu_confirm(self, key):
        # Enter, Space and fire keys all validate
        return key in (
            pygame.K_RETURN, pygame.K_KP_ENTER,
            pygame.K_SPACE, pygame.K_LCTRL, pygame.K_RCTRL,
        )

    def _menu_nav(self, direction):
        """direction: -1 up, +1 down"""
        if self.menu_screen == "main":
            n = 6  # Jouer, Difficulte, Options, High Scores, Credits, Quitter
        elif self.menu_screen == "reset_confirm":
            n = 2  # Oui, Non
        else:
            n = len(self._options_spec())
        self.menu_index = (self.menu_index + direction) % n

    def _focus_option(self, name):
        spec = self._options_spec()
        self.menu_index = spec.index(name) if name in spec else 0


    def _options_labels(self):
        """Human-readable option rows matching _options_spec order."""
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
        sl = int(getattr(self, "scanlines", 0) or 0)
        scan_label = t("no") if sl <= 0 else f"{t('opt_scanlines')} {sl}"
        lang_label = next((n for c, n in LANGS if c == self.language), self.language)
        bezel_keys = {s[0]: s[1] for s in getattr(self, "BEZEL_STYLES", [("off", "bezel_off"), ("phoenix", "bezel_phoenix")])}
        bezel_label = t(bezel_keys.get(getattr(self, "bezel_style", "phoenix"), "bezel_phoenix"))
        mapping = {
            "control": f"{t('opt_control')} :  <  {ctrl}  >",
            "autofire": f"{t('opt_autofire')} :  <  {t('yes') if getattr(self, 'autofire', True) else t('no')}  >",
            "sfx": f"{t('opt_sfx')} :  <  {vol_pct}%  >",
            "music": f"{t('opt_music')} :  <  {mus_pct}%  >",
            "rumble": f"{t('opt_rumble')} :  <  {int(getattr(self, 'rumble_level', 3))} / 5  >",
            "display": f"{t('opt_display')} :  <  {disp}  >",
            "bezel": f"{t('opt_bezel')} :  <  {bezel_label}  >",
            "fps": f"{t('opt_fps')} :  <  {fps_label}  >",
            "scanlines": f"{t('opt_scanlines')} :  <  {('OFF' if sl <= 0 else str(sl))}  >",
            "language": f"{t('opt_language')} :  <  {lang_label}  >",
            "reset_hs": t("opt_reset_hs"),
            "back": t("opt_back"),
        }
        return [mapping[k] for k in self._options_spec() if k in mapping]

    def _options_spec(self):
        """Ordered option ids (bezel / monitor only when relevant)."""
        items = ["control", "autofire", "sfx", "music", "rumble", "display"]
        mode = getattr(self, "display_mode", "fullscreen")
        if mode == "fullscreen":
            items.append("bezel")
        items.extend(["fps", "scanlines", "language", "reset_hs", "back"])
        return items

    def _menu_adjust(self, direction):
        """direction: -1 left, +1 right — change current option value"""
        if self.menu_screen == "main":
            if self.menu_index == 1:
                idx = self.DIFFICULTIES.index(self.difficulty)
                self.difficulty = self.DIFFICULTIES[(idx + direction) % len(self.DIFFICULTIES)]
            return
        if self.menu_screen != "options":
            return
        spec = self._options_spec()
        if self.menu_index < 0 or self.menu_index >= len(spec):
            return
        key = spec[self.menu_index]
        if key == "control":
            self.input_mode = "keyboard" if self.input_mode == "gamepad" else "gamepad"
            if self.input_mode == "gamepad" and not self.gamepad_detected:
                self.input_mode = "keyboard"
            self.save_settings()
        elif key == "autofire":
            self.autofire = not bool(getattr(self, "autofire", True))
            self.save_settings()
        elif key == "sfx":
            self.sfx_volume = max(0.0, min(1.0, self.sfx_volume + direction * 0.1))
            self.sounds.set_master_volume(self.sfx_volume)
            self.sounds.play("shoot")
            self.save_settings()
        elif key == "music":
            self.music_volume = max(0.0, min(1.0, self.music_volume + direction * 0.1))
            self.sounds.set_music_volume(self.music_volume)
            self.save_settings()
        elif key == "rumble":
            self.rumble_level = max(0, min(5, int(getattr(self, "rumble_level", 3)) + direction))
            if self.player:
                self.player.rumble_level = self.rumble_level
                self.player._joy = self.joystick
                self.player._rumble_enabled = True
                if self.rumble_level > 0:
                    self.player.rumble(0.35, 0.55, 180)
            self.save_settings()
        elif key == "display":
            modes = ["window", "fullscreen", "borderless"]
            idx = modes.index(self.display_mode) if self.display_mode in modes else 0
            self.display_mode = modes[(idx + direction) % len(modes)]
            self.apply_display_mode()
            self.menu_index = min(self.menu_index, len(self._options_spec()) - 1)
            self.save_settings()
        elif key == "bezel":
            styles = [s[0] for s in getattr(self, "BEZEL_STYLES", [("off", ""), ("phoenix", "")])]
            cur = getattr(self, "bezel_style", "phoenix")
            idx = styles.index(cur) if cur in styles else 0
            self.bezel_style = styles[(idx + direction) % len(styles)]
            self._load_bezel_images()
            self._layout_viewport()
            self._invalidate_present_cache()
            if self.bezel_active:
                self._ensure_bezel_cache()
            self.save_settings()
        elif key == "fps":
            self.show_fps = not self.show_fps
            self.save_settings()
        elif key == "scanlines":
            cur = int(getattr(self, "scanlines", 0) or 0)
            self.scanlines = (cur + direction) % 4  # 0..3
            self._scanline_surf = None  # rebuild overlay
            self._scanline_level_cached = None
            self.save_settings()
        elif key == "language":
            idx = LANG_CODES.index(self.language) if self.language in LANG_CODES else 0
            self.language = LANG_CODES[(idx + direction) % len(LANG_CODES)]
            set_lang(self.language)
            self.text_cache.clear()
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
        try:
            core_img = pygame.image.load(asset_path("sprites", "boss_core.png")).convert_alpha()
            ch = 36
            scale = ch / max(1, core_img.get_height())
            cw = max(1, int(core_img.get_width() * scale))
            self.help_icons["boss"] = pygame.transform.smoothscale(core_img, (cw, ch))
        except Exception:
            core = pygame.Surface((36, 40), pygame.SRCALPHA)
            pygame.draw.ellipse(core, (40, 90, 70), (4, 4, 28, 32))
            self.help_icons["boss"] = core
        # Ship + Phenix form for help page 2
        try:
            ship = pygame.image.load(asset_path("sprites", "player_ship.png")).convert_alpha()
            sh = 72
            scale = sh / max(1, ship.get_height())
            sw = max(1, int(ship.get_width() * scale))
            self.help_icons["ship"] = pygame.transform.smoothscale(ship, (sw, sh))
        except Exception:
            self.help_icons["ship"] = None
        phenix_img = None
        phenix_dir = asset_path("sprites", "phenix")
        # Prefer a mid morph / flight frame
        for name in ("phenix_04.png", "phenix_03.png", "morph_03.png", "phenix_00.png"):
            path = os.path.join(phenix_dir, name)
            if os.path.isfile(path):
                try:
                    phenix_img = pygame.image.load(path).convert_alpha()
                    break
                except Exception:
                    pass
        if phenix_img is not None:
            ph = 80
            scale = ph / max(1, phenix_img.get_height())
            pw = max(1, int(phenix_img.get_width() * scale))
            self.help_icons["phenix"] = pygame.transform.smoothscale(phenix_img, (pw, ph))
        else:
            self.help_icons["phenix"] = None


    def _draw_help_page(self, surface, page, y_off):
        """Draw help page 0 (scenario/points) or 1 (PHENIX). y_off shifts content."""
        def yy(y):
            return int(y + y_off)

        title = self.big_font.render("PHENIX REBIRTH", True, (255, 120, 255))
        surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, yy(28)))
        sub = self.font.render(t("subtitle"), True, (180, 160, 220))
        surface.blit(sub, (BASE_WIDTH // 2 - sub.get_width() // 2, yy(82)))

        if page <= 0:
            col_l = 48
            y = 120

            def hdr(txt, y):
                s = self.medium_font.render(txt, True, (255, 200, 120))
                surface.blit(s, (col_l, yy(y)))
                return y + 34

            def body(txt, y):
                s = self.font.render(txt, True, (200, 200, 230))
                surface.blit(s, (col_l, yy(y)))
                return y + 24

            y = hdr(t_help("scenario_h"), y)
            for line in t_list("scenario"):
                y = body(line, y)
            y += 10
            y = hdr(t_help("howto_h"), y)
            for line in t_list("howto"):
                y = body(line, y)
            y += 10
            y = hdr(t_help("controls_h"), y)
            for line in t_list("controls"):
                y = body(line, y)

            col_r = BASE_WIDTH // 2 + 90
            y = 120
            s = self.medium_font.render(t_help("points_h"), True, (255, 200, 120))
            surface.blit(s, (col_r, yy(y)))
            y += 40
            score_rows = [
                ("bird1", t_help("enemy_s1"), "10"),
                ("bird2", t_help("enemy_s2"), "20"),
                ("garg3", t_help("enemy_s3"), "30"),
                ("garg4", t_help("enemy_s4"), "40"),
                ("boss", t_help("enemy_boss"), "200"),
            ]
            for key, label, pts in score_rows:
                ix, iy = col_r + 28, yy(y + 14)
                if key == "bird1" and "bird1" in self.help_icons:
                    img = self.help_icons["bird1"]
                    surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                elif key == "bird2" and "bird2" in self.help_icons:
                    img = self.help_icons["bird2"]
                    surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                elif key == "garg3" and "garg3" in self.help_icons:
                    self._draw_help_gargoyle(surface, self.help_icons["garg3"], ix, iy, 0.5)
                elif key == "garg4" and "garg4" in self.help_icons:
                    self._draw_help_gargoyle(surface, self.help_icons["garg4"], ix, iy, 0.5)
                elif key == "boss" and "boss" in self.help_icons:
                    img = self.help_icons["boss"]
                    surface.blit(img, (ix - img.get_width() // 2, iy - img.get_height() // 2))
                ls = self.font.render(label, True, (200, 200, 230))
                surface.blit(ls, (col_r + 60, yy(y + 4)))
                ps = self.font.render(pts + " " + t_help("pts"), True, (110, 255, 150))
                surface.blit(ps, (col_r + 60, yy(y + 26)))
                y += 54
            note = self.font.render(t_help("vet_note"), True, (180, 160, 200))
            surface.blit(note, (col_r, yy(y + 2)))
            y += 26
            note2 = self.font.render(t_help("bonus_lives"), True, (180, 160, 220))
            surface.blit(note2, (col_r, yy(y)))
        else:
            # Page 2 — PHENIX mechanics (centered, airy) + ship / firebird art
            y = 120
            s = self.medium_font.render(t_help("phenix_h"), True, (255, 160, 80))
            surface.blit(s, (BASE_WIDTH // 2 - s.get_width() // 2, yy(y)))
            y += 42
            for line in t_list("phenix"):
                s = self.font.render(line, True, (210, 210, 235))
                surface.blit(s, (BASE_WIDTH // 2 - s.get_width() // 2, yy(y)))
                y += 28
            y += 12
            tip = self.font.render("Shift / X  ·  B", True, (255, 220, 120))
            surface.blit(tip, (BASE_WIDTH // 2 - tip.get_width() // 2, yy(y)))
            y += 40
            # Illustrations: normal ship | arrow | phenix form
            ship = self.help_icons.get("ship")
            phenix = self.help_icons.get("phenix")
            gap = 48
            total_w = 0
            if ship is not None:
                total_w += ship.get_width()
            if phenix is not None:
                total_w += phenix.get_width()
            total_w += gap + 40  # arrow space
            x0 = BASE_WIDTH // 2 - total_w // 2
            if ship is not None:
                surface.blit(ship, (x0, yy(y)))
                x0 += ship.get_width() + gap // 2
            arrow = self.medium_font.render(">>>", True, (255, 180, 80))
            surface.blit(arrow, (x0, yy(y + 28)))
            x0 += arrow.get_width() + gap // 2
            if phenix is not None:
                surface.blit(phenix, (x0, yy(y)))

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

        # Desired aim X — prefer targets nearly above the ship (easier kills)
        aim_x = None
        best = 1e9
        for e in getattr(self.formation, "enemies", []) or []:
            if not getattr(e, "alive", True) or getattr(e, "dying", False):
                continue
            ex = getattr(e, "x", 0)
            ey = getattr(e, "y", 0)
            if ey > py - 40:
                if ex < px:
                    danger_l += 2.0
                else:
                    danger_r += 2.0
            # Weight: strongly favor enemies in a vertical corridor above us
            d = abs(ex - px) * 1.6 + max(0.0, py - ey) * 0.15
            if ey >= py - 20:
                d += 200  # behind / below — ignore for aim
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
            if abs(err) > 12:
                desired = max(-1.0, min(1.0, err / 70.0))
            else:
                desired = 0.0

        # Edge soft push
        if px < 100:
            desired = max(desired, (100 - px) / 80.0)
        elif px > BASE_WIDTH - 100:
            desired = min(desired, -(px - (BASE_WIDTH - 100)) / 80.0)

        # Low-pass filter on steering (frame-rate independent-ish)
        # Higher alpha = more responsive; lower = smoother
        alpha = min(1.0, 6.0 * self.dt)
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

        # Aggressive fire: shoot whenever a target is roughly in our column
        shots_ready = len(getattr(self.player, "shots", []) or []) == 0
        if shots_ready:
            # 1) Primary aim target in wide lane
            if aim_x is not None and abs(aim_x - px) < 70:
                shoot = True
            else:
                # 2) Any living enemy roughly above us
                for e in getattr(self.formation, "enemies", []) or []:
                    if not getattr(e, "alive", True) or getattr(e, "dying", False):
                        continue
                    if abs(getattr(e, "x", 0) - px) < 55 and getattr(e, "y", 0) < py - 30:
                        shoot = True
                        break
            # 3) Boss cells / core
            if not shoot and self.boss_saucer is not None and not getattr(self.boss_saucer, "dead", False):
                if aim_x is not None and abs(aim_x - px) < 80:
                    shoot = True
            # 4) Still fire occasionally while hunting (keeps pressure)
            if not shoot and aim_x is not None and random.random() < 0.08:
                shoot = True

        # Try to activate Phenix when charged and useful
        if self.player.can_activate_phenix():
            threat_sum = danger_l + danger_r
            want = False
            if threat_sum > 0.8:
                want = True
            elif self.stage % 5 == 0 and self.player.phenix_gauge >= 3:
                want = random.random() < 0.06
            elif aim_x is not None and abs(aim_x - px) < 70:
                want = random.random() < 0.03
            if want:
                self.player.try_activate_phenix()

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
        # Help AI show Phenix on stages 2–5 (never pre-fill stage 1)
        if self.stage != 1:
            roll = random.random()
            if roll < 0.55:
                self.player.phenix_gauge = random.randint(4, 8)
            elif roll < 0.80:
                self.player.phenix_gauge = random.randint(3, 5)
            # else start empty and try to build
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
                 self.fps_target, self.show_fps, self.difficulty, self.language,
                 getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0))
        first = self.help_first_shown
        nxt = self.next_is_attract
        self.__init__(soft=True)
        (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
         self.fps_target, self.show_fps, self.difficulty, self.language,
         self.bezel_style, self.monitor_index) = saved
        set_lang(self.language)
        self.sounds.set_music_volume(self.music_volume)
        self.sounds.set_master_volume(self.sfx_volume)
        # Do NOT re-call apply_display_mode — avoids desktop flash
        self.help_first_shown = first
        self.next_is_attract = nxt
        self.attract_mode = False
        self.started = False
        self.menu_idle = 0.0
        self._paint_menu_frame()

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

    def _paint_menu_frame(self):
        """Immediate frame so soft reset never shows the desktop."""
        try:
            self.game_surface.fill((0, 0, 0))
            if getattr(self, "starfield", None):
                self.starfield.draw(self.game_surface)
            if getattr(self, "display_mode", "window") == "window":
                self.screen.blit(self.game_surface, (0, 0))
            else:
                self._layout_viewport()
                self.screen.fill((0, 0, 0))
                if getattr(self, "bezel_active", False):
                    self._draw_arcade_bezels()
                vr = getattr(self, "view_rect", pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT))
                scaled = pygame.transform.scale(self.game_surface, (vr.width, vr.height))
                self.screen.blit(scaled, vr.topleft)
            pygame.display.flip()
        except Exception:
            pass

    def _quit_to_menu(self):
        """Leave current run, return to main menu (keep settings)."""
        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
                 self.fps_target, self.show_fps, self.difficulty, self.language,
                 getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0))
        self.__init__(soft=True)
        (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
         self.fps_target, self.show_fps, self.difficulty, self.language,
         self.bezel_style, self.monitor_index) = saved
        set_lang(self.language)
        self.sounds.set_music_volume(self.music_volume)
        self.sounds.set_master_volume(self.sfx_volume)
        # Keep existing window — no set_mode flash
        self.paused = False
        self.quit_confirm = False
        self.pause_options = False
        self.menu_screen = "main"
        self.menu_index = 0
        self.input_grace = 0.35  # absorb the confirm key/button that quit the run
        self.player.infinite_lives = False
        self._paint_menu_frame()

    def _menu_back(self):

        """B / Esc — return to previous menu screen."""
        if self.menu_screen == "main":
            return
        if self.menu_screen == "reset_confirm":
            self.menu_screen = "options"
            self._focus_option("reset_hs")
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
                self.play_mode = "solo"
                self.hotseat = False
                self.player2 = None
                self._apply_difficulty_start()
                self.started = True
                self.input_grace = 0.35
            elif self.menu_index == 1:
                self._menu_adjust(1)
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
            spec = self._options_spec()
            self.menu_index = spec.index("reset_hs") if "reset_hs" in spec else 0
        elif self.menu_screen == "options":
            spec = self._options_spec()
            key = spec[self.menu_index] if 0 <= self.menu_index < len(spec) else ""
            if key == "reset_hs":
                self.menu_screen = "reset_confirm"
                self.menu_index = 1
            elif key == "back":
                if self.pause_options:
                    self.pause_options = False
                    self.menu_index = 0
                else:
                    self.menu_screen = "main"
                    self.menu_index = 2

    # --- Input ---

    def take_screenshot(self):
        """Save a PNG of the current display (fullscreen includes bezel)."""
        try:
            folder = os.path.join(user_data_dir(), "screenshots")
            os.makedirs(folder, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(folder, f"phenix_{stamp}.png")
            # Capture the real window surface (bezels + game)
            pygame.image.save(self.screen, path)
            self.cheat_msg = f"SCREENSHOT"
            self.cheat_msg_timer = 2.0
            print("Screenshot saved:", path)
            return path
        except Exception as e:
            print("Screenshot failed:", e)
            return None

    def _touch_layout_mode(self):
        if not self.started or self.game_over or self.paused or self.quit_confirm:
            return "menu"
        return "game"

    def _apply_touch_ui(self):
        """FIRE = valider, II = retour, tap ligne = action. Une seule finalize/frame."""
        if not getattr(self, "touch_enabled", False) or not hasattr(self, "touch"):
            self._ts = None
            return None
        vr = getattr(self, "view_rect", pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT))
        ts = self.touch.finalize(vr)
        self._ts = ts
        if getattr(self, "input_grace", 0) > 0 or self.attract_mode:
            return ts

        if ts.menu_pick is not None and not self.started and not self.game_over and not self.quit_confirm:
            self._reset_menu_idle()
            kind = ts.menu_kind or "confirm"
            self.menu_index = int(ts.menu_pick)
            if kind == "cycle":
                self._menu_adjust(1)
            else:
                self._menu_confirm()
            return ts

        if ts.menu_confirm:
            self._reset_menu_idle()
            if self.quit_confirm and not self.started:
                if self.quit_index == 0:
                    self.running = False
                else:
                    self.quit_confirm = False
            elif self.game_over and self.hs_phase == "enter":
                self._submit_highscore()
            elif self.game_over and self.hs_phase == "table":
                saved = (
                    self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
                    self.fps_target, self.show_fps, self.difficulty, self.language,
                    getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0),
                )
                self.__init__(soft=True)
                (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume,
                 self.fps_target, self.show_fps, self.difficulty, self.language,
                 self.bezel_style, self.monitor_index) = saved
            elif self.paused and self.started and not self.game_over:
                if self.pause_options:
                    self._menu_confirm()
                elif self.pause_index == 0:
                    self.paused = False
                elif self.pause_index == 1:
                    self.pause_options = True
                    self.menu_screen = "options"
                    self.menu_index = 0
                else:
                    self._quit_to_menu()
            elif not self.started and not self.game_over:
                if self.menu_screen in ("help", "highscores", "credits"):
                    self.menu_screen = "main"
                    self.menu_index = 0
                else:
                    self._menu_confirm()
            return ts

        if ts.menu_back:
            self._reset_menu_idle()
            if self.quit_confirm and not self.started:
                self.quit_confirm = False
            elif self.paused and self.started and not self.game_over:
                if self.pause_options:
                    if self.menu_screen == "reset_confirm":
                        self.menu_screen = "options"
                        self._focus_option("reset_hs")
                    else:
                        self.pause_options = False
                        self.menu_index = 0
                else:
                    self.paused = False
            elif self.started and not self.game_over:
                self._toggle_pause()
            elif not self.started:
                if self.menu_screen == "main":
                    self.quit_confirm = True
                    self.quit_index = 1
                else:
                    self._menu_back()
            return ts
        return ts


    def _is_app_background_event(self, event):
        et = event.type
        bg = getattr(pygame, "APP_WILLENTERBACKGROUND", -100)
        lost = getattr(pygame, "WINDOWFOCUSLOST", -101)
        if et == bg:
            return True
        if et == lost:
            try:
                from platform_io import is_mobile_runtime
                return is_mobile_runtime()
            except Exception:
                return False
        if et == getattr(pygame, "ACTIVEEVENT", -102):
            gain = getattr(event, "gain", 1)
            state = getattr(event, "state", 0)
            # state 2 = input focus, 1 = mouse focus — loss of app focus
            if gain == 0 and state in (2, 6):
                try:
                    from platform_io import is_mobile_runtime
                    return is_mobile_runtime()
                except Exception:
                    return False
        return False

    def _is_app_foreground_event(self, event):
        et = event.type
        fg = getattr(pygame, "APP_DIDENTERFOREGROUND", -103)
        gained = getattr(pygame, "WINDOWFOCUSGAINED", -104)
        if et == fg:
            return True
        if et == gained:
            try:
                from platform_io import is_mobile_runtime
                return is_mobile_runtime()
            except Exception:
                return False
        if et == getattr(pygame, "ACTIVEEVENT", -102):
            if getattr(event, "gain", 0) == 1 and getattr(event, "state", 0) in (2, 6):
                try:
                    from platform_io import is_mobile_runtime
                    return is_mobile_runtime()
                except Exception:
                    return False
        return False

    def _on_app_background(self):
        """Home / appel : pause partie + coupe le mixer."""
        self._app_suspended = True
        if self.started and not self.game_over:
            self.paused = True
            self.pause_options = False
        if hasattr(self, "sounds") and self.sounds:
            self.sounds.suspend()

    def _on_app_foreground(self):
        """Retour au jeu : mixer on, on reste en pause (le joueur valide Reprendre)."""
        self._app_suspended = False
        if hasattr(self, "sounds") and self.sounds:
            self.sounds.resume()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif self._is_app_background_event(event):
                self._on_app_background()
                continue
            elif self._is_app_foreground_event(event):
                self._on_app_foreground()
                continue
            if getattr(self, "touch_enabled", False) and hasattr(self, "touch"):
                vr = getattr(self, "view_rect", pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT))
                if self.touch.handle_event(event, vr):
                    continue
            if event.type in (getattr(pygame, "JOYDEVICEADDED", -1), getattr(pygame, "JOYDEVICEREMOVED", -2)):
                self._poll_gamepad()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F12:
                    self.take_screenshot()
                    continue
                if self.attract_mode:
                    self._end_attract()
                    continue
                if self.hotseat_wait and self.started and not self.game_over:
                    if getattr(self, "input_grace", 0) <= 0:
                        self._hotseat_resume()
                    continue
                # Phenix activation (in-game only)
                if self.started and not self.paused and not self.game_over:
                    if event.key == pygame.K_LSHIFT:
                        # Coop split-keyboard P1 only
                        if self.play_mode == "coop" and getattr(self.player, "input_scheme", "") == "kb1":
                            self._activate_phenix_from_input(self.player)
                    elif event.key == pygame.K_RSHIFT:
                        if self.play_mode == "coop":
                            # P2 keyboard (or 1P-style layout)
                            target = self.player2
                            if getattr(self.player, "input_scheme", "") == "solo":
                                target = self.player2
                            self._activate_phenix_from_input(target)
                        else:
                            self._activate_phenix_from_input(self.player)
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
                        if self._is_menu_up(event.key):
                            self._menu_nav(-1)
                        elif self._is_menu_down(event.key):
                            self._menu_nav(1)
                        elif event.key in (pygame.K_LEFT, pygame.K_a):
                            self._menu_adjust(-1)
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            self._menu_adjust(1)
                        elif self._is_menu_confirm(event.key):
                            if self.menu_screen == "reset_confirm":
                                if self.menu_index == 0:
                                    self.hs_entries = reset_highscores()
                                self.menu_screen = "options"
                                self._focus_option("reset_hs")
                            else:
                                spec = self._options_spec()
                                key = spec[self.menu_index] if 0 <= self.menu_index < len(spec) else ""
                                if key == "back":
                                    self.pause_options = False
                                    self.menu_index = 0
                                elif key == "reset_hs":
                                    self.menu_screen = "reset_confirm"
                                    self.menu_index = 1
                        elif event.key == pygame.K_ESCAPE:
                            if self.menu_screen == "reset_confirm":
                                self.menu_screen = "options"
                                self._focus_option("reset_hs")
                            else:
                                self.pause_options = False
                                self.menu_index = 0
                    else:
                        if self._is_menu_up(event.key):
                            self.pause_index = (self.pause_index - 1) % 3
                        elif self._is_menu_down(event.key):
                            self.pause_index = (self.pause_index + 1) % 3
                        elif self._is_menu_confirm(event.key):
                            if self.pause_index == 0:  # Reprendre
                                self.paused = False
                            elif self.pause_index == 1:  # Options
                                self.pause_options = True
                                self.menu_screen = "options"
                                self.menu_index = 0
                            else:  # Quitter la partie
                                self._quit_to_menu()
                                continue  # don't also confirm main-menu with same Enter
                        elif event.key == pygame.K_ESCAPE:
                            self.paused = False
                            self.pause_options = False
                            continue
                # Quit game confirm (menus) — ESC already toggled above
                elif self.quit_confirm and not self.started:
                    if self._is_menu_up(event.key):
                        self.quit_index = (self.quit_index - 1) % 2
                    elif self._is_menu_down(event.key):
                        self.quit_index = (self.quit_index + 1) % 2
                    elif self._is_menu_confirm(event.key):
                        if self.quit_index == 0:
                            self.running = False
                        else:
                            self.quit_confirm = False

                
                if not self.started and not self.game_over and not self.quit_confirm and getattr(self, "input_grace", 0) <= 0:
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
                                self.cheat_msg = t("cheat_live")
                                self.cheat_kind = "live"
                                self.cheat_msg_timer = 5.0
                            elif "PHEN" in self.cheat_buffer:
                                self.used_cheat = True
                                self.phenix_cheat = True
                                self.player.phenix_auto_refill = True
                                self.player.phenix_gauge = 10
                                self.cheat_buffer = ""
                                self.cheat_msg = t("cheat_phen")
                                self.cheat_kind = "phen"
                                self.cheat_msg_timer = 5.0
                        else:
                            # Any non-alnum key (Enter, Esc already handled, Space, arrows...) returns
                            if event.key not in (pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_CAPSLOCK):
                                self.menu_screen = "main"
                                self.menu_index = 0
                                self.cheat_buffer = ""
                    elif self._is_menu_up(event.key):
                        self._reset_menu_idle()
                        self._menu_nav(-1)
                    elif self._is_menu_down(event.key):
                        self._reset_menu_idle()
                        self._menu_nav(1)
                    elif event.key in (pygame.K_LEFT, pygame.K_a, pygame.K_q):
                        self._reset_menu_idle()
                        self._menu_adjust(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_d):
                        self._reset_menu_idle()
                        self._menu_adjust(1)
                    elif self._is_menu_confirm(event.key):
                        self._reset_menu_idle()
                        self._menu_confirm()
                
                if self.game_over:
                    if self.hs_phase == "enter":
                        if event.key == pygame.K_LEFT:
                            self.hs_char_index = (self.hs_char_index - 1) % 3
                        elif event.key == pygame.K_RIGHT:
                            self.hs_char_index = (self.hs_char_index + 1) % 3
                        elif self._is_menu_up(event.key):
                            self._hs_cycle_letter(1)
                        elif self._is_menu_down(event.key):
                            self._hs_cycle_letter(-1)
                        elif event.key == pygame.K_BACKSPACE:
                            self.hs_char_index = max(0, self.hs_char_index - 1)
                        elif self._is_menu_confirm(event.key):
                            self._submit_highscore()
                        elif event.unicode and event.unicode.isalnum():
                            self.hs_name[self.hs_char_index] = event.unicode.upper()
                            self.hs_char_index = min(2, self.hs_char_index + 1)
                            if self.hs_char_index == 2 and self.hs_name[2] != "A":
                                pass  # stay on last or auto-advance feel
                    elif self.hs_phase == "table" and self._is_menu_confirm(event.key):
                        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language, getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0))
                        self.__init__(soft=True)
                        self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language, self.bezel_style, self.monitor_index = saved
                        set_lang(self.language)
                        self.sounds.set_music_volume(self.music_volume)
                        self.sounds.set_master_volume(self.sfx_volume)
                        self._paint_menu_frame()
            
            elif event.type == pygame.JOYBUTTONDOWN:
                if self.attract_mode:
                    self._end_attract()
                    continue
                if self.hotseat_wait and self.started and not self.game_over:
                    if getattr(self, "input_grace", 0) <= 0:
                        self._hotseat_resume()
                    continue
                # B = Phenix while playing (menus still use B as back elsewhere)
                if (event.button == 1 and self.started and not self.paused
                        and not self.game_over and not self.quit_confirm):
                    target = self.player
                    if self.play_mode == "coop":
                        inst = getattr(event, "instance_id", getattr(event, "joy", None))
                        for s in self._ships():
                            joy = getattr(s, "_joy", None)
                            if joy is None:
                                continue
                            jid = getattr(joy, "get_instance_id", lambda: joy.get_id())()
                            if jid == inst or joy.get_id() == getattr(event, "joy", -1):
                                target = s
                                break
                    self._activate_phenix_from_input(target)
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
                                self._focus_option("reset_hs")
                            else:
                                spec = self._options_spec()
                                key = spec[self.menu_index] if 0 <= self.menu_index < len(spec) else ""
                                if key == "back":
                                    self.pause_options = False
                                    self.menu_index = 0
                                elif key == "reset_hs":
                                    self.menu_screen = "reset_confirm"
                                    self.menu_index = 1
                        elif event.button == 1:
                            if self.menu_screen == "reset_confirm":
                                self.menu_screen = "options"
                                self._focus_option("reset_hs")
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
                                continue  # same A must not confirm main menu
                        elif event.button == 1:
                            self.paused = False
                            self.pause_options = False
                            continue
                elif self.quit_confirm and not self.started:
                    if event.button == 0:
                        if self.quit_index == 0:
                            self.running = False
                        else:
                            self.quit_confirm = False
                    elif event.button == 1:
                        self.quit_confirm = False
                elif not self.started and not self.game_over and not self.quit_confirm and getattr(self, "input_grace", 0) <= 0:
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
                        saved = (self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language, getattr(self, "bezel_style", "phoenix"), int(getattr(self, "monitor_index", 0) or 0))
                        self.__init__(soft=True)
                        self.input_mode, self.display_mode, self.sfx_volume, self.music_volume, self.fps_target, self.show_fps, self.difficulty, self.language, self.bezel_style, self.monitor_index = saved
                        set_lang(self.language)
                        self.sounds.set_music_volume(self.music_volume)
                        self.sounds.set_master_volume(self.sfx_volume)
                        self._paint_menu_frame()
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
        self._apply_touch_ui()
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
                            self.help_page = 0
                            self.help_scroll = 0.0
                            self.help_transitioning = False
                            self.next_is_attract = True
                        elif self.next_is_attract:
                            self.next_is_attract = False
                            self._start_attract()
                        else:
                            self.next_is_attract = True
                            self.menu_screen = "help"
                            self.help_timer = 0.0
                            self.help_page = 0
                            self.help_scroll = 0.0
                            self.help_transitioning = False
                elif self.menu_screen == "help":
                    self.help_anim_t += self.dt
                    if self.help_transitioning:
                        # Smooth vertical slide page 0 → page 1
                        self.help_scroll += self.dt / max(0.05, self.HELP_SCROLL_SEC) * BASE_HEIGHT
                        if self.help_scroll >= BASE_HEIGHT:
                            self.help_scroll = 0.0
                            self.help_transitioning = False
                            self.help_page = 1
                            self.help_timer = 0.0
                    else:
                        self.help_timer += self.dt
                        if self.help_timer >= self.HELP_PAGE_SEC:
                            if self.help_page <= 0:
                                self.help_transitioning = True
                                self.help_scroll = 0.0
                            else:
                                self.menu_screen = "main"
                                self.menu_index = 0
                                self.menu_idle = 0.0
                                self.help_timer = 0.0
                                self.help_page = 0
                else:
                    self.menu_idle = 0.0
            return
        
        if self.paused:
            self.starfield.update(self.dt)
            self.sounds.play_electric(False)
            return

        if self.hotseat_wait:
            self.starfield.update(self.dt)
            self.sounds.play_electric(False)
            return

        if self.hotseat_hold > 0:
            self.hotseat_hold = max(0.0, self.hotseat_hold - self.dt)
            self.starfield.update(self.dt, self.player.x if self.player else BASE_WIDTH / 2)
            for exp in self.explosions[:]:
                exp.update(self.dt)
                if exp.is_finished():
                    self.explosions.remove(exp)
            tesla_on = False
            if self.tesla_fx is not None:
                self.tesla_fx.update(self.dt)
                tesla_on = not self.tesla_fx.is_finished()
                if not tesla_on:
                    self.tesla_fx = None
            self.sounds.play_electric(tesla_on)
            if self.shake_amount > 0:
                self.shake_amount = max(0.0, self.shake_amount - SCREEN_SHAKE_DECAY * self.dt)
            if self.hotseat_hold <= 0:
                self._hotseat_finish_hold()
            return
            
        keys = pygame.key.get_pressed()
        
        edge_killed_any = False
        if self.stage_transition is None:
            ai_move = ai_shoot = None
            if self.attract_mode:
                ai_move, ai_shoot = self._attract_ai()
            elif getattr(self, "touch_enabled", False):
                ts = getattr(self, "_ts", None)
                if ts is not None and not self.paused:
                    if ts.active or ts.fire or ts.dx != 0.0:
                        ai_move = ts.dx
                        ai_shoot = ts.fire
                    if ts.phenix:
                        self._activate_phenix_from_input(self.player)
            for ship in self._ships():
                ship.rumble_level = int(getattr(self, "rumble_level", 3))
                ship.autofire = True if self.attract_mode else bool(getattr(self, "autofire", True))
                if getattr(self, "play_mode", "solo") != "coop":
                    mode = self.input_mode
                    joy = self.joystick
                    ship.input_scheme = "solo"
                else:
                    scheme = getattr(ship, "input_scheme", "solo")
                    joy = getattr(ship, "_joy", None)
                    mode = "gamepad" if scheme == "pad" else "keyboard"
                if self.attract_mode and ship is self.player:
                    edge_killed = ship.update(
                        self.dt, keys, mode, joy,
                        allow_shoot=(self.input_grace <= 0),
                        ai_move=ai_move, ai_shoot=ai_shoot,
                    )
                else:
                    edge_killed = ship.update(
                        self.dt, keys, mode, joy,
                        allow_shoot=(self.input_grace <= 0),
                    )
                if edge_killed:
                    edge_killed_any = True
                    kind = "gameover" if ship.dying else "edge"
                    self.explosions.append(Explosion(ship.x, ship.y, kind=kind))
                    self.shake_amount = 22.0 if ship.dying else 14.0
                    self.sounds.play("explosion_big" if ship.dying else "explosion")
                    side = getattr(ship, "last_edge_side", 0) or getattr(ship, "edge_side", -1)
                    self.tesla_fx = TeslaCoilFx(side, ship.y)
                    self.sounds.play_electric(True)
                    if getattr(self, "play_mode", "") == "coop" and getattr(ship, "just_lost_life", False):
                        self._on_coop_life_lost(ship)
        else:
            edge_killed_any = False
        tesla_on = self.tesla_fx is not None and not self.tesla_fx.is_finished()
        flash_on = any(p.edge_flash > 0.08 and not p.dying for p in self._ships())
        self.sounds.play_electric(tesla_on or flash_on)
        
        # Attract mode: 30s demo or death → back to menu (no high score)
        if self.attract_mode:
            self.attract_timer -= self.dt
            if self.attract_timer <= 0 or not self.player.alive:
                self._end_attract()
                return

        # Game over / hot-seat hand-off after death disappearance or a lost life
        if not self.attract_mode and not self.game_over and self.hotseat_hold <= 0:
            if (self.hotseat and getattr(self.player, "just_lost_life", False)
                    and self.player.alive and not self.player.dying
                    and self.stage_transition is None):
                self._hotseat_arm_hold("switch", self.HOTSEAT_HOLD_LIFE)
                if self.hotseat_hold > 0:
                    return
            elif not any(p.alive for p in self._ships()):
                if self.hotseat:
                    self._hotseat_arm_hold("eliminated", self.HOTSEAT_HOLD_FINAL)
                else:
                    self._hotseat_arm_hold("gameover", self.HOTSEAT_HOLD_FINAL)
                return
        
        # Starfield with parallax based on player movement
        self.starfield.update(self.dt, self.player.x)
        
        # Stage transition: ship flies off top
        if self.stage_transition == "fly_up":
            for ship in self._ships():
                if ship.alive or ship.dying:
                    ship.y -= 420 * self.dt
                    ship.engine_intensity = 1.0
            self.starfield.update(self.dt, self.player.x)
            if all((not s.alive) or s.y < -80 for s in self._ships()):
                self.stage += 1
                self._setup_stage(self.stage)
                xs = [BASE_WIDTH // 2 - 70, BASE_WIDTH // 2 + 70] if self.play_mode == "coop" else [BASE_WIDTH // 2]
                for i, ship in enumerate(self._ships()):
                    ship.y = BASE_HEIGHT + 60
                    ship.x = xs[min(i, len(xs) - 1)]
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
            for ship in self._ships():
                if ship.alive:
                    ship.y -= 380 * self.dt
                    ship.engine_intensity = 1.0
            self.starfield.update(self.dt, self.player.x)
            self.formation.update(self.dt, self.player.x)
            if all((not s.alive) or s.y <= target_y for s in self._ships()):
                for ship in self._ships():
                    if ship.alive:
                        ship.y = target_y
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
                    bird = Enemy(x, -30, formation_index=alive_birds + random.randint(0, 6), stage=st)
                    bird.speed_mult = stage_speed_mult(self.stage) * self.difficulty_speed_mult()
                    bird.state = "formation"
                    bird.start_dive(x)  # dive in their spawn lane, not a shared player X
                    self.formation.enemies.append(bird)
        
        # Stage clear → fly to next stage (non-boss content)
        content = stage_content(self.stage)
        if (self.stage_transition is None and content != 5
                and self.formation.all_dead()
                and not any(s.dying for s in self._ships())
                and self.boss_saucer is None):
            self.stage_transition = "fly_up"
            for ship in self._ships():
                ship.destroy_bullet()
        
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
                for ship in self._ships():
                    ship.destroy_bullet()
            return
        
        # Player bullet(s) vs Enemies / Boss
        for ship in self._ships():
          for shot_i, bullet_rect in ship.get_bullet_rects():
            hit_something = False
            # Boss saucer armor / core
            if self.boss_saucer is not None and self.boss_saucer.alive:
                result = self.boss_saucer.hit_bullet(bullet_rect)
                if result is not None:
                    kind, target = result
                    if kind == "cell":
                        ship.destroy_bullet("neutral", index=shot_i)
                        self.explosions.append(Explosion(target.x, target.y, kind="enemy"))
                        self.shake_amount = 3.5
                        self.sounds.play("enemy_explosion", volume=0.4)
                        self._add_score(ship, 1)
                    elif kind == "deco":
                        ship.destroy_bullet("neutral", index=shot_i)
                        self.explosions.append(Explosion(target.x, target.y, kind="enemy"))
                        self.shake_amount = 5.0
                        self.sounds.play("enemy_explosion")
                        self._add_score(ship, 50)
                    elif kind == "boss":
                        ship.destroy_bullet("valid", index=shot_i)
                        target.kill()
                        self._add_score(ship, self._boss_points())
                        self.explosions.append(Explosion(target.x, target.y, kind="gameover"))
                        self.shake_amount = 20.0
                        self.sounds.play("explosion_big")
                    hit_something = True
            if hit_something:
                break  # indices shifted; next frame continues

            for enemy in self.formation.get_hittable_enemies():
                if isinstance(enemy, BigBird):
                    if bullet_rect.colliderect(enemy.get_left_wing_hitbox()):
                        if enemy.hit_wing("left"):
                            ship.destroy_bullet("neutral", index=shot_i)
                            self.explosions.append(Explosion(enemy.x - 35, enemy.y, kind="enemy"))
                            self.shake_amount = 3.0
                            self.sounds.play("enemy_explosion", volume=0.5)
                        else:
                            ship.destroy_bullet("neutral", index=shot_i)
                        hit_something = True
                        break
                    if bullet_rect.colliderect(enemy.get_right_wing_hitbox()):
                        if enemy.hit_wing("right"):
                            ship.destroy_bullet("neutral", index=shot_i)
                            self.explosions.append(Explosion(enemy.x + 35, enemy.y, kind="enemy"))
                            self.shake_amount = 3.0
                            self.sounds.play("enemy_explosion", volume=0.5)
                        else:
                            ship.destroy_bullet("neutral", index=shot_i)
                        hit_something = True
                        break
                    if bullet_rect.colliderect(enemy.get_body_hitbox()):
                        enemy.kill()
                        ship.destroy_bullet("valid", index=shot_i)
                        self._add_score(ship, self._enemy_points(getattr(enemy, "stage", 3)))
                        self.explosions.append(Explosion(enemy.x, enemy.y, kind="enemy"))
                        self.shake_amount = 7.0
                        self.sounds.play("enemy_explosion")
                        hit_something = True
                        break
                    # Catch-all: silhouette overlap that slipped between wing/body boxes
                    if bullet_rect.colliderect(enemy.get_hitbox()):
                        enemy.kill()
                        ship.destroy_bullet("valid", index=shot_i)
                        self._add_score(ship, self._enemy_points(getattr(enemy, "stage", 3)))
                        self.explosions.append(Explosion(enemy.x, enemy.y, kind="enemy"))
                        self.shake_amount = 7.0
                        self.sounds.play("enemy_explosion")
                        hit_something = True
                        break
                else:
                    if bullet_rect.colliderect(enemy.get_hitbox()):
                        enemy.kill()
                        ship.destroy_bullet("valid", index=shot_i)
                        self._add_score(ship, self._enemy_points(getattr(enemy, "stage", 1)))
                        self.explosions.append(Explosion(enemy.x, enemy.y, kind="enemy"))
                        self.shake_amount = 5.5
                        self.sounds.play("enemy_explosion")
                        hit_something = True
                        break
            if hit_something:
                break

        # Enemy attacks vs Player(s) — ships do not collide with each other
        for ship in self._ships():
            if not ship.alive or ship.dying:
                continue
            player_hitbox = ship.get_hitbox()
            if self.boss_saucer is not None and self.boss_saucer.alive:
                hull = self.boss_saucer.get_hull_hitbox()
                if hull.width > 0 and player_hitbox.colliderect(hull):
                    if ship.infinite_lives:
                        ship.hit()
                        self.explosions.append(Explosion(ship.x, ship.y, kind="bullet"))
                        self.shake_amount = 14.0
                        self.sounds.play("explosion")
                        ship.y = min(BASE_HEIGHT - 80, ship.y + 40)
                    else:
                        if self.play_mode == "coop":
                            ship.hit()
                            self._on_coop_life_lost(ship)
                        else:
                            ship.lives = 0
                            ship.dying = True
                            ship.death_timer = 0.0
                            ship.invulnerable = 0.0
                            ship.rumble(1.0, 1.0, 640)
                        ship.phenix_gauge = float(getattr(ship, "phenix_min_gauge", 0))
                        ship.combo_streak = 0
                        ship.phenix_timer = 0.0
                        self.explosions.append(Explosion(ship.x, ship.y, kind="gameover"))
                        self.shake_amount = 24.0
                        self.sounds.play("explosion_big")
                for b in self.boss_saucer.bullets[:]:
                    if b.alive and b.get_hitbox().colliderect(player_hitbox):
                        b.alive = False
                        if (not ship.is_phenix) and ship.invulnerable <= 0 and ship.alive and not ship.dying:
                            ship.hit()
                            if self.play_mode == "coop":
                                self._on_coop_life_lost(ship)
                            kind = "gameover" if ship.dying else "bullet"
                            self.explosions.append(Explosion(ship.x, ship.y, kind=kind))
                            self.shake_amount = 22.0 if ship.dying else 12.0
                            self.sounds.play("explosion_big" if ship.dying else "explosion")
                        break
            for bullet in self.formation.bullets[:]:
                if bullet.alive and bullet.get_hitbox().colliderect(player_hitbox):
                    bullet.alive = False
                    if (not ship.is_phenix) and ship.invulnerable <= 0 and ship.alive and not ship.dying:
                        ship.hit()
                        if self.play_mode == "coop":
                            self._on_coop_life_lost(ship)
                        kind = "gameover" if ship.dying else "bullet"
                        self.explosions.append(Explosion(ship.x, ship.y, kind=kind))
                        self.shake_amount = 22.0 if ship.dying else 12.0
                        self.sounds.play("explosion_big" if ship.dying else "explosion")
                    break
            for enemy in self.formation.get_hittable_enemies():
                if enemy.diving and enemy.get_hitbox().colliderect(player_hitbox):
                    enemy.kill()
                    self.explosions.append(Explosion(enemy.x, enemy.y, kind="collision"))
                    self.sounds.play("enemy_explosion")
                    if ship.is_phenix:
                        self.shake_amount = max(self.shake_amount, 8.0)
                    else:
                        ship.hit()
                        if self.play_mode == "coop":
                            self._on_coop_life_lost(ship)
                        pkind = "gameover" if ship.dying else "collision"
                        self.explosions.append(Explosion(ship.x, ship.y, kind=pkind))
                        self.shake_amount = 26.0 if ship.dying else 18.0
                        self.sounds.play("explosion_big")
                    break

        for exp in self.explosions[:]:
            exp.update(self.dt)
            if exp.is_finished():
                self.explosions.remove(exp)
        if self.tesla_fx is not None:
            self.tesla_fx.update(self.dt)
            if self.tesla_fx.is_finished():
                self.tesla_fx = None
                self.sounds.play_electric(False)
        
        # Soft performance cap: keep newest explosions only
        if len(self.explosions) > 24:
            self.explosions = self.explosions[-max(4, int(MAX_EXPLOSIONS)):]
        
        if self.shake_amount > 0:
            self.shake_amount = max(0.0, self.shake_amount - SCREEN_SHAKE_DECAY * self.dt)

        # Life lost mid-frame (enemy bullet / dive) — hold, then hand off
        if (self.hotseat and not self.attract_mode and not self.game_over
                and not self.hotseat_wait and self.hotseat_hold <= 0
                and self.stage_transition is None
                and getattr(self.player, "just_lost_life", False)
                and self.player.alive and not self.player.dying):
            self._hotseat_arm_hold("switch", self.HOTSEAT_HOLD_LIFE)

    # --- Render (logical canvas, then present) ---
    def _ensure_scanline_surf(self):
        """Cached CRT multiply overlay (opaque RGB). Levels 1–3.

        Black-alpha-over dest = dest * (1 - a/255). We bake that factor
        as a white/grey RGB map and blit with BLEND_RGB_MULT — same look,
        no per-pixel alpha read on the 1280×720 hot path.
        """
        level = int(getattr(self, "scanlines", 0) or 0)
        if level <= 0:
            return None
        if (
            self._scanline_surf is not None
            and getattr(self, "_scanline_level_cached", None) == level
        ):
            return self._scanline_surf

        w, h = BASE_WIDTH, BASE_HEIGHT
        try:
            if getattr(self, "game_surface", None) is not None:
                surf = pygame.Surface((w, h), 0, self.game_surface)
            else:
                surf = pygame.Surface((w, h)).convert()
        except Exception:
            surf = pygame.Surface((w, h))
        surf.fill((255, 255, 255))

        def _shade(alpha):
            v = max(0, 255 - int(alpha))
            return (v, v, v)

        if level == 1:
            row = _shade(55)
            for y in range(0, h, 2):
                surf.fill(row, (0, y, w, 1))
        elif level == 2:
            even = _shade(95)
            mid = _shade(35)
            for y in range(0, h, 2):
                surf.fill(even, (0, y, w, 1))
            for y in range(1, h, 4):
                surf.fill(mid, (0, y, w, 1))
        else:
            even = _shade(130)
            odd = _shade(45)
            for y in range(0, h, 2):
                surf.fill(even, (0, y, w, 1))
            for y in range(1, h, 2):
                surf.fill(odd, (0, y, w, 1))
            for y in list(range(0, 8)) + list(range(h - 8, h)):
                extra = 25 if y % 2 == 0 else 15
                base = 130 if y % 2 == 0 else 45
                surf.fill(_shade(base + extra), (0, y, w, 1))

        self._scanline_surf = surf
        self._scanline_level_cached = level
        return surf


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
            if self.tesla_fx is not None:
                self.tesla_fx.draw(self.game_surface)
            
            for ship in self._ships():
                ship.draw(self.game_surface)
            
            # UI (cached text — re-render only when string/color changes)
            tc = self.text_cache
            if self.play_mode == "coop" and self.player2:
                p1s = tc.get(self.font, f"P1 {self.format_score(getattr(self.player, 'score', 0))}", (110, 255, 150))
                p2s = tc.get(self.font, f"P2 {self.format_score(getattr(self.player2, 'score', 0))}", (120, 180, 255))
                self.game_surface.blit(p1s, (16, 16))
                self.game_surface.blit(p2s, (BASE_WIDTH - 16 - p2s.get_width(), 16))
                self._draw_phenix_gauge(self.player, 18, 100)
                self._draw_phenix_gauge(self.player2, BASE_WIDTH - 18 - 14, 100, align="right")
            else:
                score_surf = tc.get(self.font, self.format_score(self.score), (110, 255, 150))
                self.game_surface.blit(score_surf, (BASE_WIDTH // 2 - score_surf.get_width() // 2, 16))
                if self.hotseat and self.slots[0] and self.slots[1]:
                    s0 = self.slots[0]["score"] if self.current_p != 0 else self.score
                    s1 = self.slots[1]["score"] if self.current_p != 1 else self.score
                    c0 = (255, 230, 120) if self.current_p == 0 else (140, 140, 170)
                    c1 = (255, 230, 120) if self.current_p == 1 else (140, 140, 170)
                    hp1 = tc.get(self.font, f"P1 {self.format_score(s0)}", c0)
                    hp2 = tc.get(self.font, f"P2 {self.format_score(s1)}", c1)
                    self.game_surface.blit(hp1, (16, 44))
                    self.game_surface.blit(hp2, (BASE_WIDTH - 16 - hp2.get_width(), 44))
                if self.hotseat and self.current_p == 1:
                    self._draw_phenix_gauge(self.player, BASE_WIDTH - 18 - 14, 100, align="right")
                else:
                    self._draw_phenix_gauge(self.player, 18, 100)
            if self.attract_mode:
                demo = tc.get(self.medium_font, t("demo"), (255, 180, 80))
                self.game_surface.blit(demo, (BASE_WIDTH // 2 - demo.get_width() // 2, 72))
                hint = tc.get(self.font, t("press_any"), (180, 180, 200))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT - 36))
            if getattr(self, "used_cheat", False) and not self.attract_mode:
                ch = tc.get(self.font, t("cheat_active"), (255, 60, 60))
                self.game_surface.blit(ch, (BASE_WIDTH // 2 - ch.get_width() // 2, 74))
            
            stage_surf = tc.get(self.font, f"{t('stage')} {self.stage}", (180, 180, 220))
            stage_x = BASE_WIDTH // 2 - stage_surf.get_width() // 2 if self.play_mode == "coop" else 16
            self.game_surface.blit(stage_surf, (stage_x, 16))
            # Flags for each boss defeated — at 10+, one big flag only
            if self.bosses_defeated >= 10:
                fx = stage_x + stage_surf.get_width() + 12
                self._draw_boss_flag(self.game_surface, fx, 12, big=True)
            elif self.bosses_defeated > 0:
                fx = stage_x + stage_surf.get_width() + 10
                fy = 18
                for i in range(self.bosses_defeated):
                    self._draw_boss_flag(self.game_surface, fx + i * 18, fy, big=False)
            
            self._draw_cheat_message()
            
            # Lives as mini ships
            if self.player.infinite_lives:
                inf = self.text_cache.get(self.font, t("lives_inf"), (110, 255, 150))
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
                # Two pages with optional vertical scroll transition
                if self.help_transitioning:
                    off = int(self.help_scroll)
                    self._draw_help_page(self.game_surface, 0, -off)
                    self._draw_help_page(self.game_surface, 1, BASE_HEIGHT - off)
                else:
                    self._draw_help_page(self.game_surface, self.help_page, 0)
                hint = self.font.render(t("help_return"), True, (255, 220, 100))
                self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT - 36))
                page_lbl = self.font.render(
                    f"{t_help('help_page')} {int(self.help_page) + 1}/2",
                    True, (140, 140, 180),
                )
                self.game_surface.blit(page_lbl, (BASE_WIDTH - page_lbl.get_width() - 20, BASE_HEIGHT - 36))

            elif self.menu_screen == "main":
                diff_key = {"novice": "diff_novice", "normal": "diff_normal", "veteran": "diff_veteran"}.get(self.difficulty, "diff_normal")
                diff = t(diff_key)
                options = [
                    (t("play"), "confirm"),
                    (f"{t('difficulty')} :  <  {diff}  >", "cycle"),
                    (t("options"), "confirm"),
                    (t("high_scores"), "confirm"),
                    (t("credits"), "confirm"),
                    (t("quit"), "confirm"),
                ]
                logo_h = self.logo_frames[0].get_height() if self.logo_frames else 100
                base_y = max(300, 12 + logo_h + 48)
                spacing = 38 if base_y + 5 * 38 < BASE_HEIGHT - 110 else 34
                rows = []
                for i, (label, kind) in enumerate(options):
                    selected = (i == self.menu_index)
                    col = (255, 230, 120) if selected else (160, 160, 190)
                    prefix = "> " if selected else "  "
                    surf = self.medium_font.render(prefix + label, True, col)
                    y = base_y + i * spacing
                    x = BASE_WIDTH // 2 - surf.get_width() // 2
                    self.game_surface.blit(surf, (x, y))
                    rows.append((pygame.Rect(x - 24, y - 4, surf.get_width() + 48, surf.get_height() + 8), i, kind))
                if getattr(self, "touch_enabled", False) and hasattr(self, "touch"):
                    self.touch.set_menu_rows(rows)
                
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
                            coop=bool(entries[i].get("coop")),
                        )
                    else:
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            "---", None, (100, 100, 120), score_right,
                        )
                back = self.font.render(t("press_any"), True, (255, 220, 100))
                self.game_surface.blit(back, (BASE_WIDTH // 2 - back.get_width() // 2, BASE_HEIGHT - 60))
                self._draw_cheat_message()
            
            elif self.menu_screen == "credits":
                # Variable line heights; title uses animated logo
                logo_h = self.logo_frames[0].get_height() if self.logo_frames else 56
                heights = []
                credits_lines = get_credits_lines()
                for kind, _ in credits_lines:
                    if kind == "title":
                        heights.append(logo_h + 28)
                    elif kind == "header":
                        heights.append(46)
                    elif kind == "blank":
                        heights.append(40)
                    elif kind == "sub":
                        heights.append(36)
                    else:
                        heights.append(34)
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
                lines = self._options_labels()
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
                if self.hotseat:
                    who = self.font.render(
                        t("player_n").format(n=self.hs_slot_label), True, (255, 200, 120)
                    )
                    self.game_surface.blit(who, (BASE_WIDTH // 2 - who.get_width() // 2, 72))
                
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
                            coop=bool(entries[i].get("coop")),
                        )
                    else:
                        self._draw_hs_row(
                            self.game_surface, base_y + i * 28, rank,
                            "---", None, (100, 100, 120), score_right,
                        )
                
                restart = self.font.render(t("back_to_menu"), True, (255, 220, 100))
                self.game_surface.blit(restart, (BASE_WIDTH // 2 - restart.get_width() // 2, BASE_HEIGHT - 50))

        if self.hotseat_wait and self.started and not self.game_over:
            overlay = pygame.Surface((BASE_WIDTH, BASE_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 170))
            self.game_surface.blit(overlay, (0, 0))
            who = t("player_n").format(n=self.hotseat_next + 1)
            title = self.big_font.render(who, True, (255, 200, 80))
            self.game_surface.blit(title, (BASE_WIDTH // 2 - title.get_width() // 2, BASE_HEIGHT // 2 - 50))
            hint = self.font.render(t("hotseat_press"), True, (220, 220, 240))
            self.game_surface.blit(hint, (BASE_WIDTH // 2 - hint.get_width() // 2, BASE_HEIGHT // 2 + 24))
        
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
                    lines = self._options_labels()
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

        # FPS counter (top-right) — refresh text ~4 Hz to avoid constant render
        if self.show_fps:
            self._fps_timer = getattr(self, "_fps_timer", 0.0) + getattr(self, "dt", 0.016)
            if self._fps_timer >= 0.25:
                self._fps_timer = 0.0
                self._fps_display = int(round(self.clock.get_fps()))
            fps_surf = self.text_cache.get(
                self.font, f"{getattr(self, '_fps_display', 0)} FPS", (120, 220, 120)
            )
            self.game_surface.blit(fps_surf, (BASE_WIDTH - fps_surf.get_width() - 16, 12))

        # CRT scanlines — multiply, same format as game_surface (no alpha blit)
        if int(getattr(self, "scanlines", 0) or 0) > 0:
            sc = self._ensure_scanline_surf()
            if sc is not None:
                self.game_surface.blit(sc, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

        if getattr(self, "touch_enabled", False) and hasattr(self, "touch"):
            if self.started or self.menu_screen != "main":
                self.touch.set_menu_rows([])
            self.touch.draw(self.game_surface, mode=self._touch_layout_mode())
        
        # Present — scale game only when needed; bezel art is cached
        mode = getattr(self, "display_mode", "window")
        scr_size = self.screen.get_size()
        if getattr(self, "_present_size", None) != scr_size:
            self._present_size = scr_size
            self._layout_viewport()
            self._invalidate_present_cache()

        vr = getattr(self, "view_rect", pygame.Rect(0, 0, BASE_WIDTH, BASE_HEIGHT))

        if mode == "window" and scr_size == (BASE_WIDTH, BASE_HEIGHT):
            self.screen.blit(self.game_surface, (shake_x, shake_y))
        elif self.bezel_active and vr.width > 0 and vr.height > 0:
            self._ensure_bezel_cache()
            # Opaque cached panels (display format) — cheap side blits
            if self._bezel_blit_left is not None:
                self.screen.blit(self._bezel_blit_left, (0, 0))
            if self._bezel_blit_right is not None:
                self.screen.blit(self._bezel_blit_right, (vr.right, 0))
            # Scale the game straight into the center (no fill, no extra buffer blit)
            # when there is no screen-shake. Shake uses a temp dest.
            dest_x, dest_y = vr.x + shake_x, vr.y + shake_y
            if shake_x == 0 and shake_y == 0 and vr.width > 0:
                try:
                    dest = self.screen.subsurface(vr)
                    if vr.width == BASE_WIDTH and vr.height == BASE_HEIGHT:
                        dest.blit(self.game_surface, (0, 0))
                    else:
                        pygame.transform.scale(self.game_surface, (vr.width, vr.height), dest)
                except Exception:
                    self._present_game_scaled(vr, dest_x, dest_y)
            else:
                self.screen.fill((0, 0, 0), vr)
                self._present_game_scaled(vr, dest_x, dest_y)
        else:
            self.screen.fill((0, 0, 0))
            if vr.width > 0 and vr.height > 0:
                self._present_game_scaled(vr, vr.x + shake_x, vr.y + shake_y)
        pygame.display.flip()

    # --- Main loop ---
    def run(self):
        while self.running:
            # Cap: menu stays at 60 (enough, less CPU on iGPU).
            # In-game use detected refresh, but don't chase 120 if we can't hold it.
            cap = 60
            self.dt = self.clock.tick(cap) / 1000.0
            # Safety clamp (spiral of death protection)
            self.dt = min(self.dt, 0.05)
            
            self.handle_events()
            self.update()
            self.draw()
            
        pygame.quit()
        sys.exit(0)
