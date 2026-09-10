# Formal L2/L3 Study Kit

This kit is the operator handoff for the first formally supportable Production
cell:

```text
{style_pack_id, structure_only, xhs_grid, production}
```

It does not contain approved labels or an approval package. Template values use
`${...}` markers and are deliberately rejected by the workspace CLI until every
marker is replaced with real, canonical evidence.

## Claims Under Test

| Layer | Unit | Metric | Direction | Permitted claim |
|---|---|---|---|---|
| L2 | item | `reference_style_statistics_similarity` | `>=` | reference-style fidelity |
| L2 | complete cohort | `batch_style_consistency` | `<=` | within-cohort style consistency |
| L3 | item | `structure_edge_similarity` | `>=` | spatial structure preservation only |

L2 does not claim that style statistics are content-independent. L3 does not
claim face identity, subject identity, SKU identity, or product-instance
preservation. ControlNet remains a generation control and is not evidence for
any of these metrics.

## Roles

- Raters: at least two people label independently while metric scores and split
  names are hidden.
- Adjudicator: resolves disagreements without seeing metric scores.
- Label approver: signs `HUMAN_LABELS` only after checking rater independence,
  provenance, split isolation, and adjudication records.
- Reveal approver: signs `REVEAL_TEST` only after `VALIDATION_PASSED` is frozen.
- Production approver: `guan`; signs metric and profile approvals only after a
  held-out reveal reports `TEST_PASSED_PENDING_PRODUCTION_APPROVAL`.

The same person must not act as both a rater and the label approver for the same
study. The label approver and reveal approver should also be different people.

## Sample Plan

For each metric, use at least 40 positive and 40 negative independent isolation
groups in each calibration, validation, and test split. For the batch metric,
one sample is one complete ordered four-member cohort; counts are cohorts, not
images. A smaller pilot may exercise tooling but must remain `DRAFT`.

Freeze family hashes and assign splits before scores or labels are inspected.
No candidate, source family, reference family, or cohort member may cross a
split. Keep test observations sealed until reveal authorization.

## Workspace

Create one owner-only directory for each metric, copy `target_cell.json` into
it, and use these exact filenames:

```text
target_cell.json
study_plan.json
annotation_protocol.json
sample_manifest.json
calibration_observations.json
validation_observations.json
test_commitment.json
label_approval_receipt.json
sealed_test_observations.json
reveal_receipt.json
metric_production_approval.json
```

Directories must be mode `0700`; JSON files must be mode `0600`.

## Approval Sequence

1. Freeze the target cell, implementation pins, assets, provenance and split
   assignments.
2. Collect independent blinded labels and preserve raw annotation records.
3. Seal the test-observation hash and exact ordered test sample bindings.
4. Have the label approver issue the `HUMAN_LABELS` receipt.
5. Prepare calibration and validation evidence without opening test labels:

   ```bash
   PYTHONPATH="$PWD/src" python -m \
     specstyle.calibration.formal_study_workspace prepare \
     --workspace /private/studies/<metric-id>
   ```

6. Proceed only when the output is `VALIDATION_PASSED`. Have the independent
   reveal approver issue `REVEAL_TEST`, then run:

   ```bash
   PYTHONPATH="$PWD/src" python -m \
     specstyle.calibration.formal_study_workspace reveal \
     --workspace /private/studies/<metric-id>
   ```

7. Proceed only when the output is
   `TEST_PASSED_PENDING_PRODUCTION_APPROVAL`. `guan` then issues a separate
   metric Production approval and validates the complete chain:

   ```bash
   PYTHONPATH="$PWD/src" python -m \
     specstyle.calibration.formal_study_workspace validate \
     --workspace /private/studies/<metric-id>
   ```

8. Issue one L2 profile approval containing exactly the two L2 metric approval
   hashes, and a separate L3 profile approval containing exactly the structure
   metric approval hash. Do not combine these envelopes. Put
   `target_cell.json`, `threshold_profile_pin.json`, and
   `profile_approval.json` in each profile workspace, then validate them:

   ```bash
   PYTHONPATH="$PWD/src" python -m \
     specstyle.calibration.formal_study_workspace validate-profile \
     --workspace /private/studies/profile-l2 \
     --metric-workspace /private/studies/batch_style_consistency \
     --metric-workspace /private/studies/reference_style_statistics_similarity

   PYTHONPATH="$PWD/src" python -m \
     specstyle.calibration.formal_study_workspace validate-profile \
     --workspace /private/studies/profile-l3 \
     --metric-workspace /private/studies/structure_edge_similarity
   ```
9. Build context v4 from those immutable objects, run CPU validation, deploy the
   same content-addressed package to Radeon, and publish one unselected atomic
   Production cohort. Record the commit, environment, target-cell hash, both
   profile approval hashes, cohort manifest hash, and final bundle hash.

Any post-reveal threshold, pin, sample, label, or membership change starts a new
study and target-cell lineage. It is never patched into an approved chain.

## Licensing

The project does not declare a repository code license in this submission.
That is separate from media provenance and model-weight approval. Complete
`PROVENANCE_REGISTER.csv` for every study asset; blank or unresolved license,
consent, or authorization fields block sharing and Production approval.
