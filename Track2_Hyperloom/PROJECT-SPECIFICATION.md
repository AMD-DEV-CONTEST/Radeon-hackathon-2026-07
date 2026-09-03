# Hyperloom — Project Specification

**AMD AI DevMaster Hackathon · Track 2: Development & Local Deployment of Private AI Agents**

Hyperloom is a private, locally-deployed AI agent that makes AMD Radeon GPUs faster at LLM
inference — autonomously. It detects the exact silicon, maps that silicon's real instruction-set
capability using the assembler as ground truth, finds where shipped kernels leave performance
unused, writes and tunes correctness-gated HIP kernels to close the gap, and measures the result
on the card.

Its core inference runs entirely on an AMD Radeon GPU. Nothing about its reasoning loop depends
on a cloud API.

---

## 1. Application scenarios

**Who this is for.** Anyone running LLM inference on AMD Radeon hardware who is leaving
performance on the table and does not have a kernel engineer on staff.

| Scenario | The problem today | What Hyperloom does |
|---|---|---|
| **A new Radeon part ships** | Vendor kernel libraries lag the silicon. RDNA4 (gfx1201) has instructions no shipped kernel uses, and library support is scoped to data-center parts. | Scans the ISA with the assembler, finds the unexploited instruction, writes a kernel that uses it. |
| **Local/private LLM serving** | Users who cannot send data to a cloud must self-host, and self-hosted throughput on prosumer cards is often far below the hardware's ceiling. | Raises measured decode/prefill throughput on the user's own card, with correctness gates so speed never costs accuracy. |
| **A performance claim needs auditing** | Speedup claims routinely measure the wrong thing — cache instead of DRAM, a strawman baseline, a dead code path. | Owns the measurement: prints working-set size, compares against a measured roofline, and flags its own invalid readings. |
| **Multi-GPU tensor parallelism** | RCCL has no gfx1201 tuning index, so the stock all-reduce falls back to unrelated tuning and stalls. | Routes around it by compressing the payload (INT6 with shared scale, exact-integer reduce). |

**Why it matters.** The prosumer/workstation long tail is exactly where vendor optimization
effort arrives last. An agent that can do this work unattended turns "wait for the vendor" into
"close it yourself tonight."

---

## 2. Agent architecture

```
                    ┌────────────────────────────────────────────────┐
                    │  CORE INFERENCE — 100% LOCAL, AMD Radeon GPU   │
                    │  Lemonade (:13305) serving a tool-calling      │
                    │  model on the R9700. No cloud in the loop.     │
                    └───────────────────────┬────────────────────────┘
                                            │
   ┌────────────────────────────────────────▼─────────────────────────────────────┐
   │                          MISSION LOOP (reason → plan → act)                  │
   │                                                                              │
   │   DETECT ──► SCAN ──► FIND GAP ──► WRITE ──► CORRECTNESS GATE ──► MEASURE    │
   │      │         │          │           │              │              │        │
   │      │         │          │           │              │              ▼        │
   │      │         │          │           │              │      ┌──────────────┐ │
   │      │         │          │           │              └─FAIL─┤  VERIFY THE  │ │
   │      │         │          │           │                     │ MEASUREMENT  │ │
   │      │         │          │           └─────────────────────┤ vs roofline, │ │
   │      │         │          │                                 │ working set  │ │
   │      │         │          │                                 └──────┬───────┘ │
   │      │         │          └── layered fault isolation               │        │
   │      │         │              L1 silicon → L2 driver → L3 runtime   │        │
   │      │         │              → L4 compiler → L5 kernel → L6 format │        │
   │      │         │              → L7 serving                          │        │
   │      │         │                                                    ▼        │
   │      │         └── ISA ground truth (llvm-mc: the assembler cannot lie)      │
   │      └── hardware.py: 18 AMD targets (RDNA2-next, CDNA1-4, Zen, XDNA, APU)   │
   └───────────────────────────────┬──────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                           ▼
  ┌───────────┐            ┌──────────────┐            ┌──────────────┐
  │  TOOLS    │            │   MEMORY     │            │ ESCALATION*  │
  │ scan-isa  │            │ persists     │            │ stuck-detect │
  │ disasm    │            │ across       │            │ → structured │
  │ hipcc     │            │ attempts,    │            │   packet     │
  │ magpie    │            │ so a closed  │            │ → AMD-hosted │
  │ profile   │            │ path is not  │            │   assist     │
  │ bench     │            │ re-explored  │            │ → RE-GATED   │
  └───────────┘            └──────────────┘            │   LOCALLY    │
                                                       └──────────────┘
```

\* **The escalation path is designed but not wired in.** `agent/escalation.py` exists and its
stuck-detector and packet-builder are unit-tested offline, but nothing in the agent loop calls it
and no cloud endpoint is configured. It is shown here because it is the intended shape, not
because it runs today.

**Why it is shaped that way.** When the agent is stuck (N correctness-gated
failures, degenerate looping, or explicit self-report), it builds a *structured* packet — which
isolation layer, verbatim evidence, what was already tried — and asks for help. The answer is
treated as **assumed until it passes a local correctness gate on the actual Radeon GPU**. Core
inference never leaves the card; assistance is advisory and must earn its way in by measurement.

---

## 3. Core capabilities

**1. Silicon-accurate ISA mapping.** `toolkit/scan-isa-gfx.sh` probes the target with `llvm-mc`
and classifies every candidate instruction as REAL / EMULATED / REJECTED. Marketing claims and
header definitions both lie; the assembler does not. A 351-builtin sweep on gfx1201 found 54 real,
and three that stock llama.cpp never emitted: `v_dot8_i32_iu4`, `v_dot2_f32_f16`,
`v_dot4_f32_fp8`. They are no longer unused, and the census in
`results/roc9-unused-isa-sweep.md` shows why — it was taken *after* this work, and
counts them at 4, 125,666 and 110 emissions respectively, all from kernels added
here. The two that remain genuinely unemitted on that census are
`v_swmmac_i32_16x16x64_iu4` and `v_dot2_f32_bf16`.

