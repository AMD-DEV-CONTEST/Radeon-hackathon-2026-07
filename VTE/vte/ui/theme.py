"""
theme.py — paleta de cores da UI do VTE (dark, inspirado em "Trae Solo",
e light, contraparte clara com a mesma identidade de acento).

Os nomes de campo espelham a paleta original fornecida (BG_COLOR,
ACCENT_GREEN, etc.) para que qualquer referência futura a essas constantes
continue reconhecível; a diferença é que agora elas vivem em um dataclass
por modo (`DARK`/`LIGHT`) em vez de constantes soltas no módulo, para que a
UI possa trocar de paleta em runtime (toggle claro/escuro) sem reimportar
nada.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    mode: str

    # Core
    bg: str
    panel: str
    border: str
    input_bg: str

    # Accent
    accent_green: str
    accent_blue: str
    accent_purple: str
    accent_red: str

    # Text
    text_primary: str
    text_muted: str
    text_strong: str  # "TEXT_WHITE" no dark -- texto de máximo contraste

    # Typography
    font_mono: str = "Consolas"
    font_sans: str = "Segoe UI"


# Paleta original ("Trae Solo inspired dark developer theme").
DARK = Palette(
    mode="dark",
    bg="#030303",
    panel="#0a0b0c",
    border="#141618",
    input_bg="#0c0d0f",
    accent_green="#32f08c",
    accent_blue="#00d2ff",
    accent_purple="#8a2be2",
    accent_red="#e06c75",
    text_primary="#d1d4e0",
    text_muted="#5c6370",
    text_strong="#ffffff",
)

# Contraparte clara: mesma identidade de acento (verde/azul/roxo/vermelho),
# mas com acentos escurecidos/saturados para manter contraste AA sobre fundo
# branco (as cores neon do dark mode falham contraste em fundo claro).
LIGHT = Palette(
    mode="light",
    bg="#f4f5f7",
    panel="#ffffff",
    border="#dde1e6",
    input_bg="#eef0f3",
    accent_green="#0e8a4e",
    accent_blue="#0077c2",
    accent_purple="#6a2ec2",
    accent_red="#c22f3d",
    text_primary="#1b1f27",
    text_muted="#6b7280",
    text_strong="#000000",
)


def get_palette(mode: str) -> Palette:
    return LIGHT if mode == "light" else DARK
