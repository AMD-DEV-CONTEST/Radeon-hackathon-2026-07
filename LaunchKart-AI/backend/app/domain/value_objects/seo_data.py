"""
LaunchKart AI 2.0 — Domain Value Objects: SEO Data

Structured output models for SEO-related agent outputs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SEOData(BaseModel):
    """Complete SEO optimization output from the SEO Agent."""

    title: str = Field(max_length=200, description="SEO-optimized product title")
    subtitle: str = Field(max_length=300, description="Product subtitle / tagline")
    meta_description: str = Field(max_length=500, description="Meta description for search engines")
    primary_keywords: list[str] = Field(description="Primary high-volume keywords")
    secondary_keywords: list[str] = Field(description="Secondary supporting keywords")
    long_tail_keywords: list[str] = Field(description="Long-tail keyword phrases")
    bullet_points: list[str] = Field(description="SEO-optimized bullet points (5-7)")
    search_score: float = Field(ge=0.0, le=100.0, description="Estimated SEO search score (0-100)")
    keyword_density: dict[str, float] = Field(default_factory=dict, description="Keyword density map")
    search_volume_estimates: dict[str, str] = Field(
        default_factory=dict, description="Estimated search volume per keyword"
    )
    competitor_keyword_overlap: list[str] = Field(
        default_factory=list, description="Keywords shared with competitors"
    )
