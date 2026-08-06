# Case Log: Stabilize final-version selection under live embeddings

## Intent
Goal: Ensure explicit file-version roles remain deterministic when BGE semantic scores favor a draft, then pass local and Radeon live championship checks.

Success criteria:
- None

Risk: low

## Context
Files read:
- None

SSOT used:
- None

## Gates
First-principles check:
- None

Assumptions:
- None

Adversarial findings:
- BGE could score Draft above Final; duplicate_paths could also include the selected primary after an override.

Edge cases:
- An explicit draft request must still select Draft even though the default authoritative variant is Final or Signed.

Rejected options:
- None

## Explore Card
Mode: explore
Why: Ensure explicit file-version roles remain deterministic when BGE semantic scores favor a draft, then pass local and Radeon live championship checks.
Acceptance:
- {"criterion": "Prototype can be exercised locally", "evidence": "Local smoke check or direct manual exercise", "prohibited": "Do not present a prototype or fixture as production-ready"}
Boundary:
- No production release or irreversible data change


## Changes
- core.py
- tests/test_core.py
- docs/evidence/radeon-championship-live-20260805.json
- docs/evidence/radeon-fuzzy-holdout-live-20260805.json

## Verification
Required evidence level: 0
Achieved evidence level: 0

Commands:
- python -m unittest discover -s tests -t .
- python scripts/championship_check.py --output championship_results.local.json
- python scripts/adversarial_holdout_check.py --output docs/evidence/fuzzy-holdout-local-after-version-fix.json
- Radeon live championship_check with BGE and Qwen3-14B
- Radeon 320-query live holdout with LoRA Router, BGE embedding, and cross-encoder

Results:
- {passed:true,tests:78/78}
- {passed:true,local_holdout:320/320}
- {passed:true,radeon_championship:true,memory_finder:Customer_Delivery_Risk_Q4_Final.pptx,court_mode:local vLLM}
- {passed:true,radeon_live_holdout:320/320,unsafe_wrong_auto_selections:0,live_stack_passed:true}

## Surprises
- The family override also exposed a duplicate_paths bug that could list the selected primary as its own duplicate.

## Reusable Lessons
- Summary: Stabilized authoritative version selection under embedding bias and passed local plus Radeon live acceptance gates.
- Rank semantic relevance across file families, but resolve explicit authority and lifecycle roles deterministically inside each family.

## Follow-ups
- Add independent owner-reviewed blind queries before public submission.
