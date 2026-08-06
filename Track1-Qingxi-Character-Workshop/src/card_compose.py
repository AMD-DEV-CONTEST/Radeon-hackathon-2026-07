from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.models_schema import CharacterCard
from src.paths import ROOT
from src.world import load_world

# Module-level cache for the resolved font PATH (not the font object), so
# repeated `_font(size)` calls skip the discovery search.
# Sentinel semantics:
#   None  -> not searched yet
#   ""    -> searched, nothing found (fallback to PIL default)
#   <str> -> resolved path to a CJK-capable font file
_CACHED_FONT_PATH: str | None = None

# Known candidate font paths (Windows, macOS, Linux).
_KNOWN_FONT_PATHS: list[str] = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# Substrings (case-insensitive) used to match CJK-capable font filenames when
# globbing the filesystem.
_CJK_FONT_HINTS: tuple[str, ...] = (
    "cjk",
    "wqy",
    "zenhei",
    "microhei",
    "uming",
    "ukai",
    "droidsansfallback",
    "notosanssc",
    "notosanstc",
    "sourcehan",
    "simhei",
    "msyh",
    "pingfang",
)

# Roots to recursively search for CJK fonts when no known path exists.
_GLOB_ROOTS: list[str] = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    str(Path.home() / ".fonts"),
    str(Path.home() / ".local" / "share" / "fonts"),
]


def _font_supports_cjk(font) -> bool:
    """Return True iff `font` actually has a glyph for a CJK codepoint.

    A font without the glyph maps it to .notdef, which renders identically to
    an unmapped codepoint (U+10FFFF, guaranteed not in any BMP font). Comparing
    the rendered masks byte-for-byte detects this tofu case reliably.
    """
    try:
        probe = font.getmask("形")
        missing = font.getmask("\U0010FFFF")
        return bytes(probe) != bytes(missing)
    except Exception:
        return False


def _try_load(path: str, size: int) -> ImageFont.ImageFont | None:
    """Try to load a truetype font; return None on OSError."""
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return None


def _candidate_ok(path: str, size: int = 20) -> bool:
    """True iff `path` loads AND renders CJK glyphs."""
    f = _try_load(path, size)
    if f is None:
        return False
    return _font_supports_cjk(f)


def _bundled_font_path() -> str | None:
    """Look in the bundled assets/fonts directory for any CJK-capable font."""
    font_dir = ROOT / "assets" / "fonts"
    if not font_dir.is_dir():
        return None
    try:
        files = sorted(
            p for p in font_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".otf", ".ttf", ".ttc")
        )
    except OSError:
        return None
    for p in files:
        if _candidate_ok(str(p)):
            return str(p)
    return None


def _glob_find_cjk_font() -> str | None:
    """Recursively search common font dirs for a CJK-capable font file."""
    for root in _GLOB_ROOTS:
        try:
            base = Path(root)
        except Exception:
            continue
        if not base.exists():
            continue
        try:
            for p in base.rglob("*"):
                if not p.is_file():
                    continue
                name = p.name.lower()
                if not any(hint in name for hint in _CJK_FONT_HINTS):
                    continue
                if _candidate_ok(str(p)):
                    return str(p)
        except PermissionError:
            continue
        except OSError:
            continue
    return None


def _fc_match_font() -> str | None:
    """Use fontconfig's fc-match to resolve a default sans font path."""
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", "sans"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    candidate = out.stdout.strip()
    if candidate and Path(candidate).exists() and _candidate_ok(candidate):
        return candidate
    return None


def _resolve_font_path() -> str | None:
    """Resolve a CJK-capable font path via bundled, known, glob, then fc-match.

    Returns the path string, or None if no CJK-capable font was found. The
    result (including the fact-of-None) is cached in `_CACHED_FONT_PATH` using
    the sentinel "" so the search is not repeated.
    """
    global _CACHED_FONT_PATH
    if _CACHED_FONT_PATH is not None:
        return _CACHED_FONT_PATH or None

    # 1. Bundled fonts under assets/fonts.
    bundled = _bundled_font_path()
    if bundled:
        _CACHED_FONT_PATH = bundled
        return bundled

    # 2. Known explicit paths.
    for p in _KNOWN_FONT_PATHS:
        if Path(p).exists() and _candidate_ok(p):
            _CACHED_FONT_PATH = p
            return p

    # 3. Recursive glob search.
    found = _glob_find_cjk_font()
    if found:
        _CACHED_FONT_PATH = found
        return found

    # 4. fc-match fallback.
    matched = _fc_match_font()
    if matched:
        _CACHED_FONT_PATH = matched
        return matched

    # 5. Nothing found; cache the sentinel so we don't re-search.
    _CACHED_FONT_PATH = ""
    return None


def _font(size: int) -> ImageFont.ImageFont:
    """Return a CJK-capable ImageFont, falling back to PIL default if absent."""
    path = _resolve_font_path()
    if path is not None:
        f = _try_load(path, size)
        if f is not None:
            return f
    return ImageFont.load_default()


def has_cjk_font() -> bool:
    """True if a font capable of rendering CJK was found (glyph-level check)."""
    return _resolve_font_path() is not None


