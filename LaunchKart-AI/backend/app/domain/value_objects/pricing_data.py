"""
LaunchKart AI 2.0 — Domain Value Objects: Pricing Data

Structured output models for the Pricing Agent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PriceRange(BaseModel):
    """Price range bounds."""
    min_price: float = Field(ge=0, description="Minimum recommended price")
    max_price: float = Field(ge=0, description="Maximum recommended price")
    currency: str = Field(default="USD", description="Currency code")


class CompetitorPrice(BaseModel):
    """Individual competitor pricing data."""
    competitor_name: str = Field(description="Competitor brand or seller name")
    price: float = Field(ge=0, description="Competitor's price")
    marketplace: str = Field(description="Marketplace where competitor sells")
    url: str | None = Field(default=None, description="Competitor listing URL")
    rating: float | None = Field(default=None, ge=0, le=5, description="Competitor rating")
    review_count: int | None = Field(default=None, ge=0, description="Number of reviews")


class PricingData(BaseModel):
    """Complete pricing analysis from the Pricing Agent."""

    recommended_price: float = Field(ge=0, description="AI-recommended optimal price")
    price_range: PriceRange = Field(description="Suggested price range")
    competitor_prices: list[CompetitorPrice] = Field(
        default_factory=list, description="Competitor pricing data"
    )
    margin_analysis: str = Field(description="Margin analysis and justification")
    pricing_strategy: str = Field(description="Recommended pricing strategy name")
    price_positioning: str = Field(
        description="Market positioning (budget/mid-range/premium/luxury)"
    )
    currency: str = Field(default="USD", description="Currency for all prices")
    confidence: float = Field(ge=0.0, le=1.0, description="Pricing confidence score")
