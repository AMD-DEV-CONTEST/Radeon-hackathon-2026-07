from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from tools.manim.validator import validate_manim_file

QUALITY_FLAGS = {
    "low": "-ql",
    "medium": "-qm",
    "high": "-qh",
}
DEFAULT_TIMEOUT_SEC = 90
OUTPUT_TAIL_CHARS = 2000


@dataclass
class RenderResult:
    success: bool
    video_path: Optional[str] = None
    duration_sec: Optional[float] = None
    render_time_sec: Optional[float] = None
    error: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def _tail(text: Optional[str], n_chars: int = OUTPUT_TAIL_CHARS) -> str:
    return (text or "")[-n_chars:]


def _find_manim_binary() -> Optional[str]:
    return "python -m manim"
    return shutil.which("manim")


def _locate_rendered_video(media_dir: Path, scene_file_stem: str, scene_name: str) -> Optional[Path]:
    """
    manim's output layout is: media_dir/videos/<scene_file_stem>/<quality>/<scene_name>.mp4
    The quality-folder name (e.g. "1080p60") varies by manim version and
    config, so search for the file by name instead of assuming a fixed path.
    """
    videos_root = media_dir / "videos" / scene_file_stem
    if not videos_root.exists():
        return None
    candidates = sorted(
        videos_root.rglob(f"{scene_name}.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _probe_duration_sec(video_path: Path) -> Optional[float]:
    """Best-effort duration lookup via ffprobe. Returns None (never
    raises) if ffprobe is unavailable or the file can't be probed -
    duration is nice-to-have metadata, not something worth failing over."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return round(float(result.stdout.strip()), 2)
    except Exception:
        return None


def render_scene(
    scene_path: str,
    scene_name: str,
    output_path: str,
    quality: str = "high",
    media_dir: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    validate_first: bool = True,
) -> RenderResult:
    """Render a single Manim scene to an MP4. Never raises - see module
    docstring."""
    scene_file = Path(scene_path)
    if not scene_file.is_file():
        return RenderResult(success=False, error=f"Scene file not found: {scene_path}")

    if validate_first:
        validation = validate_manim_file(str(scene_file))
        if not validation.ok:
            return RenderResult(success=False, error=f"Validation failed: {validation.as_message()}")

    manim_bin = _find_manim_binary()
    if not manim_bin:
        return RenderResult(success=False, error="'manim' executable not found on PATH")

    quality_flag = QUALITY_FLAGS.get(quality, QUALITY_FLAGS["high"])
    work_media_dir = Path(media_dir) if media_dir else scene_file.parent / "_manim_media"
    try:
        work_media_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return RenderResult(success=False, error=f"Could not create media dir '{work_media_dir}': {e}")

    cmd = [
        "python", "-m", "manim", quality_flag, "--disable_caching",
        "--media_dir", str(work_media_dir),
        str(scene_file), scene_name,
    ]

    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return RenderResult(
            success=False,
            error=f"Render timed out after {timeout}s",
            render_time_sec=round(time.time() - start, 2),
            stdout_tail=_tail(e.stdout if isinstance(e.stdout, str) else None),
            stderr_tail=_tail(e.stderr if isinstance(e.stderr, str) else None),
        )
    except FileNotFoundError as e:
        return RenderResult(success=False, error=f"Failed to launch manim: {e}")
    except Exception as e:
        return RenderResult(success=False, error=f"Unexpected error launching manim: {e}")

    render_time = round(time.time() - start, 2)

    if proc.returncode != 0:
        return RenderResult(
            success=False,
            error=f"manim exited with code {proc.returncode}",
            render_time_sec=render_time,
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
        )

    rendered = _locate_rendered_video(work_media_dir, scene_file.stem, scene_name)
    if rendered is None:
        return RenderResult(
            success=False,
            error="manim exited successfully but no output video file was found",
            render_time_sec=render_time,
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
        )

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered, output_path)
    except Exception as e:
        return RenderResult(
            success=False,
            error=f"Rendered but failed to copy output to '{output_path}': {e}",
            render_time_sec=render_time,
        )

    duration = _probe_duration_sec(Path(output_path))

    return RenderResult(
        success=True,
        video_path=str(output_path),
        duration_sec=duration,
        render_time_sec=render_time,
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr),
    )


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Render a Manim scene to MP4")
    parser.add_argument("scene_path")
    parser.add_argument("scene_name")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quality", choices=list(QUALITY_FLAGS), default="high")
    parser.add_argument("--media-dir", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    result = render_scene(
        args.scene_path, args.scene_name, args.output,
        quality=args.quality, media_dir=args.media_dir,
        timeout=args.timeout, validate_first=not args.no_validate,
    )
    print(result.to_json())
    sys.exit(0 if result.success else 1)