"""Render the ASCII architecture diagram from docs/ARCHITECTURE.md to a PNG.

Produces a colorized, dark-themed image suitable for README embeds, slides,
and the demo video. Pure Pillow, no extra dependencies.

Layers are auto-detected: each full-width "+--...--+" rule pair delimits a
layer box; the biggest gap between layers (the RAG/Agent path region) is
colored as the "paths" tier.
"""

import re
import sys

from PIL import Image, ImageDraw, ImageFont

SRC = "docs/ARCHITECTURE.md"
NAMES = ["architecture", "agent_loop"]
OUTS = lambda n: ["docs/%s.png" % n, "demo/video_assets/%s.png" % n]

BG = "#0D1117"
TEXT = "#C9D1D9"
GAP = "#8B949E"

# (border color, band fill color), ordered by layer position in the diagram
PALETTE = [
    ("#58A6FF", "#12243E"),  # presentation
    ("#56D4DD", "#10353B"),  # orchestration / routing
    ("#D29922", "#2B2413"),  # services
    ("#F78166", "#2E1D17"),  # inference
    ("#BC8CFF", "#241A30"),  # hardware
]
PATHS = ("#3FB950", "#132B1B")  # RAG / Agent path tier

BORDER_CHARS = set("+-|")


def extract_diagrams(path: str) -> list[list[str]]:
    blocks = []
    cur: list[str] | None = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("```"):
            if cur is not None:
                blocks.append(cur)
                cur = None
            else:
                cur = []
            continue
        if cur is not None:
            cur.append(line)
    return [[l.rstrip() for l in block] for block in blocks if any(l.strip().startswith("+--") for l in block)]


def detect_layers(lines: list[str]) -> list[tuple[int, int]]:
    rules = [i for i, l in enumerate(lines) if re.match(r"^\+-{2,}\+$", l)]
    layers = [(rules[i], rules[i + 1]) for i in range(0, len(rules) - 1, 2)]
    return layers


def layer_color(row: int, layers: list[tuple[int, int]], big_gaps: set[int]) -> tuple[str, str | None]:
    for i, (r0, r1) in enumerate(layers):
        if r0 <= row <= r1:
            return PALETTE[i % len(PALETTE)]
    if row in big_gaps:
        return PATHS
    return (GAP, None)


def render(lines: list[str], name: str) -> None:
    """Render to every path in OUTS(name)."""
    size = 26
    fonts = [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cascadiamono.ttf", r"C:\Windows\Fonts\cour.ttf"]
    font = None
    for path in fonts:
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        raise SystemExit("No monospace font found")

    cell_w = int(font.getlength("M"))
    ascent, descent = font.getmetrics()
    cell_h = ascent + descent
    pad = 48
    w = pad * 2 + cell_w * max(len(l) for l in lines)
    h = pad * 2 + cell_h * len(lines)

    layers = detect_layers(lines)
    big_gaps = set()
    if layers:
        # the widest gap between layers holds the RAG / Agent path tier
        spans = []
        for i, (r0, r1) in enumerate(layers):
            next_top = layers[i + 1][0] if i + 1 < len(layers) else len(lines)
            if next_top - 1 > r1:
                spans.append((r1 + 1, next_top - 1))
        if spans:
            r0, r1 = max(spans, key=lambda s: s[1] - s[0])
            big_gaps = set(range(r0, r1 + 1))

    # layer labels: first non-empty text line below each top rule
    title_rows = set()
    for r0, r1 in layers:
        for j in range(r0 + 1, r1 + 1):
            if lines[j].strip("| ").strip():
                title_rows.add(j)
                break

    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    for i, (r0, r1) in enumerate(layers):
        _, fill = PALETTE[i % len(PALETTE)]
        if fill:
            y0 = pad + r0 * cell_h
            y1 = pad + (r1 + 1) * cell_h
            draw.rectangle([pad - 16, y0 - 8, w - pad + 16, y1 + 8], fill=fill + "33")
    if big_gaps:
        r0, r1 = min(big_gaps), max(big_gaps)
        y0 = pad + r0 * cell_h
        y1 = pad + (r1 + 1) * cell_h
        draw.rectangle([pad - 16, y0 - 8, w - pad + 16, y1 + 8], fill=PATHS[1] + "33")

    for row, line in enumerate(lines):
        if layers:
            border, _ = layer_color(row, layers, big_gaps)
        else:
            border = PATHS[0]
        y = pad + row * cell_h
        for col, ch in enumerate(line):
            if ch == " ":
                continue
            if ch in BORDER_CHARS or row in title_rows:
                color = border
            else:
                color = TEXT
            draw.text((pad + col * cell_w, y), ch, font=font, fill=color)

    for out in OUTS(name):
        img.save(out)
        print("Wrote %s (%dx%d)" % (out, w, h))


if __name__ == "__main__":
    diagrams = extract_diagrams(sys.argv[1] if len(sys.argv) > 1 else SRC)
    for name, lines in zip(NAMES, diagrams):
        render(lines, name)
