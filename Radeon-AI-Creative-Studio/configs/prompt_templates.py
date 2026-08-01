CREATIVE_TYPES = {
    "电商海报": (
        "commercial advertising poster, professional product photography, "
        "clean composition, strong visual hierarchy, premium branding, "
        "studio lighting, advertising design"
    ),
    "社交媒体配图": (
        "social media campaign artwork, eye-catching composition, "
        "trendy visual design, vibrant details, professional digital content"
    ),
    "产品摄影": (
        "professional product photography, commercial studio lighting, "
        "sharp focus, realistic material texture, premium presentation, "
        "clean background"
    ),
    "室内设计": (
        "professional interior design visualization, architectural photography, "
        "realistic materials, detailed furniture, natural lighting, "
        "spacious composition"
    ),
    "动漫插画": (
        "high quality anime illustration, detailed character design, "
        "beautiful composition, expressive lighting, clean line art"
    ),
    "概念艺术": (
        "professional concept art, cinematic composition, atmospheric lighting, "
        "highly detailed environment, imaginative visual storytelling"
    ),
}


STYLE_TEMPLATES = {
    "写实摄影": (
        "photorealistic, realistic lighting, natural colors, "
        "high detail, professional photography"
    ),
    "现代简约": (
        "modern minimalist style, clean lines, elegant layout, "
        "neutral palette, refined details"
    ),
    "法式奢华": (
        "luxury French style, elegant decorative details, "
        "ornate design, premium materials, warm sophisticated atmosphere"
    ),
    "赛博朋克": (
        "cyberpunk style, neon lights, futuristic city atmosphere, "
        "dramatic contrast, cinematic lighting"
    ),
    "动漫风格": (
        "anime style, polished illustration, vivid colors, "
        "clean line art, detailed background"
    ),
    "水彩插画": (
        "watercolor illustration, soft brush strokes, artistic texture, "
        "gentle color transitions, handmade paper feeling"
    ),
    "电影质感": (
        "cinematic style, dramatic lighting, film color grading, "
        "depth of field, atmospheric composition"
    ),
    "中国风": (
        "traditional Chinese aesthetic, elegant oriental composition, "
        "subtle ink painting influence, poetic atmosphere"
    ),
}


QUALITY_TEMPLATES = {
    "快速": {
        "steps": 15,
        "quality_prompt": "high quality",
    },
    "均衡": {
        "steps": 25,
        "quality_prompt": (
            "high quality, highly detailed, professional composition"
        ),
    },
    "最佳": {
        "steps": 35,
        "quality_prompt": (
            "masterpiece, best quality, highly detailed, professional composition, "
            "sharp details, refined lighting"
        ),
    },
}


ASPECT_RATIOS = {
    "1:1 正方形": (512, 512),
    "4:3 横图": (640, 480),
    "3:4 竖图": (480, 640),
    "16:9 横屏": (768, 432),
    "9:16 竖屏": (432, 768),
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
    """将用户的简单描述转换为完整生成提示词。"""

    user_prompt = (user_prompt or "").strip()

    if not user_prompt:
        raise ValueError("请输入画面描述。")

    scene_prompt = CREATIVE_TYPES.get(creative_type, "")
    style_prompt = STYLE_TEMPLATES.get(style, "")
    quality_prompt = QUALITY_TEMPLATES.get(
        quality,
        QUALITY_TEMPLATES["均衡"],
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

