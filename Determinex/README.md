# Determinex — Track 2 Submission

**2026 AMD Radeon GPU Hackathon · Track 2: Development & Local Deployment of Private AI Agents**

| | |
|---|---|
| **Submitter** | DarthCeltic |
| **Source code** | https://github.com/DarthCeltic/Determinex (AGPL-3.0-or-later, public) |
| **AMD hardware** | Radeon Cloud · ROCm 7.2.1 · vLLM 0.16.1 |
| **Models measured** | Qwen2.5-Coder-7B-Instruct (bf16) and Qwen2.5-Coder-32B-Instruct-AWQ |

---

## What it is

A local-first, **compiler-verified** multi-agent coding system. One rule is enforced
everywhere: **no model ever judges its own output.** A real compiler or a real test suite
is the only oracle. The model proposes; the oracle disposes.

That has a consequence most agent architectures don't have. Correctness comes from
sampling K candidates and verifying each — `P = 1 − (1 − p)^K` — so accuracy is bounded by
**GPU batch throughput**, not by model quality. Which makes "how good is this GPU" and "how
correct is this agent" the *same question*.

So we measured it, rather than asserting it.

---

## Four measured results on the Radeon

### 1. K scales almost free — until it doesn't, and the cliff is predictable

| K | aggregate tok/s | wall clock |
|---:|---:|---:|
| 1 | 28.7 | 8.92 s |
| 16 | 413.5 | 9.91 s |
| **32** | **739.9** | **10.75 s** |
| 64 | 512.6 ↓ | 29.59 s ↓ |

**25.8× the tokens for 1.21× the wall clock at K=32.** Then K=64 collapses — and vLLM
announced why at boot: `Maximum concurrency for 8,192 tokens per request: 61.83x`. Exceed
it and requests preempt instead of batching.

> **Rule any Radeon owner can apply without rerunning this:**
> keep `K < floor(kv_cache_tokens / max_model_len)`, both printed in vLLM's boot log.

At `p = 0.3`, K=32 means **99.999%** solved versus 30% for a single attempt.

**That rule is now code.** `scripts/determinex_calibrate.py` makes Determinex measure the
machine it is running on and set K from the result, because a rule in a document is a rule
nobody applies:

```bash
python scripts/determinex_calibrate.py --backend vllm --model Qwen/Qwen2.5-Coder-7B-Instruct
python scripts/determinex_calibrate.py --show
```

It **measures** rather than trusting a declared config value. vLLM publishes its capacity —
`vllm:cache_config_info{num_gpu_blocks="31504", block_size="16"}`, and `31504 × 16 ÷ 8192 = 61`
predicts the collapse at 64 exactly. But the same read-the-config approach applied to Ollama
read `OLLAMA_NUM_PARALLEL=1`, predicted full serialization, and the machine returned a 3.4×
speedup. The declared number only bounds the sweep; the measurement decides.

The objective is **candidates per second** (`K / wall_clock`) rather than tok/s, because
`P = 1 − (1 − p)^K` makes the arrival rate of independent attempts the thing that matters —
and that ratio finds the cliff for free. Applied to the captured Radeon sweep it independently
selects **K=48** and flags the collapse at **K=64**, reproducing the knee found by hand.

| Rig | Backend | Optimal K | candidates/s | Ceiling is set by |
|---|---|---:|---:|---|
| **AMD Token Factory**, MiniCPM5-1B (Radeon PRO W7900 ×4) | free shared API | **8+** | **4.51** | requests/minute quota |
| **AMD Radeon Cloud**, ROCm 7.2.1, 7B | vLLM | **48** | 3.52 | KV cache — collapses at K=64 |
| Consumer box, 12 CPU, 1.5B | Ollama | **12** | 1.63 | CPU saturation |
| Consumer box, 12 CPU, 14B | Ollama | **4** | 0.18 | CPU saturation |

**Three different reasons for three different ceilings, one rule.** That is why the
calibrator measures instead of reading a config: the *number* is unknowable in advance and
the *reason* differs per backend, but "candidates/second stopped rising, so stop adding
candidates" holds on all of them. The AMD free tier is the fastest of the four — **25× the
local 14B** — and cost nothing.

