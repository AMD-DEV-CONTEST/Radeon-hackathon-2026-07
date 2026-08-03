# DETERMINEX
### Compiler-verified AI. Private. Local. Measured on AMD Radeon.

**Track 2 · Private AI Agents · DarthCeltic · AGPL-3.0-or-later**

---

## THE PROBLEM

> Cloud coding assistants require shipping your source to a third party.
> Local assistants hand you one small model with **nothing checking its work**.
>
> A 1.5B model that is confidently wrong costs more review time than no assistant at all.

---

## THE IDEA — one rule, strictly enforced

# ❝ No model ever judges its own output. ❞

A real compiler or a real test suite is the only oracle. The model *proposes*.
The oracle *disposes*. There is no LLM-as-judge anywhere in the loop.

```
   idea ──► ARCHITECT ──► BUILDER ──► ┏━━━━━━━━━━━━━━━━━━━┓ ──► verified program
    7B          1.5B  ╲   K cands     ┃  ORACLE           ┃
                       ╲              ┃  rustc · go       ┃
                        ╲             ┃  pytest · tsc     ┃
                         ╲────────────┃  DETERMINISTIC    ┃
                          exact error ┗━━━━━━━━━━━━━━━━━━━┛
                          injected on failure
```

**P(correct) = 1 − (1 − p)^K** — any model with p > 0 is driven toward correct
by sampling more candidates. Model quality sets `p`. **The system sets `K`.**

---

## WHY THAT MAKES IT AN AMD STORY

If correctness comes from verifying K candidates, then accuracy is bounded by
**GPU batch throughput**, not by model quality. So the GPU question becomes:
*what does the 6th candidate actually cost?*

Measured on Radeon — ROCm 7.2.1 · vLLM 0.16.1 · Qwen2.5-Coder-7B-Instruct:

| | Single stream | **K=6 concurrent** |
|---|---:|---:|
| Throughput | 30.0 tok/s | **166.9 tok/s** |
| Wall clock | 17.05 s | **18.41 s** |

# 25.8× throughput · 1.21× wall clock

We swept K instead of guessing it:

| K | agg tok/s | wall | |
|---:|---:|---:|---|
| 1 | 28.7 | 8.92 s | |
| 16 | 413.5 | 9.91 s | |
| **32** | **739.9** | **10.75 s** | ← knee |
| 64 | 512.6 ↓ | 29.59 s ↓ | collapse |

**The cliff is predictable.** vLLM prints `Maximum concurrency: 61.83x` at boot.
K=64 exceeds it, so requests preempt instead of batching.
→ **Keep K < `floor(kv_cache_tokens / max_model_len)`.**

| At p = 0.3 | K=1 | K=6 | K=16 | **K=32** |
|---|---:|---:|---:|---:|
| Solve rate | 30.0 % | 88.2 % | 99.7 % | **99.999 %** |
| Wall clock | 1.00× | 1.07× | 1.11× | **1.21×** |

### 30% → 99.999% correct, for 21% more time.
*A GPU property converted directly into a correctness property.*

---

## AND THE ACCESS PATTERN IS ITSELF THE OPTIMIZATION

Verified search sends K prompts that are **identical** but for temperature.
An ordinary agent sends K *different* prompts. Measured, same GPU, K=16:

| | prefix-cache hit | agg tok/s | wall |
|---|---:|---:|---:|
| **Verified search** | **99.51 %** | **410.9** | **9.97 s** |
| Distinct prompts | 1.35 % | 292.9 | 13.98 s |

**1.40× throughput at 0.71× wall clock — free.**

---

## WHAT WE DO NOT CLAIM

| | |
|---|---|
| **ProgramBench** | **0 / 200.** A provenance audit retracted 62 of 67 prior "solves" as upstream source builds. Zero is the honest figure — and it matches every public frontier model. |
| **AMD free API** | Never executed. Portal needs a China-registered account. Wired, labelled, not claimed. |
| **~46 GiB VRAM** | *Derived* from KV-block telemetry under a stated bf16 assumption — not read from `rocm-smi`. |
| **Local Ollama path** | Documented, not measured on a physical Radeon card. |

*A benchmark number that cannot survive a provenance audit is worth less than a zero that can.*

---

```
github.com/DarthCeltic/Determinex          AGPL-3.0-or-later
python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 6
```
