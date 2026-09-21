"""Load and validate the finalized English demo narration."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NARRATION = ROOT / "video" / "narration.txt"


def _normalize(text: str) -> str:
    return " ".join(text.split())


def load_finalized_narration(
    narration_path: Path = DEFAULT_NARRATION,
) -> tuple[str, list[str]]:
    narration = narration_path.read_text(encoding="utf-8")
    paragraphs = [paragraph.strip() for paragraph in narration.split("\n\n") if paragraph.strip()]
    if len(paragraphs) != 15:
        raise ValueError(
            "Expected one finalized English narration paragraph per scene "
            f"(15 total), found {len(paragraphs)}"
        )
    return narration, [_normalize(paragraph) for paragraph in paragraphs]
