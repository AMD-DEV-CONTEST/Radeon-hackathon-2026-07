# Industry GTM operating profile V1

## Outcome

ProofLaunch no longer treats `industry` as descriptive copy. A deterministic,
evidence-bound compiler turns the operator's industry string into one of 18
specific execution archetypes or a safe B2B/B2C fallback. The profile becomes
`industry-gtm-profile.json` inside every production pack and is visible in the
release preview before approval.

## What changes by industry

Each archetype defines:

1. buying motion and decision unit;
2. the conversion unit that may be counted;
3. an ordered evidence ladder and proof gate;
4. a zero-media-budget earned-growth engine;
5. viable owned, earned, community and partner surfaces;
6. unit economics and post-release feedback signals;
7. creative, rights, privacy and representation constraints;
8. specialist roles for regulated categories.

Lifecycle and budget remain orthogonal. Pre-PMF prioritizes falsifiable problem
learning; launch proves a narrow wedge; growth optimizes repeatability and
contribution margin; mature work protects retention and incrementality. Zero
budget mechanically excludes media spend, small budget permits bounded manual
experiments, and scaled budget still requires holdout and contribution-margin
gates before paid amplification.

## Fail-closed behavior

- Unknown or ambiguous input falls back to `general_b2b` or `general_b2c` and
  requires named human classification confirmation during release review.
- A known industry used with an incompatible business model is retained as a
  hypothesis but requires the same human confirmation.
- Financial services, healthcare and real estate cannot compile under
  `standard` risk. The operator must declare `high_regulation`, supply a named
  specialist approval, and preserve the unchanged wording through release.
- No profile can publish, allocate budget, or claim causal revenue.
- Every profile binds the campaign, strategy digest and its own canonical
  SHA-256; tampering fails verification.

## Frozen coverage

`scripts/compile_gtm_industry_profile_matrix.py` compiles every specific
archetype across both B2B and B2C, all four lifecycle stages and all three
budget tiers. The two generic fallbacks are compiled in their matching market
mode. The evidence file records every case, differentiation signature and
safety flag rather than extrapolating from a few examples.

## Truth boundary

The compiler and matrix prove executable differentiation over synthetic
contracts. They do not prove universal industry knowledge, creative quality,
customer preference, production readiness, causal lift, revenue, or market
leadership. Those require named domain review, blind preference evidence,
rights-cleared production outputs and observed business results.
