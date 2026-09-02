# HipFire upstream contribution evidence

## Scope

ProtBind uses HipFire as its local OpenAI-compatible inference backend on AMD Radeon GPUs. The
participant, Huang Siming (`HUSRCF`), also submitted the following pull requests directly to the
upstream [`warpfront/hipfire`](https://github.com/warpfront/hipfire) repository. These contributions
provide attributable evidence of hands-on work on the Radeon inference stack used by the project.

Status was verified from the GitHub pull-request API on 2026-08-07 (UTC+8): **16 submitted**, of
which **7 were merged**, **5 were closed without merge**, and **4 remain open**.

## Merged upstream contributions

- [#556](https://github.com/warpfront/hipfire/pull/556) — `feat(radiowave): add gfx11 OCP FP8 lowering recipes` — merged 2026-08-01.
- [#554](https://github.com/warpfront/hipfire/pull/554) — `perf(gfx12): reuse Q8 KV across four prefill queries, ~1.7x prefill` — merged 2026-07-30.
- [#550](https://github.com/warpfront/hipfire/pull/550) — `fix(ci): restore clean-checkout beta gates` — merged 2026-07-28.
- [#549](https://github.com/warpfront/hipfire/pull/549) — `feat(runtime): FireMap - grow Qwen3.5 KV on demand with HIP VMM` — merged 2026-07-29.
- [#548](https://github.com/warpfront/hipfire/pull/548) — `perf(qwen35): reduce owned prefill scratch VRAM` — merged 2026-07-28.
- [#547](https://github.com/warpfront/hipfire/pull/547) — `feat(redline): add steady-state exactly-once dispatch profiler` — merged 2026-07-28.
- [#538](https://github.com/warpfront/hipfire/pull/538) — `fix(qwen35): prevent gated-norm MQ rotation scratch overflow` — merged 2026-07-26.

## Open upstream proposals

- [#565](https://github.com/warpfront/hipfire/pull/565) — `feat(kv): compose CASK eviction with VMM and adaptive KV`.
- [#561](https://github.com/warpfront/hipfire/pull/561) — `perf(qwen3, gfx11/gfx12): route Q8 prompts through M16 batched prefill and tiled flash decode`.
- [#559](https://github.com/warpfront/hipfire/pull/559) — `fix(client): clear beta Clippy failure and dummy spawn race`.
- [#543](https://github.com/warpfront/hipfire/pull/543) — `fix(redline): restore gfx1201 retained PM4 ordering`.

## Closed without merge

- [#555](https://github.com/warpfront/hipfire/pull/555) — fixed-head Q8 M16/query16 prefill specialization and Qwen rollover-state proposal.
- [#551](https://github.com/warpfront/hipfire/pull/551) — diagnostic isolation of dispatch timestamp-write costs.
- [#536](https://github.com/warpfront/hipfire/pull/536) — limiting RDNA3 QKVZA split-tail dispatch to long cold prefill.
- [#529](https://github.com/warpfront/hipfire/pull/529) — README quick-start and historical-benchmark labeling proposal.
- [#496](https://github.com/warpfront/hipfire/pull/496) — opt-in RDNA3 QKVZA split-tail dispatch proposal.

## Relevance to ProtBind

The merged and proposed work spans HIP virtual memory, KV-cache management, prefill/decode
kernels, FP8 lowering, scratch-memory reduction, GPU dispatch profiling, and correctness/CI fixes.
This supports the engineering claim that the participant worked below the application layer on the
local Radeon inference backend used by ProtBind.

## Evidence boundary

These upstream PRs are contribution and engineering-provenance evidence. Benchmark numbers in an
upstream PR title or discussion retain that PR's own scope and methodology; they are not silently
promoted into ProtBind benchmark results. ProtBind's formal performance claims remain limited to
its submitted W7900 Agent receipt and the separately frozen TriPharm CPU/HIP parity and timing
receipts. Open and closed-without-merge PRs are identified as proposals, not accepted upstream code.
