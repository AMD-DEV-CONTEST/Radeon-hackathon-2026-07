"""Generate a synthetic sample chest X-ray for quick demos."""
from PIL import Image, ImageDraw


def create_sample(path: str, size: tuple[int, int] = (512, 512)):
    img = Image.new("L", size, color=80)
    draw = ImageDraw.Draw(img)
    # Lungs
    draw.ellipse([60, 80, 240, 420], fill=160, outline=120)
    draw.ellipse([272, 80, 452, 420], fill=160, outline=120)
    # Heart
    draw.ellipse([200, 180, 312, 300], fill=100, outline=80)
    # Ribs
    for y in range(100, 400, 40):
        draw.line([(40, y), (472, y)], fill=120, width=3)
    img.convert("RGB").save(path)


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data", "sample_xray.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    create_sample(out)
    print(f"Wrote {out}")