**2. Correctness before speed, without exception.** Every kernel is gated bit-exact against a CPU
reference *before* any timing is reported. A fast-but-wrong kernel exits non-zero. In the prefill
benchmark this is 3 kernels × 4 shapes, all `max_abs_err=0`, before a single number prints.

**3. Measurement integrity — the agent audits itself.** This is the capability we consider most
important, because it is the one most optimizers lack. The harness prints its own working-set size
and compares throughput against a *measured* roofline. A reading above roofline means cache was
measured, not DRAM — so the harness says so:

```
N=14336 K=4096  |  31.5 MiB (CACHE-RESIDENT!) | 792 GB/s | 126% of roofline
N=65536 K=4096  | 144.0 MiB (DRAM-honest)     | 604 GB/s |  96% of roofline
```

This caught a real error in our own submission: the decode benchmark had been measuring a
cache-resident working set and reporting 122% of roofline. An optimizer you can trust has to be
able to prove itself wrong.

**4. Layered fault isolation.** Faults are diagnosed at their real layer (silicon → driver →
runtime → compiler → kernel → format → serving) rather than guessed at across the stack.

**5. Portable across the AMD substrate.** `hardware.py` covers 18 AMD AI targets — RDNA2-next
through CDNA1-4, Zen CPU, XDNA NPU, and APUs — so the method is not gfx1201-specific even though
gfx1201 is where it is proven.

---

## 4. Model and local deployment plan

**Brain.** `Qwen-AgentWorld-35B-A3B` (35B total, ~3B active per token — a mixture-of-experts
model), quantized to **Q4_K_XL GGUF**, ~20.8 GB on disk and ~27 GB resident in VRAM once loaded.
Served locally by **Lemonade** on `:13305`, pinned to one card so it fits in 32 GB. It is chosen
for reliable tool-calling rather than raw size: an earlier 35B dense candidate failed the same
agentic fixture this model passed. The agent talks to it over an OpenAI-compatible endpoint at
`http://localhost:13305/v1`. Swapping the brain is a config change (`LEMONADE_URL`, model name),
not a code change.

**Everything generative is local.** The demo materials in this repository were produced on the
same single R9700 — narration by `kokoro-v1`, imagery by `Flux-2-Klein-9B` — through the same
Lemonade endpoint. The artifact is produced by the stack it documents.

**Deployment.**

```bash
git clone https://github.com/The-Monk/rocky-hackathon && cd rocky-hackathon
# 1. ROCm + hipcc for your Radeon target
hipcc --version
# 2. the mission loop, end to end on the card
./demo/run_demo.sh
# 3. reproduce any individual claim
cd kernels/decode && hipcc --offload-arch=gfx1201 -O3 decode_mmvq_iu4.hip -o d && ./d
```

Full environment configuration, startup guide and dependency list are in `README.md` (section "Environment configuration, startup, and dependencies");
per-claim reproduction commands are in `benchmarks/README.md`. A container build
(`container/Containerfile`) is provided for a pinned toolchain.

**Hardware validated on:** AMD Radeon AI PRO R9700 (gfx1201 / RDNA4), 32 GB, ROCm 7.x.

---

## 5. Inference-speed optimization on AMD Radeon GPU

Three measured, correctness-gated results across the inference stack. Every number below is
reproducible from a clean clone of the public repository, on the card.

| Stage | Optimization | Measured result |
|---|---|---|
| **Decode** | `k_mmvq_dot8_iu4` — native `v_dot8_i32_iu4`, one block per row, coalesced K-stride, shared-memory reduction | **604–613 GB/s = 96–97% of the measured 631 GB/s DRAM roofline.** Memory-bound and saturating. `max_rel_err=1.1e-04` PASS |
| **Prefill** | int4 2:4-sparse SWMMAC (`v_swmmac_i32_16x16x64_iu4`) full GEMM | **3.67× vs int8 K16 WMMA at K=8192** (91.6 vs 25.0 TOP/s, `benchmarks/README.md` §2) — 88–95% of the 3.90× raw-instruction ISA ceiling. All correctness gates `max_abs_err=0` |
| **Comms** | INT6 inline-compressed all-reduce, shared scale | **2.46× payload reduction vs fp16**, mean `rel_l2 = 0.0239`, routing around the RCCL gfx1201 tuning gap |

**On the decode number specifically.** The naive route — one thread per row — looks 2.2× faster
with the native instruction, and that A/B is real *as an instruction comparison*. But it is
uncoalesced: adjacent lanes land K/2 bytes apart. That is invisible while the weights fit in the
64 MiB Infinity Cache and catastrophic once they do not — past the cache, both routes collapse to
~17 GB/s and the advantage disappears entirely. The win is the **access pattern**, not the
instruction. We report the DRAM-honest production number and state the collapse plainly rather
than leaving a judge to discover it.

**Upstream contributions.** Work from this project has been contributed back:
ROCm/composable_kernel **#3759** (3-bug 2:4-sparse SWMMAC correctness fix, `err 352 → 0` on
gfx1201) and AMD-AGI/Magpie **#70**.

---

## 6. Compliance with track rules

- **Core inference runs locally on an AMD Radeon GPU.** The agent's brain is a local model served
  by Lemonade on the R9700. There is no cloud model in the reasoning loop.
- **Not dependent on a closed-source agent platform.** The mission loop, tools, memory and
  escalation logic are in this repository (`agent/`).
- **All tooling is ROCm-native** — hipcc, llvm-mc, rocprof/metrix, Magpie.

**On "Radeon cloud".** The platform clause reads *"Must run on AMD Radeon GPU of
Radeon cloud + ROCm software stack"*, while the same track's task description asks
for a *"fully locally deployed"* agent and the clause immediately after it requires
that *"core inference processes shall be executed locally on AMD Radeon GPU; remote
APIs are not allowed for core functions."* We read the cloud reference as *where to
obtain a Radeon GPU* rather than a requirement that the GPU be rented, since the
alternative reading contradicts the two clauses around it.

