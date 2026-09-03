# Submission index — Track 2: Development & Local Deployment of Private AI Agents

**Project:** Hyperloom — an autonomous ROCm kernel-optimizer agent for AMD Radeon
**Hardware:** AMD Radeon AI PRO R9700 (gfx1201 / RDNA4), ROCm 7.x
**Repository:** https://github.com/The-Monk/rocky-hackathon

Every requirement from the Track 2 submission spec, and where it lives.

| # | Required artifact | Where |
|---|---|---|
| 1 | **Project Specification Document** — application scenarios · agent architecture diagram · core capabilities · model introduction & local deployment plan · optimization description for inference speed on AMD Radeon GPU | [`PROJECT-SPECIFICATION.md`](../PROJECT-SPECIFICATION.md) |
| 2 | **Project Source Code** — complete repository, README with environment configuration, startup guide, dependency list | [repo root](../) · [`README.md`](../README.md) · [`benchmarks/README.md`](../benchmarks/README.md) · [`container/`](../container/) |
| 3 | **Demo Video** — actual operation process, command line → final result, on an AMD Radeon GPU | [`demo/self-narrated/HYPERLOOM-track2-demo.mp4`](../demo/self-narrated/HYPERLOOM-track2-demo.mp4) — 4 min 53 s, 1920×1080, with narration |
| 4 | **Supplementary Material** (choose one) — PPT / Poster | [`submission/poster.pdf`](poster.pdf) (A2, single page) · [`poster.png`](poster.png) |

---

## About the demo video

`HYPERLOOM-track2-demo.mp4` is a **genuine screen capture of the system running**, not a rendered
animation or a replay of stored text. It records `demo/run_demo.sh` executing live against the
R9700 — every command shown being typed is the command that runs, and every number on screen is
produced on the card during the recording.

Reproduce the recording yourself:

```bash
./demo/run_demo.sh                 # run the workflow directly
PACE=6 POST=16 ./demo/capture_demo.sh   # or re-record the video
```

The capture runs on a private, freshly-created virtual X display so it does not depend on a desktop session;
compute runs on GPU0.

**What the video shows, in order:** detect the silicon → scan the ISA with the assembler as ground
truth → identify the unused native instruction → build both routes and prove which instruction
each emits → correctness-gate bit-exact against a CPU reference → measure → **audit the
measurement itself** → the DRAM-honest production result → prefill → comms.

Step 5 is the one worth watching. The agent deliberately re-runs its own benchmark at a
cache-resident working set so the harness prints `125% of roofline (CACHE-RESIDENT!)` — a
bandwidth above the DRAM roofline is proof that cache was measured, not memory. It then shows the
DRAM-honest number, 97% of roofline. This caught a real error in an earlier version of this
submission, where the decode benchmark had been reporting 122% of roofline as if it were a win.

`demo-hq.mp4` is a shorter 51-second title/intro piece, also produced entirely on the same card
(kokoro-v1 narration, Flux-2-Klein-9B imagery, via Lemonade). It is supplementary; the operation
capture above is the submission video.

## Verification

All headline numbers were re-verified from a **clean clone of the public repository**, on the
card, on 2026-08-04:

```
decode   613 GB/s = 97% of the measured 631 GB/s DRAM roofline   max_rel_err=1.1e-04 PASS
prefill  3.669x @ K=8192                                          all gates max_abs_err=0 PASS
comms    INT6 mean rel_l2=0.0239, 2.46x compression vs fp16
```

Per-claim reproduction commands are in [`benchmarks/README.md`](../benchmarks/README.md).
