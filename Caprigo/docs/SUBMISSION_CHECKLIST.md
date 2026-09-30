# Caprigo — Track 2 Submission Checklist

**AMD AI DevMaster Hackathon · Track 2 Agentic AI**  
**Team:** Vibes-Coded (solo) · **b_Radford** · `doteyeso@gmail.com`  
**Deadline:** Aug 6, 2026 8:59 AM PDT  
**Source:** https://github.com/doteyeso-ops/caprigo (MIT)

---

## Contest requirements (Track 2)

| # | Requirement | Evidence | Status |
|---|-------------|----------|--------|
| 1 | Project specification (scenarios, architecture, capabilities, model/deploy, AMD optimization) | [`PROJECT_SPEC.md`](PROJECT_SPEC.md) | **DONE** |
| 2 | Complete source + README (env, startup, deps) | Upstream Caprigo MIT repo + this packet README | **DONE** |
| 3 | Demo video (recommended 3–5 min; show operation on AMD GPU) | Caprigo `docs/demo/Caprigo_AMD_Demo.mp4` (~72s VO, RX580/AMD narrative) | **DONE** (shorter than recommended) |
| 4 | Supplementary PPT/Poster | [`POSTER.md`](POSTER.md) | **DONE** |
| 5 | AMD optimization / measured delta (**40%**) | [`AMD.md`](AMD.md) + [`MEASUREMENT_LOG.md`](MEASUREMENT_LOG.md) + [`../artifacts/delta.csv`](../artifacts/delta.csv) · 7B **29.21** vs scrap **~19** tok/s | **DONE** |
| — | Judge entrypoint | [`JUDGING_SCORECARD.md`](JUDGING_SCORECARD.md) | **DONE** |
| — | Demo walkthrough (mitigates short video) | [`DEMO_WALKTHROUGH.md`](DEMO_WALKTHROUGH.md) | **DONE** |
| — | Scrap agent + Session evidence | [`../artifacts/agent-demo-20260728.md`](../artifacts/agent-demo-20260728.md) · [`../artifacts/bench-agent-delta.csv`](../artifacts/bench-agent-delta.csv) | **DONE** |

English materials · PR title format: `Track 2, Vibes-Coded, Caprigo`.

---

## Measured evidence (instance destroyed after capture)

| Metric | Scrap | ROCm |
|--------|-------|------|
| 7B-class decode | ~19 tok/s (RX 580 Vulkan) | **29.21 tok/s** (gfx1100 vLLM · Qwen2.5-7B-Instruct) |
| Path smoke | — | 0.5B **215 tok/s** |
| Caprigo Session lean | ~31 s OK (scrap) | Decode delta completed; full gateway Session loop on cloud not re-timed |

---

## Honest disclosures

- Demo is **~72s**, not 3–5 min (product + AMD narrative with VO). Judges can still see Caprigo surfaces.
- Source lives in the public Caprigo repo (not a nested `Caprigo/src/` tree in this PR).
- Private SSH keys are **not** in the PR (rotated/local-only after an earlier leak cleanup).
- Cloud instance used for measurement has been **destroyed**.

---

— b_Radford / Vibes-Coded
