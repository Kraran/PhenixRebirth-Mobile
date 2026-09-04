"""Snapshot d'entrée d'une frame (clavier / pad / tactile)."""


class InputState:
    __slots__ = (
        "dx", "fire", "phenix", "pause",
        "menu_confirm", "menu_back", "menu_dir",
        "menu_pick", "menu_kind",
        "active",
    )

    def __init__(self):
        self.clear()

    def clear(self):
        self.dx = 0.0
        self.fire = False
        self.phenix = False
        self.pause = False
        self.menu_confirm = False
        self.menu_back = False
        self.menu_dir = 0
        self.menu_pick = None
        self.menu_kind = None
        self.active = False
