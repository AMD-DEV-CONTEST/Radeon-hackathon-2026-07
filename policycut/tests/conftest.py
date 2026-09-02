"""Shared pytest fixtures for PolicyCut tests.

These tests must run WITHOUT torch/ffmpeg installed: they only exercise the
pure-python surfaces defined in docs/CONTRACTS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project root (the folder containing the `policycut` package)
# importable regardless of where pytest is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch):
    """Never let tests attempt LLM/model downloads."""
    monkeypatch.setenv("POLICYCUT_NO_LLM", "1")
    monkeypatch.setenv("POLICYCUT_REQUIRE_ROCM", "0")
    yield


@pytest.fixture()
def store(tmp_path):
    """A ProjectStore rooted in a temporary data dir."""
    from policycut.core.storage import ProjectStore

    return ProjectStore(tmp_path / "data")


@pytest.fixture()
def sample_policy():
    """A representative PolicySpec covering visual + audio targets."""
    from policycut.policy.schema import (
        AudioAction,
        AudioTarget,
        PolicySpec,
        VisualAction,
        VisualTarget,
    )

    return PolicySpec(
        visual_targets=[
            VisualTarget(
                category="face",
                prompts=["human face"],
                action=VisualAction(type="pixelate", strength=65),
            ),
            VisualTarget(
                category="license_plate",
                prompts=["license plate", "vehicle registration plate"],
                action=VisualAction(type="blur", strength=60),
            ),
        ],
        audio_targets=[
            AudioTarget(category="phone", action=AudioAction(type="mute")),
            AudioTarget(category="email", action=AudioAction(type="beep")),
            AudioTarget(category="address", action=AudioAction(type="mute")),
        ],
    )


def _word_entry(text: str, start: float, end: float) -> dict:
    """Word dict tolerant to either whisper-style or contract-style key names."""
    return {"text": text, "word": text, "start": start, "end": end,
            "start_s": start, "end_s": end}


def _segment_entry(text: str, start: float, end: float, words: list[tuple[str, float, float]]) -> dict:
    return {
        "text": text,
        "start": start,
        "end": end,
        "start_s": start,
        "end_s": end,
        "words": [_word_entry(w, s, e) for (w, s, e) in words],
    }


@pytest.fixture()
def make_transcript():
    """Factory building a Transcript (model if importable, else plain dict).

    Usage:
        transcript = make_transcript([
            ("call me at 555-0123", 1.0, 3.0, [("call", 1.0, 1.3), ...]),
        ])
    Each segment tuple: (text, start_s, end_s, words) with words as
    (word_text, start_s, end_s) tuples. Pass words=[] for segment-level-only
    timestamps.
    """

    def _build(segments: list[tuple[str, float, float, list[tuple[str, float, float]]]]):
        # Prefer the real Word/Segment/Transcript classes when exposed.
        try:
            from policycut.audio.transcribe import Segment, Transcript, Word

            seg_objs = [
                Segment(
                    text=text,
                    start=start,
                    end=end,
                    words=[Word(text=w, start=s, end=e) for (w, s, e) in words],
                )
                for (text, start, end, words) in segments
            ]
            has_words = any(seg.words for seg in seg_objs)
            return Transcript(
                segments=seg_objs,
                language="en",
                has_word_timestamps=has_words,
            )
        except Exception:
            # duck-typed fallback: plain dicts with tolerant key names
            return {
                "language": "en",
                "text": " ".join(seg[0] for seg in segments).strip(),
                "has_word_timestamps": any(seg[3] for seg in segments),
                "segments": [_segment_entry(t, s, e, w) for (t, s, e, w) in segments],
            }

    return _build
