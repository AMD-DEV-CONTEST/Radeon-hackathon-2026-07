# Determinex — Track 2 Project Specification

**2026 AMD Radeon GPU Hackathon · Track 2: Development & Local Deployment of Private AI Agents**

**Submitter:** DarthCeltic · **Source:** https://github.com/DarthCeltic/Determinex ·
**License:** AGPL-3.0-or-later · **Date:** 2026-07-31

---

## 1. Application Scenarios

### The problem

Cloud AI coding tools require sending proprietary source to a third party, with no
cryptographic guarantee about retention, training use, or jurisdiction. For regulated
industries and IP-sensitive work that is not a trade-off, it is a disqualifier.

Local alternatives trade that risk for a worse one: a single small model with no
verification layer. A 1.5B model proposing wrong code *confidently* is more dangerous than
no assistant, because the reviewer's attention is the scarce resource.

Determinex refuses both. It runs locally on the developer's own hardware — including AMD
Radeon GPUs — and it never trusts a model's self-assessment. A real compiler or a real test
suite is the only judge.

### Who it is for

| Scenario | How Determinex handles it |
|---|---|
| Build a program from a plain-language idea | Synthesizes a *sound* test oracle first, then drives verified search until a program passes it |
| Repair a broken repository | Ingests the project, runs its real oracle, assigns honest blame: CODE / ENVIRONMENT / TEST |
| Use a cloud model without exposing source | Project Cloak obfuscates identifiers via AST rewriting before any outbound call |
| Evaluate a local model honestly | Compiler-validated probe harness; no LLM-as-judge anywhere in the loop |

### Why this matters on AMD hardware specifically

Determinex's accuracy is a function of how many candidates it can verify, not of how good
any single generation is. That makes it one of the few agent architectures where **GPU
batch throughput converts directly into correctness** — quantified in §5.

---

## 2. Agent Architecture

```
                    ┌───────────────────────────┐
   idea / spec ───► │  C7 ARCHITECT             │  decomposes into an ordered DAG
                    │  (7B, Mistral-family)     │  of build steps, emitted as DSL
                    └────────────┬──────────────┘
                                 │ DAG
                                 ▼
                    ┌───────────────────────────┐
                    │  C1 BUILDER               │  writes code for one step
                    │  (1.5B, Qwen2.5-Coder)    │  K candidates, varied temperature
                    └────────────┬──────────────┘
                                 │ K candidates          ◄── the AMD GPU does this in parallel
                                 ▼
        ╔════════════════════════════════════════════════╗
        ║  ORACLE — deterministic, not a model           ║
        ║  rustc · go build · python+tests · tsc         ║
        ║  PASS → commit step to WAL → next step         ║
        ║  FAIL → inject the exact compiler error → retry║
        ╚════════════════════════┬═══════════════════════╝
                                 │ verified / refuted
                                 ▼
                    ┌───────────────────────────┐
                    │  C3 MONITOR (3B, Llama-3.2)│ scores, may submit a rival approach
                    └────────────┬──────────────┘
                                 ▼
                    ┌───────────────────────────┐
                    │  ADJUDICATOR              │  may only declare IMPOSSIBLE with a
                    │  ROUTE→MATCH→UNBLOCK→     │  proof; everything else is NEEDS_WORK
                    │  IMPOSSIBLE               │
                    └───────────────────────────┘
```

### The amplification mechanism

```
per-attempt success probability   p
K candidates sampled, each verified against a sound oracle

    P(at least one correct) = 1 − (1 − p)^K
```

Any `p > 0` is driven toward correct by increasing K. The model supplies search; the oracle
supplies truth. **The soundness of the oracle is load-bearing** — a garbage oracle yields
confident garbage — which is why every synthesized oracle is validated to actually execute,
and why an oracle that can only assert "the symbol exists" is rejected as vacuous rather
than reported as a pass.

### The design rule this project is built on

