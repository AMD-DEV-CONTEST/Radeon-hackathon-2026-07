# GTM production-quality operating contract V1

## Current verdict

Current state: **mechanically_ready**. Promotion is **not allowed**.

| Evidence layer | Observed | Verdict |
|---|---:|---|
| Mechanical lanes | 14/14 | pass |
| Qualified human reviews | 0/80 | not observed |
| Named-product blind PK | 0/130 | not observed |
| Publication receipts | 0 | not observed |
| Authorized production observations | 0 | not observed |

## North Star

This is a three-axis vector, not a content-volume score:
- `time_to_first_human_publishable_asset_hours` — minimize; evidence: qualified_human_release_decision.
- `directly_publishable_rate` — maximize; evidence: qualified_human_review.
- `qualified_conversion_rate` — maximize; evidence: authorized_production_observation.

## Monotonic gates

- **G0_contract:** PASS.
- **G1_professional_editor:** BLOCKED.
- **G2_same_brief_blind_pk:** BLOCKED.
- **G3_production_effect:** BLOCKED.

## First-priority capability gaps

- **T014_product_evidence_extractor:** BLOCKED — [{"claim": "claim-owner-001", "reason": "missing_approved_by"}, {"claim": "claim-owner-001", "reason": "rights_status_not_releasable"}, {"claim": "claim-owner-001", "reason": "release_scope_is_draft_only"}]
- **T021_natural_breakout_admission:** PASS — Candidate-level within-source baselines, freshness, public counters, paid-distribution disclosures and capture hashes are sealed. Candidates remain descriptive and require named-human abstraction review.
- **T033_single_growth_tension:** PASS — passed
- **T041_platform_copy_bible:** PASS — passed

## Blocking-defect classes

- `unsupported_or_false_claim`
- `rights_or_provenance_violation`
- `platform_or_audience_mismatch`
- `wrong_or_broken_call_to_action`
- `brand_product_or_identity_drift`
- `unreadable_or_inaccessible_delivery`

## Next actions

1. Bind a named claim approver and public release scope to the current owner-attested product claim.
2. Human-review the admitted relative-breakout candidates before any mechanism abstraction or memory write.
3. Complete five qualified human reviews on exact artifact hashes.
4. Run source-hidden same-Brief comparison against a rights-cleared named baseline.
5. Manually publish one approved B2B and one approved B2C experiment with receipts.
6. Import authorized aggregate observations and keep causal status separate.

## Truth boundary

The current run is mechanically reviewable only. No professional-editor pass, named-product win, public release, production effect, causal lift, 4A parity or Top-1 standing is claimed.
