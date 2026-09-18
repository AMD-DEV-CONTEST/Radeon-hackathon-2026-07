"""Repair and validate model-produced JSON."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TypeVar

from json_repair import repair_json
from pydantic import BaseModel, ValidationError

from buildguard.exceptions import BuildGuardError

StructuredT = TypeVar("StructuredT", bound=BaseModel)
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(BuildGuardError):
    """Structured response remained invalid after one retry."""


def parse_structured(text: str, schema: type[StructuredT]) -> StructuredT:
    """Parse standard JSON, fenced JSON, then repaired JSON."""
    match = FENCE.match(text)
    candidate = match.group(1) if match else text.strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        repaired = repair_json(candidate)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"Could not parse structured JSON: {exc}") from exc
    if isinstance(payload, dict):
        payload.pop("id", None)
        payload.pop("created_at", None)
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(f"Structured output validation failed: {exc}") from exc


def parse_with_one_retry(
    first_text: str,
    schema: type[StructuredT],
    retry: Callable[[str], str],
) -> StructuredT:
    """Retry exactly once with a validation-only correction instruction."""
    try:
        return parse_structured(first_text, schema)
    except StructuredOutputError as first_error:
        correction = (
            f"Return only valid JSON matching this schema: {schema.model_json_schema()}. "
            f"Previous validation error: {first_error}"
        )
        return parse_structured(retry(correction), schema)