*A check must never report an outcome it did not establish.* §5.5 documents a live example
where the system violated that rule against AMD hardware, and what was changed.

---

## 3. Core Capabilities

**3.1 Compiler-verified build loop.** `rustc`, `go build`, Python (syntax → import → test
discovery), and `tsc --noEmit` in a purpose-built container. Languages without a configured
oracle **fail closed** with an actionable message — they are never silently passed. Every
oracle refuses an empty workspace, because a build step whose patch went nowhere would
otherwise be recorded as verified.

**3.2 Multi-agent hive.** Three specialists exchange a structured DSL rather than prose.

**3.3 Project Cloak.** AST-aware identifier obfuscation across 10 languages, so a cloud
model can assist without seeing proprietary names. Stated precisely: audits confirm that
*everything Cloak obfuscated stayed obfuscated*. Extraction completeness is a separate
property with its own test — which has caught real gaps, including JavaScript instance
fields written `this.field = 0` surviving obfuscation until they were fixed. The
distinction is documented rather than smoothed over.

**3.4 Self-improving flywheel.** Verified solves are distilled into generalized symptom→fix
classes that the fixer applies first on the next occurrence. §5.5 was added to that corpus
during this hackathon and is queryable.

**3.5 Benchmarks — stated honestly.**

| Benchmark | Result | Status |
|---|---|---|
| ProgramBench (200 CLI reimplementations) | **0/200** | Honest baseline. 62 of 67 prior "solves" were retracted by a 2026-06-30 provenance audit as upstream source builds. Matches public frontier-model reality (0–0.5%). |
| SWE-bench Lite | 14.0% (42/300) | Audited May-2026 snapshot; clean re-run pending |
| Micro-eval, Engineer v11-dsl | 81.4% (57/70) | Compiler-validated probes |
| Micro-eval, Observer v6-dsl | 75.7% (53/70) | Compiler-validated probes |

The zero is reported deliberately. A benchmark number that cannot survive a provenance
audit is worth less than a zero that can.

---

## 4. Models & Local Deployment

### 4.1 Model family

| Agent | Params | Base | Role |
|---|---|---|---|
| C1 Engineer v11-dsl | 1.5B | Qwen2.5-Coder | Builder |
| C3 Observer v6-dsl | 3B | Llama-3.2 | Monitor |
| C7 Sentinel v5-dsl | 7B | Mistral | Architect |

Published at `huggingface.co/darthceltic85` (`determinex-engineer`,
`determinex-observer-llama-3.2`, `determinex-sentinel`).

The small sizes are the point: a 1.5B builder is viable *because* the oracle catches its
mistakes and verified search retries. Model quality sets `p`; the system sets `K`.

### 4.2 Deployment on AMD Radeon

Two supported paths. Both reach the same `generate(prompt, temperature) -> str` contract,
so nothing downstream knows which produced a candidate.

**Path A — hosted vLLM on a Radeon GPU** (the path measured in this submission):

```bash
# Radeon Cloud → Add Template → Deploy Type = "vLLM Model API"
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --host 0.0.0.0 --port 8000

# .env
AMD_BASE_URL=https://.../spaces/<id>/8000/v1
AMD_API_KEY=sk-...

python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 6
```

**Path B — local Ollama on ROCm:**

```bash
curl -fsSL https://ollama.com/install.sh | sh    # auto-detects ROCm
rocminfo | grep gfx                               # gfx1100 = RDNA3
ollama pull qwen2.5-coder:14b-instruct-q4_K_M
```

**Verification status, stated exactly:** Path A is verified — every number in this document
came from it. Path B's ROCm auto-detection is Ollama's documented behaviour and Determinex's
accelerator probe covers AMD, but this submission did not run Path B on a physical Radeon
card, so it is presented as supported-and-documented, not as measured.

### 4.3 A note on key hygiene

