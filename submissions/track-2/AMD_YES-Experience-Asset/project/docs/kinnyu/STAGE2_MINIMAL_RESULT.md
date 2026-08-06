# Stage 2 minimal result: S0 versus P1

## Decision

**Select `P1-prefix-cache` for the final launch Profile, with `S0` as the
one-command rollback.** The same complete Agent and public synthetic business
journey passed on both Profiles. P1 introduced no observed schema, evidence,
correction, privacy, permission or terminal-state regression.

This is a deadline-minimal **one-case integration check**, not a statistical
application benchmark. The reproducible service-performance basis remains the
frozen Stage 1 packet, where P1 ranked first. This Stage 2 check only establishes
that the selected Profile runs the integrated product safely and records the
observed case delta.

## Paired observation

| Field | A0 / S0 | A1 / P1 |
|---|---:|---:|
| Complete public journey | PASS | PASS |
| Browser wall time | about 2.0 min | 109.21 s / 1.8 min |
| Observed one-run delta | control | about 9% lower |
| Local W7900/ROCm inference | PASS | PASS |
| Correction → invalidation → regeneration | PASS | PASS |
| Canonical evidence drawer | PASS | PASS |
| New safety/quality regression | none observed | none observed |
| Prefix-cache hit rate during this journey | not enabled | 0.0% observed |
| Stage 2 peak VRAM | NOT_MEASURED | NOT_MEASURED; post-run 40,741 MiB |

Because the P1 business run recorded a 0.0% prefix-cache hit rate, the single
timing difference must not be attributed to cache reuse or generalized. It may
be ordinary run variance. Stage 1 separately measured the warm-prefix service
benefit and retained P1's 85% warm-up reliability limitation.

## Frozen identity and launch delta

- Application implementation: `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
  (merged through PR #52).
- Model: local `Qwen/Qwen3.5-9B`, immutable revision
  `460979c3d11864dd16408d860ac930a360a2fac2`, BF16, thinking disabled.
- W7900: `gfx1100`, 96 CUs, 48 GiB VRAM; ROCm/HIP 7.2; vLLM 0.26.0.
- Shared service settings: 20K context, GPU memory utilization 0.82,
  `max-num-seqs=2`, Qwen3 tool parser and reasoning parser, localhost bind.
- Sole Candidate delta: `--enable-prefix-caching`.

The Pod is currently running P1. Rollback is the identical vLLM launch command
with `--enable-prefix-caching` removed. No application/database migration or
public endpoint is involved.

## E9-ready bounded claim

> On a Radeon PRO W7900 through ROCm, the complete local Agent passed the same
> synthetic end-to-end journey with both the original S0 service and the
> Stage-1-winning P1 prefix-cache Profile. The one P1 observation completed in
> 109.21 seconds versus about 2.0 minutes for S0, with no observed functional or
> safety regression. This one-case result is integration evidence, not a
> statistical latency claim; the run recorded no prefix-cache hit, so the
> broader optimization claim remains grounded in the frozen Stage 1 service
> benchmark.

## Evidence boundary

- S0 packet: `evidence/milestones/e8-a0-w7900/20260806T122806Z/`.
- P1 sanitized packet: `evidence/performance/stage2-minimal/20260806T124938Z/`.
- Raw logs: `/workspace/amd-track2-agent/evidence/stage2-minimal-20260806/raw/`.
- No public tunnel, private user data, credential, new model, prompt tuning or
  additional Candidate was used.
