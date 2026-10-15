"""B2选定形象的品牌色与浅/深主题语义色。"""

BRAND = {"teal": "#315D59", "gold": "#C98A3A", "cream": "#F5E3B9"}

THEMES = {
    "light": {
        "bg": "#F8F4EC",
        "panel": "#FFFCF6",
        "text": "#263F3C",
        "muted": "#62736B",
        "border": "#DCDCD0",
        "accent": BRAND["teal"],
        "active": "#E1ECE5",
        "primary": BRAND["teal"],
        "on_primary": "#FFF8E9",
        "gold_surface": BRAND["cream"],
        "on_gold": "#68472E",
    },
    "dark": {
        "bg": "#152D2B",
        "panel": "#1D3B38",
        "text": "#F5E9D4",
        "muted": "#B0BFB4",
        "border": "#3A5B55",
        "accent": "#A5D3C1",
        "active": "#2B4D47",
        "primary": "#376E67",
        "on_primary": "#FFF8E9",
        "gold_surface": "#72552D",
        "on_gold": "#F5E3B9",
    },
}