AMD exposes two unrelated endpoints: your own instance, and a shared free endpoint on a
third-party host. They now use **two distinct environment variables**
(`AMD_API_KEY` / `AMD_FREE_API_KEY`). They shared one until this work, which would have
transmitted a dedicated-instance key to the shared host on any call routed to the free
models. Found while wiring the Radeon endpoint.

---

## 5. Optimization for Inference on AMD Radeon GPU

### 5.1 Measured throughput

Qwen2.5-Coder-7B-Instruct, vLLM 0.16.1, ROCm 7.2.1, 512-token completions:

| Mode | Completion tokens | Wall clock | Throughput |
|---|---|---|---|
| Single stream | 512 | 17.05 s | 30.0 tok/s |
| **K=6 concurrent** | 3,072 | **18.41 s** | **166.9 tok/s** |

**5.56× aggregate throughput at 1.08× wall clock.** Measured end-to-end including network.

#### Reproduced three times, on two separate instances

A single measurement of a batching effect is weak evidence, so it was repeated —
including on a different instance type, and once on camera:

| Run | Instance | Single | K=6 aggregate | Speedup | Wall-clock cost |
|---|---|---:|---:|---:|---:|
| 1 | vLLM Model API endpoint | 30.0 tok/s | 166.9 tok/s | 5.56× | 1.08× |
| 2 | Notebook instance, local vLLM | 31.9 tok/s | 179.0 tok/s | 5.61× | 1.07× |
| 3 | Notebook instance (the demo video) | 32.6 tok/s | 186.9 tok/s | **5.73×** | **1.05×** |

The absolute rates vary with instance load; the *ratio* does not. Across all three,
sampling six verified-search candidates cost between 1.05× and 1.08× the wall clock
of sampling one, for 5.56–5.73× the aggregate tokens. That stability is the claim —
not any single figure. Run 3 is visible in the demo video, so the number on screen
and the number in this document can be checked against each other.

### 5.2 Why that number is the whole thesis

Verified search costs K generations per solve. If K generations cost K× the time, the
amplifier is a straight latency-for-accuracy trade. On this GPU they cost 1.08×, because
vLLM's continuous batching fills the device with concurrent sequences that would otherwise
idle during memory-bound decode.

So on Radeon hardware:

| | one sample | six samples |
|---|---|---|
| Wall clock | 17.05 s | 18.41 s (+8%) |
| P(correct) at p=0.3 | 30.0% | **88.2%** |

Correctness nearly triples for an 8% time premium. **This is a GPU property being converted
into a correctness property** — it is the concrete answer to "how does this project use the
AMD GPU", and it is why the architecture suits this hardware rather than merely running on it.

### 5.2a Choosing K: the scaling curve, and exactly where it breaks

K is the one knob that converts GPU capacity into correctness, so it was swept rather
than guessed. Same model, same GPU, 256-token completions:

| K | aggregate tok/s | wall clock | vs K=1 |
|---:|---:|---:|---|
| 1 | 28.7 | 8.92 s | — |
| 8 | 220.3 | 9.30 s | 7.7× tokens, 1.04× time |
| 16 | 413.5 | 9.91 s | 14.4× tokens, 1.11× time |
| **32** | **739.9** | **10.75 s** | **25.8× tokens, 1.21× time** |
| 48 | 849.7 | 13.62 s | 29.6× tokens, 1.53× time |
| 64 | 512.6 ↓ | 29.59 s ↓ | **collapse** |

Throughput scales near-linearly to K=32 while wall clock barely moves. Then K=64 falls
off a cliff — throughput drops below K=24 and wall clock nearly triples.

**The cliff is predictable, not mysterious.** vLLM announces its own limit at boot:

```
GPU KV cache size: 506,544 tokens
Maximum concurrency for 8,192 tokens per request: 61.83x
```

K=64 exceeds 61.83, so requests preempt instead of batching. The measured collapse sits
exactly where the KV arithmetic says it must. That yields a deployment rule any Radeon
owner can apply without re-running this sweep:

