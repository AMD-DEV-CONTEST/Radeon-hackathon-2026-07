from __future__ import annotations

import re
from typing import Any

STYLE_DIRECTIONS = {
    "Luxury": "refined premium studio scene, restrained palette, elegant materials, controlled rim lighting",
    "Minimal Studio": "minimal studio scene, uncluttered backdrop, precise soft lighting, generous negative space",
    "Lifestyle": "credible aspirational lifestyle setting, natural context, warm directional light, product remains central",
    "Promotional Sale": "high-energy retail presentation, bold color blocking, clean sale-ready composition without typography",
}

NEGATIVE_BASE = (
    "distorted product, duplicated product, unreadable text, altered packaging, "
    "deformed geometry, watermark, unwanted typography, low quality, extra objects"
)


def sanitize_prompt_field(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def build_commercial_prompt(
    configuration: dict[str, Any], creative_style: str, output_format: str
) -> tuple[str, str]:
    if creative_style not in STYLE_DIRECTIONS:
        raise ValueError("Unsupported creative style")
    fields = {
        "product": sanitize_prompt_field(configuration.get("product_name"), 120),
        "category": sanitize_prompt_field(configuration.get("product_category"), 120),
        "objective": sanitize_prompt_field(configuration.get("campaign_goal"), 240),
        "audience": sanitize_prompt_field(configuration.get("target_audience"), 240),
        "benefits": sanitize_prompt_field(configuration.get("key_benefits"), 320),
        "tone": sanitize_prompt_field(configuration.get("brand_tone"), 100),
        "format": sanitize_prompt_field(output_format, 80),
    }
    prompt = (
        f"Commercial product photograph for {fields['product']}, category {fields['category']}. "
        f"{STYLE_DIRECTIONS[creative_style]}. Campaign objective: {fields['objective']}. "
        f"Audience: {fields['audience']}. Product benefits to express visually: {fields['benefits']}. "
        f"Brand tone: {fields['tone']}. Composition suitable for {fields['format']}. "
        "Preserve general product shape and preserve general proportions. "
        "No added typography, no added packaging copy, clean advertising composition, "
        "realistic product photography, human review required."
    )
    user_negative = sanitize_prompt_field(
        configuration.get("negative_instructions"), 400
    )
    negative = f"{NEGATIVE_BASE}, {user_negative}" if user_negative else NEGATIVE_BASE
    return prompt[:1800], negative[:900]
