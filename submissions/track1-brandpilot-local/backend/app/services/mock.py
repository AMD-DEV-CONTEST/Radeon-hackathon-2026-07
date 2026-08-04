from datetime import datetime, timezone
from uuid import uuid4

STYLES = ["Luxury", "Minimal Studio", "Lifestyle", "Promotional Sale"]
COPY = {
    "Luxury": ("Made to be noticed.", "A refined campaign direction focused on material detail, restraint, and confident presentation.", "Discover the collection"),
    "Minimal Studio": ("Clear product. Clear purpose.", "A precise studio direction that gives the product room to speak.", "See the details"),
    "Lifestyle": ("Designed for real moments.", "A human-centered concept placing the product inside an everyday aspiration.", "Make it yours"),
    "Promotional Sale": ("Your next favorite, within reach.", "A high-energy promotional direction with a direct, uncluttered offer.", "Shop the promotion"),
}

def make_result(style: str, output_format: str, revision: int = 1) -> dict:
    headline, caption, cta = COPY[style]
    if revision > 1:
        headline = f"{headline} · Concept {revision}"
    return {"result_id": str(uuid4()), "style": style, "output_format": output_format, "image_url": None, "headline": headline, "caption": caption, "call_to_action": cta, "human_review_status": "pending", "review_note": None, "disclosure": "Mock output generated without AMD Radeon inference.", "created_at": datetime.now(timezone.utc).isoformat(), "revision": revision}

def generate_results(project: dict) -> list[dict]:
    formats = project["configuration"]["output_formats"]
    return [make_result(style, formats[index % len(formats)]) for index, style in enumerate(STYLES)]
