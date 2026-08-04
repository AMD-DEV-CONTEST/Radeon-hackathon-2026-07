# Demo Video

**File:** [`DEMO_MAIN_2026-08-04.mp4`](DEMO_MAIN_2026-08-04.mp4) — 2:59, 1920×1080, committed
in this directory, so it needs no external host and cannot rot.

**Mirror:** _(YouTube link added on submission)_

**Product tour:** [`PRODUCT_SHOWCASE_2026-08-04.mp4`](PRODUCT_SHOWCASE_2026-08-04.mp4) — 1:51,
seven surfaces of the IDE, each driven and filmed rather than screenshotted.

---

## What the main video is

One screen, one recording. The Determinex IDE with **its own terminal** open over the Work
cockpit, running `scripts/dev/submission_demo.py` against the live Radeon Cloud instance
`u-14786-cdc26df7`. Not two captures composited side by side — the product running its own
measurement, in one pass, on 2026-08-04.

Everything on screen was produced minutes before the video was assembled. Where a claim
genuinely cannot be measured inside a recording it is named as committed data with its file,
which is a specific claim rather than an apology.

| Section | On screen | Measured live? |
|---|---|---|
| 0 | An idea typed in, an oracle synthesised from it (3 checks, `sound: true`), a program built and verified against it | yes |
| 1 | What the Kth candidate costs: K=1 **29.8 tok/s** → K=6 **166.3 tok/s** = **5.58× throughput for 1.07× wall clock** | yes |
| 2 | Where the ceiling is: K = 8/16/32/64 by candidates-per-second, measured rather than read from vLLM's boot-time declaration | yes |
| 3 | The access pattern as a GPU optimization: **93.5 %** prefix-cache hits on the shared-prefix arm vs **~1 %** when one distinct token is prepended, read from vLLM's own counters on the GPU | yes |
| 4 | Where verified search works and where it does not — `rle` 1.000/1.000, `gron` 5-check 0.005/0.943, `gron` 6-check 0.000/0.490 | no — 1,152 generations is ~20 min of GPU, so it ships as `amd_gpu_evidence/two_model_comparison.json` |
| 5 | Refusing a vague idea, then earning a verified one, closing on the Proof ledger carrying `VERIFIED — 3 oracle checks passed` | yes |

## Supporting clips

**[`LIVE_ON_RADEON_FULL_2min.mp4`](LIVE_ON_RADEON_FULL_2min.mp4)** — 1:59, recorded
2026-08-03 against the same instance. The whole argument in one pass: the model served on the
card, what one candidate costs (**29.5 tok/s**), what the sixth costs (**5.61× throughput for
1.07× wall clock**), where the ceiling is, and the loop refusing a result it cannot verify
before earning one.

**[`LIVE_ON_RADEON_2026-08-03.mp4`](LIVE_ON_RADEON_2026-08-03.mp4)** — 0:55, recorded against
**AMD's Radeon Token Factory** while it was serving. It runs
`scripts/determinex_calibrate.py` — not a demo script, the code that actually sets K. It
sweeps the machine it is on and derives K from the measurement, so the rule found by hand in
§5.1 (`K < floor(kv_cache_tokens / max_model_len)`) is enforced by code rather than
documented.

> **What these do not show, stated rather than omitted:** no `rocm-smi`. All of them drive the
> vLLM endpoint through the instance's own tunnel rather than a shell on the box, so the GPU
> is evidenced by what it serves, not by a utilisation readout.

## On the numbers

Six independent runs across five instances give a single-stream rate between 26.1 and
32.6 tok/s and a K=6 aggregate between 163 and 187 tok/s. The absolute rates move with
instance load and generation length; the **ratio does not** — 5.56× to 5.73× throughput for
1.05× to 1.08× wall clock. That stability is the claim, not any single figure. The full table
is §5.1 of [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

One measurement did not reproduce on the first attempt. The failed hypothesis and the
correction both ship — §5.1b and §5.1c. A submission that only publishes what worked is
telling you less than it appears to.
