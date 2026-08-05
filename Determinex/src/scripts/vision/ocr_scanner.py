"""OCR extraction from screenshots. Uses tesseract via pytesseract if available."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False
    log.warning("[vision] pytesseract not installed — OCR will return empty strings")

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def extract_text(img_or_path: str | Path | Image.Image) -> str:  # type: ignore[name-defined]
    """Extract all text from an image using OCR."""
    if not _TESSERACT_AVAILABLE or not _PIL_AVAILABLE:
        return ""
    try:
        if isinstance(img_or_path, (str, Path)):
            img = Image.open(img_or_path).convert("RGB")
        else:
            img = img_or_path
        return pytesseract.image_to_string(img)
    except Exception as exc:
        log.error("[ocr] extract_text failed: %s", exc)
        return ""


def extract_words(img_or_path: str | Path | Image.Image) -> list[str]:  # type: ignore[name-defined]
    text = extract_text(img_or_path)
    return [w for w in re.split(r"\s+", text) if w]


def extract_bounding_boxes(img_or_path: str | Path | Image.Image) -> list[dict[str, Any]]:  # type: ignore[name-defined]
    """Return list of {text, x, y, w, h, conf} dicts."""
    if not _TESSERACT_AVAILABLE or not _PIL_AVAILABLE:
        return []
    try:
        if isinstance(img_or_path, (str, Path)):
            img = Image.open(img_or_path).convert("RGB")
        else:
            img = img_or_path
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        results = []
        for i, text in enumerate(data["text"]):
            if text.strip():
                results.append(
                    {
                        "text": text,
                        "x": data["left"][i],
                        "y": data["top"][i],
                        "w": data["width"][i],
                        "h": data["height"][i],
                        "conf": data["conf"][i],
                    }
                )
        return results
    except Exception as exc:
        log.error("[ocr] extract_bounding_boxes failed: %s", exc)
        return []


def find_text_in_image(
    img_or_path: str | Path | Image.Image, search: str, case_sensitive: bool = False
) -> list[dict]:  # type: ignore[name-defined]
    """Find all occurrences of search string in OCR output, with bounding boxes."""
    boxes = extract_bounding_boxes(img_or_path)
    flag = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(search), flag)
    return [b for b in boxes if pattern.search(b["text"])]
