# Determinex — Track 2 Submission

**2026 AMD Radeon GPU Hackathon · Track 2: Development & Local Deployment of Private AI Agents**

| | |
|---|---|
| **Submitter** | DarthCeltic |
| **Project** | Determinex |
| **Source code** | https://github.com/DarthCeltic/Determinex |
| **License** | AGPL-3.0-or-later |
| **AMD hardware used** | AMD Radeon Cloud, ROCm 7.2.1, vLLM 0.16.1, Qwen2.5-Coder-7B-Instruct |

---

## What Determinex is

A local-first, **compiler-verified** multi-agent coding system. The distinguishing idea is
that no language model is ever trusted to judge its own output — a real compiler or a real
test suite is the only oracle. A model proposes; the oracle disposes.

That design has a specific consequence on GPU hardware, and it is what this submission
measures: because correctness comes from sampling K candidates and verifying each,
`P(success) = 1 − (1 − p)^K`, the system's accuracy is bounded by **GPU batch throughput**
rather than by model quality. A GPU that can serve 6 concurrent candidates for roughly the
price of 1 converts raw throughput directly into correctness.

---

## Headline result, measured on a Radeon GPU

| Mode | Throughput | Wall clock |
|---|---|---|
| Single stream | 30.0 tok/s | 17.05 s |
| **K=6 concurrent** (the VerifiedSearch pattern) | **166.9 tok/s aggregate** | **18.41 s** |

**5.56× aggregate throughput for 1.08× the wall clock.** Sampling six verified-search
candidates costs 8% more time than sampling one. On this hardware, correctness
amplification is close to free.

Measured three times, on two separate instances — 5.56× / 5.61× / 5.73×, at 1.08× /
1.07× / 1.05× wall clock respectively. Absolute rates move with instance load; the
ratio does not, and the ratio is the claim. The third run is the one in the demo
video, so the figure on screen can be checked against this document.

**Then we swept K instead of stopping at 6.** Throughput scales near-linearly to
**K=32 — 25.8× the tokens for 1.21× the wall clock** — and collapses at K=64, exactly
where vLLM's own boot log says it must (`Maximum concurrency for 8,192 tokens per
request: 61.83x`). That gives a rule any Radeon owner can apply: keep K below
`floor(kv_cache_tokens / max_model_len)`. At p=0.3, K=32 is **99.999%** correct.

**And the architecture's access pattern is itself an optimization.** Verified search
sends K prompts identical but for temperature, which hits the prefix cache **99.51%**
of the time versus **1.35%** for an ordinary agent's K distinct prompts — worth 1.40×
throughput at 0.71× wall clock, for free. Full data and method in
[`PROJECT_SPEC.md`](PROJECT_SPEC.md) §5.2a–5.2b.

Applied to the amplifier's own math: a generator with per-attempt `p = 0.3` goes from 30%
to `1 − 0.7^6 = 88.2%` for that 8% time premium.

Raw data: [`amd_gpu_evidence/throughput_measured.json`](amd_gpu_evidence/throughput_measured.json).

---

## What the AMD GPU run actually found — a real bug

This is the part worth reading. Pointing Determinex at Radeon hardware immediately produced
a failure that months of local Ollama use had hidden.

The flagship "idea → verified program" path was asked for a run-length encoder. It reported:

```
result: not solved  samples=12
[vs] r1 s1/6 t=0.0 gen 9s verify 1s -> 1 fail (score 0.00)     (×12)
```

**The model was right all twelve times.** Every candidate was a correct implementation
wrapped in a ```` ```python ```` fence — which the harness's own prompt explicitly demands
("Return ONLY the code in a ```python block"). Fence-stripping was applied in exactly one
place, inside the Ollama generator. So the Ollama path was fence-safe and **every other
provider** handed markdown to the oracle, where `from solution import *` raised a
SyntaxError and every check failed. The system then reported a *correctness verdict* about
a model that had answered correctly a dozen times.

Fixed by stripping at the single boundary every candidate crosses, rather than in one
provider. Same model, same prompt, same oracle, same GPU:

```
result: SOLVED  samples=1
proof: program PASSES all 4 synthesized checks (oracle-verified, 1 samples).
```

