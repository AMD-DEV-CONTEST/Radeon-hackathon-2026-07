# Frontier GTM Employee — tomorrow-run contract

This is the cloud-frontier production path. It never falls back to MLX, Ollama or another local text model.

## What one run does

1. Strategy board: audience decision, category default, non-consensus bet, recent-signal questions and zero-budget wedge.
2. Creative board: exactly three mutually exclusive campaign platforms.
3. Executive jury: reject cliches, weak platform behavior, fake participation and media-dependent ideas.
4. Integrated production: platform-native copy, image system, 15–30 second video, SEO/GEO, zero-budget activation, measurement and claims.
5. Independent release audit.
6. If required, one bounded repair and a mandatory second audit.

Every call receives the complete 13-category / 130-named-product capability stress pack. Named products supply mechanisms and quality questions only; their expression is never copied. Human-approved learning memory is read as a prior and cannot be mutated during the run.

## Required inputs

- Copy `config/frontier-gtm-brief.template.json` and replace every placeholder.
- Put a reviewed OpenAI-compatible route in `config/frontier-gtm-provider.example.json`.
- Export the matching API key only in the process environment. Never save it in the project.
- Keep the existing 130-product distillation and human-approved memory attached.
- Supply public, brief-relevant feed/post/video seed URLs to the bounded OSS collector. The runner retains raw bytes only in the isolated evidence layer, rejects protected access, and emits a 90–180 day non-copying signal pack.

## Recent organic signal pack

```bash
PYTHONPATH=src:. .venv/bin/python -B scripts/run_open_source_social_collection.py \
  --request config/gtm-recent-public-signal-collection-v1.json \
  --output-dir evidence/v10/gtm-recent-public-signal-collection-v2-live \
  --execute

PYTHONPATH=src:. .venv/bin/python -B scripts/run_gtm_recent_organic_signal_pack.py \
  --collection-dir evidence/v10/gtm-recent-public-signal-collection-v2-live \
  --output evidence/v10/gtm-recent-organic-signal-pack-v2.json
```

The compiler fails when no dated item falls inside 180 days. It passes only public counters, freshness and abstract content structures such as evidence-led, data-hook, comparison, question, portable-utility and contrarian-correction patterns. Source expression never enters the Agent prompt or learning memory.

The production endpoint prefers `evidence/v10/gtm-recent-organic-signal-pack-v3.json`, a verified merge of feed discovery and public-video counter packs, and falls back to V2 only when V3 is absent.

The 2026-08-04 V3 execution receipt contains 8 completed sources and 179 dated public items: 132 within 90 days and 179 within 180 days. Six video sources provide 119 same-source-normalized items and 32 descriptive relative-attention candidates. One unavailable item remains an explicit handoff. No source expression, public item identifier, media file or automatic memory write is present in the strategy-facing pack. These figures establish the first observed coverage only; the global coverage receipt remains incomplete until its frozen quotas pass.

### Global organic-signal sampling standard

The frontier agent does not treat a handful of large US accounts as a universal market prior. The frozen standard at `evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json` defines 140 B2B/B2C segment-market cells and 168 platform-market lanes across North America, UK/Ireland, English-visible Europe, South Africa, Singapore, Hong Kong and Australia/New Zealand. It requires small, mid-market and enterprise/mass-brand sources, four lifecycle states and 12 public or operator-authorized platform routes.

Short-term breakout is descriptive and account-relative: an item is compared with the median of the same source inside the 90/180-day window. Absolute cross-account ranking is forbidden. Public signals can generate a hypothesis only. Durable learning requires an observed result bound to the exact strategy plus a named-human approval and evidence SHA-256; the public collector's automatic memory-write count is permanently zero.

Compile an auditable coverage receipt instead of claiming that a target matrix has been collected:

```bash
PYTHONPATH=src:. .venv/bin/python -B scripts/compile_global_organic_signal_coverage.py \
  --standard evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json \
  --signal-pack evidence/v10/gtm-recent-organic-signal-pack-v2.json \
  --output evidence/v10/gtm-global-organic-signal-coverage-v1.json
```

## Command

```bash
FRONTIER_GTM_API_KEY='redacted-runtime-value' \
PYTHONPATH=src:. .venv/bin/python -B scripts/run_frontier_gtm_agent.py \
  --brief config/frontier-gtm-brief.template.json \
  --provider-config config/frontier-gtm-provider.example.json \
  --named-capability-distillation evidence/v10/gtm-named-capability-distillation-v1.json \
  --human-capability-kernel evidence/v10/gtm-human-capability-kernel-v2.json \
  --learning-memory evidence/v10/gtm-genome-learning-memory-v1.json \
  --signal-pack evidence/v10/gtm-recent-organic-signal-pack-v2.json \
  --output artifacts/frontier-gtm-runs/run-001.json
```

The command fails closed when no cloud credential is present. A model pass is not a named-product win or market effect. Only a final audit pass makes the pack ready for named human release review; publishing, sending and spend remain disabled.

## Current finished demonstration

Open `artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/index.html`. Switch between B2B and B2C to inspect the strategy, frontier key visual, platform-native work, activation wave, distribution, measurement and real PK packets.
