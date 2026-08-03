# Demo Video

**File:** [`SUBMISSION_DEMO_v2_4min09.mp4`](SUBMISSION_DEMO_v2_4min09.mp4) — committed in this
directory, so it needs no external host and cannot rot.

**Mirror:** _(YouTube link added on submission)_

**Runtime: 4:09** · no narration required · on-screen section headers carry the structure,
which is why the runner prints them. Inside the 3–5 minute requirement.

> The recorded file is `SUBMISSION_DEMO_v2_4min09.mp4` (h264, 249.9 s, 1100×816 — 700 of
> content plus a padding band, because an earlier take cropped the last line of terminal
> output and nobody noticed until it was played back). It passes an
> automated gate that samples a frame every 2 seconds across the whole file and checks for a
> desktop leak, a frozen screen, edge bleed, and the duration window — each of which exists
> because an earlier take passed a casual look and was not shippable.
>
> The repair's silent-generation pauses were cut. The per-sample timings it prints
> (`gen 212s / 343s / 193s / 262s`) and the 427-second total remain on screen, so the cost is
> disclosed; what was removed is a motionless terminal.

Every number spoken or shown below appears in `README.md` or `amd_gpu_evidence/`. Nothing
is re-derived for the camera.

> **One honest note, stated on screen at 0:00.** The Radeon Cloud instance used for the
> GPU measurements has since been destroyed, so sections 1–3 are read from the captured
> evidence files rather than re-run live. Sections 4–5 run live on local hardware. The
> evidence files are raw tool output, committed in `amd_gpu_evidence/`.

| Section | On screen | Source |
|---|---|---|
| 1 | K-sweep: 28.7 → 739.9 tok/s, and the K=64 collapse | `k_sweep_and_prefix_cache.json` |
| 2 | Prefix cache 99.51% vs 1.35%, same GPU, same K | `k_sweep_and_prefix_cache.json` |
| 3 | Measured `p` for two models — 1.000 / 0.943 / 0.490 / 0.000 | `two_model_comparison.json` |
| **4** | **Determinex calibrates itself to the machine — LIVE sweep**, then the same objective applied to the captured Radeon data reproduces K=48 / collapse at 64 | live + `k_sweep_and_prefix_cache.json` |
| 5 | A real SWE-bench repair, oracle-verified, **live and local** | live |
| 6 | The honest boundary | — |

**Section 4 is the ROCm optimization actually running.** The rule derived in section 1
(`K < floor(kv_cache_tokens / max_model_len)`) is no longer just a documented finding —
`scripts/determinex_calibrate.py` measures the machine it is on and sets K from it. On camera
it sweeps the local box live, then applies the identical objective to the captured Radeon
sweep and independently selects **K=48** with the collapse flagged at **K=64** — the knee that
was originally found by hand. Two machines, one law, and the old hardcoded `K=6` shown wrong
on both.

> **If the Radeon instance is redeployed, this is the section to re-shoot there.** It would
> sweep the real GPU on camera instead of replaying its captured numbers, which satisfies
> Requirement 3's *"actual execution performance on an AMD Radeon GPU"* and demonstrates the
> optimization on the hardware it was designed for, in the same take.

---

## Shot list

### 0:00–0:25 — What the GPU actually did

Open `amd_gpu_evidence/k_sweep_and_prefix_cache.json` and put the table on screen:

| K | aggregate tok/s | wall clock |
|---:|---:|---:|
| 1 | 28.7 | 8.92 s |
| 16 | 413.5 | 9.91 s |
| **32** | **739.9** | **10.75 s** |
| 64 | 512.6 ↓ | 29.59 s ↓ |

Say it plainly: **25.8× the tokens for 1.21× the wall clock.** Then point at K=64 and say
why it collapses — vLLM announced the limit at boot, `Maximum concurrency for 8,192 tokens
per request: 61.83x`. Exceed it and requests preempt instead of batching.

Land the rule, because it is the part any Radeon owner can use without rerunning anything:

> Keep `K < floor(kv_cache_tokens / max_model_len)`. Both numbers are in vLLM's boot log.

### 0:25–0:50 — The agent's access pattern is itself a GPU optimization

Same file, the A/B:

