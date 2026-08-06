#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_effect_eval import Capability, Deliverable, DeliverableRole  # noqa: E402
from prooflaunch_remix.gtm_effect_packet import EffectReviewPacketBuilder, PacketArtifact  # noqa: E402
from prooflaunch_remix.gtm_last_mile_challenger import validate_receipt  # noqa: E402
from prooflaunch_remix.gtm_last_mile_diagnostic import diagnose  # noqa: E402


CHALLENGER = ROOT / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger-repaired.json"
CURRENT = ROOT / "artifacts/run-bound-multimodal-demo-v1/production-deliverables"

LANES = {
    "integrated_gtm_strategy": (Capability.STRATEGY, "gtm-strategy.json"),
    "organic_social_copy": (Capability.COPY, "channel-copy.json"),
    "landing_page": (Capability.COPY, "landing-page-draft.json"),
    "lifecycle_email": (Capability.COPY, "lifecycle-email-draft.json"),
    "content_schedule": (Capability.SCHEDULE, "content-calendar.json"),
    "seo": (Capability.SEO_GEO, "seo-geo-questions.json"),
    "geo": (Capability.SEO_GEO, "seo-geo-faq-drafts.json"),
    "advertising": (Capability.STRATEGY, "channel-portfolio.json"),
    "analytics": (Capability.ANALYTICS, "analytics-plan.json"),
    "employee_agent": (Capability.STRATEGY, "graph-loop-harness.json"),
    "cross_device_memory": (Capability.STRATEGY, "approved-learning-context.json"),
}


def _deliverable(*, lane: str, capability: Capability, role: DeliverableRole, source: Path) -> PacketArtifact:
    return PacketArtifact(
        deliverable=Deliverable(
            deliverable_id=f"{lane}-{role.value}",
            scenario_id="prooflaunch-b2b-ai-launch-zero-budget-v1",
            capability=capability,
            role=role,
            content_sha256=sha256_file(source),
            blind_artifact_locator=f"local://{source.name}",
            rights_locator="rights://prooflaunch-owner-generated-clean-room",
            evidence_locators=("evidence://claim-owner-001",),
            claim_ids=("claim-owner-001",),
            brand_profile_id="prooflaunch-cortex-x-v1",
            channel=lane,
            accessibility_locator="contract://json-utf8-human-readable",
            experiment_trace_id="run-35bf6593f7aa4a4b34100a74",
            clean_room_attested=True,
            method_reference_locators=("docs/product/GTM_CONCRETE_PRODUCT_EFFECT_PK_LEDGER_V1.md",),
        ),
        source_path=str(source),
        comparison_key=lane,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3"))
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")

    receipt = json.loads(CHALLENGER.read_text(encoding="utf-8"))
    if receipt.get("schema") != "ProofLaunchGTMLastMileChallengerRepairReceiptV1":
        raise SystemExit("repaired challenger receipt schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    import hashlib
    expected = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    if supplied != expected or receipt.get("blind_review_admission_allowed") is not True:
        raise SystemExit("repaired challenger receipt failed digest or admission gate")
    challenger = receipt["accepted_candidate"]
    diagnostic = diagnose(challenger)
    lane_root = output.parent / "challenger-lanes"
    lane_root.mkdir(parents=True, exist_ok=True)
    entries: list[PacketArtifact] = []
    for lane, (capability, current_name) in LANES.items():
        challenger_path = lane_root / f"{lane}.json"
        atomic_write_text(challenger_path, json.dumps(challenger[lane], ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        entries.append(_deliverable(lane=lane, capability=capability, role=DeliverableRole.CANDIDATE, source=CURRENT / current_name))
        entries.append(_deliverable(lane=lane, capability=capability, role=DeliverableRole.BASELINE, source=challenger_path))

    packet = EffectReviewPacketBuilder().build(
        entries,
        output,
        randomization_key=secrets.token_urlsafe(32),
        reviewer_count=5,
    )
    scope = {
        "schema": "ProofLaunchGTMLastMileInternalReviewScopeV1",
        "packet_sha256": packet.packet_sha256,
        "lane_count": len(LANES),
        "expected_human_review_count": len(LANES) * 5,
        "submitted_human_review_count": 0,
        "comparison_class": "current_system_vs_local_internal_challenger",
        "top_product_baseline": False,
        "challenger_diagnostic": diagnostic,
        "review_admission_status": "blocked_for_challenger_repair" if not diagnostic["blind_review_admission_allowed"] else "ready_for_named_human_review",
        "effect_alignment_achieved": False,
        "truth_boundary": (
            "This packet provides an identity-hidden internal stress comparison. The local Gemma "
            "challenger is not a leading-product output and cannot establish product parity or "
            "superiority. Critical challenger findings must be repaired before qualified review."
        ),
    }
    atomic_write_text(output / "scope.json", json.dumps(scope, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(output.parent / "challenger-diagnostic.json", json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"packet": packet.root, "pair_count": packet.pair_count, "reviewer_count": packet.reviewer_count, "critical_findings": diagnostic["critical_finding_count"], "review_admission_status": scope["review_admission_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
