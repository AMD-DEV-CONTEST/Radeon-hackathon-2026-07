# ProofLaunch — Multimodal GTM Studio

**Competition:** AMD Radeon Hackathon 2026-07  
**Track:** Track 1 — Development of Multimodal Content Creation Tools  
**Team:** Banyan  
**Application:** ProofLaunch  
**Direction:** Evidence-grounded multimodal campaign creation

## One sentence

ProofLaunch turns approved product evidence into a coherent GTM campaign—
strategy, copy, SEO/GEO, schedule, 4K image, audio and 4K video—then stops at an
independent human release boundary with a hash-verifiable evidence receipt.

## Evaluator quick start

From the repository root:

```bash
.venv/bin/python demos/run_track1_demo.py
```

The command performs a deterministic local replay using sealed assets; it does
not download a model or call a cloud API. Expected terminal fields include:

```json
{
  "status": "local_governed_replay_passed",
  "registered_deliverables": 10,
  "radeon_execution_observed": false,
  "named_human_quality_count": 0,
  "production_effect_attributed_count": 0
}
```

Then open the finished product website at `web/index.html`, start at
`/control/frontier-gtm`, and inspect the replay:

- `artifacts/judge-track1-replay-v1/demo-receipt.json`
- `artifacts/judge-track1-replay-v1/gtm-cockpit.json`
- `evidence/v10/local-campaign-pack-v1/delivery-v6/`

The sealed canonical receipt remains at
`artifacts/run-bound-multimodal-demo-v1/demo-receipt.json`; evaluator replays do
not overwrite it.

## Actual deliverables in the sealed demonstration

The run registers ten exact, campaign-bound outputs:

1. GTM strategy
2. content calendar
3. channel-native copy
4. analytics plan
5. GEO answer pack
6. SEO question map
7. Graph/Loop/Harness execution contract
8. channel and advertising portfolio
9. mastered audio
10. 4K campaign film

The media pack also includes a 3840×2160 hero image, a 1080×1350 social image,
a 1920×1080 landing image and captions. Every file is bound by SHA-256 in the
campaign manifest.

## Architecture

```text
Rights-bound brief
  → Evidence and claim ledger
  → Adaptive capability graph
  → Bounded specialist loops
  → Multimodal production
  → Independent audit and repair
  → Human release gate
  → Immutable delivery bundle
  → Observation
  → Human-approved learning only
```

The model may draft and repair within a node. It cannot alter the business
graph, cross tenant boundaries, publish, send, spend, or promote itself. Those
permissions live in code and require an authenticated, content-bound approval.

## Current verification

| Gate | Result | Evidence |
|---|---:|---|
| Product-critical Python tests | 827/827 | `evidence/v10/aug3-product-readiness.json` |
| UI tests | 17/17 | `web/judge-manifest.json` |
| Route validation | 10/10 | `evidence/v10/aug3-product-readiness.json` |
| Web product build | 46 routes / 60 API contracts | same receipt |
| Final integrity locks | 4/4 | `config/cortex_x_v10_final_locks.json` |
| Desktop + mobile horizontal overflow | none observed | Field Journal V5 visual QA |
| Run-bound workflow | 10 deliverables registered | `artifacts/run-bound-multimodal-demo-v1/demo-receipt.json` |
| Last-mile lanes | 14/14 mechanically ready | `evidence/v10/gtm-last-mile-production-quality-v1.json` |
| Production-quality ladder | `mechanically_ready`; G1/G2/G3 blocked | `evidence/v10/gtm-production-quality-current-v1.json` |
| Platform Copy Bible | 8/8 sealed and generation-bound | `config/gtm_platform_copy_bible_v1.json` |
| Named-product challenger dossiers | 13/13 admitted | `artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json` |
| Production-readiness controls | 9 pass / 3 gaps | `evidence/v10/agentic-product-readiness-audit.json` |
| External publish/send/spend | 0 | receipts and Harness |

Mechanical readiness is not human preference or production effect. The 130
named-product PK rows, five-human review queues and external effect gates remain
at zero until real evidence is supplied.

## AMD Radeon / ROCm path

The project contains a checksum-first Radeon handoff, live ROCm preflight,
single-residency model lifecycle and Radeon notebooks. The final recording must
show real hardware identity, ROCm/HIP, the exact model revision, a real inference,
latency/VRAM and the resulting asset. Follow `RADEON_FINAL_CAPTURE.md`.

**Truth boundary:** the current local run receipt records Apple/local and
provider-managed source execution; `radeon_execution_observed` is false. The
submission remains blocked until the live Radeon evidence and Demo Video are
captured; the official guidance recommends a 3–5 minute duration. No Mac or
cloud run is presented as Radeon execution.

## Official materials

- Project Profile: `../../docs/ProofLaunch_Project_Profile.pdf`
- Supplementary deck: `../../docs/ProofLaunch_Submission_Deck.pptx`
- Recording script: `../../docs/DEMO_VIDEO_SHOTLIST.md`
- Full source and environment guide: `../../README.md`
- Competition gate: `../../SUBMISSION_GATE.json`

## Proposed PR title

`Track 1, Banyan, ProofLaunch: Multimodal GTM Studio`