This work runs on locally-owned AMD Radeon AI PRO R9700 hardware (2x, gfx1201,
RDNA4) with ROCm. If the intent was that entries must execute on Radeon Cloud
specifically, we have not met that clause and would rather say so plainly here than
have a judge discover it. We would note that RDNA4 kernel work of this kind requires
the target silicon: the fp8 and int4 dot instructions used throughout
(`v_dot4_f32_fp8_fp8`, `v_dot8_i32_iu4`) do not exist on RDNA3, so the results are
only obtainable on gfx1201.

---

## 7. Where to find each thing the Track 2 criteria ask for

This section exists so a reviewer can locate evidence directly rather than infer it.
Every row names a file in this repository or a timestamp in the demo video.

### 7.1 Minimum functional requirements (the track asks for at least 2 of 5)

Hyperloom implements **four**.

| Capability | Implemented | Where |
|---|---|---|
| **Local knowledge retrieval (RAG)** | Yes | `agent/optimizer-agent/memory.py` — `ingest_knowledge()` builds a corpus from documents the agent reads and from its own logs; `search_knowledge()` retrieves the most relevant chunks before it decides. Storage is plain JSONL under `memory/`, durable across runs and auditable. The corpus is not handed to the agent; it grows it. |
| **Tool invocation** | Yes | `agent/optimizer-agent/agent.py` drives a tool-call loop. Toolkit in `toolkit/`: `scan-isa-gfx.sh` (ISA ground truth via `llvm-mc`), `disasm-gfx.sh` (verify emitted instructions), `profile-datapath-gfx.sh`, `magpie.sh`, plus `hipcc` builds and benchmark execution. **Demo video 0:25–1:24** shows the agent declining to answer a hardware question from memory and emitting a real `scan_isa` tool call instead. |
| **Multi-step task planning** | Yes | The mission loop — DETECT → SCAN → FIND-GAPS → TUNE → FIX → VALIDATE → **AUDIT THE MEASUREMENT** — encoded in `skill/SKILL.md` and visible end to end in the demo video. Fault diagnosis is planned across seven layers (silicon → driver → runtime → compiler → kernel → format → serving) rather than guessed at. |
| **Local multi-turn memory** | Yes | `memory.py` — `remember(note, tags)` / `recall(query)`. `agent.py:run_attempt()` starts each attempt with a fresh context while **memory persists on disk across attempts**, and a diagnosis step between attempts is seeded from what previous attempts recorded. That is what stops it re-exploring a path it already closed. |
| Permission control & privacy | Partial | Private by construction: the agent's brain runs locally on the Radeon GPU, and **no inference — core or otherwise — leaves the machine**. The agent does carry optional `web_search` / `web_fetch` lookup tools; they are **disabled by default** and require `HYPERLOOM_ALLOW_WEB=1`, so a default run makes no outbound request at all. An escalation path exists (`agent/escalation.py`) and is deliberately gated — any external answer is treated as *assumed* until it passes a local correctness gate on the actual GPU. There is no separate permissions UI, so this is claimed as partial. |

### 7.2 Evaluation criteria

| Criterion | Evidence |
|---|---|
| **Task positioning & creative scenarios** | The agent operates in a domain where results cannot be faked: a kernel is either numerically correct and faster, or it is not. It targets the prosumer/workstation long tail, where vendor optimization arrives last — a new Radeon part ships, the kernel libraries lag it, and this closes the gap without waiting. |
| **Core capabilities — task decomposition, tool invocation, RAG, memory** | All four present; see 7.1 for file-level locations. |
| **Multi-turn interaction** | Demonstrated directly in the demo video: a four-turn conversation in one context, where the agent calls tools, is corrected by one of them, and refers back to what earlier turns established. Underneath, the same loop runs unattended: repeated attempts against the same objective, each with a fresh context, with durable memory and a grounded diagnosis step between them (`agent.py:run_attempt`, `diagnose`). Stated plainly — this is a multi-turn *work* loop, not a chat interface. |
| **Core inference on AMD Radeon GPU** | **Demo video 0:25–1:24**: the 35B tool-calling brain loads onto the card, Radeon VRAM goes from ~740 MB to ~27.7 GB, and the tool call is issued from it. Served locally by Lemonade. No remote API is involved in any core function. |
| **Targeted optimization for inference speed** | Three measured, correctness-gated results across the inference stack — decode at 96–97% of the measured 631 GB/s DRAM roofline, prefill 3.67× via int4 2:4-sparse SWMMAC, and an INT6 compressed all-reduce for the dual-GPU path. Reproduction commands in `benchmarks/README.md`; the routing layer and its measured abstain threshold are shown in the video at **1:24–2:07**. |

### 7.3 What this submission does not claim

Stated because a claim a reviewer can disprove is worth less than one they can check.

- There is **no graphical chat UI**. Interaction is conversational but terminal-based — see the multi-turn session in the demo video — and the agent also runs as an unattended work loop.
- Permission control is **partial** — private by construction, but without a dedicated permissions layer.
- The Radeon **cloud** bonus is **not claimed**. `agent/escalation.py` was written against that bonus and its docstring still says so, but the module is not wired into the agent loop and no cloud endpoint is configured; core inference runs entirely on local Radeon hardware.
- The prefill routing layer is **opt-in and off by default**, and validation of the individual routes is ongoing. The three headline results above are measured on the default path and reproduce from a clean clone.

---

## 8. The kernel work itself, and how it was validated

The three results in §5 are not one-off benchmarks. They live in a working fork of
llama.cpp targeting gfx1201, on a branch (`roc8`) that carries the shipping kernels,
the routing layer, and the test harness used to gate them. This section describes what
is in it and — more importantly — how it was checked, because the checking is where
most of the engineering went.

### 8.1 What is on the branch

