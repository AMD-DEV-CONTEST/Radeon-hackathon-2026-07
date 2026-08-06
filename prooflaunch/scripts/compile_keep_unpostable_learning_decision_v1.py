#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
ROOM = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-execution-room-v1"
DEFAULT_OBSERVATION = ROOM / "observation-template.json"
DEFAULT_OUTPUT = ROOM / "learning-decision.json"
ALLOWED_OWNER_DECISIONS = {"SCALE", "ITERATE", "RETIRE"}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def missing_fields(row: dict) -> list[str]:
    required = (
        "release_url",
        "released_at_utc",
        "exposures",
        "qualified_comprehension_actions",
        "qualified_private_starts",
        "continue_opt_ins",
        "misread_as_public_reveal",
        "streak_pressure_objections",
        "owner_decision",
    )
    missing = [field for field in required if row.get(field) is None]
    day_7 = row.get("day_7_decisions", {})
    missing.extend(f"day_7_decisions.{field}" for field in ("keep", "edit", "export", "delete") if day_7.get(field) is None)
    if not row.get("evidence_urls"):
        missing.append("evidence_urls")
    return missing


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def compile_route(row: dict) -> dict:
    missing = missing_fields(row)
    if missing:
        return {
            "provider": row["provider"],
            "state": "WAITING_FOR_OBSERVED_EVIDENCE",
            "missing_fields": missing,
            "descriptive_metrics": None,
            "owner_decision": None,
            "automatic_strategy_change": False,
            "memory_promotion_state": "NOT_ELIGIBLE",
        }
    if row["owner_decision"] not in ALLOWED_OWNER_DECISIONS:
        raise SystemExit(f"invalid owner decision for {row['provider']}: {row['owner_decision']}")
    counts = [
        row["exposures"], row["qualified_comprehension_actions"], row["qualified_private_starts"],
        row["continue_opt_ins"], row["misread_as_public_reveal"], row["streak_pressure_objections"],
        *row["day_7_decisions"].values(),
    ]
    if any(not isinstance(value, int) or value < 0 for value in counts):
        raise SystemExit(f"observed counts must be non-negative integers: {row['provider']}")
    day_7_total = sum(row["day_7_decisions"].values())
    metrics = {
        "comprehension_per_exposure": safe_rate(row["qualified_comprehension_actions"], row["exposures"]),
        "private_start_per_exposure": safe_rate(row["qualified_private_starts"], row["exposures"]),
        "day_7_decision_per_private_start": safe_rate(day_7_total, row["qualified_private_starts"]),
        "continue_per_day_7_decision": safe_rate(row["continue_opt_ins"], day_7_total),
        "public_reveal_misread_per_comprehension_action": safe_rate(row["misread_as_public_reveal"], row["qualified_comprehension_actions"]),
        "streak_pressure_objection_per_comprehension_action": safe_rate(row["streak_pressure_objections"], row["qualified_comprehension_actions"]),
    }
    return {
        "provider": row["provider"],
        "state": "HUMAN_DECISION_RECORDED",
        "missing_fields": [],
        "descriptive_metrics": metrics,
        "owner_decision": row["owner_decision"],
        "evidence_urls": row["evidence_urls"],
        "automatic_strategy_change": False,
        "memory_promotion_state": "PENDING_SEPARATE_HUMAN_APPROVAL",
        "learning_candidate": {
            "scope": f"keep-the-unpostable/{row['provider']}/organic-v1",
            "provenance": row["evidence_urls"],
            "expires_after_days": 30,
            "allowed_use": "Generate a bounded next-iteration hypothesis; never claim causality or universal platform truth.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, default=DEFAULT_OBSERVATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    observation_path = args.observation.resolve()
    if not observation_path.is_file():
        raise SystemExit(f"missing observation file: {observation_path}")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    rows = observation.get("rows", [])
    if {row.get("provider") for row in rows} != {"tiktok", "instagram"}:
        raise SystemExit("observation must contain exactly TikTok and Instagram")
    route_decisions = [compile_route(next(row for row in rows if row["provider"] == provider)) for provider in ("tiktok", "instagram")]
    waiting = sum(row["state"] == "WAITING_FOR_OBSERVED_EVIDENCE" for row in route_decisions)
    payload = seal(
        {
            "schema": "ProofLaunchKeepUnpostableLearningDecisionV1",
            "campaign_id": observation["campaign_id"],
            "observation_sha256": sha256_file(observation_path),
            "route_decisions": route_decisions,
            "waiting_route_count": waiting,
            "human_decision_recorded_route_count": len(route_decisions) - waiting,
            "automatic_strategy_change_count": 0,
            "automatic_memory_promotion_count": 0,
            "causal_claim_allowed": False,
            "external_action_executed": False,
            "truth_boundary": "Rates are descriptive only. The compiler never turns platform metrics into causality, virality, revenue or superiority; strategy and memory changes require separate named human approval.",
        }
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "waiting_route_count": waiting, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
