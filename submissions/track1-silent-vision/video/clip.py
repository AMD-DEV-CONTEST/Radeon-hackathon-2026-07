from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np


@dataclass(frozen=True)
class DecodedClip:
    frames: tuple[np.ndarray, ...]
    fps: int
    duration_ms: int


def save_original_video(data: bytes, output_dir: Path, session_id: str, suffix: str = ".webm") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{session_id}-original_video{suffix}"
    path.write_bytes(data)
    return path


def decode_video_clip(data: bytes, target_fps: int) -> DecodedClip:
    av = _import_av()
    with NamedTemporaryFile(suffix=".webm") as handle:
        handle.write(data)
        handle.flush()
        with av.open(handle.name) as container:
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                raise ValueError("uploaded clip does not contain a video stream")
            frames_with_time: list[tuple[float, np.ndarray]] = []
            for frame in container.decode(stream):
                timestamp = float(frame.time or 0.0)
                frames_with_time.append((timestamp, frame.to_ndarray(format="rgb24")))
    if not frames_with_time:
        raise ValueError("uploaded clip contains no decodable video frames")
    frames = _resample_frames(frames_with_time, target_fps)
    duration_ms = int(max(1, len(frames)) * 1000 / target_fps)
    return DecodedClip(frames=tuple(frames), fps=target_fps, duration_ms=duration_ms)


def _resample_frames(frames_with_time: list[tuple[float, np.ndarray]], target_fps: int) -> list[np.ndarray]:
    source_times = [time for time, _ in frames_with_time]
    if len(source_times) == 1 or max(source_times) <= min(source_times):
        return [frame for _, frame in frames_with_time]
    start = source_times[0]
    end = source_times[-1]
    step = 1.0 / target_fps
    output: list[np.ndarray] = []
    source_index = 0
    target_time = start
    while target_time <= end + 1e-6:
        while source_index + 1 < len(source_times) and source_times[source_index + 1] <= target_time:
            source_index += 1
        output.append(frames_with_time[source_index][1])
        target_time += step
    return output


def _import_av():
    try:
        import av
    except Exception as exc:
        raise RuntimeError("PyAV is required for utterance-level video decoding. Install package 'av'.") from exc
    return av
