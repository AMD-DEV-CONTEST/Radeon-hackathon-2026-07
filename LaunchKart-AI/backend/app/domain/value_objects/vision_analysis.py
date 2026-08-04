"""
LaunchKart AI 2.0 — Domain Value Objects: Vision Analysis

Pydantic models representing the structured output from the Vision Agent.
These are pure domain objects — no database or framework dependencies.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionAnalysis(BaseModel):
    """Complete analysis output from the Vision Agent."""

    category: str = Field(description="Product category (e.g., Electronics, Clothing)")
    subcategory: str = Field(description="Product subcategory (e.g., Headphones, T-Shirt)")
    brand: str | None = Field(default=None, description="Detected brand name, if any")
    colors: list[str] = Field(default_factory=list, description="Detected colors")
    material: str | None = Field(default=None, description="Detected material (e.g., Cotton, Plastic)")
    texture: str | None = Field(default=None, description="Detected texture (e.g., Matte, Glossy)")
    usage: list[str] = Field(default_factory=list, description="Intended usage scenarios")
    features: list[str] = Field(default_factory=list, description="Detected product features")
    packaging: str | None = Field(default=None, description="Packaging description")
    damage_detected: bool = Field(default=False, description="Whether damage was detected")
    quality_score: float = Field(ge=0.0, le=1.0, description="Image quality score (0-1)")
    estimated_dimensions: str | None = Field(default=None, description="Estimated dimensions")
    confidence: float = Field(ge=0.0, le=1.0, description="Overall analysis confidence (0-1)")


class ProductFeatures(BaseModel):
    """Detailed product feature extraction from the Product Analysis Agent."""

    product_name: str = Field(description="Identified product name")
    category_hierarchy: list[str] = Field(description="Category path (e.g., ['Electronics', 'Audio', 'Headphones'])")
    key_features: list[str] = Field(description="Main selling points")
    specifications: dict[str, str] = Field(default_factory=dict, description="Technical specifications")
    target_audience: list[str] = Field(default_factory=list, description="Target demographic")
    use_cases: list[str] = Field(default_factory=list, description="Primary use cases")
    unique_selling_points: list[str] = Field(default_factory=list, description="What differentiates this product")
    quality_indicators: list[str] = Field(default_factory=list, description="Quality indicators from the image")
    confidence: float = Field(ge=0.0, le=1.0, description="Analysis confidence score")
