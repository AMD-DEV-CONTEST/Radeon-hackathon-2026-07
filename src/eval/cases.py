"""Read and validate Insurance RAG Agent evaluation cases and rules.

Case file format (JSON):
    [
        {
            "question": "What does employer liability insurance cover?",
            "expected_answer": "Employer liability insurance covers...",
            "expected_refs": ["2-Employer-Liability-Insurance"],
            "category": "rag_query",
            "difficulty": "easy",
            "context_dependency": "..."  # optional
        },
        ...
    ]

Rules file format (YAML):
    version: 1.0.0
    stage_rules:
        retrieval:
            - rule_id: retrieval.sufficient
              description: "..."
              owner: host
        ...
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


# ── required fields for a case ──
REQUIRED_CASE_FIELDS = ("question", "expected_answer", "expected_refs", "category")

# ── required fields for a rule ──
REQUIRED_RULE_FIELDS = ("rule_id", "description", "owner")

# ── valid owner values ──
VALID_OWNERS = {"host", "model"}


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Read a JSON-format evaluation-cases file.

    Args:
        path: Path to the JSON file.

    Returns:
        A list of case dicts, each containing fields such as question,
        expected_answer, expected_refs, category, difficulty, etc.

    Raises:
        ValueError: The file format is invalid or required fields are missing.
    """

    raw = path.read_text(encoding="utf-8")
    cases = json.loads(raw)
    if not isinstance(cases, list):
        raise ValueError("cases file root must be a JSON array")
    if not cases:
        raise ValueError("cases file must not be empty")

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case at index {index} must be an object")
        missing = [f for f in REQUIRED_CASE_FIELDS if not case.get(f)]
        if missing:
            raise ValueError(
                f"case at index {index} missing required fields: {', '.join(missing)}"
            )
        if not isinstance(case.get("expected_refs"), list):
            raise ValueError(
                f"case at index {index}: expected_refs must be a list"
            )

    return cases


def load_rules(path: Path) -> dict[str, Any]:
    """Read a YAML-format hierarchical evaluation-rules file.

    Args:
        path: Path to the YAML file.

    Returns:
        A rules dict containing the version and stage_rules keys.

    Raises:
        ValueError: The file format is invalid.
    """

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("rules.yaml root must be an object")
    if not isinstance(payload.get("stage_rules"), dict):
        raise ValueError("rules.yaml stage_rules must be an object")
    if not payload["stage_rules"]:
        raise ValueError("rules.yaml stage_rules must not be empty")
    return payload


def validate_case_rules(cases: list[dict[str, Any]], rules: dict[str, Any]) -> None:
    """Confirm that cases and stage rules are structurally complete and valid.

    Args:
        cases: The case list returned by load_cases().
        rules: The rules dict returned by load_rules().

    Raises:
        ValueError: The rules structure is invalid or rule_ids are duplicated.
    """

    stage_rules = rules["stage_rules"]

    rule_ids: list[str] = []
    for stage, rules_list in stage_rules.items():
        if not isinstance(rules_list, list) or not rules_list:
            raise ValueError(f"stage {stage} must define a non-empty rules list")
        for rule in rules_list:
            if not isinstance(rule, dict):
                raise ValueError(f"stage {stage} contains non-object rule")
            missing = [f for f in REQUIRED_RULE_FIELDS if not rule.get(f)]
            if missing:
                raise ValueError(
                    f"stage {stage} rule missing fields: {', '.join(missing)}"
                )
            owner = str(rule.get("owner", ""))
            if owner not in VALID_OWNERS:
                raise ValueError(
                    f"stage {stage} rule '{rule['rule_id']}': "
                    f"owner must be one of {sorted(VALID_OWNERS)}, got '{owner}'"
                )
            rule_ids.append(str(rule["rule_id"]))

    if len(rule_ids) != len(set(rule_ids)):
        seen: set[str] = set()
        duplicates = set()
        for rid in rule_ids:
            if rid in seen:
                duplicates.add(rid)
            seen.add(rid)
        raise ValueError(f"rule_id values must be unique, duplicates: {sorted(duplicates)}")


__all__ = [
    "REQUIRED_CASE_FIELDS",
    "REQUIRED_RULE_FIELDS",
    "VALID_OWNERS",
    "load_cases",
    "load_rules",
    "validate_case_rules",
]