The previously hardcoded `K=6` is wrong on both — wasting roughly **5×** of the Radeon's
correctness rate and ~37% of the consumer box's. **This is the concrete case for the GPU:**
the Radeon does not merely run the workload faster, it sustains **4× the concurrent
verification depth**, and `P` is exponential in depth.

Uncalibrated machines get a conservative `K=4` **and a logged line saying so**, naming the
command that fixes it — an absent measurement reported as absent, never a silent guess.
`DETERMINEX_AMPLIFY_K` always overrides. 13 tests in `tests/test_calibration_k.py`.

### 2. The agent's access pattern is itself a GPU optimization

Verified search issues K prompts that are **identical except for sampling temperature** —
unusual, and close to ideal for a prefix cache. An ordinary agent sends K *different*
prompts. Both arms, same GPU:

| K=16 | prefix-cache hit | aggregate tok/s | wall clock |
|---|---:|---:|---:|
| **Verified search** | **99.51%** | **410.9** | **9.97 s** |
| Distinct prompts | 1.35% | 292.9 | 13.98 s |

**1.40× throughput at 0.71× wall clock, free**, purely from how the architecture queries
the model.

### 3. `p` measured directly — 960 generations, including where it stops working

192 independent candidates per task, every one verified against the same oracle:

| Task | passes / 192 | p |
|---|---:|---:|
| `rle` | 192/192 | **1.000** |
| `gron` (JSON flattening) | 1/192 | 0.005 |
| `gron` + JSON-literal semantics | 0/192 | **0.000** |

Two of those are uncomfortable and we are reporting them anyway. `rle` is **trivial** for
this model — which is why the demo no longer uses it. And **at `p = 0` no K helps** — `1 − (1 − 0)^K = 0`. Verified
search multiplies capability; it cannot manufacture it. That's the architecture's floor,
measured rather than assumed.

### 4. Two models on one GPU — the three regimes

`p` measured for a second model, same hardware, same oracles (1,152 generations total):

| Task | 7B `p` | 32B `p` | Regime |
|---|---:|---:|---|
| `rle` | 1.000 | 1.000 | saturated — K adds nothing |
| `gron` 5-check | 0.005 | 0.943 | model solves it; K trims the tail |
| **`gron` 6-check** | **0.000** | **0.490** | **the productive middle** |

At `p = 0.490` the model fails more than half its attempts — and reaches **99.54% at K=8,
for 1.04× the wall clock.** A coin flip becomes near-certain for 4% more time. The other
two rows bound the claim: nothing to amplify at `p = 1`, and nothing to rescue at `p = 0`.

Full method and data: [`PROJECT_SPEC.md`](PROJECT_SPEC.md) §5.2a–5.2d ·
[`amd_gpu_evidence/`](amd_gpu_evidence/).

---

## Repairing a real repository

The strongest demonstration of application value isn't a synthetic task. Determinex was
pointed at **`mwaskom__seaborn-3010`** from SWE-bench Lite — a real reported issue in a real
open-source project, judged by that project's own test:

```
[repair] fix target inferred from the failure: seaborn/_stats/regression.py
[repair] using the repo's interpreter: .venv
[repair] oracle scope: 1 failing test(s), not the full suite
    [vs] r1 s1/6 t=0.0  gen 17s  verify 10s  ->  PASS

blame {'CODE': 1}   proven slop 0   FIXED True          # 27 seconds
```

```diff
- p = np.polyfit(x, y, self.order)
+ p = np.polyfit(x.dropna(), y.dropna(), self.order)
```

Blame is **`CODE`** — not environment, not test — and `proven_slop: 0`, so it declined the
easy exit of declaring the failing test wrong. Generation ran on the Radeon-hosted 32B;
verification ran against the repo's own tests with the repo's own interpreter.

**The control that makes this meaningful:** SWE-bench's official gold patch also passes
this oracle (`1 passed in 0.12s`). The target is achievable and a correct fix is recognised
as correct — without that, a pass proves much less.

### The same repair, with nothing in the cloud

Track 2 is about *local* deployment, so the run was repeated end to end on one workstation:
**Qwen2.5-Coder-14B via Ollama**, no API key, no network egress, the identical oracle.

