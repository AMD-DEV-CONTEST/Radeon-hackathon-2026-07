"""One-off script: renders assets/earth_pixelated.svg into windows/runner/
resources/app_icon.ico for the Flutter Windows build. The 8x8 pixel grid
below was read directly out of a real browser's canvas rendering of the
source SVG (getImageData), not hand-traced from the SVG path commands --
the background path is a non-trivial self-touching shape that a naive
polygon fill gets wrong.
"""
from PIL import Image

BG = (3, 3, 3, 255)          # #030303
GREEN = (50, 240, 140, 255)  # #32f08c
TRANSPARENT = (0, 0, 0, 0)

GRID = [
    "BBBBGG..",
    "BBGGGGB.",
    "BBGGGGBB",
    "BGGGGBBB",
    ".BBBGGGB",
    "..BBGGGB",
    "..GG..B.",
    "..GGGG..",
]

COLORS = {"B": BG, "G": GREEN, ".": TRANSPARENT}

SUPERSAMPLE = 32  # 8*32=256px source, downsampled per icon size with NEAREST


def render(size: int) -> Image.Image:
    scale = SUPERSAMPLE
    big = Image.new("RGBA", (8 * scale, 8 * scale), TRANSPARENT)
    pixels = big.load()
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            color = COLORS[ch]
            for dy in range(scale):
                for dx in range(scale):
                    pixels[x * scale + dx, y * scale + dy] = color
    return big.resize((size, size), Image.NEAREST)


sizes = [16, 24, 32, 48, 64, 128, 256]
images = [render(s) for s in sizes]

out_path = "aetheris_ui/windows/runner/resources/app_icon.ico"
images[0].save(out_path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
print(f"wrote {out_path}")

render(512).save("assets/earth_pixelated_512.png")
print("wrote assets/earth_pixelated_512.png")
