from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    return {**unsigned, "content_sha256": hashlib.sha256(canonical_bytes(unsigned)).hexdigest()}


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^A-Z0-9]+", " ", ascii_text.upper()).strip()


def fuzzy_contains(haystack: str, needle: str) -> float:
    haystack_norm = normalize_text(haystack)
    needle_norm = normalize_text(needle)
    if not needle_norm:
        return 1.0
    if needle_norm in haystack_norm:
        return 1.0
    needle_tokens = needle_norm.split()
    haystack_tokens = haystack_norm.split()
    if not haystack_tokens:
        return 0.0
    minimum = max(1, math.floor(len(needle_tokens) * 0.75))
    maximum = min(len(haystack_tokens), math.ceil(len(needle_tokens) * 1.25) + 2)
    best = 0.0
    for width in range(minimum, maximum + 1):
        for start in range(0, len(haystack_tokens) - width + 1):
            window = " ".join(haystack_tokens[start : start + width])
            best = max(best, SequenceMatcher(None, needle_norm, window).ratio())
    return round(best, 6)


def phrase_occurrences(haystack: str, phrase: str) -> int:
    normalized = normalize_text(haystack)
    target = normalize_text(phrase)
    return normalized.count(target) if target else 0


def evaluate_visual_release(
    *,
    artifact_id: str,
    expected_width: int,
    expected_height: int,
    observation: Mapping[str, Any],
    required_phrases: Sequence[str],
    forbidden_phrases: Sequence[str] = (),
    maximum_occurrences: Mapping[str, int] | None = None,
    minimum_phrase_score: float = 0.84,
    minimum_mean_ocr_confidence: float = 0.72,
    minimum_dynamic_range: float = 0.5,
) -> dict[str, Any]:
    full_text = str(observation.get("full_text") or "")
    observations = observation.get("observations")
    if not isinstance(observations, list):
        observations = []
    confidences = [float(row.get("confidence", 0)) for row in observations if isinstance(row, dict)]
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    required = [
        {"phrase": phrase, "score": fuzzy_contains(full_text, phrase)}
        for phrase in required_phrases
    ]
    forbidden = [
        {"phrase": phrase, "score": fuzzy_contains(full_text, phrase)}
        for phrase in forbidden_phrases
    ]
    repetitions = [
        {
            "phrase": phrase,
            "observed": phrase_occurrences(full_text, phrase),
            "maximum": int(maximum),
        }
        for phrase, maximum in (maximum_occurrences or {}).items()
    ]
    width = int(observation.get("width") or 0)
    height = int(observation.get("height") or 0)
    dynamic_range = float(observation.get("luminance_dynamic_range") or 0)
    failures: list[dict[str, Any]] = []
    if (width, height) != (expected_width, expected_height):
        failures.append({"gate": "exact_canvas", "expected": [expected_width, expected_height], "actual": [width, height]})
    for item in required:
        if item["score"] < minimum_phrase_score:
            failures.append({"gate": "required_copy", **item, "minimum": minimum_phrase_score})
    for item in forbidden:
        if item["score"] >= minimum_phrase_score:
            failures.append({"gate": "forbidden_copy", **item, "maximum_exclusive": minimum_phrase_score})
    for item in repetitions:
        if item["observed"] > item["maximum"]:
            failures.append({"gate": "duplicate_copy", **item})
    if mean_confidence < minimum_mean_ocr_confidence:
        failures.append({"gate": "ocr_confidence", "actual": round(mean_confidence, 6), "minimum": minimum_mean_ocr_confidence})
    if dynamic_range < minimum_dynamic_range:
        failures.append({"gate": "luminance_dynamic_range", "actual": round(dynamic_range, 6), "minimum": minimum_dynamic_range})
    core = {
        "schema": "ProofLaunchVisualReleaseGateV1",
        "artifact_id": artifact_id,
        "release_ready": not failures,
        "canvas": {"expected": [expected_width, expected_height], "actual": [width, height]},
        "mean_ocr_confidence": round(mean_confidence, 6),
        "luminance_dynamic_range": round(dynamic_range, 6),
        "required_phrase_results": required,
        "forbidden_phrase_results": forbidden,
        "repetition_results": repetitions,
        "failures": failures,
        "truth_boundary": (
            "This deterministic gate detects release-blocking canvas, copy, OCR and contrast defects. "
            "It does not measure creative preference, platform distribution, virality, conversion or revenue."
        ),
    }
    return seal(core)
