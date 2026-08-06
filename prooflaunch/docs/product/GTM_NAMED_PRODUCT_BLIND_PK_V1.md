# Named-product last-mile blind PK V1

## Purpose

This protocol connects the 130 authorized named-product capture slots to a real same-brief human preference result. It never pairs a capture automatically. A named operator must first prepare source-hidden review artifacts and attest that identity removal preserved meaning and quality.

The benchmark pool contains 13 categories and 10 named products per category. A row is complete only after five distinct qualified reviewers return hash-valid judgments. A category aligns only when the ProofLaunch challenger passes all ten product rows. Portfolio alignment requires 130/130 passes.

## Graph

1. Capture a named-product output through the rights-attested baseline kit.
2. Import the capture into the immutable baseline registry.
3. Compile all sealed challenger deliverables into one self-contained, source-hidden review dossier and run category-specific material admission.
4. Repair every missing-material finding; a blocked challenger cannot enter pair preparation.
5. Prepare one source-hidden baseline dossier and the admitted challenger dossier.
6. Create a named preparation receipt with all four attestations.
7. Explicitly compile five randomized and counterbalanced reviewer kits.
8. Give each qualified reviewer only their assigned ZIP; never share `private/mapping.json`.
9. Import five returned review JSON files immutably.
10. Aggregate the product row, then compile the 13-category/130-product portfolio truth state.
11. Repair and rerun the same frozen brief for any failed row.

## Loop

Every reviewer records:

- stronger final delivery: left, right, or abstain;
- a mandatory left, right, or tie decision for every frozen category quality axis;
- direct publishability for both sides;
- major-rework requirement for both sides;
- blocking defect side and located explanation;
- a located independent rationale.

The candidate passes a product row only when all predeclared checks pass: five distinct reviewers, preference rate at least 75%, Wilson 95% lower bound above 50%, direct-publishability rate at least 95%, major-rework rate at most 5%, zero candidate blocking defects, and no net loss on any declared quality axis. With five reviewers, the combined preference and Wilson gates require a unanimous 5–0 candidate preference.

## Harness

- The original captured baseline, sealed challenger, both review artifacts, frozen brief, operator, preparation receipt, every task and every human review are SHA-256 bound.
- Review media must remain directly inspectable and cannot change media family during source hiding.
- Randomization is cryptographically generated, counterbalanced 2/3 across five reviewers, and its seed is not persisted.
- Public packets exclude product/provider roles; private mapping is owner-only. Intrinsic style can still be recognizable, so the protocol truthfully calls this `source-hidden`, not guaranteed identity-blind.
- Reviewer identity cannot drift or occupy multiple slots.
- Review and aggregate records are immutable and idempotent.
- Model judges cannot fill human reviews or promote a result.
- Multi-artifact executions are carried in self-contained HTML/PDF dossiers; a single attractive frame or thin JSON cannot substitute for the frozen task.
- Category-specific admission blocks missing memory lifecycle evidence, decision lineage, holdout/revenue reconciliation, technical SEO evidence, executed Agent recovery, advertising variants, or lifecycle observation.
- Runtime switch, strategy mutation, publishing, sending, and spend remain disabled.

## Operator commands

Compile and audit the 13 complete challenger dossiers first:

```bash
PYTHONPATH=src .venv/bin/python scripts/compile_gtm_named_product_challenger_dossiers.py
```

Only categories with `named_product_pk_preparation_admitted=true` may proceed. A multi-asset baseline should be exported from the authorized product as a self-contained HTML/PDF dossier so both sides expose the full same-brief output.

Create the mandatory preparation receipt after the four human checks:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_gtm_named_product_pk_pair.py \
  --capture-slot-id pk-0123456789abcdef \
  --baseline-review-artifact evidence/operator-input/baseline-anonymous.json \
  --candidate-review-artifact artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/content_scheduling_operations.html \
  --operator-id qualified-operator-01 \
  --output evidence/operator-input/preparation.json \
  --attest-same-frozen-brief-outputs \
  --attest-provider-and-candidate-identity-removed-or-intrinsically-absent \
  --attest-meaning-and-quality-preserved \
  --attest-review-assets-authorized-to-retain
```

Compile the five source-hidden review kits:

```bash
PYTHONPATH=src .venv/bin/python scripts/compile_gtm_named_product_blind_pk.py \
  --capture-slot-id pk-0123456789abcdef \
  --preparation evidence/operator-input/preparation.json \
  --baseline-review-artifact evidence/operator-input/baseline-anonymous.json \
  --candidate-review-artifact artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/content_scheduling_operations.html \
  --output-dir evidence/operator-input/named-product-packet
```

Import each returned human review into a slot-bound store:

```bash
PYTHONPATH=src .venv/bin/python scripts/import_gtm_named_product_blind_review.py \
  --packet-dir evidence/operator-input/named-product-packet \
  --review evidence/operator-input/review-01.json \
  --store-dir evidence/v10/named-product-pk-reviews-v1/pk-0123456789abcdef
```

Compile portfolio truth:

```bash
PYTHONPATH=src .venv/bin/python scripts/compile_gtm_named_product_pk_portfolio.py
```

## Current truth state

All 13 self-contained challenger dossiers now pass material admission. Seven initially blocked lanes were repaired with explicit synthetic-mechanics artifacts: memory conflict/tenant/deletion execution, lineage/uncertainty/scenario decision memo, holdout/revenue analytics contract, technical SEO execution, forced-failure/approval-denial Agent trace, three-route inactive advertising system and lifecycle observation/next-cycle dossier. These repairs establish review-material completeness only. The checked-in portfolio still has zero authorized product-row aggregates: 0/130 completed, 0/130 candidate wins and 0/13 effect-aligned categories. No 4A, Top-product, publication, causal lift, or revenue claim has been earned.
