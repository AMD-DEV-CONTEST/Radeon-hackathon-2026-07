# GTM Human Judge Calibration V1

This protocol closes a specific production-risk gap: an LLM judge may not influence promotion until its frozen binary decisions are calibrated against genuinely independent human labels. It does not claim 4A preference, causal lift, revenue, or model quality.

## Frozen protocol

- Supply 100–500 case-distinct, hash-bound artifacts. One artifact cannot be counted twice.
- Include at least 40 sealed positive and 40 sealed negative judge predictions.
- Assign exactly three of five invited reviewer slots to every case. The public packet exposes neither the judge prediction nor provider/model identity.
- Require each human to attest that they reviewed independently and did not see the judge prediction, private mapping, or another label.
- Persist one immutable, digest-bound review per task. A replay must be byte-equivalent; identity drift and pseudonym reuse across reviewer slots fail closed.
- Use the three-person majority as the case gold label. Record disagreements for named-human adjudication instead of silently erasing them.
- Compute TPR and TNR against all distinct case gold labels. Both must be strictly greater than 0.80 and at least 100 cases must be complete.
- Require all five reviewer identities, at least 20 leave-two-out comparable cases per reviewer, reviewer agreement of at least 0.70, and at least 0.80 full-human-consensus rate.
- Completing calibration never auto-promotes creative, mutates strategy, spends media budget, or publishes externally.

## Real queue creation

Prepare a private JSON array whose rows contain `case_id`, `artifact_sha256`, `evaluation_prompt`, `evidence_locator`, `failure_slice`, and boolean `judge_prediction`. The artifact locator must resolve for invited reviewers through the separately governed evidence system.

Set the assignment seed outside shell history and compile into an empty owner-controlled directory:

```bash
export PROOFLAUNCH_JUDGE_CALIBRATION_SEED='externally-managed-secret-at-least-16-chars'
PYTHONPATH=src .venv/bin/python scripts/compile_gtm_judge_calibration.py \
  --cases /owner-controlled/real-cases.json \
  --output-dir .prooflaunch-runtime/judge-calibration
```

Configure five invitation tokens through `PROOFLAUNCH_REVIEWER_TOKENS_JSON`, then start the local API. The available control-plane routes are:

- `GET /v1/judge-calibration/status`
- `GET /v1/judge-calibration/tasks?slot=N` with `X-ProofLaunch-Reviewer-Token`
- `POST /v1/judge-calibration/reviews` with the same invitation token

The same-origin browser console is available at
`http://127.0.0.1:8765/control/training`: select **Judge calibration**, enter one
assigned slot token and a stable named-human pseudonym, then label only the
cases returned for that slot. Each card displays the frozen criterion, artifact
digest, evidence locator, PASS/FAIL controls, reason field, and independence
attestation. It does not download or expose the sealed model prediction.

There is intentionally no public private-mapping route and no early aggregate endpoint. Status exposes only counts, completion, calibration state, and a completed aggregate digest.

For the frozen synthetic-representative governance queue used by the current local
product proof, run the digest-pinned localhost model builder instead. It performs
100 independent calls, compiles negative Boolean evidence into monotonic checks,
uses a closed JSON schema, and creates the empty 300-label packet atomically:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_local_gtm_judge_queue.py
```

If `PROOFLAUNCH_JUDGE_CALIBRATION_SEED` is absent, this command generates a
cryptographically strong ephemeral assignment seed. Only its SHA-256 digest is
stored; the raw seed is neither printed nor persisted. The frozen assignments in
the resulting packet are authoritative.

## Current evidence boundary

The sealed queue now contains 100 real digest-pinned localhost model calls over 50
positive and 50 single-failure governance cases. It covers 20 industries, B2B and
B2C, four lifecycle stages, three budget tiers, and both standard and regulated
risk. The public packet contains 100 distinct cases and exactly 300 empty human
review tasks; it exposes neither exact model predictions nor provider identity.

This is a synthetic-representative governance calibration queue, not creative
preference or production-effect evidence. It still contains zero qualifying human
calibration labels, no TPR/TNR has been computed, PR-11 remains a gap, and
judge-based promotion remains disabled. The authoritative status receipt is
`evidence/v10/local-judge-calibration-queue-status.json`.
