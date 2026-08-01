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

## What running on AMD exposed

The first Radeon run of the greenfield path reported `not solved, samples=12`. **The model
was right all twelve times** — correct code inside a ```` ```python ```` fence, which the
harness's own prompt demands, and fence-stripping lived in exactly one provider. Every
other provider handed markdown to the oracle, where the module failed to import. The system
reported a *verdict about the model* for a *defect in the harness*.

Fixed at the one boundary every candidate crosses. Same model, prompt, oracle and GPU:
**SOLVED on sample 1.**

The durable output is a rule now stored in the project's knowledge corpus:

> A uniform 0.00 across every sample **and** every temperature is a *harness* signature.
> A genuinely weak model fails in **varied** ways. Import error on every candidate → the
> harness is wrong. Assertion failures → the model is wrong.

A pre-existing regression test had fed fenced code while asserting only that no *generation
error* occurred — never that the build solved. That is how a green suite carried the bug.
The new guard asserts the outcome and was negative-controlled: reverting the fix fails 4 of 7.

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

- **ProgramBench: 0/200 resolved.** A 2026-06-30 provenance audit found 62 of 67 prior
  "solves" were upstream source builds and retracted them. Zero is the honest figure under
  the surviving methodology, and it matches every public frontier model.
- **AMD's free Token Factory endpoint was never exercised** — its portal needs a
  China-registered account. Those config entries are wired and labelled unverified.
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

# Radeon Cloud -> Add Template -> Deploy Type = Notebook
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --host 127.0.0.1 --port 8000

# generation on the Radeon, verification wherever your toolchain lives
export DETERMINEX_VLLM_BASE_URL=http://127.0.0.1:8000/v1
python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 32
```

`generate()` and `verify()` are decoupled by design, so the model can serve from a Radeon
GPU while the compiler oracle runs anywhere — which is exactly how the benchmark numbers
above were produced.
