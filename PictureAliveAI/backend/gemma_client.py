"""
Gemma 4 Vision → Text Generator via Google AI Studio.

Usage:
    from gemma_client import generate
    text = generate(image_bytes, "audio_guide")
"""
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL
from prompts import MODE_PROMPTS


def generate(image_bytes: bytes, mode: str) -> str:
    """
    Analyze an image with Gemma 4, then generate mode-specific text.
    
    Args:
        image_bytes: Raw JPEG/PNG bytes
        mode: 'education' | 'accessibility' | 'heritage_tourism' | 'digital_world' | 'content_creation'
    
    Returns:
        str: Generated text (education, accessibility, audio historical guide, narration,  wildlige & product, story, context, or prompts)
    """
    if mode not in MODE_PROMPTS:
        raise ValueError(f"Unknown mode: {mode}. Valid: {list(MODE_PROMPTS)}")
    
    prompts = MODE_PROMPTS[mode]
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Step 1: Vision analysis
    vision_resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
            prompts["vision"],
        ],
    )
    analysis = vision_resp.text
    
    # Step 2: Mode-specific text generation
    text_prompt = prompts["text"].format(analysis=analysis)
    text_resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[text_prompt],
    )
    
    return text_resp.text
