"""Snapshot d'entrée d'une frame (clavier / pad / tactile)."""


class InputState:
    __slots__ = (
        "dx", "fire", "phenix", "pause",
        "menu_confirm", "menu_back", "menu_dir",
        "active",
    )

    def __init__(self):
        self.clear()

    def clear(self):
        self.dx = 0.0          # -1 / 0 / +1
        self.fire = False      # tenu
        self.phenix = False    # edge
        self.pause = False     # edge
        self.menu_confirm = False
        self.menu_back = False
        self.menu_dir = 0
        self.active = False    # True si un doigt / souris est sur le HUD

    def copy_from(self, other):
        self.dx = other.dx
        self.fire = other.fire
        self.phenix = other.phenix
        self.pause = other.pause
        self.menu_confirm = other.menu_confirm
        self.menu_back = other.menu_back
        self.menu_dir = other.menu_dir
        self.active = other.active
