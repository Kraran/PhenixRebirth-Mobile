"""
Scrolling multi-layer starfield with parallax, planets, and nebulae.

Stars are procedural; planets use solar-system inspired art; nebulae use
Hubble-inspired assets. At most one planet or one nebula is visible at a time.
"""
import pygame
import random
import math
import os
from settings import *

from settings import asset_path
NEBULA_DIR = asset_path("sprites", "nebulae")
PLANET_DIR = asset_path("sprites", "planets")

NEBULA_FILES = [
    "galaxy_andromeda.png",
    "galaxy_whirlpool.png",
    "galaxy_elliptical.png",
    "nebula_orion.png",
    "nebula_helix.png",
    "nebula_dark.png",
]

PLANET_FILES = [
    "mercury.png",
    "venus.png",
    "earth.png",
    "mars.png",
    "jupiter.png",
    "saturn.png",
    "uranus.png",
    "neptune.png",
]


class Star:
    def __init__(self, layer=0):
        self.layer = layer
        self.reset(random_y=True)
        
        if layer == 0:
            self.size = random.choice([1, 1, 1, 2])
            self.speed = random.uniform(18, 35)
            self.parallax = 0.04
            self.color = random.choice([
                (40, 60, 140), (50, 70, 160), (30, 50, 120), (60, 80, 180)
            ])
        elif layer == 1:
            self.size = random.choice([1, 2, 2])
            self.speed = random.uniform(45, 75)
            self.parallax = 0.09
            self.color = random.choice([
                (80, 120, 220), (100, 140, 255), (70, 100, 200), (120, 160, 255)
            ])
        else:
            self.size = random.choice([2, 2, 3])
            self.speed = random.uniform(90, 140)
            self.parallax = 0.16
            self.color = random.choice([
                (160, 190, 255), (200, 220, 255), (140, 180, 255), (180, 210, 255)
            ])

    def reset(self, random_y=False):
        self.x = random.uniform(0, BASE_WIDTH)
        if random_y:
            self.y = random.uniform(0, BASE_HEIGHT)
        else:
            self.y = random.uniform(-20, -5)

    def update(self, dt, player_dx=0.0):
        self.y += self.speed * dt
        self.x -= player_dx * self.parallax
        
        if self.x < -5:
            self.x += BASE_WIDTH + 10
        elif self.x > BASE_WIDTH + 5:
            self.x -= BASE_WIDTH + 10
        
        if self.y > BASE_HEIGHT + 10:
            self.reset()

    def draw(self, surface):
        if self.size <= 1:
            surface.set_at((int(self.x), int(self.y)), self.color)
        else:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), self.size)


