# Novel Fate Simulator - Project Specification

## 1. Submission identity

- **Track:** Track 2 - Development and Local Deployment of Private AI Agents
- **Team:** Silent Core
- **Member:** asher
- **Application:** Novel Fate Simulator
- **Primary language for the competition:** English

## 2. Product vision

Novel Fate Simulator is a private, stateful narrative agent that turns a
user-owned novel into a persistent interactive world. The player enters the
world as a selected character. Every decision can change relationships,
factions, goals, canon anchors, and possible endings while the system preserves
the identity and rules of the source material.

The intended experience is:

> I entered this fictional world, and this is how the world changed because of
> me.

## 3. Application scenarios and users

### 3.1 Private manuscript simulation

A writer can test alternate character decisions without sending an unpublished
manuscript to a third-party inference provider. The extracted lore and generated
state stay in the team-controlled environment.

### 3.2 Canon-aware interactive fiction

A reader enters a familiar novel as a key character. The system preserves canon
anchors but allows their outcomes to change through accumulated actions.

### 3.3 Persistent role-playing worlds

TRPG and text-role-playing players receive a world that remembers alliances,
hostility, objectives, unlocked contacts, and earlier decisions instead of
resetting context every turn.

## 4. Agent architecture

```text
                         Novel upload
                              |
                 Deep novel analysis pipeline
                              |
       lore + characters + factions + rules + story anchors
                              |
                              v
User action ---> Game Engine / Agent Orchestrator
                    |        |        |
                    |        |        +--> ending and closure evaluator
                    |        +-----------> goal and faction systems
                    +--------------------> scene and action generation
                              |
       retrieve lore + current WorldState + recent interactions
                              |
                              v
           OpenAI-compatible private model gateway
             |               |                  |
       Qwen3-8B          Z-Image-Turbo      Kokoro-82M
       Radeon/ROCm       Radeon/ROCm        CPU scheduled
             |               |                  |
             +------- narrative response -------+
                              |
                   validate and persist changes
                              |
       PostgreSQL / Redis / saves / ending archives
```

## 5. Agent execution loop

1. Receive the user's action or intent.
2. Load the current session, WorldState, recent interactions, and relevant
   source-material anchors.
3. Construct a constrained prompt for the current character and world state.
4. Generate the next scene and context-aware actions.
5. Validate and apply relationship, faction, goal, divergence, and anchor
   updates.
6. Invoke image generation when a visual scene is required.
7. Invoke speech synthesis when narration is enabled.
8. Persist the new state and evaluate whether an ending can be generated.

This loop distinguishes the system from a stateless chat interface: the model
does not receive only the latest user message, and its output is not accepted as
an isolated block of prose.

## 6. Core capability mapping

### 6.1 Multi-step planning

The Game Engine coordinates several bounded steps rather than asking a model to
produce the entire experience in one prompt. Scene generation, action
generation, goal updates, faction snapshots, contact unlocks, illustration, and
ending evaluation are separate operations.

### 6.2 Private knowledge grounding

The novel-analysis pipeline extracts a structured representation of the source:

- world rules and central conflict;
- characters and character arcs;
- factions, alliances, and hostility;
- story anchors that preserve the identity of the source;
- world, faction, character, and fate goals.

Each turn retrieves the applicable structure and the current WorldState. This
submission describes that mechanism as structured private knowledge retrieval,
not as vector RAG unless a vector index is used in the final demonstrated build.

### 6.3 Persistent multi-turn memory

Memory is stored as explicit state rather than relying only on an expanding chat
history. The application maintains:

- player and NPC relationship changes;
- faction influence and controlled regions;
- active, completed, drifted, and newly created goals;
- contact unlocks and high-impact communication summaries;
- automatic, manual, and checkpoint saves;
- generated endings and ending archives.

### 6.4 Tool and service invocation

The application orchestrator invokes the LLM, image, TTS, data, and state
services. This is a deterministic application-level tool workflow. The current
submission does not claim autonomous LLM function calling unless that behavior
is enabled and demonstrated later.

### 6.5 Privacy and permissions

Core inference is hosted by the team instead of a third-party inference API.
The application layer includes user authentication, administrator
authentication, user-owned saves, and protected model endpoints using bearer
authentication. Secrets remain in server-side environment variables.

## 7. Models and local deployment plan

### 7.1 LLM

