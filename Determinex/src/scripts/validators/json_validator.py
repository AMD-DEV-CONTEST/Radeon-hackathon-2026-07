"""
validators/json_validator.py - JSON Schema Validator

Validates that the generated output is:
  1. Valid JSON
  2. Optionally conforms to a task-specific JSON Schema (draft-07)

Used for: json_structured_output, api_routing_decisions (output verification)
"""

import json
import logging
import re

log = logging.getLogger("oracle.validator.json")


def _strip_markdown_fences(text: str) -> str:
    """Extract raw JSON from markdown-fenced output."""
    text = text.strip()
    # Remove ```json or ``` fences
    text = re.sub(r"^```(?:json)?\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate JSON output.

    Args:
        output:    Raw text from teacher model.
        task_meta: Curriculum task dict. If task_meta contains 'validator_config'
                   with a 'schema' key, validates against that JSON Schema.

    Returns:
        (True, reason) on pass, (False, reason) on fail.
    """
    clean = _strip_markdown_fences(output)

    if len(clean) < 2:
        return False, "Output too short to be valid JSON"

    # ── Stage 1: JSON parse ──────────────────────────────────────────────────
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        log.debug("JSON parse fail: %s", e)
        return False, f"Invalid JSON at position {e.pos}: {e.msg}"

    # ── Stage 2: JSON Schema validation (optional) ───────────────────────────
    schema = task_meta.get("validator_config", {}).get("schema")
    if schema:
        try:
            import jsonschema

            jsonschema.validate(instance=parsed, schema=schema)
        except ImportError:
            log.warning(
                "jsonschema not installed -- skipping schema validation. pip install jsonschema"
            )
        except jsonschema.ValidationError as e:
            log.debug("JSON Schema fail: %s", e.message)
            return False, f"Schema validation failed: {e.message}"
        except jsonschema.SchemaError as e:
            log.warning("Task schema itself is invalid: %s", e.message)
            # Don't penalize the sample for a broken task schema
            return True, "Valid JSON (schema check skipped -- task schema error)"

    # ── Stage 3: Minimum content check ───────────────────────────────────────
    # Reject trivially empty objects/arrays
    if isinstance(parsed, (dict, list)) and len(parsed) == 0:
        return False, "JSON is empty object or array"

    log.debug("JSON validator PASS")
    return True, f"Valid JSON ({type(parsed).__name__})"
