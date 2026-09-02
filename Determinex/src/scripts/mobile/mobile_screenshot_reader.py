"""Mobile screenshot reader — wraps vision primitives for mobile-specific analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_mobile_screenshot(path: str | Path) -> Any:
    from vision.screenshot_loader import load_screenshot

    return load_screenshot(path)


def hash_mobile_screenshot(path: str | Path) -> str:
    from vision.screenshot_loader import screenshot_hash

    return screenshot_hash(path)


def extract_mobile_text(path: str | Path) -> str:
    from vision.ocr_scanner import extract_text

    return extract_text(path)


def find_text(path: str | Path, search: str) -> list[dict]:
    from vision.ocr_scanner import find_text_in_image

    return find_text_in_image(path, search)


def diff_mobile_screenshots(path_before: str, path_after: str, threshold: float = 0.05) -> dict:
    from vision.visual_diff import compare

    result = compare(path_before, path_after, threshold=threshold)
    return result.to_dict()


def redact_mobile_screenshot(path: str | Path, output_path: str | Path | None = None) -> dict:
    """Redact PII from a mobile screenshot before corpus storage or cloud API use."""
    from vision.visual_cloak import redact

    result = redact(path, output_path)
    return result.to_dict()
