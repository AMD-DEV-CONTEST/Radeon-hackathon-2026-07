# AMD Radeon Inference Optimization Report

> Novel Fate Simulator — a private, stateful narrative agent on AMD Radeon

| Submission field | Value |
|---|---|
| Competition track | Track 2 — Development and Local Deployment of Private AI Agents |
| Team | Silent Core |
| Member | asher |
| Application | Novel Fate Simulator |
| Report date | 2026-08-06 |
| Measurement platform | One AMD Radeon `gfx1100` GPU, 48 GiB VRAM |
| Runtime | ROCm 7.2.1 |

## 1. Executive Summary

Novel Fate Simulator is a private, stateful narrative agent that transforms a
user-owned novel into a persistent simulated world. Its agent workflow retrieves
private story knowledge, plans each turn, generates scenes and candidate actions,
invokes image and speech services, validates state transitions, and persists
changes to relationships, factions, goals, story anchors, and possible endings.

This report documents the inference optimization work performed for the project's
single-GPU AMD Radeon deployment. The objective was not to claim absolute
datacenter state of the art. The objective was to obtain the best measured
interactive latency, throughput, API compatibility, and mixed-workload stability
for this project on one `gfx1100` Radeon GPU.

The selected serving architecture achieved the following measured results:

| Workload | Baseline | Selected configuration | Measured result |
|---|---:|---:|---:|
| LLM single-stream decode | 23.76 tok/s | 91.60 tok/s | **3.86x throughput** |
| LLM engine TTFT | 137 ms | 42 ms | **69% lower** |
| Warm application-compatible image endpoint | 320.438 s memory-cliff reference | 10.827 s | **29.6x endpoint latency improvement** |
| TTS real-time factor | 1.091 | 0.514 | **53% lower RTF; faster than real time** |

The final architecture uses:

- Qwen3-8B Q4_K_M through llama.cpp's HIP backend on the Radeon GPU;
- Z-Image-Turbo through Diffusers with model CPU offload and Radeon execution;
- Kokoro-82M on 16 CPU threads to avoid competing with the GPU workloads;
- an authenticated OpenAI-compatible gateway with stable application model IDs.

With all three model services healthy, the GPU used approximately 11.09 GB in
decimal ROCm reporting, or about 10.3 GiB. A mixed two-LLM-plus-image smoke test
reached 98% GPU utilization at approximately 216 W without an out-of-memory
failure.

## 2. Competition Relevance

The official Track 2 submission requirements explicitly request:

- a model introduction and local deployment plan;
- an optimization description for inference speed on AMD Radeon;
- a demonstration of actual operation on Radeon, emphasizing fluidity and
  functional completeness.

This work addresses those requirements with a measured before/after comparison,
an explicit optimization decision process, reproducible benchmark scripts, a
rollback path, and honest disclosure of methodology limitations.

Official submission requirements:
<https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>

The optimization is directly relevant to the agent experience:

- faster LLM decoding makes multi-step scene generation responsive;
- reduced LLM memory usage prevents image generation from entering a severe
  VRAM-pressure path;
- CPU TTS scheduling allows narration to run without occupying Radeon capacity;
- stable API contracts allow the application orchestrator to invoke all three
  services as agent tools.

## 3. Agent Inference Architecture

```text
Novel Fate Simulator Agent
  |
  |-- retrieve private lore and the current WorldState
  |-- plan the next narrative transition
  |-- generate the scene and candidate actions
  |-- validate and persist the state transition
  |-- invoke illustration and narration services
  v
Authenticated OpenAI-Compatible Gateway
  |-- silent-core/llm   -> Qwen3-8B Q4_K_M -> llama.cpp HIP -> Radeon
  |-- silent-core/image -> Z-Image-Turbo   -> Diffusers     -> Radeon
  `-- silent-core/tts   -> Kokoro-82M       -> PyTorch       -> 16 CPU threads
