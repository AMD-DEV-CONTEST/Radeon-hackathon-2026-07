# costbench — Project Specification

**AMD AI DevMaster · Track 2: Development & Local Deployment of Private AI Agents**

Author: Saad Kaicar (solo) · Tortona, Italy · [github.com/Artkill24](https://github.com/Artkill24)
Repository: https://github.com/Artkill24/costbench
Hardware: AMD Radeon PRO W7900 (gfx1100), Radeon Cloud

---

## 1. Application scenarios

An organisation runs LLM inference on its own hardware, for one of two
reasons: the data cannot leave the building, or the API bill has become
larger than a GPU. Both create a problem that cloud users never face.

**When the GPU is yours, the invoice disappears.** There is no per-token
line item, so nobody can answer basic operational questions: what did this
task cost? which tenant consumed the capacity? is it cheaper to batch these
jobs overnight or serve them now? On-prem inference *feels* free, and
therefore goes unmeasured and unoptimised.

costbench targets three concrete situations.

**Regulated on-prem deployment.** A legal, clinical or industrial team runs
an assistant on documents that must not reach a third party. They need a
technical artefact proving no data left the network — not a policy
statement, an audit log. costbench enforces `X-Privacy: strict` as a
constraint and records every request, its route and its egress in a local
SQLite ledger that can be exported and inspected.

**Internal chargeback.** A platform team hosts one GPU for several
departments and must attribute cost. costbench meters per-tenant token
usage and converts it to energy and euros using a curve measured on that
specific card, giving a defensible number instead of an arbitrary
allocation key.

**Capacity and scheduling decisions.** An operator choosing between "serve
immediately" and "queue and batch" needs the actual trade-off. costbench
measured it: batching to concurrency 16 cuts energy per token by 88% and
raises time-to-first-token by 7.8×. That is a scheduling policy input, and
it is a measurement, not an estimate.

---

## 2. Agent architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  agent.py — sandboxed on-prem agent                              │
│                                                                  │
│   task ──▶ plan ──▶ tool ──▶ observe ──┐                         │
│              ▲                          │                        │
│              └──────────────────────────┘  (loop detection)      │
│                                                                  │
│   tools: list_files · read_file · grep · stat                    │
│   sandbox: realpath confined to --root; ../ and absolute paths   │
│            raise PermissionError before any read                 │
│   actions: constrained by JSON schema → GBNF grammar             │
│   accounting: tokens · joules · euros · egress bytes per task    │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTP, X-Privacy: strict, X-Tenant
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  gateway.py — cost-governance gateway (OpenAI-compatible)        │
│                                                                  │
│   ┌────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│   │  Policy    │  │  Energy meter    │  │  Audit ledger      │  │
│   │            │  │                  │  │                    │  │
│   │ strict ⇒   │  │ tokens/joule     │  │ SQLite, on-prem    │  │
│   │ local,     │  │ curve MEASURED   │  │ route · reason ·   │  │
│   │ always     │  │ on this GPU;     │  │ privacy · egress · │  │
│   │            │  │ interpolated by  │  │ tokens · joules ·  │  │
│   │ else:      │  │ concurrency at   │  │ eur · ttft         │  │
│   │ queue depth│  │ request time     │  │                    │  │
│   │ + latency  │  │                  │  │ export → JSON      │  │
│   │ budget     │  │ cost_model_source│  │                    │  │
│   └────────────┘  └──────────────────┘  └────────────────────┘  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ /v1/chat/completions (streaming + sync)
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  llama.cpp server, HIP backend                                   │
│  Qwen2.5-Coder-7B / 14B Q4_K_M · -ngl 99 · continuous batching   │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
              AMD Radeon PRO W7900 (gfx1100), ROCm 7.2.1
                            │
                  sysfs power1_average, PCI-resolved
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  costbench.py — the measurement that everything above depends on │
│  closed-loop load · sensor ramp compensation · achieved          │
│  concurrency verified · results → proofs/*.json                  │
└──────────────────────────────────────────────────────────────────┘
```

The direction of the arrows matters. The benchmark is not a report produced
after the fact: it is the **source of the constants** the gateway uses at
runtime. Every euro the agent reports is traceable, via the
`cost_model_source` field on each request, back to a JSON file in
`proofs/`.

---

## 3. Core capabilities

**Tool invocation.** Four read-only filesystem tools. Arguments are parsed
from a JSON action object; unknown tools and bad arguments return an
observation rather than crashing the loop.

**Multi-step planning.** Observe–decide–act loop with a step budget. The
opening turn is seeded with a real listing of the workspace, which removed
a failure mode where a 7B model spent its whole budget guessing at
`/var/log`, `/opt/logs`, `/usr/local/logs`. Identical repeated tool calls
are detected and reported back to the model instead of silently consuming
steps.

**Constrained decoding.** Actions conform to a JSON schema passed as
`response_format`; llama.cpp compiles it to a GBNF grammar, so a malformed
action is not merely discouraged by the prompt — it is unreachable at
sampling time. This is what makes a small, fast model usable as an agent.

**Privacy and on-prem enforcement.** `X-Privacy: strict` is not a
preference. It routes locally regardless of queue depth, latency budget, or
whether an external provider is configured, and the audit ledger records
the decision and its reason for every request.

**Per-task cost accounting.** At the end of a task the agent reports steps,
tokens, joules, euros and egress bytes. A recorded run: 3 steps, 194
tokens, 404.2 J, €0.000028, 0 bytes leaving the network — the last figure
verified against the gateway's audit export, not asserted.

---

## 4. Model and local deployment plan

**Models.** Qwen2.5-Coder-7B-Instruct and 14B-Instruct, Q4_K_M GGUF. The 7B
is the production choice: it fits comfortably in the W7900's 51.5 GB
alongside a 32k context, sustains 696 tok/s at concurrency 16, and is
capable enough to drive the constrained agent loop. The 14B was measured to
test whether the findings generalise across model size; it does.

**Runtime.** llama.cpp built from source with `-DGGML_HIP=ON` and
`-DAMDGPU_TARGETS=gfx1100`, all layers offloaded (`-ngl 99`), continuous
batching enabled (`-cb`).

**Context allocation — a deployment detail worth stating**, because getting
it wrong silently breaks agents: llama.cpp *divides* `-c` among parallel
slots. With `-c 8192 -np 16` each request receives 512 tokens and multi-turn
agent output is truncated mid-JSON. The agent is served with `-np 4` and
`-c 32768` (8192 per slot); the benchmark uses `-np 16` where per-slot
context does not matter.

**Deployment sequence.** `setup.sh` performs the whole install unattended:
verifies power telemetry and aborts within two minutes if it is absent,
detects the GPU architecture, builds llama.cpp with HIP, fetches the model,
starts the server, runs the benchmark and writes checksummed proofs.
`demo.sh` then starts the gateway and agent and produces the audit export.

**Dependencies.** Python 3.12; `fastapi`, `uvicorn`, `httpx` for the
gateway; `huggingface_hub` for model download; `matplotlib` for figures.
The benchmark and the agent use only the standard library — deliberately,
so the measurement path has no third-party surface.

---

## 5. Inference optimisation on AMD Radeon GPU

This is where the project's contribution sits, and it is measurement rather
than a code change: the optimisation that matters most on this hardware is
**batch scheduling**, and its magnitude was unknown until measured.

### Results (measured, `proofs/`)

| Model | Conc | Throughput (tok/s) | Power (W) | Tokens/J | TTFT p50 | EUR/1M tok |
|:--|---:|---:|---:|---:|---:|---:|
| 7B | 1 | 103.1 | 216.5 | 0.476 | 25 ms | 0.1458 |
| 7B | 4 | 216.6 | 229.0 | 0.946 | 67 ms | 0.0734 |
| 7B | 16 | 696.3 | 168.1 | 4.142 | 196 ms | 0.0168 |
| 14B | 1 | 57.3 | 226.1 | 0.253 | 56 ms | 0.2741 |
| 14B | 4 | 116.6 | 236.9 | 0.492 | 170 ms | 0.1410 |
| 14B | 16 | 411.6 | 184.7 | 2.229 | 571 ms | 0.0312 |

**Finding 1 — batching gives 8.7× energy efficiency, and the factor is
model-independent.** 8.70× on the 7B, 8.80× on the 14B. Normalised, the two
curves coincide.

**Finding 2 — absolute efficiency scales inversely with model size.** The
14B/7B tokens-per-joule ratio is 0.53 / 0.52 / 0.54 at concurrency 1 / 4 /
16: constant, and close to the 0.5 predicted if decode is
memory-bandwidth-bound.

**Finding 3 — power draw is not monotonic in batch size.** Both models peak
at concurrency 4 (229 W and 237 W) and then draw *less* at concurrency 16
(168 W and 185 W) while doing ~6.8× the work. Reproduced across models and
four independent sessions.

**Practical consequence for a Radeon deployment:** an under-utilised W7900
serving one request at a time is not merely slow, it is 8.7× more expensive
per token in electricity alone. The optimisation is to keep the batch full,
and the cost of doing so is 7.8× on time-to-first-token — which is exactly
the trade-off the gateway's routing policy exists to arbitrate.

### Measurement methodology

Four failure modes were found and fixed. Each produced plausible-looking
data, which is why they are documented rather than quietly corrected.

| Failure | Symptom | Fix |
|:--|:--|:--|
| Sensor lag | `power1_average` is a long-window mean; 2–5 s runs reported 14 W under full load | 90 s sustained runs, first 25 s of samples discarded |
| Shared host | sysfs exposes all 8 GPUs; first readable path was another user's card | Resolve assigned GPU by PCI bus (`rocm-smi --showbus`), read only that hwmon; bus recorded in every result |
| Wave-barrier load | Firing N and waiting for all leaves an idle straggler tail that grows with N, deflating power at high batch | Closed-loop generator; `achieved_concurrency` measured and recorded per run |
| Stale server | Liveness check answered by a leftover process; a "14B" run re-measured the 7B | Free the port, then verify the *served model name*; the invalid run is preserved in `rejected/` |

### Declared limits

GPU board power only — CPU, RAM, cooling, datacenter PUE and hardware
amortisation are excluded, so real operating cost is higher. The cause of
the power drop is **hypothesised, not proven**: clock probing could not test
it, because `mclk` is pinned at 1124 MHz at every concurrency level and
therefore carries no information about memory traffic (raw data in
`proofs/clockprobe_*.csv`). Settling it requires bandwidth counters. Token
counting approximates one streaming chunk as one token. Three concurrency
levels, one quantisation, one GPU. The electricity tariff (0.25 EUR/kWh) is
assumed, and is a linear multiplier on every euro figure.

---

## 6. Deliverables

| | |
|:--|:--|
| Source | https://github.com/Artkill24/costbench (MIT) |
| Benchmark | `costbench.py` — PCI-resolved sensor, closed-loop load |
| Gateway | `gateway.py` — metering, privacy routing, audit ledger |
| Agent | `agent.py` — tools, sandbox, per-task accounting |
| Automation | `setup.sh`, `demo.sh` — unattended GPU sessions |
| Evidence | `proofs/` — results, logs, audit exports, SHA256SUMS |
| Negative result | `rejected/` — invalidated measurement + post-mortem |
| Figures | `charts/` — regenerated from `proofs/` by `charts.py` |

Reproduction: clone, `bash setup.sh`, `bash demo.sh`, `python3 charts.py`.
`setup.sh` aborts within two minutes if power telemetry is unavailable,
rather than consuming a GPU hour to produce nothing.
