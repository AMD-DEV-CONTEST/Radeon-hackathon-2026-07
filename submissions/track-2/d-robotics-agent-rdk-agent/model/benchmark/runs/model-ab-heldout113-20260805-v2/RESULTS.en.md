> Chinese version: [RESULTS.md](RESULTS.md)

# Base/SFT result: capped frozen prefix

This is the human-readable view of [`summary.json`](summary.json), which remains
the canonical machine-readable result. Verify the exported evidence with
`sha256sum -c SHA256SUMS` from this directory.

- Run ID: `model-ab-heldout113-20260805-v2`
- Evidence status: `CAPPED_RECOVERY_SEALED`
- Frozen Test: 113 tasks, 3,562,357 bytes, SHA-256
  `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283`
- Evaluated prefix: the first 49 complete tasks (task indices 0 through 48),
  containing 170 assistant turns per arm: 121 tool-call turns and 49 final turns
- Canonical Test in this repository:
  [`data/releases/rdk-sft-v1-20260803/agentic/test.jsonl`](../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl)

## Result

| Metric | Base | SFT | Delta |
|---|---:|---:|---:|
| Strict tool-call exact | 45/121 (37.19%) | 82/121 (67.77%) | +30.58 pp |
| Tool-name exact | 48/121 (39.67%) | 93/121 (76.86%) | +37.19 pp |
| Tool-arguments exact | 45/121 (37.19%) | 82/121 (67.77%) | +30.58 pp |
| Tool-call-count exact | 81/121 (66.94%) | 97/121 (80.17%) | +13.22 pp |
| Clean final response | 44/49 (89.80%) | 48/49 (97.96%) | +8.16 pp |
| All-turn task contract | 0/49 (0.00%) | 15/49 (30.61%) | +30.61 pp |

For strict tool-call exactness, the paired outcomes are 42 both-correct, 40
SFT-only, 3 Base-only, and 36 neither. For the all-turn task contract, they are
0 both, 15 SFT-only, 0 Base-only, and 34 neither.

The main observed gain is selecting the correct tools, arguments, and number of
calls—not merely emitting structured output. Structured-output agreement changed
only from 114/121 (94.21%) to 115/121 (95.04%).

## Observed cost

| Measure | Base | SFT | Ratio |
|---|---:|---:|---:|
| Mean latency | 15.825 s | 33.269 s | 2.10x |
| P50 latency | 10.393 s | 18.797 s | 1.81x |
| P95 latency | 45.246 s | 76.301 s | 1.69x |
| Completion tokens | 12,274 | 25,259 | 2.06x |

Both arms used the same 746,617 prompt tokens. These latency measurements are
descriptive observations from sequential service runs, not a causal performance
attribution to SFT alone.

## Claim boundary

The supported claim is:

> On this hash- and model-identity-bound frozen ordered prefix, SFT increased
> strict tool-call agreement from 37.19% to 67.77% and made 15 of 49 tasks satisfy
> the complete per-turn contract, compared with 0 of 49 for Base.

This prefix is not random or representative of the full 113-task Test. It contains
28 curated live-diagnostic, 5 curated controlled-actuation, and 16 promoted
live-diagnostic tasks; it omits all 15 promoted controlled-actuation tasks. Both
arms scored 0/49 on strict final-text equality, so this run does not establish
semantic or factual correctness of final prose.

This is teacher-trajectory replay agreement. It does not prove `rdk-agent`
end-to-end success, board execution, or physical effect. The original evaluators
were stopped with `SIGTERM`; the recovery seals bind the later read-only snapshots
and seal-time service identities, not stop-time runner-finalized evidence. Base
captured one extra next-plan record (`base:49:2`), which was verified and excluded
before all paired calculations.

## Evidence anchors

- `summary.json` SHA-256:
  `cb49818d372d52fa42a5dfd29208384cc9bd57c3505d5925920b6ea783ad59b2`
- Frozen evaluator SHA-256:
  `645f29a31afa510c313f8e979507babf5037446d33da6b67d486c452024f5012`
- Base selected raw prefix SHA-256:
  `02b84cf3969816494d0943dfa5edb6fb4e38ca44b3b7a518de1adb33049e3abf`
- SFT raw SHA-256:
  `7d34a5dfb905a202e42ebf43ba762df2fd0b4c3c1d20eb0f42e69bc56ebdbd81`
