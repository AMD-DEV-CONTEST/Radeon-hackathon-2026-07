# Novel Fate Simulator

> A private, stateful narrative agent on AMD Radeon

| Submission field | Value |
|---|---|
| Track | Track 2 - Development and Local Deployment of Private AI Agents |
| Team | Silent Core |
| Member | asher |
| Application | Novel Fate Simulator |
| Submission status | Draft update with verified Radeon model-service evidence |

## One-sentence summary

Novel Fate Simulator transforms a user-owned novel into a persistent simulated
world: it retrieves canon anchors, plans each turn, invokes text, image, and
speech services, updates structured memory, and runs core inference in a
team-controlled environment using AMD Radeon and ROCm.

## The problem

Generic story chatbots are stateless. They forget relationships, contradict the
source novel, and reduce meaningful player choices to isolated text generation.
Sending an unpublished manuscript to a third-party inference API also creates a
privacy problem for writers and readers.

Novel Fate Simulator addresses both limitations. It extracts a structured world
model from a novel and then maintains the consequences of the player's choices
across turns, saves, faction changes, relationship changes, goals, and endings.

## Why this is an agent

For each player turn, the application performs a multi-step agent workflow:

```text
User intent
  -> retrieve private lore and the current WorldState
  -> plan the next narrative transition
  -> generate a scene and context-aware actions
  -> validate the state transition
  -> invoke image and speech services when needed
  -> update relationships, factions, goals, anchors, and fate
  -> persist memory and evaluate possible endings
```

The product is not presented as autonomous function calling. Tool invocation is
performed by the application orchestrator, and private-knowledge grounding is
implemented through structured lore, canon anchors, and WorldState retrieval.

## Core capabilities

- **Multi-step planning:** the game engine coordinates retrieval, scene and
  action generation, state updates, goal evaluation, and ending evaluation.
- **Private knowledge grounding:** novel analysis extracts world rules,
  characters, factions, conflicts, and story anchors used in later turns.
- **Persistent multi-turn memory:** relationships, factions, goals, saves,
  archives, and the WorldState survive beyond a single prompt.
- **Multimodal service invocation:** the orchestrator calls text, image, and
  speech services behind one authenticated interface.
- **Privacy and permissions:** inference stays in the team-controlled model
  environment; the application includes authentication and user-owned saves.

## Model stack

| Capability | Stable API model ID | Current implementation | Compute |
|---|---|---|---|
| Narrative and agent reasoning | `silent-core/llm` | Qwen3-8B Q4_K_M, llama.cpp HIP | AMD Radeon GPU |
| Scene illustration | `silent-core/image` | Z-Image-Turbo, Diffusers CPU offload | AMD Radeon GPU |
| English narration | `silent-core/tts` | Kokoro-82M, PyTorch | 16 CPU threads |

TTS is intentionally scheduled on the CPU so it does not contend with the LLM
and image workloads on the single GPU. Client applications use stable
`silent-core/*` identifiers through an OpenAI-compatible gateway.

## Verified AMD Radeon results

Measurements were collected on 2026-08-06 on one AMD Radeon `gfx1100` GPU with
48 GiB VRAM and ROCm 7.2.1.

| Workload | Baseline | Selected configuration | Result |
|---|---:|---:|---:|
| LLM decode | 23.76 tok/s, vLLM BF16 eager | 91.60 tok/s, llama.cpp HIP Q4_K_M | 3.86x |
| LLM engine TTFT | 137 ms | 42 ms | 69% lower |
| Warm application-compatible image endpoint | 320.438 s memory-cliff reference | 10.827 s | 29.6x endpoint latency |
| TTS | sherpa-onnx INT8 RTF 1.091 | PyTorch CPU RTF 0.514 | faster than real time |

The image comparison is an end-to-end application latency comparison, not a
like-for-like native-resolution model benchmark. The selected path renders at a
memory-safe internal aspect ratio and applies Lanczos fitting to the requested
output dimensions.

A mixed two-LLM-plus-image test reached 98% GPU utilization at approximately
216 W without an out-of-memory failure. With all three services healthy, idle
GPU memory was approximately 10.1 GiB.

See [Performance Results](PERFORMANCE_RESULTS.md) for the full A/B table and
methodology.

## API surface

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/images/generations`
- `POST /v1/audio/speech`
- `GET /v1/models`
- `GET /health`

See [Model API](MODEL_API.md) for the application integration contract. Public
hostnames and credentials are deliberately excluded from the repository.

## Submission materials

- [Project Specification](PROJECT_SPECIFICATION.md)
- [AMD Radeon Inference Optimization Report](RADEON_INFERENCE_OPTIMIZATION_REPORT.md)
- [Model API](MODEL_API.md)
- [Performance Results](PERFORMANCE_RESULTS.md)

The following required items are still being prepared and are intentionally not
claimed as complete in this draft:

- complete public application source and English startup README;
- 3-5 minute end-to-end demo video;
- English presentation or poster;
- final English PDF export of the project specification.

## Honest limitations

- The current public transport option is a temporary demo tunnel, so the final
  video should use a direct or stable HTTPS endpoint.
- Image requests are serialized on the single GPU.
- The image acceleration number includes a different internal render strategy;
  it should not be interpreted as a native-resolution kernel-only speedup.
- These results describe one Radeon host and a fixed workload; they are not a
  claim to beat multi-GPU datacenter systems in absolute performance.
