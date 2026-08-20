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
        
        self.bullet = None
        
        self.lives = PLAYER_MAX_LIVES
        self.infinite_lives = False
        self.invulnerable = 0.0
        self.alive = True
        
        self.rect = self.image.get_rect(center=(self.x, self.y))
        
        self.hitbox_w = 24
        self.hitbox_h = 32
        
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
                for b in (0, 1, 2, 3, 5):
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
        
        if self.bullet is not None:
            self.bullet[1] -= BULLET_SPEED * dt
            if self.bullet[1] < -30:
                self.bullet = None
        
        if allow_shoot and shoot_pressed and self.bullet is None:
            self.shoot()
        
        return self._check_edge_kill()

    def _check_edge_kill(self):
        if self.edge_timer >= self.EDGE_KILL_TIME and self.invulnerable <= 0 and self.alive and not self.dying:
            self.hit()
            self.edge_timer = 0.0
            self.edge_flash = 0.0
            return True  # damage applied — always trigger explosion
        return False

    def shoot(self):
        if self.dying:
            return
        self.bullet = [self.x, self.y - self.height // 2 - 4]
        if getattr(self, "sounds", None):
            self.sounds.play("shoot", volume=0.45)

    def destroy_bullet(self):
        self.bullet = None

    def hit(self):
        """Apply damage. Returns True if this hit started the death sequence."""
        if self.invulnerable > 0 or not self.alive or self.dying:
            return False
            
        if not self.infinite_lives:
            self.lives -= 1
        self.invulnerable = PLAYER_INVULN_TIME
        
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
        
        flicker = 0.85 + 0.15 * math.sin(self.engine_time * 28.0 + cx * 0.1)
        length = intensity * flicker * random.uniform(14, 22)
        width = 5 + intensity * 3
        
        for i in range(3, 0, -1):
            h = length * (0.5 + 0.5 * (i / 3.0))
            w = width * (1.4 - 0.2 * i)
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
                self._draw_engine_flame(surface, self.x - 8, ship_bottom, 0.6 * (1.0 - t))
                self._draw_engine_flame(surface, self.x + 8, ship_bottom, 0.6 * (1.0 - t))
            return
        
        # Blink when invulnerable
        if self.invulnerable > 0 and int(self.invulnerable * 12) % 2 == 0:
            return
        
        draw_x = int(self.x - self.width // 2)
        draw_y = int(self.y - self.height // 2)
        surface.blit(self.image, (draw_x, draw_y))

        ship_bottom = self.y + self.height // 2 - 4
        offset = 8
        self._draw_engine_flame(surface, self.x - offset, ship_bottom, self.engine_intensity)
        self._draw_engine_flame(surface, self.x + offset, ship_bottom, self.engine_intensity)
        
        self._draw_edge_lightning(surface)
        
        if self.bullet is not None:
            bx, by = self.bullet
            pygame.draw.rect(surface, (140, 255, 255), (int(bx) - 3, int(by), 6, 16))
            pygame.draw.rect(surface, (255, 255, 255), (int(bx) - 1, int(by), 2, 16))

    def get_bullet_rect(self):
        if self.bullet is None or self.dying:
            return None
        bx, by = self.bullet
        return pygame.Rect(int(bx) - 3, int(by), 6, 16)

    def get_hitbox(self):
        if self.dying or not self.alive:
            return pygame.Rect(0, 0, 0, 0)
        return pygame.Rect(
            self.x - self.hitbox_w // 2,
            self.y - self.hitbox_h // 2,
            self.hitbox_w,
            self.hitbox_h
        )
