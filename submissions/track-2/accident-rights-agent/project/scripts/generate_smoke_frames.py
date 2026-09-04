#!/usr/bin/env python3
"""Generate deterministic PNGs for local multimodal smoke tests.

The images are synthetic and intentionally simple. They validate that the local
vision endpoint accepts one image and an ordered set of eight images; they are
not accident evidence or a liability-evaluation dataset.
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

Color = tuple[int, int, int]

WIDTH = 640
HEIGHT = 360


class Canvas:
    def __init__(self, width: int, height: int, background: Color) -> None:
        self.width = width
        self.height = height
        self.pixels = [bytearray(background * width) for _ in range(height)]

    def point(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = x * 3
            self.pixels[y][offset : offset + 3] = bytes(color)

    def rectangle(self, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
        left, right = sorted((max(0, x0), min(self.width - 1, x1)))
        top, bottom = sorted((max(0, y0), min(self.height - 1, y1)))
        run = bytes(color) * (right - left + 1)
        for y in range(top, bottom + 1):
            start = left * 3
            self.pixels[y][start : start + len(run)] = run

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: Color,
        thickness: int = 1,
    ) -> None:
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            radius = max(0, thickness // 2)
            self.rectangle(x0 - radius, y0 - radius, x0 + radius, y0 + radius, color)
            if x0 == x1 and y0 == y1:
                break
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    def circle(
        self, center_x: int, center_y: int, radius: int, color: Color, fill: bool = False
    ) -> None:
        radius_squared = radius * radius
        inner_squared = max(0, (radius - 2) * (radius - 2))
        for y in range(center_y - radius, center_y + radius + 1):
            for x in range(center_x - radius, center_x + radius + 1):
                distance = (x - center_x) ** 2 + (y - center_y) ** 2
                if distance <= radius_squared and (fill or distance >= inner_squared):
                    self.point(x, y, color)

    def save_png(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b"".join(b"\x00" + bytes(row) for row in self.pixels)

        def chunk(kind: bytes, data: bytes) -> bytes:
            checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, level=9))
            + chunk(b"IEND", b"")
        )
        path.write_bytes(payload)


def draw_scene(index: int) -> Canvas:
    canvas = Canvas(WIDTH, HEIGHT, (205, 228, 247))

    # Crossroads and lane markings.
    canvas.rectangle(0, 205, WIDTH - 1, HEIGHT - 1, (72, 76, 82))
    canvas.rectangle(280, 0, 390, HEIGHT - 1, (72, 76, 82))
    canvas.rectangle(0, 200, WIDTH - 1, 204, (238, 238, 232))
    canvas.rectangle(275, 0, 279, HEIGHT - 1, (238, 238, 232))
    canvas.rectangle(391, 0, 395, HEIGHT - 1, (238, 238, 232))
    for x in range(20, WIDTH, 80):
        canvas.rectangle(x, 276, x + 38, 281, (245, 210, 63))
    for y in range(20, HEIGHT, 65):
        canvas.rectangle(331, y, 336, y + 30, (245, 210, 63))

    # Fixed red traffic signal.
    canvas.rectangle(405, 90, 431, 160, (36, 39, 43))
    canvas.circle(418, 106, 8, (224, 45, 45), fill=True)
    canvas.circle(418, 126, 8, (66, 70, 74), fill=True)
    canvas.circle(418, 146, 8, (66, 70, 74), fill=True)
    canvas.rectangle(416, 160, 420, 205, (36, 39, 43))

    # Blue sedan travels from left to right.
    car_x = 28 + (index - 1) * 34
    car_y = 238
    canvas.rectangle(car_x, car_y, car_x + 102, car_y + 40, (35, 107, 190))
    canvas.rectangle(car_x + 22, car_y - 25, car_x + 75, car_y, (35, 107, 190))
    canvas.rectangle(car_x + 28, car_y - 20, car_x + 47, car_y - 3, (183, 222, 244))
    canvas.rectangle(car_x + 51, car_y - 20, car_x + 70, car_y - 3, (183, 222, 244))
    canvas.circle(car_x + 24, car_y + 41, 10, (22, 24, 27), fill=True)
    canvas.circle(car_x + 79, car_y + 41, 10, (22, 24, 27), fill=True)
    canvas.circle(car_x + 24, car_y + 41, 4, (175, 180, 185), fill=True)
    canvas.circle(car_x + 79, car_y + 41, 4, (175, 180, 185), fill=True)

    # Red two-wheeler travels downward toward the crossing.
    bike_x = 350
    bike_y = 52 + (index - 1) * 20
    canvas.circle(bike_x - 17, bike_y + 35, 12, (30, 32, 35))
    canvas.circle(bike_x + 20, bike_y + 35, 12, (30, 32, 35))
    canvas.line(bike_x - 17, bike_y + 35, bike_x, bike_y + 12, (210, 52, 58), 4)
    canvas.line(bike_x, bike_y + 12, bike_x + 20, bike_y + 35, (210, 52, 58), 4)
    canvas.line(bike_x - 17, bike_y + 35, bike_x + 20, bike_y + 35, (210, 52, 58), 3)
    canvas.line(bike_x, bike_y + 12, bike_x + 8, bike_y - 7, (210, 52, 58), 3)
    canvas.circle(bike_x + 8, bike_y - 15, 7, (239, 190, 143), fill=True)
    canvas.line(bike_x + 8, bike_y - 7, bike_x + 2, bike_y + 13, (50, 55, 61), 6)

    # A frame index marker gives an unambiguous ordering without relying on text.
    for marker in range(index):
        canvas.circle(18 + marker * 14, 18, 5, (20, 92, 156), fill=True)

    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/smoke"),
        help="Directory that will contain single/ and frames/.",
    )
    args = parser.parse_args()

    frames_dir = args.output_root / "frames"
    single_dir = args.output_root / "single"
    for index in range(1, 9):
        canvas = draw_scene(index)
        canvas.save_png(frames_dir / f"frame_{index:02d}.png")
        if index == 4:
            canvas.save_png(single_dir / "synthetic_intersection.png")

    print(f"Generated 8 ordered frames in {frames_dir.resolve()}")
    print(f"Generated one single-image test in {single_dir.resolve()}")


if __name__ == "__main__":
    main()
