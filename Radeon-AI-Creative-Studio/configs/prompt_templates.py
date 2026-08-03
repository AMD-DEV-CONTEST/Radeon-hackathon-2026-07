CREATIVE_TYPES = {
    "Commercial Poster": (
        "commercial advertising poster, professional product photography, "
        "clean composition, strong visual hierarchy, premium branding, "
        "studio lighting, advertising design"
    ),
    "Social Media Artwork": (
        "social media campaign artwork, eye-catching composition, "
        "trendy visual design, vibrant details, professional digital content"
    ),
    "Product Photography": (
        "professional product photography, commercial studio lighting, "
        "sharp focus, realistic material texture, premium presentation, "
        "clean background"
    ),
    "Interior Design": (
        "professional interior design visualization, architectural photography, "
        "realistic materials, detailed furniture, natural lighting, "
        "spacious composition"
    ),
    "Anime Illustration": (
        "high quality anime illustration, detailed character design, "
        "beautiful composition, expressive lighting, clean line art"
    ),
    "Concept Art": (
        "professional concept art, cinematic composition, atmospheric lighting, "
        "highly detailed environment, imaginative visual storytelling"
    ),
}


STYLE_TEMPLATES = {
    "Photorealistic": (
        "photorealistic, realistic lighting, natural colors, "
        "high detail, professional photography"
    ),
    "Modern Minimalist": (
        "modern minimalist style, clean lines, elegant layout, "
        "neutral palette, refined details"
    ),
    "Luxury French": (
        "luxury French style, elegant decorative details, "
        "ornate design, premium materials, warm sophisticated atmosphere"
    ),
    "Cyberpunk": (
        "cyberpunk style, neon lights, futuristic city atmosphere, "
        "dramatic contrast, cinematic lighting"
    ),
    "Anime Style": (
        "anime style, polished illustration, vivid colors, "
        "clean line art, detailed background"
    ),
    "Watercolor Illustration": (
        "watercolor illustration, soft brush strokes, artistic texture, "
        "gentle color transitions, handmade paper feeling"
    ),
    "Cinematic": (
        "cinematic style, dramatic lighting, film color grading, "
        "depth of field, atmospheric composition"
    ),
    "Traditional Chinese": (
        "traditional Chinese aesthetic, elegant oriental composition, "
        "subtle ink painting influence, poetic atmosphere"
    ),
}


QUALITY_TEMPLATES = {
    "Fast": {
        "steps": 15,
        "quality_prompt": "high quality",
    },
    "Balanced": {
        "steps": 25,
        "quality_prompt": (
            "high quality, highly detailed, professional composition"
        ),
    },
    "Best": {
        "steps": 35,
        "quality_prompt": (
            "masterpiece, best quality, highly detailed, professional composition, "
            "sharp details, refined lighting"
        ),
    },
}


ASPECT_RATIOS = {
    "1:1 Square": (512, 512),
    "4:3 Landscape": (640, 480),
    "3:4 Portrait": (480, 640),
    "16:9 Widescreen": (768, 432),
    "9:16 Vertical": (432, 768),
}


DEFAULT_NEGATIVE_PROMPT = (
    "low quality, worst quality, blurry, distorted, deformed, "
    "bad anatomy, bad proportions, duplicate, watermark, logo, "
    "signature, text, letters, cropped, out of frame"
)


def build_prompt(
    user_prompt: str,
    creative_type: str,
    style: str,
    quality: str,
) -> str:
    """Convert a short user description into a complete generation prompt."""

    user_prompt = (user_prompt or "").strip()

    if not user_prompt:
        raise ValueError("Please enter a scene description.")

    scene_prompt = CREATIVE_TYPES.get(creative_type, "")
    style_prompt = STYLE_TEMPLATES.get(style, "")
    quality_prompt = QUALITY_TEMPLATES.get(
        quality,
        QUALITY_TEMPLATES["Balanced"],
    )["quality_prompt"]

    return ", ".join(
        part
        for part in [
            user_prompt,
            scene_prompt,
            style_prompt,
            quality_prompt,
        ]
        if part
    )