> **Keep K below `floor(kv_cache_tokens / max_model_len)`** — read both from vLLM's boot
> log. Here that is `506544 / 8192 = 61`, and 64 broke.

Correctness follows directly, since `P = 1 − (1 − p)^K`. For a generator right 30% of the
time: K=6 → 88.2%, K=16 → 99.7%, **K=32 → 99.999%, for 1.21× the wall clock of a single
sample.**

### 5.2b The agent's access pattern is itself a GPU optimization

Verified search issues K requests whose prompts are **identical**, differing only in
sampling temperature. That is close to the ideal case for a prefix cache, and unusual —
an ordinary multi-request agent sends K *different* prompts. Both arms were measured:

| K | arm | prefix-cache hit rate | aggregate tok/s | wall clock |
|---:|---|---:|---:|---:|
| 16 | verified search (shared prefix) | **99.51%** | 410.9 | 9.97 s |
| 16 | distinct prompts | **1.35%** | 292.9 | 13.98 s |
| 32 | verified search (shared prefix) | **99.51%** | 748.5 | 10.73 s |
| 32 | distinct prompts | 49.59% | 517.6 | 15.83 s |

**1.40× the throughput at 0.71× the wall clock, for free**, purely because of how the
architecture happens to query the model. `enable_prefix_caching=True` is therefore not a
generic nicety here — it is load-bearing for this workload specifically.

> **Method note, because it changed the answer.** The first version of this A/B appended
> the variant marker to the *end* of each distinct prompt. The long prefix stayed shared,
> the "distinct" arm scored a 99% hit rate too, and the gap looked like ~30%. Diverging at
> token 0 is what actually defeats a prefix cache. The corrected arm drops to 1.35%. A
> control that does not control is worse than no control, so the flawed version is
> reported here rather than quietly replaced.

Raw data for all three sweeps: [`amd_gpu_evidence/k_sweep_and_prefix_cache.json`](amd_gpu_evidence/k_sweep_and_prefix_cache.json).

### 5.2c Measuring `p` directly — including where the architecture stops working

`P = 1 − (1 − p)^K` is the load-bearing claim, and `p` is normally assumed. We measured it:
**960 independent generations on the Radeon GPU**, 192 per task across five difficulties,
every candidate verified against the same synthesized oracle. Sampling at fixed temperature
0.6 so the draws are i.i.d. and `p` is well defined, at concurrency 32 — using this
project's own K-sweep result to run its own experiment faster.

| Task | checks | passes / 192 | p |
|---|---:|---:|---:|
| `rle` | 4 | 192/192 | **1.000** |
| `rle` + double-digit run lengths | 6 | 192/192 | **1.000** |
| `gron` (JSON flattening) | 4 | 0/192 | 0.000 |
| `gron` | 5 | 1/192 | 0.005 |
| `gron` + JSON-literal semantics | 6 | 0/192 | **0.000** |

Three things follow, and two of them are uncomfortable.

**1. Our own demo task is trivial.** `rle` — the task in our demo video — is solved by this
model **192 times out of 192**, and stays 192/192 after adding double-digit run lengths.
Verified search contributes nothing there, because there is nothing to rescue. We would
rather state that than let a judge infer it.

**2. Amplification has a floor, and we hit it.** At `p = 0`, `1 − (1 − 0)^K = 0` for every
K. No amount of sampling rescues a model that cannot do the task at all. The white-paper
phrasing "any `p > 0` is driven toward correct" is exactly right and exactly load-bearing:
**verified search multiplies capability, it cannot manufacture it.** That boundary is
measured here, not assumed.

**3. Competence looked near-bimodal.** We could not find a task in the middle within budget.
Removing the array case from `gron` did not raise `p`, so the barrier is
container-declaration semantics rather than indexing. For this model on this family, the
transition from 1.000 to ~0.000 is sharp.

