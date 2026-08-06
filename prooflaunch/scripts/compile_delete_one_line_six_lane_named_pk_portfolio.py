from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
V3 = ROOT / "evidence/v10/delete-one-line-five-lane-named-pk-portfolio-v3.json"
CANDIDATE = ROOT / "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/cross-device-memory-execution.json"
MEM0_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet/packet-receipt.json"
MEM0_PUBLIC_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet/public/packet.json"
MEM0_CAPTURE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/mem0/capture.json"
MEM0_PROVENANCE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/mem0/provenance.json"
OUTPUT = ROOT / "evidence/v10/delete-one-line-six-lane-named-pk-portfolio-v4.json"


MEMORY_STRESS = {
    "ChatGPT Memory": "Preserve user-legible controls and useful personalization while exposing the exact source event, scope, expiry, contradiction rule and deletion proof for every GTM decision.",
    "Claude Memory": "Carry project context through long work without silently merging an inference into an approved fact or losing why the later decision superseded the earlier one.",
    "Gemini personalization": "Keep personalization consistent across surfaces while separating account context, workspace evidence and current-task permissions under one inspectable deletion boundary.",
    "Microsoft 365 Copilot Memory": "Respect tenant and work-context boundaries while reconstructing which approved source, owner and time window authorized the remembered launch decision.",
    "Zep": "Match temporal knowledge-graph retrieval while making contradiction resolution, episode lineage and exact erasure independently reproducible.",
    "Mem0": "Beat the captured local same-task run on concise decision usefulness without losing provenance, tenant isolation, newer-fact precedence or zero-after-delete evidence.",
    "Letta": "Sustain agent memory across long execution loops while keeping core memory edits explicit, bounded, reversible and subordinate to human-approved evidence.",
    "MemOS": "Route among memory tiers without allowing compression or promotion to erase source identity, temporal validity, contradiction state or deletion semantics.",
    "Personal AI": "Offer person-specific continuity without identity imitation, private-data leakage or an opaque memory claim the owner cannot inspect and revoke.",
    "Glean Assistant": "Retrieve the decision across enterprise knowledge sources with permission-aware citations and no cross-tenant or stale-source contamination.",
}


def binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def row_id(category_id: str, product: str) -> str:
    return f"dol-pk-{category_id}-{hashlib.sha256(f'{category_id}\0{product}'.encode()).hexdigest()[:12]}"


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    previous = json.loads(V3.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    packet = json.loads(MEM0_PACKET.read_text(encoding="utf-8"))
    public_packet = json.loads(MEM0_PUBLIC_PACKET.read_text(encoding="utf-8"))
    capture = json.loads(MEM0_CAPTURE.read_text(encoding="utf-8"))
    provenance = json.loads(MEM0_PROVENANCE.read_text(encoding="utf-8"))
    if previous["lane_count"] != 5 or previous["named_product_row_count"] != 50:
        raise SystemExit("five-lane portfolio drifted")
    if packet["capture_slot_id"] != capture["capture_slot_id"] or packet["submitted_review_count"] != 0:
        raise SystemExit("Mem0 packet state drifted")
    if public_packet["expected_review_count"] != 5 or public_packet["source_roles_exposed"]:
        raise SystemExit("Mem0 packet is not source-hidden five-reviewer work")
    evaluation = provenance["evaluation"]
    required = (
        "all_operations_succeeded", "evidence_boundary_retrieved", "exact_deletion_observed",
        "newer_channel_retrieved", "source_provenance_present", "tenant_isolation_observed",
    )
    if not all(evaluation[key] is True for key in required) or evaluation["memory_count_after_delete"] != 0:
        raise SystemExit("Mem0 baseline mechanics are incomplete")
    rows = [row for row in ledger["product_pk_rows"] if row["category_id"] == "cross_device_memory"]
    if len(rows) != 10 or set(MEMORY_STRESS) != {row["reference_product"] for row in rows}:
        raise SystemExit("memory named-product coverage drifted")
    candidate_binding = binding(CANDIDATE)
    lane = {
        "category_id": "cross_device_memory",
        "candidate_binding": candidate_binding,
        "support_bindings": [binding(MEM0_PACKET), binding(MEM0_PUBLIC_PACKET), binding(MEM0_CAPTURE), binding(MEM0_PROVENANCE)],
        "named_product_target_count": 10,
        "authorized_named_product_baseline_count": 1,
        "source_hidden_five_human_packet_count": 1,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "qualified_human_review_count": 0,
        "release_eligible": False,
    }
    compiled = []
    for row in rows:
        mem0 = row["reference_product"] == "Mem0"
        compiled.append({
            "row_id": row_id(row["category_id"], row["reference_product"]),
            "category_id": row["category_id"],
            "reference_product": row["reference_product"],
            "reference_product_url": row["reference_product_url"],
            "reference_capability": row["reference_capability"],
            "same_brief_task": row["same_brief_task"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": row["quality_axes"],
            "opponent_specific_stress_test": MEMORY_STRESS[row["reference_product"]],
            "candidate_sha256": candidate_binding["sha256"],
            "authorized_named_product_baseline_present": mem0,
            "source_hidden_five_human_packet_present": mem0,
            "qualified_human_review_count": 0,
            "comparison_status": "source_hidden_packet_ready_awaiting_five_humans" if mem0 else "awaiting_authorized_same_brief_baseline",
            "candidate_won": False,
            "effect_alignment_achieved": False,
        })
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineSixLaneNamedPKPortfolioV4",
        "source_ledger_sha256": ledger["content_sha256"],
        "source_five_lane_portfolio_sha256": previous["content_sha256"],
        "campaign_id": "delete-one-line",
        "lane_count": 6,
        "named_product_row_count": 60,
        "lanes": [*previous["lanes"], lane],
        "rows": [*previous["rows"], *compiled],
        "authorized_named_product_baseline_count": 3,
        "source_hidden_five_human_packet_count": 3,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "effect_aligned_lane_count": 0,
        "automatic_product_execution_enabled": False,
        "automatic_promotion_enabled": False,
        "production_effect_observed": False,
        "truth_boundary": "This portfolio binds Delete One Line challengers to sixty named-product rows across text, scheduling, GTM lifecycle, image, audio and cross-device memory. Qwen-Image, Qwen3-TTS and Mem0 each have one authorized same-task baseline and an empty five-human packet. All sixty wins and all market-effect claims remain zero.",
    })
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "lane_count": 6, "named_product_row_count": 60, "authorized_named_product_baseline_count": 3, "source_hidden_five_human_packet_count": 3, "candidate_win_count": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
