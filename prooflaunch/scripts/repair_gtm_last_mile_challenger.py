#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_last_mile_challenger import validate_receipt  # noqa: E402
from prooflaunch_remix.gtm_last_mile_diagnostic import diagnose  # noqa: E402


SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger-repaired.json"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def repair(candidate: dict[str, object]) -> tuple[dict[str, object], list[dict[str, str]]]:
    value = deepcopy(candidate)
    changes: list[dict[str, str]] = []

    replacements = {
        "integrated_gtm_strategy.commercial_hypothesis": "Hypothesis to test: an inspectable audit trail may earn qualified design-partner conversations; measure it against the same-window evidence-light baseline before making a performance claim.",
        "organic_social_copy.cta": "Inspect the attached evidence card, then decide whether the design-partner review is worth your time.",
        "lifecycle_email.cta": "For opted-in recipients: inspect the evidence pack at /evidence-pack, then decide whether to request a design-partner review.",
        "geo.question": "How does ProofLaunch Cortex-X keep AI-generated GTM work inspectable before release?",
        "geo.direct_answer": "ProofLaunch Cortex-X binds an approved evidence source to generated drafts, named human review, release controls and a traceable learning record; external release remains disabled until approval.",
        "geo.entity_statement": "ProofLaunch Cortex-X is a governed multimodal GTM workspace; this statement describes the approved product workflow, not a measured market outcome.",
        "analytics.decision_rule": "After the preregistered 14-day window and at least 25 eligible sessions per arm, advance only if the evidence-first treatment has no critical safety defect and the qualified-action interval supports a follow-up test; otherwise repair or stop.",
        "cross_device_memory.retrieve": "Retrieve only consented first-party campaign preferences and approved memories by tenant, purpose and source; third-party social profiles are out of scope.",
        "cross_device_memory.privacy_rule": "Require explicit purpose, tenant scope, source provenance, retention expiry, export and exact deletion for every memory; deny retrieval when consent or scope is absent.",
    }
    for path, replacement in replacements.items():
        lane, field = path.split(".", 1)
        old = str(value[lane][field])
        value[lane][field] = replacement
        changes.append({"path": path, "reason": "evidence, consent, channel or experiment repair", "before_sha256": hashlib.sha256(old.encode()).hexdigest(), "after_sha256": hashlib.sha256(replacement.encode()).hexdigest()})

    body = value["organic_social_copy"]["body"]
    value["organic_social_copy"]["body"] = [
        paragraph.replace("Inspect the end-to-end evidence pack. Link in bio.", "Inspect the attached evidence card and name the first unresolved condition.")
        for paragraph in body
    ]
    value["lifecycle_email"]["body"] = [
        paragraph.replace("Request access to the evidence pack.", "If you opted in to this design-partner update, inspect the evidence pack at /evidence-pack.")
        for paragraph in value["lifecycle_email"]["body"]
    ]
    value["content_schedule"]["days"] = [
        {
            **day,
            "asset": "Opt-in lifecycle email to registered evidence-pack recipients",
            "learning_question": "Do opted-in recipients inspect the cited proof and request a qualified review?",
        }
        if "Email to LinkedIn Engagers" in str(day.get("asset", ""))
        else {
            **day,
            "learning_question": str(day.get("learning_question", "")).replace("generate qualified leads", "surface qualified, consented design-partner conversations"),
        }
        for day in value["content_schedule"]["days"]
    ]
    value["analytics"]["stop_rules"] = [
        "Stop immediately on a consent, rights, safety or channel-policy breach.",
        "Do not interpret before the preregistered 14-day window and minimum 25 eligible sessions per arm unless a safety stop fires.",
        "Stop or repair if instrumentation loss exceeds 5% or the eligible-arm balance deviates materially from the assignment log.",
    ]
    value["advertising"]["test_design"] = (
        "Draft-only 2x2 test: proof-object vs workflow-map creative crossed with inspect-evidence vs name-the-objection CTA; "
        "same eligible audience, exclusions and window; spend and activation remain disabled pending named human approval."
    )
    return value, changes


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    validate_receipt(source)
    before = diagnose(source["accepted_candidate"])
    candidate, changes = repair(source["accepted_candidate"])
    after = diagnose(candidate)
    payload = {
        "schema": "ProofLaunchGTMLastMileChallengerRepairReceiptV1",
        "source_receipt_sha256": source["content_sha256"],
        "repair_kind": "bounded_human-authored_safety_and_execution_repair",
        "change_count": len(changes),
        "changes": changes,
        "diagnostic_before": before,
        "diagnostic_after": after,
        "accepted_candidate": candidate,
        "blind_review_admission_allowed": after["blind_review_admission_allowed"],
        "human_review_completed": False,
        "winner_selected": False,
        "automatic_release_authority": False,
        "top_product_baseline": False,
        "truth_boundary": (
            "This receipt proves a bounded, content-addressed repair removed enumerated defects. "
            "It is still an internal challenger, not a leading-product baseline, human preference, "
            "4A parity, publication, lift, revenue or Top-1 evidence."
        ),
    }
    unsigned = dict(payload)
    payload["content_sha256"] = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "change_count": len(changes), "critical_before": before["critical_finding_count"], "critical_after": after["critical_finding_count"], "major_after": after["major_finding_count"], "review_admission": payload["blind_review_admission_allowed"], "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0 if payload["blind_review_admission_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