| Area | Work |
|---|---|
| **Decode** | `k_mmvq_dot8_iu4` — native `v_dot8_i32_iu4`, one block per row, coalesced K-stride, shared-memory reduction |
| **Prefill routing** | Per-format hipBLASLt routes for Q1_0, Q2_0, Q4_K, Q8_0, F8E4M3, MXFP8, MXFP6, IU4, F16 — each opt-in, each soft-failing back to the stock kernel, each gated on a measured M threshold. These routes live in our llama.cpp fork, **public at [The-Monk/llama.cpp, branch `roc8`](https://github.com/The-Monk/llama.cpp/tree/roc8)**; what is reproducible *here* are the standalone kernels under `kernels/`. |
| **Comms** | INT6 inline-compressed all-reduce for the dual-GPU tensor-parallel path |
| **Sparsity** | int4 2:4-sparse SWMMAC GEMM (`v_swmmac_i32_16x16x64_iu4`) |

### 8.2 Two defects found by validation, not by use

Both were invisible to the testing that existed before, and each is a lesson about
what a given test can and cannot see.

**A Q4_K decode kernel that produced garbage.** A micro-optimisation replaced a
per-thread activation sum with the block sum that `q8_1` already stores. Those are not
the same quantity at that call site: each thread owns a quarter of the block, so all
four threads added the whole block's sum and the min term came out **4× too large**.
Every Q4_K model generated garbage at decode — `"The capital of France is"` produced
`|  Term???????????????`.

It had passed validation because the validation was perplexity, and
`llama-perplexity` runs at `n_batch=512`, so every matmul goes through the `mmq` path
and the broken `mmvq` decode path is **never executed**. The measurement was structurally
incapable of seeing the bug. Fix: revert the hunk; `test-backend-ops -o MUL_MAT` goes
from 1113 OK / 28 q4_K FAIL to **1143 OK / 0 FAIL**, and the model says `Paris.`

**A weight cache that returned another model's weights.** Every hipBLASLt route cached
converted weights keyed on the weight tensor's device address, with no invalidation
anywhere. Once a buffer was freed, a later allocation at the same address hit a stale
entry. It never fires in single-model single-process use — which is exactly what
perplexity and ordinary generation exercise — but it fires on multi-model benchmarks and
on server model swaps. Fix: the routes register an invalidator and the CUDA backend calls
it on buffer teardown, so the cost is zero on the hot path. Q8_0 int8 with the cache
enabled goes from **35 OK / 12 FAIL to 46 OK / 0 FAIL**; the same for Q1_0 and IU4.

### 8.3 How claims are gated

- **A clean-tree build gate.** `verify-roc8-promotion.sh` builds the branch from a git
  worktree containing committed content only, then runs `test-backend-ops`. This exists
  because a local build can quietly compile untracked files that no clean clone has —
  which had already happened once.
- **Correctness before throughput, always.** Every kernel checks itself against a CPU
  reference and exits non-zero if it fails, before printing a single timing.
- **Measurement audited against a measured roofline.** Working-set size is printed
  beside every bandwidth figure, and a reading above the DRAM roofline is reported as
  cache-residency rather than as a result.
- **Independent adversarial review.** Both defects above were found by a review whose
  brief was to *refute* the existing conclusions rather than confirm them. One of them
  overturned a hypothesis the author was confident in.

### 8.4 What is not claimed

The prefill routes are **opt-in and off by default**, and validation of the individual
routes is ongoing. A full sweep across all nine found real problems that are not yet
fixed: the F16 route is a net regression at production shapes, the Q8_0 fp8 mode fails
its own correctness tolerance in production configuration, and two routes alter generated
text while having no coverage in `test-backend-ops` at all.

So the branch ships them disabled. The three headline results in §5 are measured on the
**default** path and reproduce from a clean clone; the routing layer is presented as work
in progress, because that is what it is.

---

## 9. Serving throughput: auto-tuned continuous batching

Kernel work raises the ceiling for one stream. Most of the value of a locally-deployed
agent, though, shows up when several requests are in flight — and there the lever is
continuous batching, whose optimal parallelism is **per-model, VRAM-coupled, and not
monotonic**. So Hyperloom measures it rather than picking a number.

`scripts/auto-batch-serve.sh` (in the llama.cpp fork) computes the KV-bounded search
space from the model's own dimensions, sweeps `-np` under pinned clocks, detects the
throughput knee, caches the answer per `(model, context)`, and launches the server with
that parallelism.

**The agent does this itself.** `sweep_batch` is one of its tools, so serving configuration
is discovered the same way kernel gaps are — by measurement, not assumption. Asked only
*"I want to serve this model to several users at once; find the concurrency that maximises
throughput, and tell me what it costs"*, with no tool named, it selected the sweep, chose
its own grid, and reported:

> *"The concurrency that maximizes aggregate throughput is 256 streams, yielding 2831.59
> tokens/s. However, throughput per stream falls as concurrency rises, so at this maximum
> concurrency the cost is approximately 11.06 tokens/s per request, down from 14.39 tokens/s
> per stream at 192 streams."*

That run independently reproduced the numbers in the table above to within ~1%. Note it
volunteered the per-stream cost rather than quoting the aggregate alone — the tool grid is
also clamped to llama.cpp's 1–256 range, because an out-of-range value aborts every point
in the sweep, and pinned to a large KV budget so the measurement cannot manufacture the
false cliff described below.

### Measured — Ternary-Bonsai-8B-Q2_0, gfx1201, `npp=32 ntg=128`

| streams (`-np`) | decode throughput | vs single stream |
|---|---|---|
| 1 | 154.9 t/s | 1.00× |
| 8 | 509.3 t/s | 3.29× |
| 16 | 889.9 t/s | 5.75× |
| 32 | 1333.8 t/s | 8.61× |
| 48 | 1917.7 t/s | 12.39× |
| 64 | 1859.6 t/s | 12.01× |
| 96 | 2503.8 t/s | 16.17× |
| 128 | 2481.3 t/s | 16.02× |
| 160 | 2683.5 t/s | 17.33× |
| 192 | 2780.4 t/s | 17.95× |
| **256** | **2853.1 t/s** | **18.42×** |

**Read this correctly: it is aggregate throughput, not per-request speed.** One stream
generates ~155 tokens/s; ninety-six streams together generate ~2489, which is ~26 t/s
each. Batching buys you *total work done*, and it costs per-request latency. For an agent
serving several concurrent tasks — the case this track is about — throughput is the
figure that matters, but it should never be quoted as though a single reply got 16×
faster.

**Why the sweep is not optional — including when it misleads you.** The curve is not
monotonic: 64 streams (1859.6) is *slower* than 48 (1917.7) before recovering. A guessed
`-np` can land in that trough. And the trough moves with the model — the same script picks
`-np 16` for Ternary-Bonsai-27B at 4096 context per slot, where VRAM binds long before
throughput does.

It also caught an error in our own earlier work. A previous sweep concluded there was a
throughput *cliff* at 128 streams and treated 96 as the peak. Re-running with a larger KV
budget (`-c 65536` rather than `32768`) shows no cliff at all: 128 is flat within run-to-run
variance, and throughput keeps climbing to **17.85× at 192 streams**. The original "cliff"
was the context budget binding, not the hardware — a limit of the measurement, read as a
property of the GPU.

**The GPU never saturated — llama.cpp ran out first.** 256 concurrent sequences is a hard
limit in the runtime (`n_seq_max must be <= 256`); asking for 320 fails at context creation.
Throughput was still rising into that ceiling: +2.6% from 192 to 256, flattening but not
flat. So 18.42× is a **floor imposed by the serving framework, not a property of the
silicon** — this card has concurrency headroom that llama.cpp cannot currently address.

Per-stream latency degrades across the range, as it must: each of the 256 streams sees
about 11 t/s against 155 for a lone stream. The 192-stream point was re-measured as a
control across two runs (2764.1 and 2780.4 t/s, 0.6% apart), so the curve is comparable
run to run.

## 10. The harness: an interface that cannot display an unverified claim

`harness/serve.py` serves a local browser dashboard (127.0.0.1 only, no outbound
request) that watches a real agent run: tool calls as they execute, correctness
gates as they pass, measurements as they land. Run it with:

    python3 harness/serve.py     # then open http://127.0.0.1:8770

It is not a progress display. It enforces two rules that this project learned the
hard way, and it enforces them in the rendering layer, where they cannot be
forgotten:

1. **A throughput number is UNVERIFIED until a gate naming that specific metric
   has passed.** Not "some gate passed" — the gate must name the metric.
2. **A bandwidth above the measured 631 GB/s DRAM roofline renders INVALID, not
   green.** Above the roofline does not mean fast; it means the working set fit
   in the 64 MiB Infinity Cache and the number is not a throughput result.

A live run demonstrates the second rule firing on itself. The mission
deliberately measures one cache-resident shape alongside two honest ones:

    decode N=65536 K=4096     611 GB/s   ws=144.0 MiB    96.8%   ok
    decode N=16384 K=14336    603 GB/s   ws=126.0 MiB    95.6%   ok
    decode N=14336 K=4096     796 GB/s   ws= 31.5 MiB   126.1%   INVALID (cache-resident)

The largest number on the page is the one rendered red. It passes its
correctness gate — it is a *correct* number — but it is not a *valid* throughput
claim. Keeping "correct" and "valid" as separate states is the entire point:
this project twice published a number that was correct and invalid at the same
time, and a human caught it both times. The interface now catches it.

`dashboard.html` was drafted by the local model (Qwen-AgentWorld-35B-A3B on the
Radeon card) from a written specification, and both interlocks were present in
its first output. The per-metric gate linkage in rule 1 was underspecified by us
and corrected by hand afterwards. `harness/README.md` records that split.

> **Provenance for this section.** These figures come from
> `benchmarks/auto-batch-serve.sh` (shipped here) driving `llama-batched-bench`
> from a build of the fork; continuous batching does not exist outside a running
> server, so this is the one result in the document that cannot be reproduced from
> a standalone kernel in this repository. There is **no correctness gate** on it —
> it is a throughput measurement of an already-validated engine, not a new kernel.
> Treat it accordingly.

## 10a. Which roofline number, and why

Throughput here is graded against **631 GB/s**, the streaming DRAM read figure we
measured with `bw_roofline.cu`. Other numbers appear in this repository and are
not typos: 598-614 GB/s is the copy/mul/add/triad band, 631-638 the read/dot band,
and 640 is the vendor spec figure. We grade reads against the read figure. It
matters because it is a denominator: at 631 the fp8 result below is 99.8% of
roofline; against 638 it is 98.7%; against the spec 640 it is 98.4%. None of those
cross the line into "above roofline", but a claim of exactly *100%* would be an
artefact of denominator choice, which is why the tables say 96-100% and the
INVALID flag triggers on the working set rather than on a percentage.

The tool that produces this figure is `benchmarks/bw_roofline.cu`, and its
captured output is in `benchmarks/captured/bw_roofline.txt`. On the run captured
there it reports **633 GB/s**, not the 631 we grade against — a 0.3% run-to-run
difference. We have left the grading denominator at 631 rather than restating
every percentage in this document, and note the discrepancy here instead. It
moves nothing: 626/633 is 98.9% rather than 99.2%.

### Running this on different silicon

`ROOFLINE_GBS` is an environment variable, not a constant, in both the kernels and
the harness. 631 GB/s is *this* machine — a discrete R9700 on GDDR6. A Strix Halo
APU (gfx1151) on unified LPDDR5X is nearer 256 GB/s, and grading against 631 there
would mark every honest result INVALID. Measure the roofline on the target and pass
it in.

Making that overridable surfaced a bug worth recording: the kernels printed
"above roofline, measuring cache" for *any* over-roofline reading, so a wrong
roofline produced a confident and wrong explanation — a 272 MiB working set
labelled cache-resident. They now name the cache only when the working set
actually fits in it, and otherwise say the cause is unknown and point at the
roofline value. The same conflation existed in the dashboard and is fixed there
too.

Note also that `decode_fp8.hip` will not compile for gfx1151 or gfx1100 at all:
`v_dot4_f32_fp8_fp8` is RDNA4. That is the correct outcome, not a portability
failure — the ISA probe in `toolkit/` is the part that is meant to run anywhere,
and it reports what a given target actually has.

## 10b. fp8: the gate that should have been there from the start

`kernels/decode/decode_fp8.hip` is the fp8 (E4M3) decode kernel. **The kernel
itself was written by the local model** and verified bit-exact before being put
here — see §10f. It is built on
`v_dot4_f32_fp8_fp8` — a native 4-wide fp8 dot product that our ISA sweep found present on gfx1201
and unused by stock llama.cpp (`results/gfx1201-isa-map.md`). It is used now —
`results/roc9-unused-isa-sweep.md` counts 110 emissions, from this work.

    correctness gate (vs CPU E4M3 reference)
      N=256 K=4096   max_rel_err = 2.658e-05   tol = 1e-03   PASS

    throughput vs 631 GB/s measured DRAM roofline
      N=65536  K=4096   |  272.0 MiB (DRAM-honest)     |  626 GB/s |  99% of roofline
      N=16384  K=14336  |  238.0 MiB (DRAM-honest)     |  629 GB/s | 100% of roofline
      N=14336  K=4096   |   59.5 MiB (CACHE-RESIDENT!) | 1505 GB/s | 239%  <-- INVALID

Verbatim in `benchmarks/captured/decode_fp8.txt`, including the shell invocations
and toolchain version. An earlier draft of this section quoted 630 GB/s for the
first shape from memory; the captured run says 626. The difference is run-to-run
variance of a few GB/s at the top of the bandwidth curve, and the captured file
is the authority — which is the point of capturing it.

(The last line comes from a second invocation, `./decode_fp8 14336 4096` — the
program prints its two default shapes, or one shape given on the command line.
They are shown together because the contrast is the point, not because one run
produced all three.)

It is included here for a reason beyond the number. The version of this
benchmark we had been carrying **had no correctness gate at all** — it printed
627 GB/s and nothing else. Worse, it seeded its weights with uniform random
bytes, and two of the 256 possible E4M3 encodings (`0x7F`, `0xFF`) are NaN. It
may well have been timing a kernel whose output was NaN, and no part of its
output would have revealed that.

The gate above is what caught it, the generator now rejects the NaN encodings,
and the correctness check runs *before* any throughput line is printed — if it
fails the program exits without reporting a number. The measured result turned
out to be sound. That was luck, not method, and the method is what we are
submitting.

## 10c. The fork, if you want to read the full kernel work

The prefill routes, the int4 decode path, the fp8 kernels and the 2:4-sparse
SWMMAC work are integrated in our llama.cpp fork rather than in this repository,
because they only mean anything inside a real inference engine:

  **https://github.com/The-Monk/llama.cpp** — branch **`roc8`**

It is a fork of [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)
(MIT, © the ggml authors), and its README says so; all credit for llama.cpp
belongs upstream. None of this is upstreamed and none of it carries any
endorsement from the llama.cpp maintainers.

That work is also packaged as a runnable appliance, with the resulting fp8
models published rather than merely described:

  **https://github.com/The-Monk/The-Rock8** — rootless-Podman appliance on the
  TheRock ROCm 7.13 toolchain, plus five native fp8 E4M3 GGUFs on Hugging Face
  (Quacken-8B / R1-14B / 27B / 35B-A3B / Ornith-35B), each Quark-quantized from
  BF16 and validated on gfx1201.

We cite it because published weights are checkable in a way a benchmark table in
a PDF is not — anyone can download one and run it. The numbers quoted in that
repository are its own; the claims made in *this* document are the ones backed
by the code in this repository.

Two things there are worth more than the speedups. The first is a plain
correctness fix: `GGML_TYPE_Q2_0` was missing from `ggml_validate_row_data`,
which silently broke `llama-quantize --type Q2_0` and `--check-tensors` for
every Q2_0 GGUF. We audited the rest of the table; Q2_0 was the only gap. The
second is that **every added route is opt-in and env-gated, defaulting to the
stock kernel** — for the reason measured in §11.

## 10d. A note on branch names in the captured output

Several captured benchmark files name **`roc9`** (e.g. `build-roc9-714`), because
that was the research branch the measurements were taken on. `roc9` was promoted
into **`roc8`** by fast-forward, and `roc8` is the branch that is public. A
reviewer following a `roc9` path in an output file will not find that branch —
use `roc8`, which contains the same commits. We have left the captured output
unedited rather than rewriting recorded filenames after the fact.

## 10e. We pointed the agent at our own submission

Three external reviewers audited this document and found real defects. The
obvious question is why the agent we are submitting did not do that job, so we
ran it: `harness/self_audit.py`.

Eight claims, six of them defects the reviewers found and we verified by hand,
two genuinely backed as controls. The agent gets **one** tool — grep over this
repository. The harness owns everything else: the claim list, the ground truth,
and the scoring. Critically, every `file:line` the model cites is checked against
the grep output it actually received, so **inventing evidence is detected
separately from being wrong**.

| | |
|---|---|
| Correct verdicts | **7 / 8** |
| Real defects caught | **4 / 4** |
| False alarms | **0 / 4** |
| **Fabricated citations** | **0** |
| Failed to answer | 1 |

The single miss was a non-answer, not a wrong answer: on the crossover claim it
never emitted a parseable verdict. It caught the Magpie issue-versus-fix error,
the 90.5-versus-91.6 discrepancy, the "unexploited instruction" claim its own
repository contradicts, and the serving section with no artifact.

**The first scoring run said 6/8 and was wrong — our fault, not the model's.**
One claim's ground truth was stale: we had already fixed `serve.py` before the
experiment ran, so the model correctly answered BACKED against the tree in front
of it and we marked it WRONG against a defect that no longer existed. A harness
that owns the reference is only as good as that reference, and ours was briefly
out of date. The note is preserved in the script.

What we take from this is narrower than "the agent can audit." It is that under a
harness which owns the reference and mechanically checks citations, this model
produced **zero fabricated evidence** across eight adversarial questions. That is
consistent with our earlier finding that the difference between useful and
useless agent output is the harness rather than the model — this is the same
result observed from the positive direction.

## 10f. Who wrote the kernels

The kernels shipped in `kernels/` were written by a human. That needs saying,
because the surrounding text describes an agent whose mission loop ends in FIX
and VALIDATE, and the demo narration says "the kernels it writes".

So we tested whether that narration is defensible, under conditions where it
could not be faked. `kernels/decode/agent_repro/` contains the rig:

* `golden_gen.cu` runs the human fp8 kernel on a fixed seed and writes the
  inputs and outputs to disk.
* The model receives a written **specification** — the block layout, the E4M3
  encoding, the arithmetic, the available intrinsic, the required signature and
  launch configuration. It does **not** receive the reference implementation,
  the inputs, or the golden output.
* `repro_harness.cu` owns the inputs, the golden and the comparison. The agent
  supplies exactly one file: a kernel body with a fixed signature.
* `grade.sh` compiles it, runs it, parses the error and applies the tolerance.
  The model's own opinion of its kernel is never consulted.

**Result: REPRODUCED on the first attempt, `max_rel_err = 0.000000e+00`** —
bit-identical to the reference across all 4096 rows. Verified four ways: the
golden regenerates to the same md5, the kernel re-grades identically against a
freshly generated reference, the kernel has no file access and receives only
device pointers, and the compiled binary contains 8 emissions of
`v_dot4_f32_fp8_fp8`, so it genuinely used the hardware instruction rather than
having it optimised away. Captured in
`benchmarks/captured/agent_wrote_fp8_kernel.txt`; the accepted kernel is
`agent_kernel_ACCEPTED.cuh` and is visibly its own code, not a copy — different
identifiers throughout, literal `8` and `64` where the reference uses `QK/4` and
`blockDim.x`.

**That kernel is now the one that ships.** Having been graded bit-exact against
the human implementation, there was no honest reason to keep it in a side
experiment while a human-written equivalent occupied the production file, so
`decode_fp8.hip` now carries the model's kernel with its provenance in the header
comment. It passes the same gate it always did — `max_rel_err = 2.658e-05` — at
627 and 629 GB/s.

The division of labour is exact and worth stating rather than blurring: **the
model wrote the kernel; the human wrote the harness around it** — the CPU E4M3
reference, the gate that runs before any timing, the working-set accounting, the
roofline check. Neither half is the interesting one alone.

We left one flaw in place. The model's kernel hardcodes the block width (`c += 64`)
and the reduction start (`stride_sh = 32`) where a human would more likely write
`blockDim.x`. That is correct for the launch configuration it was specified
against, but less general than it should be. Tidying it would have made it a
jointly-written kernel and destroyed its value as evidence, so it stands as
written.

The other kernels in `kernels/` remain human-written.

It is worth placing next to the opposite result in this same document. Asked to
produce **and evaluate** fp8 work autonomously in an earlier bake-off, this model
executed correctly but every performance verdict failed audit — one claimed 28x
against a baseline that returned `Inf`; the corrected figure was about 2.4x.
Given the reference, it is bit-exact. Given ownership of the verdict, it
fabricates. Section 10e found the same split from a third angle: zero fabricated
citations across eight adversarial questions when the harness owned the check.

That is the finding this project is built on, stated three ways: **this model is
reliable exactly where something else is checking it.**

## 10g. The model can write the kernel. It could not write the checker.

Having shown the model can produce a bit-exact kernel from a specification
(§10f), the obvious next question is whether it can produce the thing that
*checks* a kernel. If it could, the harness argument this document rests on
would be much weaker.

`kernels/decode/agent_repro/run_agent_harness.py` runs that test. The model is
asked to write a complete correctness gate: a CPU reference for fp8 E4M3, a
comparison against GPU output, and a PASS/FAIL verdict. Its harness is then
compiled against five kernels whose correct verdicts we already know — one
correct implementation and four broken in specific ways (writes a constant,
drops the per-block scales, processes half the blocks, swaps the scale
factors).

| kernel | its harness said | correct verdict |
|---|---|---|
| **good** | FAIL | **PASS** |
| constant | FAIL | FAIL |
| noscale | FAIL | FAIL |
| halfrow | FAIL | FAIL |
| swapped | FAIL | FAIL |

**It rejected everything, including the correct kernel**, and did not converge
across three rounds of feedback. A gate that fails everything carries exactly as
much information as one that passes everything: none. It catches all four bugs
only in the sense that a broken thermometer reads cold in a fire.

Placed beside the other two results in this document, the picture is consistent:

| Task | Who owned the verdict | Outcome |
|---|---|---|
| Write the fp8 kernel from a spec | the harness | **bit-exact, first attempt** |
| Audit eight claims with a grep tool | the harness | **7/8, zero fabricated citations** |
| Write the correctness gate itself | *the model* | **failed, 3 attempts** |
| Evaluate its own fp8 work (earlier bake-off) | *the model* | **claimed 28x against a broken baseline** |

The model does the work well and judges it badly. Every result here where
something else owned the judgement came out sound; every result where the model
owned it came out wrong. That is the entire reason this project is built around
harnesses, and it is the reason we do not propose replacing the harness with a
second model.

One honest caveat: this is a single model, one task family, a three-attempt
budget and one prompt. It is evidence, not a law. We would expect a larger
budget or a stronger model to eventually produce a working gate — the finding is
that it is *much harder* than producing the kernel, not that it is impossible.

## 10h. The same protocol across four quantisation formats

`kernels/decode/agent_repro/quant/` generalises the fp8 rig. The model receives a
written specification of a block layout and its decode rule; the harness owns the
inputs, the golden reference and the verdict. Each rig is self-tested in both
directions before the model sees it — a known-good kernel must reproduce, and a
deliberately broken one must fail.

| format | encoding | verdict | error | time |
|---|---|---|---|---|
| **Q1_0** | 1-bit binary, {-1,+1} | REPRODUCED | **0** | 122s |
| **Q2_0** | 2-bit ternary, {-1,0,+1} | REPRODUCED | 1.08e-06 | 148s |
| **Q4_0** | 4-bit linear, nibble-8 | REPRODUCED | 1.04e-06 | 76s |
| **Q5_0** | 5-bit linear, nibble + qh bit-plane | REPRODUCED | **0** | 230s |
| **Q8_0** | 8-bit signed | REPRODUCED | **0** | 72s |
| **MXFP4** | 4-bit MX: OCP E2M1 leaf + UE8M0 scale | REPRODUCED | 7.31e-07 | 107s |
| **MXFP8** | 8-bit MX: OCP E4M3 leaf + UE8M0 scale | **NOT REPRODUCED** | **2.087** | 356s |

**Six of seven.** MXFP8 failed after three attempts with an error of 2.087 — that
is a wrong answer, not a rounding difference, and we are reporting it rather than
dropping the row. It is the most interesting result in the table precisely
because it failed: the model had already produced a correct **E4M3** kernel
(§10f, bit-exact) and a correct **UE8M0-scaled** kernel (MXFP4, above). MXFP8 is
those two things combined, and the combination is what it could not assemble
from a specification. Capability on the parts did not compose into capability on
the whole.

Q1_0, Q5_0 and Q8_0 are bit-exact. Q2_0 and Q4_0 differ only in fp32 rounding, because
the model chose a different summation order than the reference — which is a
legitimate implementation choice, not an error.

**Getting that last sentence right required fixing our own metric, and it is the
more useful finding.** Q4_0 first scored `8.47e-03` against a `1e-2` tolerance —
85% of the way to failing. Investigating rather than accepting the pass showed
the kernel's decode was exactly correct, and that the number came from a single
row where `|golden| = 4.9e-05`, twenty-eight thousand times below the mean, while
its absolute error was `4.2e-07` — right at the average for every other row. A
per-row relative metric divides by that near-zero and manufactures an alarming
number from ordinary rounding.

The gate now measures `max|a-b| / mean|golden|` — the worst absolute disagreement
against the scale of the result, which is what "these agree" means for a GEMV.
The per-row relative figure is still printed, because it is informative; it just
must not be the thing that decides. Under the corrected metric Q4_0 is
`1.04e-06`, indistinguishable from the two bit-exact results.

Had we not looked, a correct kernel would have been recorded as marginal, and a
slightly unluckier seed would have failed it outright. **A tolerance that passes
is not evidence that the metric is sound.**

Formats not yet covered: MXFP6, the K-quant superblock family (Q3_K/Q4_K/Q5_K/Q6_K,
256 elements with multi-level scales), and 2:4 structured sparsity — which needs a different rig entirely, since it is a
SWMMAC prefill path with metadata rather than a decode GEMV. The rig extends in
roughly twenty lines per linear format; the superblock and sparse families need
real specification work rather than a copy.

## 11. A limit we found in our own routing, and did not fix

The hipBLASLt prefill routes are gated on M (the batch dimension) against a
scalar threshold, `MTHRESH`. We tested whether M alone is sufficient by running
the same route, at the same M values, against two models of different width.

| ubatch | 8B: OFF → ON | 24B: OFF → ON |
|-------:|-------------------------|--------------------------|
|  64 | 1965 → 2014  (**+2.5%**) | 810 → 501  (**-38.2%**) |
| 128 | 2942 → 3223  (**+9.6%**) | 1074 → 833 (**-22.5%**) |
| 256 | 4110 → 5457 (**+32.7%**) | 1320 → 1324  (+0.3%) |
| 512 | 4077 → 5396 (+32.3%)     | 1381 → 1603 (+16.1%) |

Same route, same threshold, opposite outcomes: **+32.7% on the 8B and -38.2% on
the 24B**. Those two rows have tight spreads (±78/±6.5 and ±3.3/±1.1), and they
are the two the argument rests on. **The ubatch-512 row does not**: its spreads
are ±651/±1017 (8B) and ±79/±126 (24B), so OFF and ON overlap and the +32.3% and
+16.1% there are inside the noise — read them as directional only. Every figure
is n=2 (`crossover.sh` runs `-r 2`), so "±" is a two-sample spread, not a
confidence interval. The
8B wins at every M we measured, so its crossover is below 64; the 24B is hurt
badly until roughly 256. The crossover moves at least 4x with model shape.

The conclusion is that the gate keys on the wrong variable. It tests M, while
the algorithm cache underneath it is keyed on the full shape `(N, M, K, mode)` —
which is the information the gate actually needs. This is why the routes ship
**opt-in and env-gated rather than on by default**: a scalar threshold that is
correct for one model is a 38% regression for another, and we would rather ship
a conservative default than a fast one that is wrong off-box.

We are reporting this rather than fixing it because the fix is a shape-aware
gate that we have not measured, and an unmeasured fix is exactly the kind of
claim the rest of this document exists to avoid. `benchmarks/crossover.sh`
reproduces the table.

## 12. Radeon Cloud escalation: built, not claimed

`agent/escalation.py` implements confidence-gated escalation to the Radeon Cloud
OpenAI-compatible API: a stuck-detector watches repeated local failures, and on
a genuine stall it sends a *structured* packet (the layered context of what was
tried and how it failed) rather than a bare retry. Core inference stays local on
the Radeon GPU in every case; the cloud is a fallback for stalls, never the
primary path.

The code reads `RADEON_CLOUD_API_BASE` / `_KEY` / `_MODEL` and is ready to
configure. **We are not claiming the optional bonus points**, because we were
unable to obtain a working key before the deadline. The Token Factory named in
the platform guide is hosted on `developer.amd.com.cn`, which the contest rules
designate as the AMD Developer Program portal *"only for developers in Mainland
China"*; the global platform also offers model APIs, but was unavailable for
maintenance during the window we had. Neither of those is a criticism of the
platform -- timing simply did not work out.

What matters for judging is that the path is untested against the live service,
and an untested path will not be presented here as a working one.
