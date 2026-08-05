"""Spec-driven task functions: student prompts, parsing, scoring.

Single source of truth for what the student sees and how it's judged,
parameterized by TaskSpec so datagen, training, and eval cannot drift.
"""

import json

from .spec import TaskSpec


def student_system(spec: TaskSpec) -> str:
    return (
        f"{spec.description} "
        f"Given a {spec.example_noun}, respond with a single JSON object "
        f"and nothing else: {spec.schema_line()}"
    )


def student_messages(spec: TaskSpec, input_text: str) -> list[dict]:
    """The exact conversation the student sees, in training and at inference."""
    return [
        {"role": "system", "content": student_system(spec)},
        {"role": "user", "content": input_text},
    ]


def target_text(spec: TaskSpec, row: dict) -> str:
    """The exact assistant completion the student is trained to produce."""
    return json.dumps({f: row[f] for f in spec.output_fields()})


def _balanced_json(text: str):
    if not isinstance(text, str):
        # Defense in depth: transport normalization should make this
        # unreachable, but a parse error beats an AttributeError.
        return None, f"non_string_response:{type(text).__name__}"
    start = text.find("{")
    if start == -1:
        return None, "no_json_object"
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None, "unbalanced_json"
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None, "json_decode_error"
    if not isinstance(obj, dict):
        return None, "not_an_object"
    return obj, None


def parse_response(spec: TaskSpec, text: str):
    """Extract and validate the student's output fields from a response.

    Returns (dict, None) on success or (None, reason) on failure.
    """
    obj, reason = _balanced_json(text)
    if obj is None:
        return None, reason
    out = {}
    for field, fs in spec.output_schema.items():
        if field not in obj:
            return None, f"missing_field:{field}"
        val = str(obj[field]).strip()
        if fs["type"] == "enum":
            match = next((v for v in fs["values"] if v.lower() == val.lower()), None)
            if match is None:
                return None, f"bad_value:{field}:{val}"
            out[field] = match
        else:
            out[field] = val
    return out, None


def score(spec: TaskSpec, predictions: list, references: list) -> dict:
    """predictions: list of (dict|None); references: list of dicts."""
    n = len(references)
    fields = spec.output_fields()
    valid = sum(1 for p in predictions if p is not None)
    field_acc = {
        f: sum(1 for p, r in zip(predictions, references) if p and p[f] == r[f]) / n
        for f in fields
    }
    exact = sum(
        1
        for p, r in zip(predictions, references)
        if p and all(p[f] == r[f] for f in fields)
    )
    return {
        "n": n,
        "json_valid": valid / n,
        "field_acc": field_acc,
        "exact_match": exact / n,
    }
