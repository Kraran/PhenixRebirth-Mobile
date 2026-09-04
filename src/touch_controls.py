"""HUD tactile paysage + souris debug PC.

Coordonnées = canvas 1280x720 (pas pixels écran).
Pad = 1 axe, sortie digitale -1/0/+1. Fire = hold. Phenix / pause = edge.
"""
import pygame
from input_state import InputState


class TouchControls:
    DEADZONE = 0.15

    def __init__(self, width=1280, height=720):
        self.w = width
        self.h = height
        self.state = InputState()
        self._prev_phenix = False
        self._prev_pause = False
        self._prev_fire_btn = False
        self._holds = {}
        self._pad_x = None
        self._layout()

    def _layout(self):
        w, h = self.w, self.h
        pad_w, pad_h = 360, 220
        self.pad = pygame.Rect(24, h - pad_h - 20, pad_w, pad_h)
        btn = 130
        right = w - 24
        self.fire = pygame.Rect(right - btn, h - btn - 24, btn, btn)
        self.phenix = pygame.Rect(right - 100, self.fire.y - 100 - 14, 100, 100)
        self.pause = pygame.Rect(right - 64, 16, 64, 48)

    def _hit(self, x, y):
        if self.fire.collidepoint(x, y):
            return "fire"
        if self.phenix.collidepoint(x, y):
            return "phenix"
        if self.pause.collidepoint(x, y):
            return "pause"
        if self.pad.collidepoint(x, y):
            return "pad"
        return None

    def _pad_dx(self, x):
        cx = self.pad.centerx
        half = self.pad.width * 0.5
        if half <= 1:
            return 0.0
        t = (x - cx) / half
        if t > self.DEADZONE:
            return 1.0
        if t < -self.DEADZONE:
            return -1.0
        return 0.0

    def screen_to_canvas(self, sx, sy, view_rect):
        if view_rect is None or view_rect.width <= 0 or view_rect.height <= 0:
            return sx, sy
        x = (sx - view_rect.x) * self.w / float(view_rect.width)
        y = (sy - view_rect.y) * self.h / float(view_rect.height)
        return x, y

    def handle_event(self, event, view_rect):
        et = event.type
        finger_down = getattr(pygame, "FINGERDOWN", -10)
        finger_up = getattr(pygame, "FINGERUP", -11)
        finger_move = getattr(pygame, "FINGERMOTION", -12)
        down = et == pygame.MOUSEBUTTONDOWN or et == finger_down
        up = et == pygame.MOUSEBUTTONUP or et == finger_up
        move = et == pygame.MOUSEMOTION or et == finger_move
        if not (down or up or move):
            return False

        if et in (finger_down, finger_up, finger_move):
            try:
                win = pygame.display.get_surface()
                sw, sh = win.get_size() if win else (self.w, self.h)
            except Exception:
                sw, sh = self.w, self.h
            sx, sy = event.x * sw, event.y * sh
            pid = ("f", getattr(event, "finger_id", 0))
        else:
            if down and getattr(event, "button", 1) != 1:
                return False
            if up and getattr(event, "button", 1) != 1:
                return False
            sx, sy = event.pos
            pid = ("m", 0)

        x, y = self.screen_to_canvas(sx, sy, view_rect)
        zone = self._hit(x, y)

        if down:
            if zone is None:
                return False
            self._holds[pid] = zone
            if zone == "pad":
                self._pad_x = x
            return True
        if up:
            if pid in self._holds:
                if self._holds[pid] == "pad":
                    self._pad_x = None
                del self._holds[pid]
                return True
            return False
        if move and pid in self._holds:
            if self._holds[pid] == "pad":
                self._pad_x = x
            return True
        return pid in self._holds

    def finalize(self, view_rect):
        dx = 0.0
        fire = False
        phenix_held = False
        pause_held = False

        for pid, zone in list(self._holds.items()):
            if zone == "fire":
                fire = True
            elif zone == "phenix":
                phenix_held = True
            elif zone == "pause":
                pause_held = True
            elif zone == "pad":
                if self._pad_x is not None:
                    dx = self._pad_dx(self._pad_x)
                elif pid[0] == "m":
                    try:
                        mx, my = pygame.mouse.get_pos()
                        x, _y = self.screen_to_canvas(mx, my, view_rect)
                        dx = self._pad_dx(x)
                    except Exception:
                        pass

        self.state.dx = dx
        self.state.fire = fire
        self.state.phenix = phenix_held and not self._prev_phenix
        self.state.pause = pause_held and not self._prev_pause
        self.state.active = bool(self._holds)
        self.state.menu_confirm = fire and not self._prev_fire_btn
        self.state.menu_back = self.state.pause
        self._prev_phenix = phenix_held
        self._prev_pause = pause_held
        self._prev_fire_btn = fire
        return self.state

    def draw(self, surface):
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        banner = pygame.Rect(0, 0, self.w, 36)
        pygame.draw.rect(overlay, (220, 40, 180, 210), banner)
        pygame.draw.rect(overlay, (80, 180, 255, 100), self.pad, border_radius=18)
        pygame.draw.rect(overlay, (200, 240, 255, 230), self.pad, 3, border_radius=18)
        pygame.draw.line(
            overlay, (200, 240, 255, 180),
            (self.pad.centerx, self.pad.y + 10),
            (self.pad.centerx, self.pad.bottom - 10), 3,
        )
        pygame.draw.rect(overlay, (255, 50, 50, 150), self.fire, border_radius=self.fire.w // 2)
        pygame.draw.rect(overlay, (255, 220, 220, 240), self.fire, 3, border_radius=self.fire.w // 2)
        pygame.draw.rect(overlay, (255, 160, 30, 150), self.phenix, border_radius=18)
        pygame.draw.rect(overlay, (255, 230, 160, 240), self.phenix, 3, border_radius=18)
        pygame.draw.rect(overlay, (220, 220, 240, 150), self.pause, border_radius=8)
        pygame.draw.rect(overlay, (255, 255, 255, 240), self.pause, 2, border_radius=8)
        font = pygame.font.Font(None, 28)
        big = pygame.font.Font(None, 32)
        title = big.render("MOBILE TOUCH ON  —  PAD / FIRE / PHENIX", True, (255, 255, 255))
        overlay.blit(title, title.get_rect(center=banner.center))
        for label, rect in (("PAD", self.pad), ("FIRE", self.fire),
                            ("PHENIX", self.phenix), ("II", self.pause)):
            txt = font.render(label, True, (255, 255, 255))
            overlay.blit(txt, txt.get_rect(center=rect.center))
        surface.blit(overlay, (0, 0))