```

Applications call stable IDs rather than implementation-specific model names:

| Capability | Stable model ID | Primary API |
|---|---|---|
| Narrative generation and agent reasoning | `silent-core/llm` | `POST /v1/chat/completions` |
| Scene illustration | `silent-core/image` | `POST /v1/images/generations` |
| English narration | `silent-core/tts` | `POST /v1/audio/speech` |

The gateway also exposes the Responses API, model listing, authentication, and a
public health endpoint. This lets the application change the serving engine
without changing its model identifiers or orchestration logic.

## 4. Hardware and Software Environment

The following values were verified on the contest host on 2026-08-06.

| Component | Verified value |
|---|---|
| GPU architecture | AMD RDNA 3, `gfx1100` |
| GPU memory | 51,522,830,336 bytes, approximately 48 GiB |
| ROCm | 7.2.1 |
| PyTorch | `2.9.1+gitff65f5b` |
| vLLM | `0.16.1.dev0`, ROCm 7.2.1 build |
| Diffusers | 0.39.0 |
| Kokoro | 0.9.4 |
| LLM runtime selected | llama.cpp HIP |

`rocm-smi` identified the active device as an AMD Radeon GPU with GFX version
`gfx1100`. The report therefore uses the verified architecture and memory size
instead of inferring a retail product name from the instance.

## 5. Baseline Bottlenecks

### 5.1 LLM launch and decode overhead

The initial Qwen3-8B service used vLLM BF16 with eager execution. The
`--enforce-eager` option disabled graph replay and compilation. It remained a
useful compatibility baseline, but the fixed single-user narrative workload
decoded at only 23.76 tok/s in the median trial.

### 5.2 Image-generation VRAM cliff

The original co-resident layout kept the BF16 LLM and image pipeline competing
for almost all of the 48 GiB GPU memory. A 1024x1024 image trial consumed about
46.4 GiB and took 320.438 seconds. This was a memory-pressure cliff, not a normal
steady-state image latency.

### 5.3 TTS GPU contention and variance

The original Kokoro GPU path competed with the LLM and image model and showed
high latency variance. Because Kokoro has only 82 million parameters and the
host has substantial CPU capacity, GPU residency was not the best system-level
choice for this workload.

### 5.4 Public transport latency

The local engine reached a 42 ms median TTFT, while the temporary public Quick
Tunnel measured a 1.325 second median TTFT over three runs. The difference is a
transport bottleneck rather than a Radeon inference bottleneck. Quick Tunnels
are suitable for temporary testing but should not be used to represent stable
streaming performance in the final demonstration.

## 6. Optimization Process and Decisions

### 6.1 LLM engine and precision comparison

The project evaluated eager execution, decode graph replay, two graph modes,
AWQ, and GGUF quantization through a HIP-native runtime.

| Engine and precision | Median TTFT | Median decode | Decision |
|---|---:|---:|---|
| vLLM BF16 eager | 137 ms | 23.76 tok/s | Original baseline |
| vLLM BF16 full-decode graph | 132 ms | 25.63 tok/s | BF16 rollback path |
| vLLM BF16 piecewise graph | 135 ms | 25.33 tok/s | Rejected |
| vLLM AWQ | 66 ms | 18.23 tok/s | Memory fallback only |
| llama.cpp HIP Q4_K_M | **42 ms** | **91.60 tok/s** | **Production default** |

The results show why quantization format alone was not used as a performance
claim. The vLLM AWQ candidate reduced TTFT but decoded more slowly than the BF16
baseline on this RDNA 3 system. The selected result came from the measured
combination of engine, HIP backend, precision, kernels, and workload.

The production llama.cpp configuration uses:

```text
model:       Qwen3-8B Q4_K_M GGUF
context:     32,768 tokens
parallelism: 2
GPU layers:  all
Flash Attn:  enabled
CPU threads: 16
reasoning:   disabled for normal narrative output
```

The BF16 vLLM full-decode graph configuration is retained as a rollback path.

### 6.2 Memory-aware image serving

The image service was changed to a memory-safe application path:

1. quantize the resident LLM and release substantial Radeon memory;
2. move TTS off the GPU;
3. use Diffusers model CPU offload for Z-Image-Turbo;
4. warm the production request path;
5. render a memory-safe internal image with the requested aspect ratio;
6. apply high-quality Lanczos fitting to the final application dimensions;
7. serialize image requests on the single GPU.

This design prioritizes reliable `1024x1536` visual-novel output and coexistence
with the LLM over native full-resolution kernel benchmarking.

### 6.3 Resource-aware TTS scheduling

Five measured TTS configurations were compared:

| Backend | Threads | Median RTF | Median first sentence | Decision |
|---|---:|---:|---:|---|
| sherpa-onnx INT8 | 8 | 1.091 | 4.160 s | Rejected |
| sherpa-onnx INT8 | 16 | 1.057 | 3.885 s | Rejected |
| PyTorch CPU | 4 | 0.629 | 2.716 s | Rejected |
| PyTorch CPU | 8 | 0.528 | 2.089 s | Good |
| PyTorch CPU | 16 | **0.514** | **1.988 s** | **Production default** |

The selected TTS path is approximately 1.95 times real time. It is not presented
as Radeon-accelerated TTS. It is a deliberate system scheduling optimization
that protects Radeon capacity for the LLM and image workloads that benefit most
from GPU execution.

## 7. Benchmark Methodology

### 7.1 LLM workload

All API trials used:

- the same English fantasy prompt;
- one warm-up before measured trials;
- streaming output;
- 256 generated tokens;
- temperature 0.8 and top-p 0.95;
- thinking disabled;
- a direct local engine endpoint to isolate inference from tunnel latency;
- median values rather than the fastest single trial.

The prompt was:

> Write a continuous English fantasy scene about a city built above a sleeping
> dragon. Use vivid but concise prose and do not use headings.

The original vLLM eager, BF16 graph, and AWQ configurations used three measured
trials each. The selected llama.cpp configuration used five measured trials,
ranging from 91.43 to 91.66 tok/s. A separate `llama-bench` run measured 92.55
tok/s generation and 3,073 tok/s prompt processing.

### 7.2 Image workload

The image contract test used:

- a fixed English visual-novel prompt;
- seed 2026;
- one output image;
- URL response format;
- requested application dimensions of 1024x1536 for the selected endpoint;
- HTTP status validation and direct PNG download validation.

Cold and warm requests were measured separately. The original 320.438-second
reference was a BF16 1024x1024 run under the old co-resident memory layout.

### 7.3 TTS workload

The TTS benchmark used the same two-sentence English passage for all candidates.
The output contains approximately 7.2 seconds of audio. RTF is defined as:

```text
RTF = synthesis latency / generated audio duration
```

An RTF below 1.0 means synthesis is faster than real time. Both the OpenAI binary
audio contract and the application's MiniMax-compatible sentence-streaming
contract were validated.

## 8. Detailed Results

### 8.1 LLM results

The production configuration improved single-stream decode throughput by:

```text
91.60 / 23.76 = 3.86x
```

It improved over the best measured BF16 graph candidate by:

```text
91.60 / 25.63 = 3.57x
```

Median engine TTFT decreased by approximately 69%:

```text
(137 ms - 42.4 ms) / 137 ms = 69.1%
```

The narrative quality smoke test produced coherent English prose without empty
Qwen thinking tags or reasoning leakage. The gateway strips empty thinking
markers for normal narrative output.

### 8.2 Image results

| Configuration | Latency | Contract result |
|---|---:|---|
| BF16 1024x1024 under old co-resident layout | 320.438 s | Severe VRAM pressure |
| CPU-offload cold compatibility request | 26.759 s | HTTP 200 |
| CPU-offload warm compatibility request | 10.827 s | HTTP 200 |
| Public warm 1024x1536 URL request | 11.694 s | Downloadable valid PNG |

The 29.6x figure is calculated as:

```text
320.438 / 10.827 = 29.6x
```

This is an end-to-end application endpoint comparison. It is not a
like-for-like native-resolution model or kernel comparison because the selected
path uses a different internal render strategy and returns a fitted output.

### 8.3 TTS results

The selected 16-thread PyTorch CPU path produced:

- median RTF: 0.514;
- median first sentence: 1.988 seconds;
- production verification RTF: 0.516;
- production first sentence: 2.001 seconds;
- valid MP3 output;
- final stream statuses `[1, 2]`.

Compared with the eight-thread sherpa-onnx INT8 reference, the selected path
reduced RTF by approximately 53%.

### 8.4 Mixed-load behavior

With the LLM, image service, and CPU TTS all healthy:

- idle GPU memory: 11,092,443,136 bytes in live ROCm reporting;
- mixed smoke-test GPU utilization: 98%;
- observed board power: approximately 216 W;
- observed OOM events: none;
- service health response: LLM, image, and TTS all healthy.

This is evidence of functional coexistence, not a statistically complete load
or endurance test.

## 9. Reproduction

The repository includes reusable benchmark scripts. Credentials must be passed
through environment variables and must never be committed.

### 9.1 LLM benchmark

```bash
export SILENT_CORE_INTERNAL_API_KEY='<internal-test-key>'