```
[repair] fix target inferred from the failure: seaborn/_stats/regression.py
    [vs] r1 s1/6 t=0.0  gen 228s  verify 77s  ->  PASS

blame {'CODE': 1}   proven slop 0   FIXED True          # 337 seconds
```

Same verdict, same oracle, first sample — 12× slower than the Radeon and **entirely
private**. That is the trade the architecture is built to let you make: `generate()` and
`verify()` are decoupled, so the model can sit on a Radeon when throughput matters and on
your own box when the code cannot leave it. Nothing else in the pipeline changes.

**And the honest denominator: 1 of 4.** The same 14B was pointed at all four single-file
seaborn instances in SWE-bench Lite. It fixed one. The other three generated candidates
that the project's own tests rejected — which is the system working: three wrong answers
were caught by the oracle and none was reported as a fix.

That number is small and it is the *system's* number, not the model's ceiling. `p` is
per-model and per-task; the K-sweep above is what converts a low `p` into a high solve
rate, and at K=6 on a 14B this is what `p` bought. The measured `p = 0.490` case in §4
reaches 99.54% at K=8 — the mechanism is the same, the input is a stronger `p`.

## Offline integrity

The benchmark loop reverse-engineers CLI tools black-box — no source, no internet at
inference. That was verified in **both** directions, because a build that merely succeeds
also succeeds when the container secretly has network:

```
stdlib-only  + --network=none  ->  BUILD_OK
third-party  + --network=none  ->  "to add it: go get"  ->  REFUSED
```

---

## What is not claimed

- ~~AMD's free Token Factory endpoint was never exercised~~ — **retired 2026-08-02.** It
  works from an ordinary account: five models served on AMD GPUs, and `MiniCPM5-1B` (four
  Radeon PRO W7900 workers per the portal) returned 200 tokens in **2.0 s**. A live K-sweep
  measured **4.51 candidates/second at K=8** — the highest of any backend measured here,
  above the captured Radeon vLLM figure of 3.52. Free tier, no instance, no credits.
- **The ~46 GiB VRAM figure is derived** from KV-block telemetry under a stated bf16
  assumption, not read from `rocm-smi`.
- **The amplification curve fit is weak evidence *as a fit*.** At `p = 0.0052` it tracked
  `1 − (1 − p)^K` to 0.0021 max error, but with a single success in the pool that is close
  to tautological. The mid-range case (`p = 0.490`, §4) is the one that carries weight,
  and it is a measurement of `p` rather than a curve fit.

*A benchmark number that cannot survive a provenance audit is worth less than a zero that can.*

---

## Contents

| Path | What |
|---|---|
| `PROJECT_SPEC.md` | Track 2 specification — all five required sections |
| `POSTER.md` | Supplementary material |
| `DEMO_VIDEO.md` | Demo video link + shot list |
| `demo_run.sh` | One command that reproduces the demo on a Radeon Notebook instance |
| `amd_gpu_evidence/` | Throughput, K-sweep, prefix-cache, measured `p`, vLLM telemetry |

## Reproducing

```bash
git clone https://github.com/DarthCeltic/Determinex && cd Determinex
pip install -r scripts/requirements.txt          # inference-only; Python 3.11+

# Radeon Cloud -> Add Template -> Deploy Type = Notebook
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --host 127.0.0.1 --port 8000

# generation on the Radeon, verification wherever your toolchain lives
export DETERMINEX_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export DETERMINEX_VLLM_API_KEY=whatever-you-passed-to---api-key   # omit if vLLM has none
python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 32
```

`idea.md` ships in the repository, so that command runs as written. It should print a
synthesized oracle, the verified-search rounds, and a program that passes:

```
=== BUILD FROM IDEA (vllm) ===
synthesized oracle: 3 checks
result: SOLVED  samples=1
proof: program PASSES all 3 synthesized checks (oracle-verified, 1 samples).
```

**Then delete the "For example…" lines from `idea.md` and run it again.** It will refuse —
`result: not solved`, *"that cannot verify behaviour. Add one concrete input/output example
and re-run."* That refusal is the product, not an error: no oracle, no claim. Checking both
directions takes about a minute and is the fastest way to see what this actually is.

`generate()` and `verify()` are decoupled by design, so the model can serve from a Radeon
GPU while the compiler oracle runs anywhere — which is exactly how the benchmark numbers
above were produced.
