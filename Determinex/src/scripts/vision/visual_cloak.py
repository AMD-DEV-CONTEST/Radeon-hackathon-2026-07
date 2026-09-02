"""
Visual Cloak — PII and secret redaction from screenshots before cloud vision API calls.
Must run on every screenshot before it leaves local scope.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    log.warning("[visual_cloak] Pillow not installed — redaction will be skipped")


# ---------------------------------------------------------------------------
# PII / secret patterns for text-based redaction (OCR → regex → redact region)
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b")),
    ("phone_us", re.compile(r"\b(\+1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b")),
    ("phone_intl", re.compile(r"\+\d{1,3}[\s\-.]?\(?\d+\)?[\s\-.\d]{7,}")),
    (
        "street_address",
        re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(St|Ave|Blvd|Rd|Dr|Ln|Ct|Way|Pl|Sq)\b", re.I),
    ),
    (
        "api_key_generic",
        re.compile(r"\b(sk|pk|api|key|token|secret)[_\-]?[A-Za-z0-9]{20,}\b", re.I),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret", re.compile(r"\b[A-Za-z0-9/+]{40}\b")),
    ("github_token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{40,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{48}\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    ("session_cookie", re.compile(r"\b(session|sess|auth|token)[=:][A-Za-z0-9_\-\.]{20,}\b", re.I)),
    (
        "url_with_secret",
        re.compile(r"https?://[^\s]*?(key|token|secret|password|pwd|api)[=:][^\s&]{8,}", re.I),
    ),
    (
        "private_path",
        re.compile(
            r"(/home/\w+/|/Users/\w+/|C:\\Users\\\w+\\)[^\s]*?(\.pem|\.key|secret|token)", re.I
        ),
    ),
    ("license_plate", re.compile(r"\b[A-Z]{1,3}[\s\-]?\d{1,4}[\s\-]?[A-Z]{0,3}\b")),
    ("ssn", re.compile(r"\b\d{3}[\s\-]\d{2}[\s\-]\d{4}\b")),
    (
        "credit_card",
        re.compile(
            r"\b(?:4[0-9]{12}(?:[0-9]{3})?|[25][1-7][0-9]{14}|6(?:011|5[0-9][0-9])[0-9]{12}|3[47][0-9]{13})\b"
        ),
    ),
]

_REDACT_COLOR = (0, 0, 0)  # black fill
_REDACT_PADDING = 4  # pixels of extra padding around matched text region


@dataclass
class RedactionResult:
    redacted_path: str
    original_hash: str
    redacted_hash: str
    redaction_count: int
    categories_hit: list[str] = field(default_factory=list)
    cloak_active: bool = True

    def to_dict(self) -> dict:
        return {
            "redacted_path": self.redacted_path,
            "original_hash": self.original_hash,
            "redacted_hash": self.redacted_hash,
            "redaction_count": self.redaction_count,
            "categories_hit": self.categories_hit,
            "cloak_active": self.cloak_active,
        }


def redact_text_regions(
    img: Image.Image,
    bounding_boxes: list[dict[str, Any]],
) -> tuple[Image.Image, int]:
    """
    For each bounding box whose text matches a PII/secret pattern,
    paint a solid black rectangle over that region.
    Returns (redacted_image, count).
    """
    if not _PIL_AVAILABLE:
        return img, 0
    draw = ImageDraw.Draw(img)
    count = 0
    categories_hit: set[str] = set()
    for box in bounding_boxes:
        text = box.get("text", "")
        for category, pattern in _PII_PATTERNS:
            if pattern.search(text):
                x, y, w, h = box["x"], box["y"], box["w"], box["h"]
                draw.rectangle(
                    [
                        x - _REDACT_PADDING,
                        y - _REDACT_PADDING,
                        x + w + _REDACT_PADDING,
                        y + h + _REDACT_PADDING,
                    ],
                    fill=_REDACT_COLOR,
                )
                count += 1
                categories_hit.add(category)
                break  # one pattern match per box is enough
    return img, count


def redact(
    path: str | Path,
    output_path: str | Path | None = None,
) -> RedactionResult:
    """
    Full redaction pipeline:
    1. Load screenshot
    2. OCR → find PII regions
    3. Paint black rectangles
    4. Save to output_path (default: overwrite with _redacted suffix)

    Returns RedactionResult with hashes and counts.
    """
    from vision.ocr_scanner import extract_bounding_boxes
    from vision.screenshot_loader import screenshot_hash

    path = Path(path)
    orig_hash = screenshot_hash(path)

    if output_path is None:
        output_path = path.parent / (path.stem + "_redacted" + path.suffix)
    output_path = Path(output_path)

    if not _PIL_AVAILABLE:
        log.warning(
            "[visual_cloak] Pillow not available — skipping redaction, marking cloak_active=False"
        )
        return RedactionResult(
            redacted_path=str(path),
            original_hash=orig_hash,
            redacted_hash=orig_hash,
            redaction_count=0,
            cloak_active=False,
        )

    img = Image.open(path).convert("RGB")
    boxes = extract_bounding_boxes(img)
    categories_hit: set[str] = set()

    draw = ImageDraw.Draw(img)
    count = 0
    for box in boxes:
        text = box.get("text", "")
        for category, pattern in _PII_PATTERNS:
            if pattern.search(text):
                x, y, w, h = box["x"], box["y"], box["w"], box["h"]
                draw.rectangle(
                    [
                        x - _REDACT_PADDING,
                        y - _REDACT_PADDING,
                        x + w + _REDACT_PADDING,
                        y + h + _REDACT_PADDING,
                    ],
                    fill=_REDACT_COLOR,
                )
                count += 1
                categories_hit.add(category)
                break

    img.save(output_path)
    redacted_hash = screenshot_hash(output_path)

    if count > 0:
        log.info(
            "[visual_cloak] redacted %d region(s) from %s — categories: %s",
            count,
            path.name,
            sorted(categories_hit),
        )

    return RedactionResult(
        redacted_path=str(output_path),
        original_hash=orig_hash,
        redacted_hash=redacted_hash,
        redaction_count=count,
        categories_hit=sorted(categories_hit),
        cloak_active=True,
    )


def scan_text_for_pii(text: str) -> list[tuple[str, str]]:
    """
    Scan raw text for PII/secret matches.
    Returns list of (category, matched_value) tuples.
    """
    hits = []
    for category, pattern in _PII_PATTERNS:
        for match in pattern.finditer(text):
            hits.append((category, match.group()))
    return hits
