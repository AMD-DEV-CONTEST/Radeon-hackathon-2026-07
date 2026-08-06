# GTM unified offline human review V2

## Outcome

V2 closes the evidence gap between an identity-hidden comparison page and an auditable last-mile recommendation. Five named qualified reviewers each receive one offline page containing 16 same-brief pairs: 11 text/decision pairs, three audio pairs, one 4K video pair, and one three-format visual-system pair. The complete protocol contains 80 human judgments across 14 delivery lanes.

This protocol compares the current ProofLaunch system with sealed internal challengers. It does **not** yet compare against the 130 named leading products and therefore cannot prove Top-product parity, 4A quality, causal lift, publication, or revenue.

## Graph

1. Export the V2 kit with `scripts/export_gtm_unified_offline_review_kit.py`.
2. Assign exactly one `reviewer-XX.html` page to each qualified independent reviewer.
3. Each reviewer evaluates all 16 pairs and returns one 15-row JSONL file plus one visual JSON file.
4. Import each bundle with `scripts/import_gtm_unified_offline_reviews.py`.
5. Aggregate only when all five immutable bundles are present.
6. Repair and rerun every failed lane against the same frozen brief.

## Loop

Within each pair the reviewer must choose a preferred side, assess each side's direct publishability and major-rework status, identify any blocking production defect, and provide a located rationale. Every row is bound to the pair SHA-256 and receives its own content SHA-256. A reviewer pseudonym must remain stable across all 16 judgments and cannot occupy another slot.

## Harness

The importer enforces exact schemas, 15 unique generic pairs, the assigned visual task, timestamps with timezones, attestation text, pair digests, review digests, reviewer identity consistency, immutable/idempotent storage, and exact private mapping coverage. It rejects partial aggregation, digest drift, task substitution, undisclosed identity drift, and contradictory publishable/major-rework flags.

For every comparison the candidate must satisfy all predeclared conditions:

- five qualified independent reviewers;
- preference rate at least 75%;
- 95% Wilson lower bound strictly above 50%;
- direct-publishability rate at least 95%;
- major-rework rate at most 5%;
- zero blocking defects.

With five reviewers, the combined preference and Wilson requirements effectively demand a unanimous 5–0 preference. Portfolio recommendation eligibility requires all 16 pairs and all 14 lanes to pass. Even then, the aggregate is recommendation-only: runtime switch, strategy mutation, publish, send, and spend remain disabled.

## Current truth state

- Review tasks executable: 80/80.
- Human observations submitted: 0/80.
- Internal pair results: unavailable until all five reviewer bundles are imported.
- Named-product baseline captures: 0/130.
- 4A or Top-product parity: unproven.
- Radeon local inference: unobserved.