> **Honest limit on the curve fit.** At `p = 0.0052` the bootstrap solve-rate curve tracked
> `1 − (1 − p)^K` to a maximum absolute error of **0.0021** across K=1…32. With a single
> success in the pool that is close to tautological — resampling one positive nearly
> reproduces the binomial by construction. It is *consistent with* the law, not strong
> evidence *for* it. A proper validation needs a task with mid-range `p`, which we did not
> find in the credits available.

**What this means in practice.** Verified search is worth nothing at `p = 0`, nothing at
`p = 1`, and everything in between — but §5.2a shows the *cost* is near-zero out to K=32
(1.21× wall clock for 25.8× the tokens). So the correct deployment policy is not to tune K
per task. It is to **run large K always**: nearly free on this hardware, and it pays exactly
when `p` lands in the middle, which you cannot know in advance.

Raw data: [`amd_gpu_evidence/measured_p_and_amplification.json`](amd_gpu_evidence/measured_p_and_amplification.json).

### 5.3 Memory configuration

Telemetry from the running instance:

```
block_size=16 · num_gpu_blocks=31504 · gpu_memory_utilization=0.9 · enable_prefix_caching=True
```

504,064 tokens of KV cache = 26.9 GiB on device (56 KiB/token at 28 layers × 4 KV heads ×
128 head-dim, bf16), plus ~14.2 GiB of weights — implying ~46 GiB of Radeon device memory.
The headroom is what permits K=6 concurrency without KV eviction; `kv_cache_usage_perc`
stayed at 0.0 throughout, so the concurrency measurement was never cache-bound.

`enable_prefix_caching=True` matters more here than in ordinary serving: verified search
sends K near-identical prompts, so the shared prefix is computed once and reused K−1 times.

### 5.4 Quantization guidance (Path B)

| GPU | VRAM | Model |
|---|---|---|
| RX 7900 XTX | 24 GB | qwen2.5-coder:32b-instruct-q4_K_M |
| RX 7800 XT | 16 GB | qwen2.5-coder:14b-instruct-q4_K_M |
| RX 7600 | 8 GB | qwen2.5-coder:7b-instruct-q4_K_M |

VRAM fit is arithmetic from published quantization sizes; throughput on these specific cards
was not measured and no figures are claimed for them.

### 5.5 What running on AMD hardware exposed

The first Radeon run of the flagship path reported `not solved, samples=12`, with all twelve
candidates scoring 0.00 at every temperature.

Every candidate was correct. All twelve were valid implementations inside a ```` ```python ````
fence — which the harness's own prompt *demands*. Fence-stripping existed in exactly one
place, inside the Ollama generator, so the Ollama path worked and every other provider
delivered markdown to the oracle, where the module failed to import and every assertion
failed. The system reported a verdict about a model that had been right twelve times.

The fix strips at the one boundary all candidates cross. Same model, prompt, oracle and GPU:
**SOLVED on sample 1.**

Three durable outcomes:

1. **A diagnostic rule, now in the corpus:** a uniform 0.00 across every sample *and* every
   temperature is a harness signature — a weak model fails in varied ways. An import error
   on every candidate means the harness is wrong; an assertion failure means the model is.
2. **A regression guard, negative-controlled.** The pre-existing test fed fenced code and
   asserted only that no *generation error* occurred, never that the build solved — which is
   how a green suite carried this. The new tests assert the outcome; reverting the fix fails
   4 of 7.
3. **A provider fix.** The `vllm` provider could not reach a *remote* vLLM at all: it sent no
   bearer token and probed `{base}/health`, which does not exist under a hosted `/v1` base
   URL, so a working endpoint reported itself unavailable. It now probes `/models` first and
   carries an optional key. No AMD-specific provider was added — the general one was made
   correct.

That is the honest AMD story: the hardware ran the workload, and pointing a
verification-first architecture at a new backend surfaced a class of defect that months of
single-provider use had concealed.

---

*Determinex · DarthCeltic · AGPL-3.0-or-later*
