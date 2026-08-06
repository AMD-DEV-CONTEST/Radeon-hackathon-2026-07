from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_gold_candidates import (  # noqa: E402
    BRIEF_GATES,
    build_gold_brief_candidate,
    build_gold_campaign_candidate,
)


def main() -> int:
    root = ROOT / "data/v10_gold_candidates"
    briefs = [json.loads(line) for line in (root / "brief-candidates.jsonl").read_text(encoding="utf-8").splitlines() if line]
    campaigns = [json.loads(line) for line in (root / "campaign-candidates.jsonl").read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sources = [json.loads(line) for line in (ROOT / manifest["source_path"]).read_text(encoding="utf-8").splitlines() if line]
    failures: list[str] = []
    for index, (brief, source) in enumerate(zip(briefs, sources[:300], strict=True), start=1):
        if brief != build_gold_brief_candidate(source, index):
            failures.append(f"brief_rebuild:{index}")
        if set(brief["mechanical_gate_results"]) != set(BRIEF_GATES) or not all(brief["mechanical_gate_results"].values()):
            failures.append(f"brief_gate:{index}")
    by_id = {brief["brief_id"]: brief for brief in briefs}
    for index, campaign in enumerate(campaigns, start=1):
        linked = [by_id[brief_id] for brief_id in campaign["brief_ids"]]
        if campaign != build_gold_campaign_candidate(linked, index):
            failures.append(f"campaign_rebuild:{index}")
    observed = {
        "brief_candidate_count": len(briefs),
        "campaign_candidate_count": len(campaigns),
        "unique_brief_count": len({row["content_sha256"] for row in briefs}),
        "unique_campaign_count": len({row["content_sha256"] for row in campaigns}),
        "brief_channel_counts": dict(sorted(Counter(row["channel"] for row in briefs).items())),
        "mechanical_brief_gate_failure_count": sum(not all(row["mechanical_gate_results"].values()) for row in briefs),
        "campaign_reference_failure_count": sum(any(brief_id not in by_id for brief_id in row["brief_ids"]) for row in campaigns),
    }
    expected = {
        "brief_candidate_count": 300,
        "campaign_candidate_count": 150,
        "unique_brief_count": 300,
        "unique_campaign_count": 150,
        "brief_channel_counts": {channel: 50 for channel in ("audio", "email", "search", "social", "video", "web")},
        "mechanical_brief_gate_failure_count": 0,
        "campaign_reference_failure_count": 0,
    }
    for key, value in expected.items():
        if observed[key] != value or manifest.get(key) != value and key in manifest:
            failures.append(f"recount:{key}")
    if hashlib.sha256((root / "brief-candidates.jsonl").read_bytes()).hexdigest() != manifest["brief_file_sha256"]:
        failures.append("brief_file_hash")
    if hashlib.sha256((root / "campaign-candidates.jsonl").read_bytes()).hexdigest() != manifest["campaign_file_sha256"]:
        failures.append("campaign_file_hash")
    report = {
        "schema": "ProofLaunchGoldCandidateIndependentAuditV1",
        "status": "passed_pre_review_candidates_not_human_gold" if not failures else "failed",
        **observed,
        "all_records_independently_reconstructed": not failures,
        "rights_failure_count": sum(not row["rights_verified"] for row in briefs + campaigns),
        "hidden_chain_of_thought_count": sum(row["hidden_chain_of_thought_present"] for row in briefs + campaigns),
        "human_review_count": 0,
        "human_mean_quality_score": None,
        "teacher_model_used": False,
        "training_observed": False,
        "failure_count": len(failures),
        "failures": failures[:100],
        "manifest_sha256": manifest["manifest_sha256"],
    }
    output = ROOT / "evidence/v10/gold-candidates-independent-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
