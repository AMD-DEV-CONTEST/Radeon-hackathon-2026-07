# GTM Platform Craft Blind Review V1

## Purpose

This protocol evaluates the editorial and platform craft of the thirteen real B2B
ProofLaunch drafts that already passed deterministic publication checks. It does
not compare ProofLaunch with any named product. The separate 130-row named-product
PK remains at its observed state until authorized baselines and human votes exist.

## Frozen scope

- 13 surfaces: LinkedIn, TikTok, Reddit, YouTube, Instagram, X, Google Search,
  Bing Search, ChatGPT, Claude, Gemini, Perplexity and Copilot.
- 5 distinct human reviewers; each reviewer independently evaluates all 13 artifacts.
- 65 required, hash-bound review rows. Missing rows are never imputed.
- Provider, model, private source mapping and other reviewers' decisions stay hidden.
- The B2C artifacts remain synthetic benchmarks and are not admitted to publication review.

## Per-artifact rubric

Each reviewer scores `1–5` on strategic fit, platform nativeness, hook strength,
editorial craft, proof discipline, participation mechanism and direct publishability.
They must also record direct publishability, major rework, any blocking defect and a
located written rationale.

An artifact passes only when all five reviewers are present, its overall dimension
mean is at least `4.7`, every dimension mean is at least `4.5`, direct publishability
is `5/5`, major rework is `0/5`, and blocking defects are `0/5`.

## Execution

```bash
.venv/bin/python scripts/export_gtm_platform_craft_review_kit.py
```

Give each reviewer only their assigned `reviewer-XX.html` from the public ZIP. Keep
`private/platform-craft-review-private.json` private. After five JSONL files return:

```bash
.venv/bin/python scripts/import_gtm_platform_craft_reviews.py \
  --public-packet artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/public/platform-craft-review-public.json \
  --private-mapping artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/private/platform-craft-review-private.json \
  --review reviewer-01.jsonl --review reviewer-02.jsonl --review reviewer-03.jsonl \
  --review reviewer-04.jsonl --review reviewer-05.jsonl \
  --output evidence/v10/gtm-platform-craft-review-aggregate-v1.json
```

## Claim boundary

Even a `13/13` craft result proves only these human judgments for these drafts. It
does not prove named-product preference, publication outcome, organic breakout,
conversion, causal revenue, 4A quality or Top-1 status. No result authorizes automatic
model switching, strategy mutation, publication, send or spend.