python3 scripts/benchmark_llm.py \
  --base-url http://127.0.0.1:8001/v1 \
  --model silent-core/llm \
  --trials 5 \
  --max-tokens 256 \
  --output evidence/llm-benchmark.json
```

### 9.2 TTS benchmark

```bash
python3 scripts/benchmark_tts.py \
  --base-url http://127.0.0.1:8003/v1
```

### 9.3 Image contract benchmark

```bash
bash scripts/benchmark_image_contract.sh image-contract
cat /persistent/silent-core/logs/image-contract.meta
```

### 9.4 Radeon monitoring

```bash
watch -n 1 /opt/rocm/bin/rocm-smi \
  --showuse --showmemuse --showpower --showtemp
```

The final demonstration should record the application request and the monitoring
terminal in the same continuous capture so the GPU activity is visibly tied to
the agent operation.

## 10. Reliability, Security, and Rollback

- All `/v1/*` model endpoints require bearer authentication.
- API keys and host-specific URLs are excluded from the submission report.
- Client applications use stable `silent-core/*` model identifiers.
- Image requests are serialized to avoid unsafe single-GPU concurrency.
- The BF16 vLLM graph configuration remains available as a rollback path.
- The pre-change deployment snapshot is stored on the contest host under a
  timestamped backup directory.
- Health checks report each model service independently.

The final public submission must not include SSH endpoints, private keys, API
keys, internal bearer tokens, or temporary tunnel credentials.

## 11. Limitations and Claim Boundaries

1. **Single-host scope.** Results describe one `gfx1100` Radeon host and this
   project's workload. They do not claim superiority over multi-GPU datacenter
   systems.
2. **Small measured sample.** The reported LLM medians use three or five trials,
   depending on the candidate. They are sufficient for the contest A/B record
   but not a substitute for a long-duration p95/p99 production study.
3. **Quantized quality.** The Q4_K_M model passed a narrative smoke test, but a
   larger blinded quality evaluation should be added if time permits.
4. **Image comparison boundary.** The 29.6x result compares application paths
   under different internal rendering strategies. It must not be described as
   a pure native-resolution kernel speedup.
5. **CPU TTS.** Kokoro TTS is scheduled on the CPU. The Radeon acceleration
   claim applies to the core LLM and image inference paths.
6. **Transport overhead.** Temporary public tunnel latency is much higher than
   local engine TTFT. A direct or stable HTTPS endpoint is recommended for the
   final demo.
7. **Serialized image generation.** The single-GPU image endpoint favors
   stability over simultaneous high-concurrency image requests.

## 12. Recommended Competition Claims

The following statements are supported by the recorded evidence:

- “Core LLM and image inference run locally on one AMD Radeon GPU through
  ROCm.”
- “The selected LLM configuration improved measured single-stream decode from
  23.76 to 91.60 tok/s, a 3.86x increase.”
- “Median engine TTFT decreased from 137 ms to 42 ms.”
- “A memory-aware service layout eliminated the observed image-generation VRAM
  cliff and produced a warm application-compatible image response in 10.827
  seconds.”
- “CPU TTS scheduling reserves Radeon capacity for the latency-sensitive LLM
  and image workloads while remaining faster than real time.”
- “The final mixed-service smoke test reached 98% GPU utilization without an
  observed out-of-memory failure.”

The following claims should not be used:

- “world-record” or unqualified “state-of-the-art” inference;
- “29.6x native-resolution model acceleration”;
- “all three models run on Radeon”;
- “production p95 latency” without a larger repeated test;
- “no quality loss” without a formal quality evaluation.

## 13. Conclusion

The final configuration is not merely a faster model server. It is a
resource-aware inference architecture designed around the actual behavior of a
private multimodal agent on one Radeon GPU.

The optimization process produced three system-level outcomes:

1. **Interaction speed:** Qwen3-8B single-stream generation increased to a
   measured median of 91.60 tok/s with a 42 ms engine TTFT.
2. **Functional coexistence:** released GPU memory allows LLM and image services
   to coexist without returning to the observed 46.4 GiB memory-pressure path.
3. **Application compatibility:** the gateway exposes stable, authenticated
   text, image, and speech contracts that the narrative agent can invoke without
   third-party inference APIs.

These results directly support the Track 2 requirements for private local agent
deployment, Radeon execution, inference-speed optimization, and a fluid
end-to-end demonstration.

## Appendix A. Evidence Inventory

| Evidence | Purpose |
|---|---|
| `scripts/benchmark_llm.py` | Streaming TTFT and decode throughput |
| `scripts/benchmark_tts.py` | OpenAI and application-compatible TTS validation |
| `scripts/benchmark_image_contract.sh` | Portrait image contract and latency |
| `scripts/start_llm.sh` | Selected llama.cpp HIP configuration |
| `scripts/start_llm_vllm.sh` | BF16 graph rollback configuration |
| `PERFORMANCE_RESULTS.md` | Concise final A/B record |
| `API.md` | Application integration contract |

## Appendix B. Suggested Demo Overlay

During the optimization segment of the 3–5 minute demo, display this compact
summary beside live `rocm-smi` output:

```text
Qwen3-8B:       23.76 -> 91.60 tok/s  (3.86x)
Engine TTFT:    137 ms -> 42 ms       (-69%)
Warm image API: 320.4 s -> 10.8 s     (application path)
TTS:            RTF 0.514             (CPU scheduled)
Mixed load:     98% GPU, ~216 W, no observed OOM
```
