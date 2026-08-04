from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class ProjectCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    product_category: str = Field(min_length=1, max_length=120)
    campaign_goal: str = Field(min_length=1, max_length=500)
    target_audience: str = Field(min_length=1, max_length=500)
    key_benefits: str = Field(min_length=1, max_length=1000)
    brand_tone: str = Field(min_length=1, max_length=100)
    brand_colors: list[str] = Field(min_length=1, max_length=8)
    negative_instructions: str = Field(default="", max_length=1000)
    creative_styles: list[str] = Field(min_length=1, max_length=4)
    output_formats: list[str] = Field(min_length=1, max_length=4)

    @field_validator("brand_colors")
    @classmethod
    def colors_are_hex(cls, values: list[str]) -> list[str]:
        if any(len(value) != 7 or not value.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in value[1:]) for value in values):
            raise ValueError("Brand colors must be six-digit hex values")
        return values

class ReviewRequest(BaseModel):
    status: Literal["approved", "rejected", "needs_changes"]
    note: str | None = Field(default=None, max_length=1000)

class ResultEdit(BaseModel):
    headline: str | None = Field(default=None, min_length=1, max_length=200)
    caption: str | None = Field(default=None, min_length=1, max_length=1000)
    call_to_action: str | None = Field(default=None, min_length=1, max_length=120)
