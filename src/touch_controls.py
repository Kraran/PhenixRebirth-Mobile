"""HUD tactile paysage + souris debug PC.

Coordonnées = canvas 1280x720.
Pad 1 axe digital. Fire = hold / confirm. Phenix & pause = edge.
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
        self._pending_pick = None
        self._pending_kind = None
        self.menu_rows = []
        self._layout()

    def _layout(self):
        w, h = self.w, self.h
        pad_w, pad_h = 320, 180
        self.pad = pygame.Rect(22, h - pad_h - 18, pad_w, pad_h)
        btn = 108
        right = w - 22
        self.fire = pygame.Rect(right - btn, h - btn - 22, btn, btn)
        self.phenix = pygame.Rect(right - 88, self.fire.y - 88 - 12, 88, 88)
        self.pause = pygame.Rect(right - 56, 14, 56, 42)

    def set_menu_rows(self, rows):
        """rows: list of (pygame.Rect, index, kind)."""
        self.menu_rows = list(rows or [])

    def _hit_button(self, x, y):
        if self.fire.collidepoint(x, y):
            return "fire"
        if self.phenix.collidepoint(x, y):
            return "phenix"
        if self.pause.collidepoint(x, y):
            return "pause"
        if self.pad.collidepoint(x, y):
            return "pad"
        return None

    def _hit_row(self, x, y):
        for rect, idx, kind in self.menu_rows:
            if rect.collidepoint(x, y):
                return idx, kind
        return None

    def _pad_dx(self, x):
        half = self.pad.width * 0.5
        if half <= 1:
            return 0.0
        t = (x - self.pad.centerx) / half
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
        zone = self._hit_button(x, y)

        if down:
            if zone is None:
                hit = self._hit_row(x, y)
                if hit is None:
                    return False
                self._pending_pick, self._pending_kind = hit
                self._holds[pid] = "row"
                return True
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

        self.state.dx = dx
        self.state.fire = fire
        self.state.phenix = phenix_held and not self._prev_phenix
        self.state.pause = pause_held and not self._prev_pause
        self.state.active = bool(self._holds)
        self.state.menu_confirm = fire and not self._prev_fire_btn
        self.state.menu_back = self.state.pause
        self.state.menu_pick = self._pending_pick
        self.state.menu_kind = self._pending_kind
        self._pending_pick = None
        self._pending_kind = None
        self._prev_phenix = phenix_held
        self._prev_pause = pause_held
        self._prev_fire_btn = fire
        return self.state

    def draw(self, surface, mode="game"):
        """mode: 'game' (pad+tir+phenix+pause) ou 'menu' (OK + retour)."""
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        font = pygame.font.Font(None, 24)

        if mode == "game":
            pygame.draw.rect(overlay, (30, 90, 160, 48), self.pad, border_radius=16)
            pygame.draw.rect(overlay, (180, 220, 255, 90), self.pad, 2, border_radius=16)
            pygame.draw.line(
                overlay, (180, 220, 255, 70),
                (self.pad.centerx, self.pad.y + 10),
                (self.pad.centerx, self.pad.bottom - 10), 2,
            )
            pygame.draw.ellipse(overlay, (200, 40, 40, 70), self.fire)
            pygame.draw.ellipse(overlay, (255, 200, 200, 120), self.fire, 2)
            pygame.draw.rect(overlay, (200, 120, 20, 70), self.phenix, border_radius=14)
            pygame.draw.rect(overlay, (255, 210, 120, 120), self.phenix, 2, border_radius=14)
            pygame.draw.rect(overlay, (200, 200, 220, 60), self.pause, border_radius=8)
            pygame.draw.rect(overlay, (230, 230, 240, 120), self.pause, 2, border_radius=8)
            for label, rect in (("FIRE", self.fire), ("PHENIX", self.phenix), ("II", self.pause)):
                txt = font.render(label, True, (255, 255, 255))
                overlay.blit(txt, txt.get_rect(center=rect.center))
        else:
            pygame.draw.ellipse(overlay, (200, 40, 40, 90), self.fire)
            pygame.draw.ellipse(overlay, (255, 210, 210, 150), self.fire, 2)
            pygame.draw.rect(overlay, (200, 200, 220, 80), self.pause, border_radius=8)
            pygame.draw.rect(overlay, (240, 240, 250, 150), self.pause, 2, border_radius=8)
            ok = font.render("OK", True, (255, 255, 255))
            back = font.render("II", True, (255, 255, 255))
            overlay.blit(ok, ok.get_rect(center=self.fire.center))
            overlay.blit(back, back.get_rect(center=self.pause.center))

        surface.blit(overlay, (0, 0))
