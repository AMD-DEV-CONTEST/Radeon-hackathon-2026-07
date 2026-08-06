# Campaign Pack Visual Blind Review V1

## Decision being measured

This gate asks one bounded question: when candidate identity, provider, model,
private side mapping, and other reviewers' choices are hidden, do five invited
humans prefer the V6 three-format campaign system over the mechanically ready V5
baseline? It measures comparative human preference for this frozen pair. It does
not measure causal lift, revenue, universal 4A quality, Top-1 standing, Radeon
execution, or fitness for external publication.

## Frozen evaluation dataset and baseline

- Baseline: `delivery-v5`, content SHA-256
  `bd3f0e2d5f57782f243e2e30b06855d0fe1c4b306ff0c3dd32c42649afed919f`.
- Challenger: `delivery-v6`, content SHA-256
  `70beadc46880aae6569cf759e829f65c12c01c33d87d9e45760593086b3b21c1`.
- Each side contains the exact hash-bound 4K hero, 1080×1350 social, and
  1920×1080 landing assets from its campaign manifest.
- Five reviewer tasks compare the same campaign systems. Side order is
  deterministically counterbalanced 3/2 and every slot receives different
  opaque asset aliases.
- Public assignment and private deblinding packets are separately sealed; the
  public packet commits to the private mapping without disclosing it.

The executable bundle is in
`artifacts/campaign-pack-visual-blind-review-v1/`. The private mapping is mode
`0600`; invitation tokens are not stored in the bundle.

## Offline reviewer delivery

After authenticating one reviewer slot, the Training surface can download an
identity-hidden ZIP from
`GET /v1/campaign-pack-blind-review/offline-kit?slot={1..5}`. Each deterministic
kit contains:

- one offline `review.html` form;
- the slot's public task and exact task/pair hashes;
- six opaque, hash-bound PNG files covering both sides and three formats;
- a sealed manifest stating that no invitation token, candidate identity,
  provider identity, private mapping, submission channel, or publication
  authority is included.

The human opens `review.html`, works without network access, and downloads an
exact `ProofLaunchCampaignPackVisualHumanReviewV1` JSON file. The JSON has a
browser-computed SHA-256 over its canonical content. The operator then uses the
same invitation-bound product surface to submit the returned JSON; the server
rechecks the token, slot, task, pair, attestation, timestamp, fields, and digest
before writing an immutable mode-`0600` record. This permits independent review
without exposing the local production API or embedding credentials in a shared
file.

When all five invitation tokens are already configured locally, an operator can
prepare the five shareable kits at once without printing or copying any token:

```bash
.venv/bin/python scripts/export_campaign_pack_offline_review_kits.py
```

The generated ZIPs and their manifest stay under the owner-only
`.prooflaunch-secrets/campaign-pack-offline-kits/` boundary, which is excluded
from Radeon and submission archives.

## Rubric

Each reviewer must choose an overall winner; no overall tie is allowed. They
also choose LEFT, RIGHT, or TIE for every frozen dimension:

1. `concept_originality`: a distinctive campaign idea rather than a generic
   technology or growth visual.
2. `information_hierarchy`: the eye reaches brand, promise, proof, and action
   in a clear intentional order.
3. `evidence_credibility`: proof is specific, legible, restrained, and
   trustworthy rather than decorative.
4. `cross_format_extensibility`: the idea remains coherent across hero, social,
   and landing formats without appearing mechanically cropped.
5. `action_motivation`: the system creates an earned reason to inspect,
   challenge, or act without unsupported hype.

Reviewers must also identify a blocking defect on NONE, LEFT, RIGHT, or BOTH.
A blocking defect is a located factual, evidence, legibility, brand, safety, or
production defect severe enough to stop release. Every review includes an
independence attestation, stable pseudonym, timezone-bearing timestamp,
rationale, task/pair hashes, and its own content digest.

## Predeclared pass and regression gates

A candidate can become recommendation-eligible only when all conditions hold:

- all five independent invitation-bound reviews are present;
- at least four of five overall votes select the candidate;
- the candidate has zero blocking-defect votes;
- the candidate loses none of the five rubric dimensions to the other side.

A passing aggregate is advisory only. Automatic runtime switching, automatic
publishing, product admission, spend, and 4A/effect claims remain disabled. A
dimension loss or any blocking defect on the recommended candidate is a
regression and closes the gate even if overall votes reach 4/5.

## Deterministic checks and human evaluation

Deterministic tests verify manifest hashes, exact asset bytes and dimensions,
public/private commitments, balanced side placement, identity hiding, invitation
authorization, immutable/idempotent review storage, complete-only deblinding,
and fail-closed aggregation. These checks establish protocol integrity, not
visual quality.

Human evaluation supplies the visual-preference evidence. Five actual people
must inspect all three formats at usable size and submit independently. Model or
assistant labels cannot fill empty slots.

## Current evidence status

The protocol and product surface are runnable. Current observed human reviews:
`0 / 5`. Therefore human preference, promotion recommendation, product
admission, 4A preference, and production effect are all unobserved or false.
