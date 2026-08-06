from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v2/content-calendar.json"
TEXT = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v2.json"
PLATFORM = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-receipt.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-response-loop-v1/response-learning-contract.json"


def main() -> None:
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    text = json.loads(TEXT.read_text(encoding="utf-8"))
    platform = json.loads(PLATFORM.read_text(encoding="utf-8"))
    if schedule.get("slot_count") != 7 or text.get("candidate", {}).get("asset_count") != 4 or platform.get("accepted_surface_count") != 13:
        raise SystemExit("response loop sources are incomplete")
    payload = seal({
        "schema": "ProofLaunchDeleteOneLineResponseLearningContractV1",
        "campaign_id": schedule["campaign_id"],
        "source_bindings": [
            {"role": "seven_job_schedule", "path": str(SCHEDULE.relative_to(ROOT)), "sha256": sha256_file(SCHEDULE)},
            {"role": "four_asset_copy_system", "path": str(TEXT.relative_to(ROOT)), "sha256": sha256_file(TEXT)},
            {"role": "thirteen_surface_transcreation", "path": str(PLATFORM.relative_to(ROOT)), "sha256": sha256_file(PLATFORM)},
        ],
        "triage_sequence": [
            "Capture only authorized public response text and its exact platform/thread locator.",
            "Separate what the responder observed from what they inferred or requested.",
            "Assign one signal class; preserve uncertainty instead of forcing a positive/negative label.",
            "Reply with the shortest platform-native move that advances the specific disagreement.",
            "Escalate only reproducible rule failures or release decisions to a named editor.",
            "Write no learning until provenance, scope, expiry, contradiction policy and deletion key are complete."
        ],
        "signal_classes": [
            {
                "id": "reproducible_false_rejection",
                "meaning": "A responder identifies a defensible claim the current witness rule rejects, and the failure reproduces on the frozen brief.",
                "priority": "P0_product_rule_review",
                "reply_job": "Acknowledge the located failure, restate it neutrally and ask permission to test the minimal rule change.",
                "learning_eligible": True
            },
            {
                "id": "missing_witness_class",
                "meaning": "A responder supplies a materially different evidence class or decision owner absent from the current docket.",
                "priority": "P1_evidence_model_review",
                "reply_job": "Ask for the smallest non-private example that distinguishes the proposed witness from an existing class.",
                "learning_eligible": True
            },
            {
                "id": "decision_changed",
                "meaning": "A qualified operator locates a real sentence they would delete, downgrade or hold after using the trial.",
                "priority": "P1_activation_evidence",
                "reply_job": "Ask which part of the mechanism changed the release decision; do not solicit confidential copy or a testimonial.",
                "learning_eligible": True
            },
            {
                "id": "mechanism_misread",
                "meaning": "A responder treats NO WITNESS as proof of falsity, automated legal approval or a ban on ambition.",
                "priority": "P0_message_repair",
                "reply_job": "Correct the one mistaken boundary publicly, then repair the originating asset before further distribution.",
                "learning_eligible": True
            },
            {
                "id": "generic_praise_or_vanity",
                "meaning": "Praise, likes, emoji, follower growth or unspecific agreement with no located decision or counterexample.",
                "priority": "P3_no_learning",
                "reply_job": "Use a human thank-you when appropriate; do not turn it into strategy evidence, advocacy or a lead score.",
                "learning_eligible": False
            },
            {
                "id": "unsafe_or_private_request",
                "meaning": "The response includes private campaign material, asks for deceptive proof, evasion, harassment or unauthorized access.",
                "priority": "P0_stop_and_escalate",
                "reply_job": "Do not process or reproduce the material; route to the named safety or account owner when authorized.",
                "learning_eligible": False
            }
        ],
        "platform_reply_cards": [
            {
                "surface": "linkedin",
                "native_move": "Answer the strongest objection in public before posting any product link.",
                "starter": "That is the strongest failure case for the rule so far. The precise question is whether ___ should count as a witness when ___. We have not resolved it.",
                "forbidden_move": "Converting praise into a sales DM or quoting the responder as validation without permission."
            },
            {
                "surface": "reddit",
                "native_move": "Edit the original post with a timestamped rule correction when the community exposes a real defect.",
                "starter": "Builder here. This counterexample changes the test at ___. I can reproduce / cannot yet reproduce it on the frozen brief; here is the unresolved boundary.",
                "forbidden_move": "Deleting criticism, hiding affiliation or replying with a lead-capture link before resolving the objection."
            },
            {
                "surface": "short_video",
                "native_move": "Turn one recurring misread into a visible follow-up experiment, not a defensive talking-head response.",
                "starter": "You heard ‘no witness’ as ‘false forever.’ Watch the same line move from BLOCKED to REVIEW when one complete docket appears.",
                "forbidden_move": "Fabricating a hostile comment, fake stitch or synthetic user reaction."
            },
            {
                "surface": "instagram",
                "native_move": "Pin one clarification and update the saveable diagnostic when the carousel causes a repeated classification error.",
                "starter": "Important boundary: ambition can stay. It must be labeled as ambition until the outcome has a witness.",
                "forbidden_move": "Treating saves as completed trials or using private screenshots without explicit permission."
            },
            {
                "surface": "owned_interactive",
                "native_move": "Use only consented, aggregated failure classes to revise field labels or examples.",
                "starter": "The current gate could not distinguish ___. The next candidate changes only ___ and remains pending human review.",
                "forbidden_move": "Persisting pasted claims, silently training on them or presenting a structural gate as adjudication."
            }
        ],
        "learning_write_gate": {
            "required": [
                "authorized source locator and captured-at time",
                "signal class and exact observed fragment",
                "named human reproducer and decision",
                "scope: audience, platform, format and lifecycle stage",
                "contradiction policy, expiry and exact deletion key",
                "linked source asset and candidate rule change"
            ],
            "minimum_reproducible_examples": 1,
            "automatic_memory_write": False,
            "automatic_strategy_mutation": False,
            "automatic_reply": False,
            "automatic_direct_message": False
        },
        "observation_state": {
            "responses_observed": None,
            "qualified_decision_changes": None,
            "reproducible_false_rejections": None,
            "mechanism_misreads": None,
            "production_effect_observed": False
        },
        "next_cycle": {
            "decision": "await_named_human_release_and_real_observation",
            "allowed_actions": ["hold", "repair_draft", "prepare_source_hidden_variant"],
            "external_activation_allowed": False
        },
        "truth_boundary": "This contract defines how authorized responses could become bounded learning. No response was observed, no reply was sent, no memory was written and no product or market effect was established."
    })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "signal_class_count": len(payload["signal_classes"]), "platform_reply_card_count": len(payload["platform_reply_cards"]), "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
