from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from policyseal.evals.assets import EvalAssets, load_eval_assets
from policyseal.policy.loader import load_policy_pack

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COUNTS = {
    "scenarios": 30,
    "semantic_snippets": 60,
    "retrieval_questions": 20,
    "copilot_dialogues": 6,
}
EXPECTED_STATUS_COUNTS = {
    "block": 8,
    "processing_failed": 2,
    "require_approval": 8,
    "safe": 12,
}
SYSTEM_RULE_PREFIXES = (
    "PS-DEFAULT-",
    "PS-MODEL-",
    "PS-PREFLIGHT-",
    "PS-RESIDUAL-",
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+)\b", re.IGNORECASE)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|token|api[_-]?key|secret)\s*[:=]\s*['\"]?[A-Za-z0-9+/_.-]{8,}"
)


def _assert_unique(label: str, values: list[str]) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(duplicates)}")


def _is_known_rule(rule_id: str, policy_rule_ids: set[str]) -> bool:
    return rule_id in policy_rule_ids or rule_id.startswith(SYSTEM_RULE_PREFIXES)


def validate_eval_assets(assets: EvalAssets) -> None:
    actual_counts = {
        "scenarios": len(assets.scenarios),
        "semantic_snippets": len(assets.semantic_snippets),
        "retrieval_questions": len(assets.retrieval_questions),
        "copilot_dialogues": len(assets.copilot_dialogues),
    }
    if actual_counts != EXPECTED_COUNTS:
        raise ValueError(f"evaluation counts changed: {actual_counts}")
    if assets.scenario_status_counts != EXPECTED_STATUS_COUNTS:
        raise ValueError(f"scenario status distribution changed: {assets.scenario_status_counts}")

    _assert_unique("scenario", [item.id for item in assets.scenarios])
    _assert_unique("semantic", [item.id for item in assets.semantic_snippets])
    _assert_unique("retrieval", [item.id for item in assets.retrieval_questions])
    _assert_unique("dialogue", [item.id for item in assets.copilot_dialogues])

    manifest = json.loads((REPO_ROOT / "demo_data/source_manifest.json").read_text())
    source_hashes = {item["id"]: item["sha256"] for item in manifest["files"]}
    policy = load_policy_pack(REPO_ROOT / "policies/v1")
    policy_rule_ids = {rule.id for rule in policy.rules}
    evidence_ids = {record.id for record in policy.evidence}
    scenario_ids = {scenario.id for scenario in assets.scenarios}

    for scenario in assets.scenarios:
        if source_hashes.get(scenario.source_id) != scenario.source_sha256:
            raise ValueError(f"{scenario.id} has a stale source hash")
        for decision in scenario.decisions:
            unknown_rules = [
                rule_id
                for rule_id in decision.rule_ids
                if not _is_known_rule(rule_id, policy_rule_ids)
            ]
            if unknown_rules:
                raise ValueError(f"{scenario.id} cites unknown rules: {unknown_rules}")
            unknown_evidence = set(decision.evidence_ids) - evidence_ids
            if unknown_evidence:
                raise ValueError(f"{scenario.id} cites unknown evidence: {unknown_evidence}")

    for question in assets.retrieval_questions:
        unknown_evidence = set(question.expected_evidence_ids) - evidence_ids
        if unknown_evidence:
            raise ValueError(f"{question.id} cites unknown evidence: {unknown_evidence}")

    for dialogue in assets.copilot_dialogues:
        if dialogue.scenario_id not in scenario_ids:
            raise ValueError(f"{dialogue.id} cites an unknown scenario")
        for turn in dialogue.turns:
            unknown_rules = [
                rule_id
                for rule_id in turn.expected_rule_ids
                if not _is_known_rule(rule_id, policy_rule_ids)
            ]
            if unknown_rules:
                raise ValueError(f"{dialogue.id} cites unknown rules: {unknown_rules}")
            unknown_evidence = set(turn.expected_evidence_ids) - evidence_ids
            if unknown_evidence:
                raise ValueError(f"{dialogue.id} cites unknown evidence: {unknown_evidence}")

    raw_assets = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "evals/goldens").glob("*.json*"))
    )
    for email_match in EMAIL_PATTERN.finditer(raw_assets):
        if not email_match.group(1).endswith(".example"):
            raise ValueError(f"non-reserved email domain found: {email_match.group(0)}")
    if "BEGIN PRIVATE KEY" in raw_assets or SECRET_ASSIGNMENT_PATTERN.search(raw_assets):
        raise ValueError("evaluation assets contain a credential-shaped raw value")


def main() -> None:
    assets = load_eval_assets(REPO_ROOT / "evals/goldens")
    validate_eval_assets(assets)
    print(
        "PolicySeal evals valid: "
        f"{len(assets.scenarios)} scenarios, "
        f"{len(assets.semantic_snippets)} semantic snippets, "
        f"{len(assets.retrieval_questions)} retrieval questions, "
        f"{len(assets.copilot_dialogues)} dialogues"
    )


if __name__ == "__main__":
    main()
