from __future__ import annotations

import subprocess
from pathlib import Path

from colorgraph.config import settings


class FrameExtractionError(RuntimeError):
    pass


def extract_frame(
    media_path: str | Path,
    time_seconds: float,
    output_path: str | Path,
    *,
    maximum_width: int = 1280,
    high_quality: bool = False,
) -> Path:
    source = Path(media_path).resolve()
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    scale_filter = f"scale='min(iw,{maximum_width})':-2"
    if high_quality:
        scale_filter += ":flags=lanczos"
    # Exact browser previews use PNG so FFmpeg must cross the YUV/RGB boundary
    # while the source's video color metadata is still available.  Writing an
    # HD BT.709 YUV frame straight to JPEG can preserve BT.709 chroma samples
    # that image decoders later interpret with JPEG's YCbCr convention, which
    # creates a visible color jump when switching between <img> and <video>.
    if destination.suffix.lower() == ".png":
        scale_filter += ",format=rgb24"
    command = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(time_seconds, 0):.6f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        scale_filter,
        "-q:v",
        "1" if high_quality else "2",
        *(
            ["-pix_fmt", "yuvj444p"]
            if high_quality and destination.suffix.lower() in {".jpg", ".jpeg"}
            else (["-pix_fmt", "rgb24"] if destination.suffix.lower() == ".png" else [])
        ),
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        raise FrameExtractionError(stderr.decode("utf-8", errors="replace")) from exc
    if not destination.is_file():
        raise FrameExtractionError(f"ffmpeg did not create {destination}")
    return destination