Twelve false failures → a first-sample pass.

Three things about this are the actual submission:

1. **The oracle caught it, not a human.** A uniform 0.00 across every sample and every
   temperature is a *harness* signature; a genuinely weak model fails in varied ways. That
   distinction is now a documented rule the system consults.
2. **A green test suite carried the bug.** An existing regression test fed fenced code and
   asserted only that no *generation error* occurred — never that the build solved. The new
   guard asserts the outcome, and was negative-controlled (reverting the fix fails 4 of 7).
3. **The system learned it.** The failure class was written into the knowledge corpus as a
   symptom→fix pattern, so the grounded fixer applies it first next time. It is retrievable:
   querying the corpus for *"candidate scores 0.00 not solved fenced"* returns it as the top
   hit.

---

## GPU evidence

Beyond throughput, the serving layer's own telemetry pins the hardware
([`amd_gpu_evidence/vllm_metrics.txt`](amd_gpu_evidence/vllm_metrics.txt)):

```
vllm:cache_config_info{block_size="16", num_gpu_blocks="31504",
                       gpu_memory_utilization="0.9", ...}
```

31,504 GPU KV blocks × 16 tokens = **504,064 tokens of KV cache**. For
Qwen2.5-Coder-7B-Instruct (28 layers, 4 KV heads, 128 head-dim, bf16) that is 56 KiB/token
= **26.9 GiB of KV cache on the device**, plus ~14.2 GiB of bf16 weights = 41.1 GiB at
`gpu_memory_utilization=0.9`, implying **~46 GiB of Radeon device memory**. The container
image is `amd-oneclick-base:rocm7.2.1-py3.12`.

---

## Contents

| Path | What it is |
|---|---|
| `README.md` | This index |
| `PROJECT_SPEC.md` | The Track 2 specification document (5 required sections) |
| `amd_gpu_evidence/throughput_measured.json` | Single vs K=6 concurrent measurements |
| `amd_gpu_evidence/vllm_metrics.txt` | vLLM Prometheus telemetry from the Radeon instance |
| `amd_gpu_evidence/raw_model_output_incorrect.json` | Raw model call — an unstaged example of the wrong answer the oracle exists to reject |
| `DEMO_VIDEO.md` | Demonstration video link + shot list |
| `POSTER.md` | Supplementary material (Track 2 item 4) |

---

## Reproducing the measurements

```bash
git clone https://github.com/DarthCeltic/Determinex && cd Determinex

# Launch a Radeon Cloud instance: Deploy Type = "vLLM Model API",
#   vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --host 0.0.0.0 --port 8000
# The ready dialog gives a base URL and an API key. Put both in .env:
#   AMD_BASE_URL=https://.../spaces/<id>/8000/v1
#   AMD_API_KEY=sk-...

# idea -> oracle -> verified program, executed on the Radeon GPU
python scripts/determinex_build_from_idea.py \
    --idea your_idea.md --provider vllm --lang python --k 6
```

The `vllm` provider reaches any OpenAI-compatible vLLM server, local or hosted; a Radeon
Cloud instance is just the hosted case.

---

## Honest boundaries

Stated plainly, because a submission that overstates is worth less than one that doesn't:

- **ProgramBench: 0/200 resolved.** A 2026-06-30 provenance audit found that 62 of 67 prior
  "solves" were upstream source builds rather than reimplementations, and they were
  retracted. 0/200 is the honest figure under the legitimate methodology, and it matches
  public leaderboard reality for every frontier model.
- **AMD's free Token Factory endpoint was never exercised.** Its portal requires a
  China-registered account. Those `litellm_config.yaml` entries are wired and labelled
  unverified. Nothing in this submission depends on them.
- **The throughput figures are end-to-end**, including trans-Pacific network latency, and
  are a property of this GPU and this batch size. They should be re-measured per device.
- **SWE-bench Lite 14.0%** is an audited May-2026 snapshot pending a clean re-run.
- **The `~46 GiB` VRAM figure is derived** from KV-block telemetry under a stated bf16
  assumption, not read from `rocm-smi` — the Model API deploy type provides no shell.
