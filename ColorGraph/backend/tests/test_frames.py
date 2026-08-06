from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from colorgraph.config import settings
from colorgraph.media.frames import extract_frame


def _rgb_frame(path: Path, width: int, height: int) -> np.ndarray:
    result = subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 3)


def test_png_frame_extraction_preserves_bt709_rgb_colors(tmp_path: Path) -> None:
    width, height = 64, 36
    source = tmp_path / "bt709-source.mkv"
    destination = tmp_path / "exact-frame.png"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate=1:duration=1",
            "-frames:v",
            "1",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv444p",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    expected = _rgb_frame(source, width, height)

    extract_frame(
        source,
        0,
        destination,
        maximum_width=width,
        high_quality=True,
    )

    with Image.open(destination) as image:
        actual = np.asarray(image.convert("RGB"), dtype=np.uint8)
    difference = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
    assert destination.suffix == ".png"
    assert image.format == "PNG"
    assert difference.max() <= 1
