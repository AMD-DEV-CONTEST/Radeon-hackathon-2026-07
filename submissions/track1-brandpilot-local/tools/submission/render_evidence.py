"""Render sanitized, judge-facing evidence cards and their checksum manifest."""

import hashlib
import json
from datetime import datetime, timezone

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1200, 675
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "evidence" / "final-submission" / "screenshots" / "final-dns-blocker.png"
HASH_MANIFEST = ROOT / "evidence" / "final-submission" / "screenshot-hashes.json"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#050506")
    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            distance = ((x - 960) ** 2 + (y - 30) ** 2) ** 0.5
            glow = max(0.0, 1.0 - distance / 720)
            pixels[x, y] = (int(5 + 41 * glow), int(5 + 7 * glow), int(6 + 13 * glow))

    draw = ImageDraw.Draw(image)
    draw.text((62, 48), "BrandPilot", font=font(20, True), fill="#f7f4f2")
    draw.text((166, 48), "LOCAL", font=font(20, True), fill="#ef3340")
    draw.rounded_rectangle((914, 44, 1138, 89), radius=22, outline="#63313a", width=1)
    draw.text((1026, 67), "SANITIZED EVIDENCE", anchor="mm", font=font(13), fill="#ff9aa1")
    draw.text((62, 150), "FINAL OFFICIAL TUNNEL RETRY", font=font(14, True), fill="#ef3340")
    draw.text((62, 195), "Public browser edge stopped at DNS.", font=font(50, True), fill="#f7f4f2")
    draw.text((62, 270), "The platform-assigned rc-tunnel hostname did not resolve in public DNS.", font=font(21), fill="#bdb7b5")
    draw.text((62, 303), "The bounded retry ended before TLS, model load, or generation.", font=font(21), fill="#bdb7b5")

    cards = [
        ("OFFICIAL RC-TUNNEL", "0.3.0 active", "#70d6a7"),
        ("LOOPBACK AUTH", "401 / 200 verified", "#70d6a7"),
        ("PUBLIC DNS", "Resolution failed", "#ff6874"),
        ("SAFETY OUTCOME", "Instance destroyed", "#70d6a7"),
    ]
    for index, (label, value, color) in enumerate(cards):
        left = 62 + index * 273
        draw.rounded_rectangle((left, 385, left + 255, 519), radius=16, fill="#121215", outline="#28282d")
        draw.text((left + 22, 411), label, font=font(13), fill="#8e8988")
        draw.text((left + 22, 456), value, font=font(23, True), fill=color)

    draw.text(
        (62, 612),
        "Source: sanitized Session 3 diagnostics - no hostname, URL, token, account, or instance identifier shown",
        font=font(13),
        fill="#777273",
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, "PNG", optimize=True)

    files = []
    for screenshot in sorted(OUTPUT.parent.glob("*.png")):
        payload = screenshot.read_bytes()
        files.append(
            {
                "file": screenshot.relative_to(HASH_MANIFEST.parent).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    manifest = {
        "algorithm": "SHA-256",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }
    HASH_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
