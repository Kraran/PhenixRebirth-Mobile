"""
Player ship: movement, single-bullet shot, edge lightning / kill timer,
thruster animation, and multi-stage death sequences.

Input supports keyboard and gamepad with a short post-menu grace period
to avoid accidental fire when confirming "Play".
"""
import pygame
import os
import math
import random
from settings import *

from settings import asset_path
SHIP_PATH = asset_path("sprites", "player_ship.png")

class Player:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        
        self.image = pygame.image.load(SHIP_PATH).convert_alpha()
        self.width = self.image.get_width()
        self.height = self.image.get_height()
        self.speed = PLAYER_SPEED

        # Phenix form: flight loop + morph sequence (ship ↔ firebird)
        self.phenix_frames = []
        self.morph_frames = []  # 1→4 becoming Phenix
        self.phenix_anim_time = 0.0
        self.PHENIX_ANIM_FPS = 10.0
        self.morph_timer = 0.0
        self.morph_duration = 0.0
        self.morph_dir = 0  # +1 to phenix, -1 to ship, 0 idle
        self.MORPH_IN_SEC = 0.45
        self.MORPH_OUT_SEC = 0.40
        phenix_dir = asset_path("sprites", "phenix")
        if os.path.isdir(phenix_dir):
            for name in sorted(os.listdir(phenix_dir)):
                path = os.path.join(phenix_dir, name)
                try:
                    fr = pygame.image.load(path).convert_alpha()
                except Exception as e:
                    print("phenix asset skip:", name, e)
                    continue
                if name.startswith("phenix_") and name.endswith(".png"):
                    self.phenix_frames.append(fr)
                elif name.startswith("morph_") and name.endswith(".png"):
                    self.morph_frames.append(fr)
        
        # Active shots: list of {x, y, resolved, flame}
        # Normal: max 1. Phenix: max 2 (pair from rear wings), one volley on screen.
        self.shots = []
        
        # Phenix gauge (0–10). Each valid kill +1, each miss -1 (no combo required).
        self.phenix_gauge = 0
        self.combo_streak = 0  # kept for compatibility; no longer used for fill
        self.phenix_timer = 0.0  # remaining transform time (seconds)
        self.phenix_duration = 0.0  # total duration at activation
        self.phenix_start_level = 0  # gauge level spent at activation
        self.PHENIX_SPEED_MULT = 1.35
        self.PHENIX_END_INVULN = 0.45
        self.phenix_sec_per_point = 0.6  # duration per gauge level
        self.phenix_min_gauge = 0  # novice keeps at least 1
        self.phenix_auto_refill = False  # PHEN cheat
        self.PHENIX_REFILL_TIME = 3.0  # seconds 0→10
        self.phenix_cooldown = 0.0
        self.PHENIX_COOLDOWN_SEC = 1.25
        
        self.lives = PLAYER_MAX_LIVES
        self.infinite_lives = False
        self.invulnerable = 0.0
        self.alive = True
        
        self.rect = self.image.get_rect(center=(self.x, self.y))
        
        # Hitbox covers fuselage + wings (shots must not pass through wings)
        self.hitbox_w = max(28, int(self.width * 0.78))
        self.hitbox_h = max(32, int(self.height * 0.52))
        # Twin engines spacing (px from center each side)
        self.engine_offset = 8
        
        # Engine animation
        self.moving = False
        self.engine_time = 0.0
        self.engine_intensity = 0.0
        
        # Edge collision / lightning
        self.edge_contact = False
        self.edge_side = 0
        self.edge_timer = 0.0
        self.EDGE_KILL_TIME = 0.50
        self.edge_flash = 0.0
        self.slowdown_timer = 0.0
        self.SLOWDOWN_DURATION = 1.7
        self.SLOWDOWN_FACTOR = 0.35
        
        # Death disappearance
        self.dying = False
        self.death_timer = 0.0
        self.DEATH_DURATION = 0.70
        self.death_flash = False
        self._white_image = None

    def update(self, dt, keys, input_mode="keyboard", joystick=None, allow_shoot=True, ai_move=None, ai_shoot=None):
        if not self.alive:
            return False
        
        # Death animation — no control
        if self.dying:
            self.death_timer += dt
            self.death_flash = (int(self.death_timer * 18) % 2) == 0
            self.engine_intensity = max(0.0, self.engine_intensity - dt * 2.0)
            if self.death_timer >= self.DEATH_DURATION:
                self.alive = False
                self.dying = False
            return False
            
        if self.invulnerable > 0:
            self.invulnerable = max(0.0, self.invulnerable - dt)
        if getattr(self, "phenix_cooldown", 0) > 0:
            self.phenix_cooldown = max(0.0, self.phenix_cooldown - dt)

        # Morph ship ↔ Phenix (must advance every frame)
        if getattr(self, "morph_dir", 0) != 0:
            self.morph_timer += dt
            if self.morph_timer >= self.morph_duration:
                if self.morph_dir < 0:
                    # Morph-out done → normal ship
                    self.morph_dir = 0
                    self.morph_timer = 0.0
                    self.phenix_timer = 0.0
                    self.phenix_duration = 0.0
                    self.phenix_start_level = 0
                    if getattr(self, "phenix_saved_gauge", None) is not None:
                        self.phenix_gauge = max(
                            float(self.phenix_min_gauge),
                            min(10.0, float(self.phenix_saved_gauge)),
                        )
                        self.phenix_saved_gauge = None
                    else:
                        self.phenix_gauge = float(self.phenix_min_gauge)
                    self.phenix_cooldown = float(getattr(self, "PHENIX_COOLDOWN_SEC", 1.25))
                else:
                    # Morph-in done → full Phenix flight loop
                    self.morph_dir = 0
                    self.morph_timer = 0.0

        # Phenix form countdown — only while fully transformed (not during morph)
        if self.phenix_timer > 0 and getattr(self, "morph_dir", 0) == 0:
            self.phenix_timer = max(0.0, self.phenix_timer - dt)
            if not hasattr(self, "phenix_anim_time"):
                self.phenix_anim_time = 0.0
            self.phenix_anim_time += dt
            if self.phenix_duration > 0:
                self.phenix_gauge = self.phenix_start_level * (self.phenix_timer / self.phenix_duration)
            if self.phenix_timer <= 0:
                self.end_phenix(grant_invuln=True)
        elif self.phenix_auto_refill and self.alive and not self.dying and getattr(self, "morph_dir", 0) == 0:
            rate = 10.0 / max(0.1, self.PHENIX_REFILL_TIME)
            if self.phenix_gauge < 10.0:
                self.phenix_gauge = min(10.0, self.phenix_gauge + rate * dt)
        
        dx = 0.0
        shoot_pressed = False

        # Attract-mode AI overrides human input when provided
        if ai_move is not None:
            # Same units as keyboard: -1 / 0 / +1 (speed applied later)
            dx = float(ai_move)
            shoot_pressed = bool(ai_shoot) if allow_shoot else False
            _ai = True
        else:
            _ai = False
        
        if not _ai and input_mode == "gamepad" and joystick is not None:
            try:
                axis = joystick.get_axis(0)
                if abs(axis) > 0.25:
                    dx = 1.0 if axis > 0 else -1.0
                # D-pad hat
                if joystick.get_numhats() > 0:
                    hat = joystick.get_hat(0)
                    if hat[0] < 0:
                        dx = -1.0
                    elif hat[0] > 0:
                        dx = 1.0
                # Face buttons: 0=A, 1=B, 2=X, 3=Y — also shoulder
                # B (1) reserved for Phenix activation (edge-triggered in Game)
                for b in (0, 2, 3, 5):
                    if joystick.get_numbuttons() > b and joystick.get_button(b):
                        shoot_pressed = True
                        break
            except Exception:
                pass
        elif not _ai:
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                dx -= 1.0
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                dx += 1.0
            shoot_pressed = keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]
        
        self.moving = dx != 0.0
        
        if self.slowdown_timer > 0:
            self.slowdown_timer = max(0.0, self.slowdown_timer - dt)
            speed_mult = self.SLOWDOWN_FACTOR
        else:
            speed_mult = 1.0
        if self.is_phenix:
            speed_mult *= self.PHENIX_SPEED_MULT
            
        self.x += dx * self.speed * speed_mult * dt
        
        margin = 36
        left_limit = margin
        right_limit = BASE_WIDTH - margin
        
        self.edge_contact = False
        self.edge_side = 0
        
        if self.x <= left_limit:
            self.x = left_limit
            if dx < 0:
                self.edge_contact = True
                self.edge_side = -1
        elif self.x >= right_limit:
            self.x = right_limit
            if dx > 0:
                self.edge_contact = True
                self.edge_side = 1
        
        if self.edge_contact and self.invulnerable <= 0:
            # Any edge spark empties Phenix gauge (and ends form if active)
            if self.is_phenix:
                self.end_phenix(grant_invuln=True)
                self.edge_timer = 0.0
                self.edge_flash = 0.35
                self.slowdown_timer = max(self.slowdown_timer, 0.5)
            else:
                if self.phenix_gauge > self.phenix_min_gauge or self.combo_streak > 0:
                    self.phenix_gauge = float(self.phenix_min_gauge)
                    self.combo_streak = 0
                self.edge_timer += dt
                self.edge_flash = min(1.0, self.edge_timer / 0.25)
                if self.slowdown_timer <= 0:
                    self.slowdown_timer = self.SLOWDOWN_DURATION
                else:
                    self.slowdown_timer = max(self.slowdown_timer, 0.35)
        else:
            self.edge_timer = max(0.0, self.edge_timer - dt * 2.5)
            self.edge_flash = max(0.0, self.edge_flash - dt * 4.0)
        
        self.rect.center = (int(self.x), int(self.y))
        
        self.engine_time += dt
        target = 1.0 if self.moving else 0.25
        self.engine_intensity += (target - self.engine_intensity) * min(1.0, 8.0 * dt)
        
        # Update shots
        for shot in self.shots[:]:
            shot["y"] -= BULLET_SPEED * dt
            if shot["y"] < -30:
                if not shot.get("resolved"):
                    self.register_miss()
                self.shots.remove(shot)
        
        if allow_shoot and shoot_pressed and not self.shots:
            self.shoot()
        
        return self._check_edge_kill()

    def _check_edge_kill(self):
        if self.edge_timer >= self.EDGE_KILL_TIME and self.alive and not self.dying:
            if self.invulnerable <= 0 and not self.is_phenix:
                self.hit()
                self.edge_timer = 0.0
                self.edge_flash = 0.0
                return True  # damage applied
        return False

    def shoot(self):
        if self.dying or self.shots:
            return
        by = self.y - self.height // 2 - 4
        if self.is_phenix:
            # Dual fire from rear wings
            wing = max(12, int(self.width * 0.28))
            self.shots = [
                {"x": self.x - wing, "y": by + 4, "resolved": False, "flame": True},
                {"x": self.x + wing, "y": by + 4, "resolved": False, "flame": True},
            ]
        else:
            self.shots = [
                {"x": self.x, "y": by, "resolved": False, "flame": False},
            ]
        if getattr(self, "sounds", None):
            self.sounds.play("shoot", volume=0.45)

    def destroy_bullet(self, result=None, index=None):
        """Remove one shot (index) or all. result: 'valid' | 'neutral' | None."""
        if not self.shots:
            return
        if index is None:
            # Clear all (stage transition, etc.) — no miss penalty
            for s in self.shots:
                s["resolved"] = True
            self.shots.clear()
            return
        if index < 0 or index >= len(self.shots):
            return
        shot = self.shots[index]
        if result == "valid":
            self.register_valid_hit()
            shot["resolved"] = True
        elif result == "neutral":
            shot["resolved"] = True
        self.shots.pop(index)

    def _clamp_phenix_gauge(self):
        """Respect difficulty floor (novice: never below 1)."""
        self.phenix_gauge = max(float(self.phenix_min_gauge), float(self.phenix_gauge))
        if self.phenix_gauge > 10:
            self.phenix_gauge = 10.0

    def register_miss(self):
        """Shot left the screen with no valid/neutral contact — -1 gauge."""
        if self.is_phenix:
            return  # no gauge change during form
        self.combo_streak = 0
        self.phenix_gauge = max(float(self.phenix_min_gauge), float(self.phenix_gauge) - 1.0)

    @property
    def is_phenix(self):
        if not self.alive or self.dying:
            return False
        if getattr(self, "morph_dir", 0) != 0:
            return True
        return self.phenix_timer > 0

    def can_activate_phenix(self):
        return (
            self.alive and not self.dying
            and not self.is_phenix
            and self.phenix_gauge >= 3
            and getattr(self, "phenix_cooldown", 0) <= 0
        )

    def try_activate_phenix(self):
        """Spend gauge for 0.6s * level; bar drains over the duration as timer."""
        if not self.can_activate_phenix():
            return False
        level = int(self.phenix_gauge)
        self.phenix_start_level = level
        self.phenix_duration = self.phenix_sec_per_point * level
        self.phenix_timer = self.phenix_duration
        # Keep gauge full at start; update() drains it toward 0
        self.phenix_gauge = float(level)
        self.combo_streak = 0
        self.phenix_anim_time = 0.0
        self.morph_dir = 1
        self.morph_timer = 0.0
        self.morph_duration = self.MORPH_IN_SEC if self.morph_frames else 0.0
        if getattr(self, "sounds", None):
            self.sounds.play("phenix_activate")
        return True

    def end_phenix(self, grant_invuln=False, keep_gauge=False):
        """End Phenix form — reverse morph 4→1.

        keep_gauge=True: player cancelled early — conserve remaining gauge.
        """
        # Already morphing out
        if getattr(self, "morph_dir", 0) < 0:
            return

        was_active = (
            self.phenix_timer > 0 or self.phenix_duration > 0
            or getattr(self, "morph_dir", 0) > 0
        )
        if not was_active:
            return

        # Snapshot remaining gauge before clearing timers
        if keep_gauge:
            # Prefer live gauge (already tracks remaining time); fallback to timer ratio
            remaining = float(self.phenix_gauge)
            if remaining <= 0 and self.phenix_duration > 0 and self.phenix_timer > 0:
                remaining = self.phenix_start_level * (self.phenix_timer / self.phenix_duration)
            self.phenix_saved_gauge = max(
                float(self.phenix_min_gauge), min(10.0, remaining)
            )
        else:
            self.phenix_saved_gauge = None

        if getattr(self, "morph_frames", None):
            self.morph_dir = -1
            self.morph_timer = 0.0
            self.morph_duration = self.MORPH_OUT_SEC
            self.phenix_timer = 0.0
            if getattr(self, "sounds", None):
                self.sounds.play("phenix_end")
            if grant_invuln and self.alive and not self.dying:
                self.invulnerable = max(self.invulnerable, self.PHENIX_END_INVULN)
            return

        # No morph frames — instant end
        self.morph_dir = 0
        self.morph_timer = 0.0
        self.phenix_timer = 0.0
        self.phenix_duration = 0.0
        self.phenix_start_level = 0
        if self.phenix_saved_gauge is not None:
            self.phenix_gauge = self.phenix_saved_gauge
            self.phenix_saved_gauge = None
        else:
            self.phenix_gauge = float(self.phenix_min_gauge)
        self.phenix_cooldown = float(getattr(self, "PHENIX_COOLDOWN_SEC", 1.25))
        if getattr(self, "sounds", None):
            self.sounds.play("phenix_end")
        if grant_invuln and self.alive and not self.dying:
            self.invulnerable = max(self.invulnerable, self.PHENIX_END_INVULN)

    def cancel_phenix(self):
        """Manual early exit (B again) — keep remaining gauge."""
        if not self.is_phenix:
            return False
        if getattr(self, "morph_dir", 0) < 0:
            return False  # already exiting
        self.end_phenix(grant_invuln=True, keep_gauge=True)
        return True


    def register_valid_hit(self):
        """Body/core kill — +1 gauge (capped at 10). No combo required."""
        if self.is_phenix:
            return  # no refill during form
        self.phenix_gauge = min(10.0, float(self.phenix_gauge) + 1.0)
        self.combo_streak = 0

    def hit(self):
        """Apply damage. Returns True if this hit started the death sequence."""
        # Phenix: immune to normal hits (bullets / dives). Hull/edge handled separately.
        if self.is_phenix:
            return False
        if self.invulnerable > 0 or not self.alive or self.dying:
            return False
            
        if not self.infinite_lives:
            self.lives -= 1
        self.invulnerable = PLAYER_INVULN_TIME
        # Any life loss clears Phenix gauge / combo (novice keeps floor)
        self.phenix_gauge = float(self.phenix_min_gauge)
        self.combo_streak = 0
        self.phenix_timer = 0.0
        
        if self.lives <= 0 and not getattr(self, 'infinite_lives', False):
            self.lives = 0
            self.dying = True
            self.death_timer = 0.0
            self.invulnerable = 0.0
            return True
        
        return False

    def _get_white_image(self):
        if self._white_image is None:
            w, h = self.image.get_size()
            white = pygame.Surface((w, h), pygame.SRCALPHA)
            for y in range(h):
                for x in range(w):
                    r, g, b, a = self.image.get_at((x, y))
                    if a > 20:
                        white.set_at((x, y), (255, 255, 255, a))
            self._white_image = white
        return self._white_image

    def _draw_engine_flame(self, surface, cx, cy, intensity):
        if intensity < 0.05:
            return
        
        phenix = self.is_phenix
        # Boost size when transformed
        if phenix:
            intensity = max(intensity, 0.85) * 1.55
        
        flicker = 0.85 + 0.15 * math.sin(self.engine_time * 28.0 + cx * 0.1)
        length = intensity * flicker * random.uniform(14, 22)
        width = 5 + intensity * 3
        if phenix:
            length *= 1.35
            width *= 1.45
        
        for i in range(3, 0, -1):
            h = length * (0.5 + 0.5 * (i / 3.0))
            w = width * (1.4 - 0.2 * i)
            if phenix:
                # Outer dark red → orange → bright core
                color = (
                    (160, 20, 5),
                    (220, 50, 10),
                    (255, 110, 25),
                )[min(2, 3 - i)]
            else:
                color = (40, 160 + i * 30, 255)
            points = [
                (cx - w, cy),
                (cx + w, cy),
                (cx + w * 0.3, cy + h),
                (cx - w * 0.3, cy + h),
            ]
            pygame.draw.polygon(surface, color, points)
        
        core_h = length * 0.7
        core_w = width * 0.45
        if phenix:
            pygame.draw.polygon(surface, (255, 200, 60), [
                (cx - core_w, cy),
                (cx + core_w, cy),
                (cx + core_w * 0.2, cy + core_h),
                (cx - core_w * 0.2, cy + core_h),
            ])
            pygame.draw.circle(surface, (255, 245, 180), (int(cx), int(cy + core_h * 0.85)), 3)
        else:
            pygame.draw.polygon(surface, (180, 255, 255), [
                (cx - core_w, cy),
                (cx + core_w, cy),
                (cx + core_w * 0.2, cy + core_h),
                (cx - core_w * 0.2, cy + core_h),
            ])
            pygame.draw.circle(surface, (220, 255, 255), (int(cx), int(cy + core_h * 0.85)), 2)

    def _draw_edge_lightning(self, surface):
        if self.edge_flash < 0.05 or self.dying:
            return
        
        intensity = self.edge_flash
        cx, cy = self.x, self.y
        num_arcs = 3 + int(intensity * 5)
        
        for i in range(num_arcs):
            angle = random.uniform(0, math.pi * 2)
            dist = random.uniform(18, 38 + intensity * 20)
            x1 = cx + math.cos(angle) * 12
            y1 = cy + math.sin(angle) * 10
            x2 = cx + math.cos(angle) * dist
            y2 = cy + math.sin(angle) * dist * 0.7
            
            points = [(x1, y1)]
            steps = random.randint(3, 5)
            for s in range(1, steps):
                t = s / steps
                mx = x1 + (x2 - x1) * t + random.uniform(-8, 8)
                my = y1 + (y2 - y1) * t + random.uniform(-6, 6)
                points.append((mx, my))
            points.append((x2, y2))
            
            if random.random() > intensity * 0.7:
                continue
            
            color = (200, 230, 255) if random.random() < 0.4 else (80, 160, 255)
            width = 2 if color[0] > 150 else 1
            pygame.draw.lines(surface, color, False, points, width)
        
        if random.random() < intensity * 0.35:
            r = int(22 + intensity * 18 + random.uniform(-4, 4))
            pygame.draw.circle(surface, (120, 190, 255), (int(cx), int(cy)), r, 1)
        
        if self.edge_side != 0:
            wall_x = 8 if self.edge_side < 0 else BASE_WIDTH - 8
            for _ in range(2):
                y_off = random.uniform(-25, 25)
                points = [
                    (cx + self.edge_side * 15, cy + y_off * 0.3),
                    (cx + self.edge_side * 25 + random.uniform(-5, 5), cy + y_off * 0.6),
                    (wall_x, cy + y_off + random.uniform(-8, 8)),
                ]
                pygame.draw.lines(surface, (150, 210, 255), False, points, 1)

    def draw(self, surface):
        if not self.alive:
            return
        
        # Death disappearance
        if self.dying:
            t = self.death_timer / self.DEATH_DURATION
            alpha = max(0, int(255 * (1.0 - t)))
            scale = 1.0 + 0.45 * t
            
            img = self._get_white_image() if (self.death_flash and t < 0.55) else self.image
            w = max(1, int(self.width * scale))
            h = max(1, int(self.height * scale))
            scaled = pygame.transform.smoothscale(img, (w, h))
            scaled.set_alpha(alpha)
            surface.blit(scaled, (int(self.x - w // 2), int(self.y - h // 2)))
            
            # Dying engine sputter
            if t < 0.5:
                ship_bottom = self.y + h // 2 - 4
                off = getattr(self, "engine_offset", 8)
                self._draw_engine_flame(surface, self.x - off, ship_bottom, 0.6 * (1.0 - t))
                self._draw_engine_flame(surface, self.x + off, ship_bottom, 0.6 * (1.0 - t))
            return
        
        # Blink when invulnerable
        if self.invulnerable > 0 and int(self.invulnerable * 12) % 2 == 0:
            return
        
        morph_frames = getattr(self, "morph_frames", None) or []
        morph_dir = getattr(self, "morph_dir", 0)
        if morph_dir != 0 and morph_frames:
            n = len(morph_frames)
            prog = 0.0 if self.morph_duration <= 0 else min(1.0, self.morph_timer / self.morph_duration)
            if morph_dir > 0:
                # 1→4 (indices 0..n-1)
                idx = int(prog * (n - 1) + 1e-6)
            else:
                # 4→1
                idx = int((1.0 - prog) * (n - 1) + 1e-6)
            idx = max(0, min(n - 1, idx))
            img = morph_frames[idx]
            iw, ih = img.get_width(), img.get_height()
            surface.blit(img, (int(self.x - iw // 2), int(self.y - ih // 2)))
            ship_bottom = self.y + ih // 2 - 6
        elif self.is_phenix and getattr(self, "phenix_frames", None):
            n = len(self.phenix_frames)
            idx = int(self.phenix_anim_time * self.PHENIX_ANIM_FPS) % n
            img = self.phenix_frames[idx]
            iw, ih = img.get_width(), img.get_height()
            surface.blit(img, (int(self.x - iw // 2), int(self.y - ih // 2)))
            ship_bottom = self.y + ih // 2 - 6
        else:
            draw_x = int(self.x - self.width // 2)
            draw_y = int(self.y - self.height // 2)
            surface.blit(self.image, (draw_x, draw_y))
            ship_bottom = self.y + self.height // 2 - 2

        offset = getattr(self, "engine_offset", 8)
        self._draw_engine_flame(surface, self.x - offset, ship_bottom, self.engine_intensity)
        self._draw_engine_flame(surface, self.x + offset, ship_bottom, self.engine_intensity)
        
        self._draw_edge_lightning(surface)
        
        for shot in self.shots:
            bx, by = int(shot["x"]), int(shot["y"])
            if shot.get("flame"):
                # Orange-red flame bolt, bright yellow-orange core
                pygame.draw.rect(surface, (180, 40, 10), (bx - 5, by, 10, 15))
                pygame.draw.rect(surface, (255, 100, 20), (bx - 4, by, 8, 14))
                pygame.draw.rect(surface, (255, 180, 50), (bx - 2, by, 4, 13))
                pygame.draw.rect(surface, (255, 240, 160), (bx - 1, by, 2, 10))
                pygame.draw.circle(surface, (255, 220, 120), (bx, by), 3)
            else:
                pygame.draw.rect(surface, (140, 255, 255), (bx - 3, by, 6, 16))
                pygame.draw.rect(surface, (255, 255, 255), (bx - 1, by, 2, 16))

    def get_bullet_rects(self):
        """List of (index, rect) for active shots."""
        if self.dying:
            return []
        out = []
        for i, shot in enumerate(self.shots):
            bx, by = shot["x"], shot["y"]
            if shot.get("flame"):
                out.append((i, pygame.Rect(int(bx) - 4, int(by), 8, 16)))
            else:
                out.append((i, pygame.Rect(int(bx) - 3, int(by), 6, 16)))
        return out

    def get_bullet_rect(self):
        """Primary shot rect (compat)."""
        rects = self.get_bullet_rects()
        return rects[0][1] if rects else None

    @property
    def bullet(self):
        """Compat: truthy if any shot on screen (attract AI, etc.)."""
        return self.shots[0] if self.shots else None

    def get_hitbox(self):
        if self.dying or not self.alive:
            return pygame.Rect(0, 0, 0, 0)
        return pygame.Rect(
            self.x - self.hitbox_w // 2,
            self.y - self.hitbox_h // 2,
            self.hitbox_w,
            self.hitbox_h
        )