| K=16 | prefix-cache hit | aggregate tok/s | wall clock |
|---|---:|---:|---:|
| Verified search | **99.51%** | 410.9 | 9.97 s |
| Distinct prompts | 1.35% | 292.9 | 13.98 s |

Verified search sends K prompts identical except for sampling temperature. An ordinary
agent sends K different prompts. **1.40× throughput at 0.71× wall clock, free** — purely
from how the architecture queries the model.

### 0:50–1:25 — Where it works, and where it does not

`amd_gpu_evidence/two_model_comparison.json`, 1,152 generations:

| Task | 7B `p` | 32B `p` | Regime |
|---|---:|---:|---|
| `rle` | 1.000 | 1.000 | saturated — K adds nothing |
| `gron` 5-check | 0.005 | 0.943 | model solves it; K trims the tail |
| **`gron` 6-check** | **0.000** | **0.490** | **the productive middle** |

Do not skip the outer rows — they are what makes the middle one credible. At `p = 0.490`
the model fails more than half its attempts and reaches **99.54% at K=8 for 1.04× the wall
clock**. At `p = 0` no K helps: `1 − (1 − 0)^K = 0`. Verified search multiplies capability;
it cannot manufacture it.

### 1:25–2:50 — A real repository, repaired live *(the section to spend time on)*

This runs on local hardware, so it is reproducible on camera. Point Determinex at
`mwaskom__seaborn-3010` — a real reported issue in a real open-source project, judged by
that project's own test.

```bash
python scripts/determinex_repair.py <workspace>
```

Let it print, and read the lines out as they land:

```
[repair] fix target inferred from the failure: seaborn/_stats/regression.py
[repair] using the repo's interpreter: .venv
[repair] oracle scope: 1 failing test(s), not the full suite
    [vs] r1 s1/6 t=0.0  gen 228s  verify 77s  ->  PASS

blame {'CODE': 1}   proven slop 0   FIXED True
```

```diff
- p = np.polyfit(x, y, self.order)
+ p = np.polyfit(x.dropna(), y.dropna(), self.order)
```

Three things to say while it runs:

1. **Blame is `CODE`** — not environment, not test. And `proven_slop: 0`: it declined the
   easy exit of declaring the failing test wrong.
2. **The control.** SWE-bench's official gold patch also passes this oracle
   (`1 passed in 0.12s`). The target is achievable and a correct fix is recognised as
   correct — without that, a pass proves much less.
3. **Nothing left the machine.** Qwen2.5-Coder-14B via Ollama, no API key, no egress. The
   same run on the Radeon-hosted 32B finished in 27 s. `generate()` and `verify()` are
   decoupled by design, so the model sits on a Radeon when throughput matters and on your
   own box when the code cannot leave it.

### 2:50–3:30 — The boundary, said out loud

State it on camera rather than burying it:

- **ProgramBench: 0/200 resolved.** A provenance audit found 62 of 67 prior "solves" were
  upstream source builds and retracted them. Zero is the honest figure under the surviving
  methodology, and it matches every public frontier model.
- **The ~46 GiB VRAM figure is derived** from KV-block telemetry under a stated bf16
  assumption, not read from `rocm-smi`.
- ~~AMD's free Token Factory endpoint was never exercised~~ — **retired 2026-08-02.** It
  works from an ordinary account: five models served on AMD GPUs, and `MiniCPM5-1B` (four
  Radeon PRO W7900 workers per the portal) returned 200 tokens in **2.0 s**. A live K-sweep
  measured **4.51 candidates/second at K=8** — the highest of any backend measured here,
  above the captured Radeon vLLM figure of 3.52. Free tier, no instance, no credits.

Close on: *a benchmark number that cannot survive a provenance audit is worth less than a
zero that can.*

---

## Recording notes

- **No API keys on screen, ever** — not in a `curl`, not in an environment dump, not in a
  scrollback. A key captured in a video frame is a published key.
- Terminal at a large font. Judges watch these small.
- The REPAIR (now section 5) is the long one — 427 s in the shipped take, one candidate
  alone spending `gen 343s`. Cut the motionless stretches, never the printed timings: the
  elapsed numbers stay on screen so the cost is disclosed rather than implied.
- Section numbering below predates the calibration section; the table at the top of this
  file is the authoritative running order (1-3 evidence, 4 calibration, 5 repair, 6 boundary).