class Planet:
    """Realistic solar system planet sprites"""
    
    _cache = {}
    
    def __init__(self):
        self.reset()
        self.alive = True
        self.parallax = 0.08

    @classmethod
    def _load_image(cls, filename):
        if filename not in cls._cache:
            path = os.path.join(PLANET_DIR, filename)
            img = pygame.image.load(path).convert_alpha()
            cls._cache[filename] = img
        return cls._cache[filename]

    def reset(self):
        filename = random.choice(PLANET_FILES)
        base = self._load_image(filename)
        
        # Variable size (same spirit as before)
        target_h = random.randint(36, 88)
        scale = target_h / base.get_height()
        w = max(1, int(base.get_width() * scale))
        h = max(1, int(base.get_height() * scale))
        self.image = pygame.transform.smoothscale(base, (w, h))
        
        if random.random() < 0.35:
            self.image = pygame.transform.flip(self.image, True, False)
        
        self.w = self.image.get_width()
        self.h = self.image.get_height()
        self.radius = max(self.w, self.h) // 2
        
        self.x = random.uniform(self.w // 2 + 40, BASE_WIDTH - self.w // 2 - 40)
        self.y = random.uniform(-self.h - 60, -self.h // 2 - 20)
        self.speed = random.uniform(22, 40)
        self.alive = True

    def update(self, dt, player_dx=0.0):
        self.y += self.speed * dt
        self.x -= player_dx * self.parallax
        
        if self.x < -self.w:
            self.x += BASE_WIDTH + self.w * 2
        elif self.x > BASE_WIDTH + self.w:
            self.x -= BASE_WIDTH + self.w * 2
        
        if self.y > BASE_HEIGHT + self.radius + 40:
            self.alive = False

    def draw(self, surface):
        rect = self.image.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(self.image, rect)


class Galaxy:
    def __init__(self):
        self.reset()
        self.alive = True
        self.parallax = 0.06

    def reset(self):
        self.x = random.uniform(60, BASE_WIDTH - 60)
        self.y = random.uniform(-140, -50)
        self.speed = random.uniform(25, 45)
        self.size = random.randint(8, 16)
        self.color = random.choice([
            (100, 180, 255), (140, 200, 255), (80, 160, 255), (160, 140, 255)
        ])
        self.alive = True

    def update(self, dt, player_dx=0.0):
        self.y += self.speed * dt
        self.x -= player_dx * self.parallax
        
        if self.x < -40:
            self.x += BASE_WIDTH + 80
        elif self.x > BASE_WIDTH + 40:
            self.x -= BASE_WIDTH + 80
        
        if self.y > BASE_HEIGHT + 40:
            self.alive = False

    def draw(self, surface):
        cx, cy = int(self.x), int(self.y)
        s = self.size
        
        pygame.draw.line(surface, self.color, (cx - s, cy), (cx + s, cy), 2)
        pygame.draw.line(surface, self.color, (cx, cy - s), (cx, cy + s), 2)
        d = int(s * 0.7)
        pygame.draw.line(surface, self.color, (cx - d, cy - d), (cx + d, cy + d), 1)
        pygame.draw.line(surface, self.color, (cx - d, cy + d), (cx + d, cy - d), 1)
        pygame.draw.circle(surface, (220, 240, 255), (cx, cy), 2)


class Nebula:
    """Real Hubble-style galaxy / nebula sprite"""
    
    _cache = {}
    
    def __init__(self):
        self.reset()
        self.alive = True
        self.parallax = 0.05

    @classmethod
    def _load_image(cls, filename):
        if filename not in cls._cache:
            path = os.path.join(NEBULA_DIR, filename)
            img = pygame.image.load(path).convert_alpha()
            scale = random.uniform(0.55, 0.85)
            w = int(img.get_width() * scale)
            h = int(img.get_height() * scale)
            img = pygame.transform.smoothscale(img, (w, h))
            cls._cache[filename] = img
        return cls._cache[filename].copy()

    def reset(self):
        filename = random.choice(NEBULA_FILES)
        self.image = self._load_image(filename)
        
        if random.random() < 0.4:
            self.image = pygame.transform.flip(self.image, True, False)
        
        self.w = self.image.get_width()
        self.h = self.image.get_height()
        
        self.x = random.uniform(self.w // 2 + 40, BASE_WIDTH - self.w // 2 - 40)
        self.y = random.uniform(-self.h - 40, -self.h // 2)
        self.speed = random.uniform(12, 22)
        self.alive = True

    def update(self, dt, player_dx=0.0):
        self.y += self.speed * dt
        self.x -= player_dx * self.parallax
        
        if self.x < -self.w:
            self.x += BASE_WIDTH + self.w * 2
        elif self.x > BASE_WIDTH + self.w:
            self.x -= BASE_WIDTH + self.w * 2
        
        if self.y > BASE_HEIGHT + self.h // 2 + 30:
            self.alive = False

    def draw(self, surface):
        rect = self.image.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(self.image, rect)


class Starfield:
    def __init__(self):
        self.stars = []
        self.planets = []
        self.galaxies = []
        self.nebula = None
        
        for _ in range(STAR_FAR_COUNT):
            self.stars.append(Star(layer=0))
        for _ in range(STAR_MID_COUNT):
            self.stars.append(Star(layer=1))
        for _ in range(STAR_NEAR_COUNT):
            self.stars.append(Star(layer=2))
        
        if random.random() < 0.30:
            self.planets.append(Planet())
        
        if random.random() < 0.4:
            self.galaxies.append(Galaxy())
        
        self.planet_timer = random.uniform(14.0, 24.0)
        self.galaxy_timer = random.uniform(10.0, 18.0)
        self.nebula_timer = random.uniform(18.0, 32.0)
        
        self.last_player_x = BASE_WIDTH / 2

    def update(self, dt, player_x=None):
        player_dx = 0.0
        if player_x is not None:
            player_dx = player_x - self.last_player_x
            self.last_player_x = player_x
        
        for star in self.stars:
            star.update(dt, player_dx)
        
        for planet in self.planets[:]:
            planet.update(dt, player_dx)
            if not planet.alive:
                self.planets.remove(planet)
        
        for galaxy in self.galaxies[:]:
            galaxy.update(dt, player_dx)
            if not galaxy.alive:
                self.galaxies.remove(galaxy)
        
        if self.nebula is not None:
            self.nebula.update(dt, player_dx)
            if not self.nebula.alive:
                self.nebula = None
        
        self.planet_timer -= dt
        if self.planet_timer <= 0:
            if len(self.planets) == 0 and self.nebula is None:
                self.planets.append(Planet())
            self.planet_timer = random.uniform(16.0, 30.0)
        
        self.galaxy_timer -= dt
        if self.galaxy_timer <= 0:
            self.galaxies.append(Galaxy())
            self.galaxy_timer = random.uniform(12.0, 22.0)
        
        self.nebula_timer -= dt
        if self.nebula_timer <= 0:
            if self.nebula is None and len(self.planets) == 0:
                self.nebula = Nebula()
            self.nebula_timer = random.uniform(20.0, 36.0)

    def draw(self, surface):
        if self.nebula is not None:
            self.nebula.draw(surface)
        
        for star in self.stars:
            if star.layer == 0:
                star.draw(surface)
        
        for planet in self.planets:
            planet.draw(surface)
        
        for galaxy in self.galaxies:
            galaxy.draw(surface)
        
        for star in self.stars:
            if star.layer >= 1:
                star.draw(surface)
