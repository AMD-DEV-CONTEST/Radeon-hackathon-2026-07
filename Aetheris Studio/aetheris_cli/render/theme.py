"""
Semantic theme registry and palette definitions ported from ROCm CLI.
Provides bespoke and 16-color ANSI theme definitions including default-dark, tokyo-night, dracula, catppuccin-mocha, nord, and one-dark.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


def hex_to_rgb(hex_str: str) -> str:
    cleaned = hex_str.lstrip("#")
    return f"#{cleaned}"


@dataclass
class Theme:
    name: str
    bg: str
    surface: str
    surface_2: str
    fg: str
    muted: str
    accent: str
    accent_2: str
    ok: str
    warn: str
    err: str
    border: str

    @classmethod
    def default_dark(cls) -> "Theme":
        return cls(
            name="default-dark",
            bg="#131416",
            surface="#1d1f21",
            surface_2="#27272a",
            fg="#eaebec",
            muted="#b4b9bc",
            accent="#00c2de",
            accent_2="#007db8",
            ok="#1aa01a",
            warn="#f59e0b",
            err="#ed1c24",
            border="#656b72",
        )

    @classmethod
    def default_light(cls) -> "Theme":
        return cls(
            name="default-light",
            bg="#fafafb",
            surface="#f2f3f5",
            surface_2="#e4e7ea",
            fg="#171a1d",
            muted="#555a60",
            accent="#00769b",
            accent_2="#004f71",
            ok="#148014",
            warn="#b26b00",
            err="#c4181f",
            border="#a8aeb4",
        )

    @classmethod
    def solarized_dark(cls) -> "Theme":
        return cls(
            name="solarized-dark",
            bg="#002b36",
            surface="#002b36",
            surface_2="#586e75",
            fg="#eee8d5",
            muted="#586e75",
            accent="#93a1a1",
            accent_2="#268bd2",
            ok="#859900",
            warn="#b58900",
            err="#dc322f",
            border="#586e75",
        )

    @classmethod
    def tokyo_night(cls) -> "Theme":
        return cls(
            name="tokyo-night",
            bg="#1a1b26",
            surface="#1a1b26",
            surface_2="#414868",
            fg="#c0caf5",
            muted="#414868",
            accent="#7dcfff",
            accent_2="#7aa2f7",
            ok="#9ece6a",
            warn="#e0af68",
            err="#f7768e",
            border="#414868",
        )

    @classmethod
    def tokyo_night_light(cls) -> "Theme":
        return cls(
            name="tokyo-night-light",
            bg="#d5d6db",
            surface="#d5d6db",
            surface_2="#4c505e",
            fg="#343b58",
            muted="#4c505e",
            accent="#0f4b6e",
            accent_2="#34548a",
            ok="#33635c",
            warn="#8f5e15",
            err="#8c4351",
            border="#4c505e",
        )

    @classmethod
    def dracula(cls) -> "Theme":
        return cls(
            name="dracula",
            bg="#282a36",
            surface="#282a36",
            surface_2="#6272a4",
            fg="#f8f8f2",
            muted="#6272a4",
            accent="#a4ffff",
            accent_2="#bd93f9",
            ok="#50fa7b",
            warn="#f1fa8c",
            err="#ff5555",
            border="#6272a4",
        )

    @classmethod
    def gruvbox_dark(cls) -> "Theme":
        return cls(
            name="gruvbox-dark",
            bg="#282828",
            surface="#282828",
            surface_2="#928374",
            fg="#ebdbb2",
            muted="#928374",
            accent="#8ec07c",
            accent_2="#458588",
            ok="#98971a",
            warn="#d79921",
            err="#cc241d",
            border="#928374",
        )

    @classmethod
    def nord(cls) -> "Theme":
        return cls(
            name="nord",
            bg="#2e3440",
            surface="#2e3440",
            surface_2="#4c566a",
            fg="#d8dee9",
            muted="#4c566a",
            accent="#8fbcbb",
            accent_2="#81a1c1",
            ok="#a3be8c",
            warn="#ebcb8b",
            err="#bf616a",
            border="#4c566a",
        )

    @classmethod
    def one_dark(cls) -> "Theme":
        return cls(
            name="one-dark",
            bg="#282c34",
            surface="#282c34",
            surface_2="#5c6370",
            fg="#abb2bf",
            muted="#5c6370",
            accent="#56b6c2",
            accent_2="#61afef",
            ok="#98c379",
            warn="#e5c07b",
            err="#e06c75",
            border="#5c6370",
        )

    @classmethod
    def monokai(cls) -> "Theme":
        return cls(
            name="monokai",
            bg="#272822",
            surface="#272822",
            surface_2="#75715e",
            fg="#f8f8f2",
            muted="#75715e",
            accent="#a1efe4",
            accent_2="#66d9ef",
            ok="#a6e22e",
            warn="#f4bf75",
            err="#f92672",
            border="#75715e",
        )

    @classmethod
    def catppuccin_mocha(cls) -> "Theme":
        return cls(
            name="catppuccin-mocha",
            bg="#1e1e2e",
            surface="#1e1e2e",
            surface_2="#585b70",
            fg="#cdd6f4",
            muted="#585b70",
            accent="#94e2d5",
            accent_2="#89b4fa",
            ok="#a6e3a1",
            warn="#f9e2af",
            err="#f38ba8",
            border="#585b70",
        )

    @classmethod
    def catppuccin_latte(cls) -> "Theme":
        return cls(
            name="catppuccin-latte",
            bg="#eff1f5",
            surface="#eff1f5",
            surface_2="#6c6f85",
            fg="#4c4f69",
            muted="#6c6f85",
            accent="#179299",
            accent_2="#1e66f5",
            ok="#40a02b",
            warn="#df8e1d",
            err="#d20f39",
            border="#6c6f85",
        )

    @classmethod
    def ayu_dark(cls) -> "Theme":
        return cls(
            name="ayu-dark",
            bg="#0a0e14",
            surface="#0a0e14",
            surface_2="#686868",
            fg="#b3b1ad",
            muted="#686868",
            accent="#95e6cb",
            accent_2="#53bdfa",
            ok="#91b362",
            warn="#f9af4f",
            err="#ea6c73",
            border="#686868",
        )

    @classmethod
    def ayu_light(cls) -> "Theme":
        return cls(
            name="ayu-light",
            bg="#fafafa",
            surface="#fafafa",
            surface_2="#828c99",
            fg="#5c6166",
            muted="#828c99",
            accent="#4cbf99",
            accent_2="#41a6d9",
            ok="#86b300",
            warn="#f29718",
            err="#f51818",
            border="#828c99",
        )

    @classmethod
    def github_dark(cls) -> "Theme":
        return cls(
            name="github-dark",
            bg="#0d1117",
            surface="#0d1117",
            surface_2="#6e7681",
            fg="#c9d1d9",
            muted="#6e7681",
            accent="#56d4dd",
            accent_2="#58a6ff",
            ok="#3fb950",
            warn="#d29922",
            err="#ff7b72",
            border="#6e7681",
        )


THEME_REGISTRY: Dict[str, Theme] = {
    "default-dark": Theme.default_dark(),
    "default-light": Theme.default_light(),
    "solarized-dark": Theme.solarized_dark(),
    "tokyo-night": Theme.tokyo_night(),
    "tokyo-night-light": Theme.tokyo_night_light(),
    "dracula": Theme.dracula(),
    "gruvbox-dark": Theme.gruvbox_dark(),
    "nord": Theme.nord(),
    "one-dark": Theme.one_dark(),
    "monokai": Theme.monokai(),
    "catppuccin-mocha": Theme.catppuccin_mocha(),
    "catppuccin-latte": Theme.catppuccin_latte(),
    "ayu-dark": Theme.ayu_dark(),
    "ayu-light": Theme.ayu_light(),
    "github-dark": Theme.github_dark(),
}


def get_theme(name: str = "default-dark") -> Theme:
    return THEME_REGISTRY.get(name.lower().strip(), Theme.default_dark())


def list_theme_names() -> List[str]:
    return list(THEME_REGISTRY.keys())