def _wrap_text(draw, text, font, max_width):
    """Wrap `text` to fit within `max_width` pixels, breaking per character."""
    lines: list[str] = []
    buf = ""
    for ch in text:
        if ch == "\n":
            if buf:
                lines.append(buf)
            buf = ""
            continue
        trial = buf + ch
        if draw.textlength(trial, font=font) <= max_width:
            buf = trial
        else:
            if buf:
                lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    return lines


def draw_radar(
    affinities: dict[str, int],
    size: int = 400,
    primary: str | None = None,
) -> Image.Image:
    world = load_world()
    names = world.affinity_names()
    img = Image.new("RGBA", (size, size), (20, 24, 32, 255))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    radius = size * 0.35
    n = len(names)
    # grid
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            r = radius * ring
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        draw.polygon(pts, outline=(80, 90, 110, 255))
    # axis lines
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        draw.line(
            (cx, cy, cx + radius * math.cos(ang), cy + radius * math.sin(ang)),
            fill=(55, 62, 80, 255),
        )
    # values
    val_pts = []
    label_font = _font(14)
    num_font = _font(12)
    primary = primary if primary in names else None
    for i, lab in enumerate(names):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        score = max(0, min(100, int(affinities.get(lab, 0))))
        r = radius * (score / 100.0)
        px = cx + r * math.cos(ang)
        py = cy + r * math.sin(ang)
        val_pts.append((px, py))
        # vertex dot
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=(150, 210, 255, 255))
        lx = cx + (radius + 30) * math.cos(ang)
        ly = cy + (radius + 30) * math.sin(ang)
        is_primary = lab == primary
        fill = (255, 210, 120, 255) if is_primary else (220, 230, 240, 255)
        draw.text((lx - 20, ly - 20), lab, fill=fill, font=label_font)
        draw.text(
            (lx - 8, ly + 2),
            str(score),
            fill=(150, 200, 255, 255) if is_primary else (140, 150, 170, 255),
            font=num_font,
        )
    poly_fill = (80, 160, 220, 90)
    poly_outline = (120, 200, 255, 255)
    if primary is not None:
        poly_fill = (200, 150, 60, 90)
        poly_outline = (255, 200, 110, 255)
    draw.polygon(val_pts, fill=poly_fill, outline=poly_outline)
    return img.convert("RGB")


def compose_card(
    card: CharacterCard,
    portrait: Image.Image,
    out_path: str | Path,
    canvas_size: tuple[int, int] = (1400, 900),
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = canvas_size
    canvas = Image.new("RGB", (w, h), (18, 20, 28))
    draw = ImageDraw.Draw(canvas)

    world = load_world()

    # --- Left column: portrait thumbnail ---
    pw, ph = 500, 760
    port = portrait.convert("RGB").copy()
    port.thumbnail((pw, ph), Image.Resampling.LANCZOS)
    px = 50
    py = 60 + (ph - port.height) // 2
    canvas.paste(port, (px, py))
    # subtle 2px border around portrait
    draw.rectangle(
        (px - 1, py - 1, px + port.width, py + port.height),
        outline=(80, 90, 110),
        width=2,
    )

    # --- Right zone: x = 600..1350 (width 750) ---
    rx = 600
    right_edge = 1350
    right_w = right_edge - rx  # 750

    title_f = _font(40)
    oneliner_f = _font(20)
    body_f = _font(18)
    small_f = _font(15)

    # Title (name) at (600, 40)
    draw.text((rx, 40), card.name, fill=(240, 244, 255), font=title_f)

    # one_liner at (600, 100), wrapped to width 750
    for i, ln in enumerate(_wrap_text(draw, card.one_liner, oneliner_f, right_w)):
        draw.text((rx, 100 + i * 26), ln, fill=(160, 180, 210), font=oneliner_f)

    # Radar at (620, 160), size 320
    radar = draw_radar(card.affinities, size=320, primary=card.primary_affinity)
    canvas.paste(radar, (620, 160))

    # Lore block starts at (980, 170), wrap width 370 (up to x=1350)
    lore_x = 980
    lore_y = 170
    lore_max_w = right_edge - lore_x  # 370
    font_size = 18
    line_h = int(font_size * 1.5)  # 27px per line
    bottom_limit = 855
    entry_gap = 8

    entries = [
        ("Affinity", card.primary_affinity),
        (world.spirit_domain.name, card.spirit_domain),
        ("Appearance", card.appearance),
        ("Personality", card.personality),
        ("Backstory", card.backstory),
        ("Showcase", card.ability_showcase),
    ]

    for label, value in entries:
        if lore_y > bottom_limit:
            break
        combined = f"{label}: {value}"
        wrapped = _wrap_text(draw, combined, body_f, lore_max_w)
        for ln in wrapped:
            if lore_y + line_h > bottom_limit:
                draw.text((lore_x, lore_y), "...", fill=(210, 218, 230), font=body_f)
                lore_y = bottom_limit + 1
                break
            draw.text((lore_x, lore_y), ln, fill=(210, 218, 230), font=body_f)
            lore_y += line_h
        lore_y += entry_gap

    # Footer at (50, 855)
    draw.text(
        (50, 855),
        f"{world.world_name} | {card.primary_affinity} | Local ROCm",
        fill=(100, 110, 130),
        font=small_f,
    )

    canvas.save(out_path, format="PNG")
    return out_path
