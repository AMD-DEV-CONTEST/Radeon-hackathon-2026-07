"""
LaunchKart AI 2.0 — Domain Value Objects: Marketing Content

Structured output models for the Marketing and Branding Agents.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailCampaign(BaseModel):
    """Email marketing campaign content."""
    subject_line: str = Field(description="Email subject line")
    preview_text: str = Field(description="Email preview text")
    headline: str = Field(description="Email headline")
    body: str = Field(description="Email body content (HTML-friendly)")
    cta_text: str = Field(description="Call-to-action button text")
    cta_url: str = Field(default="#", description="Call-to-action URL")


class LaunchCampaign(BaseModel):
    """Product launch campaign strategy."""
    campaign_name: str = Field(description="Campaign name")
    campaign_theme: str = Field(description="Overall campaign theme")
    target_audience: list[str] = Field(description="Target audience segments")
    channels: list[str] = Field(description="Marketing channels to use")
    timeline: str = Field(description="Campaign timeline and phases")
    key_messages: list[str] = Field(description="Key marketing messages")
    budget_recommendation: str = Field(description="Suggested budget range")


class MarketingContent(BaseModel):
    """Complete marketing output from the Marketing Agent."""

    instagram_caption: str = Field(description="Instagram post caption with hashtags")
    facebook_ad: str = Field(description="Facebook ad copy")
    google_ad_copy: str = Field(description="Google Ads headline + description")
    linkedin_post: str = Field(description="LinkedIn professional post")
    email_campaign: EmailCampaign = Field(description="Email marketing campaign")
    product_story: str = Field(description="Brand storytelling content")
    launch_campaign: LaunchCampaign = Field(description="Full launch campaign strategy")
    tone: str = Field(default="professional", description="Content tone")
    target_demographics: list[str] = Field(default_factory=list, description="Target demographics")


class BrandingData(BaseModel):
    """Branding analysis from the Branding Agent."""

    brand_voice: str = Field(description="Recommended brand voice / tone")
    brand_personality: list[str] = Field(description="Brand personality traits")
    color_palette: list[str] = Field(description="Recommended brand color hex codes")
    tagline_options: list[str] = Field(description="Suggested tagline options")
    brand_story: str = Field(description="Brand narrative / origin story")
    visual_identity: str = Field(description="Visual identity recommendations")
    competitive_positioning: str = Field(description="Brand positioning statement")
