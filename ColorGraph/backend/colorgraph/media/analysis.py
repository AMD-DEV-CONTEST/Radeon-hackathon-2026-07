from __future__ import annotations

from pathlib import Path

from colorgraph.domain.grade_graph import MediaInfo, TimeRange
from colorgraph.media.probe import probe_media
from colorgraph.media.representative_frames import (
    extract_representative_candidates,
    materialize_representatives,
    quality_representative_sources,
)
from colorgraph.media.shots import detect_shot_ranges


def analyze_media(
    media_path: str | Path,
    frames_directory: str | Path,
) -> tuple[MediaInfo, list[TimeRange], list[Path]]:
    media = probe_media(media_path)
    ranges = detect_shot_ranges(media.path)
    frames_dir = Path(frames_directory).resolve()
    frames_dir.mkdir(parents=True, exist_ok=True)
    candidates = extract_representative_candidates(
        media.path,
        ranges,
        frames_dir,
        fps=media.fps,
    )
    representative_frames = materialize_representatives(
        candidates,
        quality_representative_sources(candidates),
    )
    return media, ranges, representative_frames