- **Model:** Qwen3-8B Q4_K_M
- **Runtime:** llama.cpp compiled with HIP
- **Device:** AMD Radeon `gfx1100`
- **Role:** narrative generation, action generation, structured analysis, and
  agent planning support
- **Reason for selection:** best measured single-stream latency and throughput
  among the evaluated configurations while reducing resident memory.

### 7.2 Image model

- **Model:** Z-Image-Turbo
- **Runtime:** PyTorch/Diffusers with ROCm
- **Device:** AMD Radeon GPU with model CPU offload
- **Role:** scene backgrounds and character illustrations
- **Scheduling:** serialized image inference avoids simultaneous high-memory
  image jobs on the single GPU.

### 7.3 TTS model

- **Model:** Kokoro-82M
- **Runtime:** PyTorch
- **Device:** 16 CPU threads
- **Role:** English narration and character speech
- **Scheduling reason:** CPU placement preserves Radeon capacity for the LLM
  and image model and achieved an RTF below 1.0 on the contest host.

### 7.4 Gateway

One authenticated, OpenAI-compatible gateway exposes stable application model
IDs:

- `silent-core/llm`
- `silent-core/image`
- `silent-core/tts`

This keeps application integration unchanged if an implementation model is
replaced after additional quality testing.

## 8. AMD Radeon inference optimization

### 8.1 Optimization process

We evaluated the following LLM configurations with the same English prompt, one
warm-up, streaming output, and 256 generated tokens:

- vLLM BF16 eager mode;
- vLLM BF16 full-decode graph;
- vLLM BF16 piecewise graph;
- vLLM AWQ;
- llama.cpp HIP with Q4_K_M quantization.

The final choice was based on measured latency, throughput, compatibility,
memory use, and narrative-output smoke tests rather than framework preference.

### 8.2 Selected result

llama.cpp HIP Q4_K_M reached a median 91.60 tokens/s with a 42 ms direct-engine
TTFT. The original vLLM BF16 eager baseline reached 23.76 tokens/s and 137 ms.
This is a 3.86x decode-rate improvement and a 69% TTFT reduction for the fixed
single-stream workload.

### 8.3 Image memory optimization

The original co-resident BF16 image path reached approximately 46.4 of 48 GiB
and fell into a 320.438-second memory-pressure path. The selected service uses
model CPU offload, a memory-safe aspect-matched internal render, and high-quality
Lanczos fitting. A warm `1024x1536` application-compatible request completed in
10.827 seconds.

Because the internal rendering strategy changed, the 29.6x figure is reported
as an end-to-end endpoint improvement, not a native-resolution kernel-only
speedup.

### 8.4 Resource-aware heterogeneous scheduling

The LLM and image model use the Radeon GPU. TTS uses the CPU. With all three
services healthy, idle GPU memory was approximately 10.1 GiB. A mixed workload
of two LLM requests plus one image request reached 98% GPU utilization at about
216 W and completed without an out-of-memory failure.

## 9. API integration

The application consumes model services through an OpenAI-compatible contract:

- Chat Completions and Responses for narrative text;
- Image Generations for scene art;
- Audio Speech plus a MiniMax-compatible adapter for narration;
- Models and Health endpoints for discovery and readiness checks.

Authentication, hostnames, and model IDs are provided through backend
environment variables. Credentials are never embedded in the public frontend.

## 10. Reproducibility and evaluation

The model-service benchmark suite covers:

- direct-engine and gateway LLM TTFT and decode rate;
- image contract validation for requested dimensions and downloadable output;
- TTS real-time factor, first-sentence latency, and output validity;
- mixed-load GPU utilization and out-of-memory behavior.

All performance claims in this document are scoped to one Radeon host and the
documented fixed workload. They are not presented as absolute state-of-the-art
claims against datacenter or multi-GPU systems.

## 11. Demo plan

The final 3-5 minute video will show:

1. the Radeon device, ROCm runtime, and healthy local model services;
2. a user entering a novel world and taking a first action;
3. a second action that proves the previous relationship/state change persists;
4. image and speech service invocation;
5. the LLM before/after benchmark;
6. mixed workload GPU utilization without an out-of-memory failure;
7. saves, world-state changes, and an ending or fate summary.

## 12. Known limitations

- Image requests are serialized on the single GPU.
- The temporary demo tunnel is not a production transport and is excluded from
  stable endpoint claims.
- Full application-source publication, the demo video, and the presentation are
  still pending in this draft submission update.
- Model-output quality requires continued evaluation in addition to latency
  benchmarking.

