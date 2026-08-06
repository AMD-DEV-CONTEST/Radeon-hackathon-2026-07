from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_curated_human_audit import aggregate_completed_reviews  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    root = ROOT / "data/v10_curated_human_audit"
    cases = _read(root / "blind-cases.jsonl")
    reviews: list[dict[str, Any]] = []
    review_dir = root / "completed-reviews"
    if review_dir.is_dir():
        for path in sorted(review_dir.glob("reviewer-*.jsonl")):
            reviews.extend(_read(path))
    aggregate = aggregate_completed_reviews(cases, reviews)
    if aggregate["freeze_passed"]:
        status = "passed_curated_corpus_v2_human_audit"
    elif aggregate["review_set_complete"]:
        status = "failed_complete_human_audit_below_freeze_gate"
    else:
        status = "not_observed_incomplete_human_audit"
    routes = aggregate.pop("routes")
    route_digest = stable_sha256(routes) if routes else None
    report = {
        "schema": "ProofLaunchCuratedCorpusHumanAuditGateV1",
        "status": status,
        **aggregate,
        "routing_observed": bool(routes),
        "route_digest": route_digest,
        "human_review_claim_allowed": aggregate["review_set_complete"],
        "agreement_claim_allowed": aggregate["alpha_passed"],
        "positive_mean_4_7_claim_allowed": aggregate["positive_mean_passed"],
        "curated_corpus_v2_freeze_claim_allowed": aggregate["freeze_passed"],
        "model_generated_review_count": 0,
        "official_api_generated_review_count": 0,
        "truth_boundary": "Only completed, attested, hash-bound human rows count. Official or third-party model ratings cannot satisfy the human audit, agreement, routing, or freeze gate.",
    }
    report["report_sha256"] = stable_sha256(report)
    output = ROOT / "evidence/v10/curated-1500-human-audit-gate.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if routes:
        route_root = root / "verified-routes"
        route_root.mkdir(parents=True, exist_ok=True)
        for route in ("positive", "remove", "repair", "replay"):
            selected = [row for row in routes if row["route"] == route]
            text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in selected)
            if text:
                text += "\n"
            atomic_write_text(route_root / f"{route}.jsonl", text)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if aggregate["freeze_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
