from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CreativeStyle = Literal["Luxury", "Minimal Studio", "Lifestyle", "Promotional Sale"]
OutputFormat = Literal[
    "Instagram Square",
    "Instagram Portrait",
    "Story / Reel Cover",
    "Landscape Advertisement",
]


class RocmGenerationRequest(BaseModel):
    creative_style: CreativeStyle
    output_format: OutputFormat
    seed: int = Field(default=20260725, ge=0, le=2**32 - 1)
