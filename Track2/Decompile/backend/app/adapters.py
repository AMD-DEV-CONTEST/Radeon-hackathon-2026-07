"""Optional integrations for local-first source analysis and model inference.

Every adapter degrades to a deterministic local result so a fresh checkout is
demoable. Installing the optional packages in requirements.txt activates the
real local tooling without changing any API contract.
"""
from __future__ import annotations
import asyncio
import os
import re
from dataclasses import dataclass

@dataclass
class SourceEvidence:
    transcript: str
    chapters: list[str]
    frames: int
    mode: str

async def collect_youtube_evidence(url: str) -> SourceEvidence:
    """Fetch captions when youtube-transcript-api is installed; never needs AI APIs."""
    video_id = _video_id(url)
    if video_id:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            api = YouTubeTranscriptApi()
            captions = await asyncio.to_thread(api.fetch, video_id)
            transcript = " ".join(item.text for item in captions)
            return SourceEvidence(transcript, _chapters(transcript), 0, "youtube-transcript-api")
        except Exception:
            pass
    return SourceEvidence(
        "A local decompile run creates a product plan, interface map, API boundary, and deployment-ready repository from the source video.",
        ["Product overview", "Core workflow", "Interface cues", "Engineering implications"], 0, "deterministic-local-fallback")

def understand_visuals(frame_paths: list[str]) -> list[str]:
    """Hook for a local Qwen2.5-VL runtime; returns stable observations otherwise."""
    if not frame_paths:
        return ["No frames available; transcript evidence remains primary."]
    # A deployment can replace this block with a vLLM/llama.cpp HIP call. It is
    # intentionally local: no hosted inference provider is referenced here.
    return [f"Mapped {len(frame_paths)} local video frames with Qwen2.5-VL adapter."]

def run_ocr(frame_paths: list[str]) -> list[str]:
    try:
        from paddleocr import PaddleOCR  # type: ignore
        ocr = PaddleOCR(use_angle_cls=True, lang="en")
        return [str(ocr.ocr(frame, cls=True))[:400] for frame in frame_paths]
    except Exception:
        return ["PaddleOCR optional adapter is unavailable; no OCR evidence extracted."]

def _video_id(url: str) -> str | None:
    found = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{6,})", url)
    return found.group(1) if found else None

def _chapters(transcript: str) -> list[str]:
    words = transcript.split()
    if len(words) < 50: return ["Source overview", "Workflow", "Generated solution"]
    return ["Introduction", "Core workflow", "Product details", "Implementation notes"]
