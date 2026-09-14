# BeaverBeaver: A Private, Evidence-Grounded Memory Agent on M5Stack CoreS3 and AMD Radeon

> AMD Radeon Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents
>
> Team: **Beaver Genius** · Project: **BeaverBeaver**
>
> Document status: English submission version · 2026-08-06

## 0. Submission Deliverables (Track 2)

This submission covers the four Track 2 deliverables:

1. **Project specification** (this document): application scenarios, agent
   architecture, core capabilities, model introduction and local deployment
   plan, and AMD Radeon GPU inference optimization notes.
2. **Complete source code** with READMEs covering environment setup, startup
   steps, and dependency lists: the CoreS3 firmware package
   (`firmware/`) and the Beaver Memory service package (`memory-server/`).
3. **Demo video** (3–5 minutes): a continuous, uncut real operation from the
   physical device through Radeon inference to an evidence-backed answer.
   *The video is being finalized and will be linked here and in the PR.*
4. **Presentation deck** (`presentation/`): a 10-slide English deck summarizing
   the project.

The runtime evidence screenshots referenced in Section 6 are included under
`radeon-inference/evidence/`.

---

## 1. Project Overview

### 1.1 One-line positioning

BeaverBeaver is a private multimodal memory agent that runs on M5Stack CoreS3
wearable hardware. The device continuously records first-person sound and
images; a private memory service (Beaver Memory) organizes the fragmentary
evidence into searchable, traceable long-term memory; and AMD Radeon inference
provides the listening, reasoning, and speaking loop:

- **Reasoning** — `Qwen3.6-35B-A3B` through the AMD Radeon API;
- **Speech recognition** — `Qwen3-ASR-1.7B` self-hosted on a Radeon Cloud GPU node;
- **Speech synthesis** — `VoxCPM-0.5` self-hosted on a Radeon Cloud GPU node.

### 1.2 Problem statement

Conventional voice assistants answer the current question but do not understand
what the user actually experienced. People still forget:

- Where they last put their keys, glasses, or charger;
- Who promised what during a conversation;
- What happened today, and when and where;
- Which memory came from which photo or original recording;
- Whether unsynced records were lost after a temporary network outage or a
  device restart.

BeaverBeaver's goal is not to generate an unverifiable "life summary". It builds
a private memory system in which **raw audio and images are the primary
evidence**, memories accumulate over a long horizon, and the user can inspect
and correct every result.

### 1.3 Deployment boundary (honest statement)

The contest demo uses a three-layer deployment:

- **M5Stack CoreS3** — edge device;
- **Beaver Memory server** — on the private LAN;
- **Radeon inference layer** — the interactive LLM is called through the AMD
  Radeon API; the ASR and TTS models are self-hosted by the team on Radeon Cloud
  GPU nodes. Models are not invoked from a public chat page: the agent calls
  Bearer-token HTTP APIs.

**Important:** the current demo is a "LAN-private memory service + AMD Radeon
API + self-hosted Radeon Cloud speech models" setup, **not** a fully offline
single-workstation deployment. Section 4.4 describes the migration path to a
completely local Radeon/ROCm workstation, keeping the API contract unchanged.

Raw images and WAV files are stored by Beaver Gateway. Device uploads use a
Bearer token. Raw evidence, derived memories, and user indexes are isolated per
user. Outbound model requests never carry local server file paths.

---

## 2. Application Scenarios

### 2.1 Everyday experience recall

Users ask "What did I do this afternoon?" or "Who did I discuss the project
with just now?" The system retrieves relevant experiences from long-term
Episodes and returns the time, the memory fragment, and the original audio/visual
evidence.

### 2.2 Finding objects

The device captures first-person images on a fixed interval. A dedicated object
chain extracts observations of items with recovery value. When the user asks
"Where did I last see my keys?", the system searches Object Observations instead
of letting the LLM guess from common sense.

### 2.3 Conversation commitments and to-dos

The system extracts explicit commitments from fully transcribed, evidence-backed
windows — for example, "I will send you the report on Friday." Candidates are
not treated as facts: the user confirms, edits, completes, or cancels them in the
web workbench.

### 2.4 Daily review

A daily review is generated in Beijing time with source constraints, including
"Today", "Worth noting", and "Special moments". Every entry must link to a real
Episode; a failed generation never overwrites the previous successful version.

### 2.5 Accessibility and cognitive assistance

For users who forget easily, want a life log, or want to reduce cognitive load,
BeaverBeaver provides a voice-first natural interaction entry point. The
M5Stack CoreS3 has a microphone, speaker, camera, screen, and touch — the user
does not always need a phone app.

### 2.6 Research and personal knowledge base

Researchers can use the system as a traceable personal multimodal pipeline:
raw evidence is stored stably, and VAD, ASR, captions, object cards, and
long-term memory are all re-runnable derived results, which is convenient for
comparing models and optimization schemes.

---

## 3. Agent Architecture

### 3.1 Overall architecture

```text
+----------------------------------------------------------------------------+
|  EDGE: M5Stack CoreS3 (ESP32-S3)                                            |
|  Camera (~1 frame / 5 s)   Microphone (30 s WAV slices)   Screen + Speaker  |
|  +--------------------+        +------------------------------------------+ |
|  |  SD persistent queue  | ---> |  Reliable upload: sequence + SHA-256     | |
|  +--------------------+        +------------------------------------------+ |
+-------------------------------------|---------------------------------------+
                                      | authenticated upload (ACK before delete)
                                      v
+----------------------------------------------------------------------------+
|  PRIVATE LAN: Beaver Memory service                                        |
|  Beaver Gateway   (auth, validate, dedupe, time-align, store)              |
|      |-- Multimodal understanding & parallel tasks                         |
|      |     Experience chain / Object chain / Person chain / Commitment chain|
|      |-- EverOS  (Episodes, Facts, Profiles)                               |
|      |-- Object Observation index (last-seen item locations)               |
|      `-- Memory Web (search, daily review, to-dos, evidence, correction)   |
+-------------------------------------|---------------------------------------+
                                      | /llm/  /asr/  /tts/   (single entry)
                                      v
+----------------------------------------------------------------------------+
|  AMD RADEON INFERENCE LAYER                                                 |
|  Nginx single entry: /llm/ -> AMD Radeon API (Qwen3.6-35B-A3B)             |
|                     /asr/ -> Radeon Cloud ROCm: Qwen3-ASR-1.7B (vLLM)      |
|                     /tts/ -> Radeon Cloud ROCm: VoxCPM-0.5 (PyTorch BF16)  |
+----------------------------------------------------------------------------+
```

A high-resolution vector version of the memory architecture is included in the
presentation assets (`presentation/beaver-memory-architecture.svg`).

### 3.2 Two parallel loops

BeaverBeaver splits realtime voice interaction and background continuous memory
into two independent chains:

- **Realtime loop:** speak → ASR → LLM + memory tools → TTS → CoreS3 playback
  with subtitles;
- **Memory loop:** continuous audio/vision → SD queue → Gateway → time window →
  multimodal understanding → Capsule → EverOS / object index.

This split ensures that a slow memory-consolidation task never blocks the
current conversation, and that a single model failure does not take down every
capability.

### 3.3 Reliable edge capture

Built on the M5Stack CoreS3 board support of the open-source Xiaozhi ESP32
project, the firmware adds a `BackgroundCaptureService`. It captures an image
about every 5 seconds and produces 30-second WAV slices. Media first enters a
durable SD-card queue; every record carries
`device_id + boot_id + stream_id + sequence`, capture time, and a SHA-256 hash;
the local file is deleted only after the server returns an explicit ACK.

The firmware also implements failure backoff, resume-on-reconnect, independent
audio/image sequences, upload concurrency degradation, shared SPI bus
protection for the SD/LCD, and low-memory resource-release policies. The
design principle is *"being able to record is more important than uploading in
real time"*.

### 3.4 Gateway and evidence chain

The Gateway performs authentication, length and SHA-256 validation, idempotent
deduplication, atomic persistence, and SQLite metadata commit. Audio and images
of the same boot are aligned by monotonic time into ~30-second technical
windows. Raw JPEG and WAV are first-class evidence; ASR transcripts, captions,
object cards, and Episodes can all be regenerated from the evidence.

### 3.5 Memory understanding and long-term storage

The memory service decomposes capabilities into non-blocking tasks:

- **Experience chain:** VAD gating → full-window ASR → first-person caption →
  cross-window semantic boundary → Capsule → EverOS;
- **Object chain:** YOLOE detection → cross-frame candidate aggregation →
  multimodal object card → Object Observation;
- **Person chain:** face candidates and voice-print candidates are maintained
  separately; a real name is written only after user confirmation;
- **Commitment chain:** candidate to-dos are extracted from transcripts and
  speaker evidence, then confirmed by the user;
- **Product layer:** memory timeline, natural-language search, object search,
  daily review, to-dos, and evidence drill-down.

EverOS is the single long-term Episode/Fact/profile aggregation engine; the
Gateway does not re-implement a second source of truth.

---

## 4. Core Capabilities

1. **Continuous, low-intrusion first-person recording.** The CoreS3 forms
   audio and image slices in the background; the user can still switch between
   normal-agent, memory-agent, text-only, and vision-enhanced modes via touch.
   Capture and realtime dialogue run in parallel.
2. **Offline-resilient reliable upload.** The local SD queue, unique sequence
   keys, content hashing, idempotent ACK, and retry backoff solve weak-network,
   restart, out-of-order, and duplicate-upload problems. If the same unique key
   ever maps to different content, the server refuses to overwrite it.
3. **Multimodal experience understanding.** Each technical window contains the
   full audio, the ASR transcript, and the timeline-aligned images. The system
   generates first-person experience descriptions from the wearer's "I"
   perspective, then decides across windows whether an event continues or a new
   event begins, reducing fragmentation caused by fixed 30-second slices.
4. **Traceable long-term memory.** Retrieval results can be drilled down to the
   Capsule, source images, and source audio. Model output is not an uncheckable
   final fact: users can view sources, confirm people, correct Episodes, and
   manage commitments.
5. **Parallel object/person/commitment processing.** Object, face, voice-print,
   and commitment tasks are independent with their own failure state. When any
   chain is offline or late, the main experience chain keeps running. Person and
   voice-print candidates are never auto-bound merely by temporal proximity.
6. **Private voice loop.** Qwen3-ASR-1.7B and VoxCPM-0.5 are team-deployed
   services on Radeon Cloud; Qwen3.6-35B-A3B is provided through the AMD Radeon
   API. The three capabilities are routed through a single Nginx entry, so the
   user's voice can complete the loop: *ask a question — retrieve private
   memory — generate an answer — play it back*.

---

## 5. Models and Deployment Plan

### 5.1 Model and component inventory

| Component | Model / implementation | Role | Deployment | Status |
| --- | --- | --- | --- | --- |
| ASR | `Qwen/Qwen3-ASR-1.7B` | Speech to text (interactive + memory windows) | Radeon Cloud / ROCm / vLLM | Running; startup and request screenshots available |
| Interactive LLM | `Qwen3.6-35B-A3B` | 35B total params, ~3B activated per token (sparse MoE); dialogue, orchestration, memory Q&A | AMD Radeon API (OpenAI-compatible) | Model name and call contract confirmed |
| TTS | `openbmb/VoxCPM-0.5` | Synthesize the final answer to natural speech | Radeon Cloud / ROCm / PyTorch BF16 | Loaded in BF16; request returns HTTP 200 |
| First-person understanding | `qwen3.5-omni-flash` | First-person caption from window audio + images + transcript | External inference service (Beaver Memory config) | Confirmed from running configuration |
| Cross-window memory model | `qwen3.7-flash` | `CONTINUE / BOUNDARY` decisions; commitment, daily-review text tasks | External inference service (Beaver Memory config) | Confirmed from running configuration |
| Production memory ASR | `fun-asr-flash-2026-06-15` | Full-window transcription of the memory chain | External inference service (Beaver Memory config) | Confirmed; contest version switches to Qwen3-ASR |
| Long-term memory | EverOS | Aggregates Episodes, facts, profiles | LAN private server | Wired into the memory pipeline |
| Object perception | YOLOE-26S + multimodal object cards | Detect and maintain object observations | Pluggable external/local worker | Independent chain in the memory system |

> Scope note: the current production memory-enrichment chain uses external
> Qwen3.5/Qwen3.7 and `fun-asr-flash`; the contest realtime voice loop uses
> Qwen3.6-35B-A3B on the AMD Radeon API and self-hosted Qwen3-ASR + VoxCPM on
> Radeon Cloud. These are two distinct configurations and are not conflated in
> this submission.

The Qwen3.6 call contract is OpenAI-compatible Chat Completions:

```bash
curl https://developer.amd.com.cn/radeon/api/v1/chat/completions \
  -H "Authorization: Bearer ${AMD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":"Hello"}]}'
```

Qwen also publishes the open weights `Qwen/Qwen3.6-35B-A3B` (Apache 2.0) with
vLLM, SGLang, and Transformers deployment guides. This lets the contest version
start on the AMD Radeon API and later migrate to a local Radeon host while
keeping model capability and interface largely identical.

### 5.2 Current deployment topology

1. **M5Stack CoreS3**: ESP-IDF firmware; captures images and PCM/WAV; maintains
   the SD queue; displays subtitles and plays TTS;
2. **LAN server**: Beaver Gateway, Web, persistent queue, retrieval projection,
   and EverOS;
3. **AMD Radeon API**: `Qwen3.6-35B-A3B` via
   `POST https://developer.amd.com.cn/radeon/api/v1/chat/completions`;
4. **Radeon Cloud node**: self-hosted `Qwen3-ASR-1.7B` and `VoxCPM-0.5`;
5. **Nginx**: because the platform exposes only one service, one entry routes
   `/llm/` to the AMD Radeon API and `/asr/` and `/tts/` to the local model
   ports (see `radeon-inference/nginx-three-services.conf` — externally listens
   on `8080`, forwards `/llm/v1/chat/completions`, `/asr/`, `/tts/`);
6. **Callers**: the LAN agent service uses a single Radeon entry and calls
   different models by path with the corresponding Bearer token.

### 5.3 Fully local migration plan

To satisfy a completely offline deployment, the team can migrate to a single
Radeon Linux workstation:

1. Install the same ROCm version and compatible PyTorch/vLLM as the contest env;
2. Download `Qwen/Qwen3.6-35B-A3B` open weights plus the Qwen3-ASR and VoxCPM
   weights into a local model directory;
3. Load the three models in three separate long-lived systemd or container
   services;
4. Keep the same Nginx path contract as the Radeon Cloud deployment;
5. Point the Gateway inference base URL at the LAN Radeon host;
6. With public egress disabled, run regression tests for ASR, memory search,
   LLM answering, and TTS playback;
7. Record VRAM, power, first-token latency, and end-to-end time with `amd-smi`
   and application logs.

Because the API contract is unchanged, the device firmware does not need to know
which GPU hosts the models — it only needs to reach the Beaver Gateway.

---

## 6. AMD Radeon GPU Inference Optimization

### 6.1 Verified runtime environment

The following values were measured live in the Radeon runtime:

| Item | Measured value |
| --- | --- |
| OS | Linux `6.8.0-79-generic` x86_64, glibc 2.39 |
| Python | 3.12.3 |
| PyTorch | `2.9.1+gitff65f5b` |
| ROCm/HIP | `7.2.53211-e1a6bc5663` |
| PyTorch CUDA field | `None` (not a CUDA build) |
| GPU available | `True`, 1 GPU |
| GPU name | AMD Radeon Graphics |
| VRAM | 47.98 GiB |
| Multiprocessors | 48 |
| vLLM | `0.16.1.dev0+g89a77b108.d20260317` |

These values match the `amd-smi` screenshot showing ROCm 7.2.1 and ~49 GB VRAM.

> Note: `device: cuda` appearing in PyTorch/application logs does **not** mean
> an NVIDIA GPU is in use. ROCm preserves the `cuda` device name for PyTorch
> CUDA-API compatibility; the GPU vendor should be confirmed via `amd-smi` and
> the ROCm environment.

### 6.2 Completed / evidenced optimizations

1. **Native ROCm runtime**: PyTorch `2.9.1+gitff65f5b` uses ROCm/HIP
   `7.2.53211`; CUDA field is `None`; inference runs on one 47.98 GiB AMD
   Radeon Graphics GPU.
2. **Sparse MoE model selection**: Qwen3.6-35B-A3B has ~35B total parameters but
   activates only ~3B per token, reducing per-forward compute while retaining a
   large model capacity. This is an application-level inference efficiency
   choice — not a claim of custom GPU kernels.
3. **BF16 inference**: VoxCPM-0.5 is loaded in `bfloat16`, lowering VRAM and
   bandwidth pressure versus FP32.
4. **Persistent vLLM service**: Qwen3-ASR-1.7B is served by vLLM with an
   OpenAI-style transcription API; the model stays resident to avoid reloading
   weights per request.
5. **KV-cache pre-allocation**: logs show ~35.63 GiB available for KV cache,
   capacity 333,536 tokens; concurrent-request headroom at the largest single
   context is estimated at ~5.09×.
6. **Model warm-up**: multimodal warm-up completes during service startup so
   that live requests do not pay first-time graph compilation and weight-paging
   costs.
7. **Inference role split**: ASR and TTS are independent long-lived processes;
   the LLM uses the AMD Radeon API; Nginx only routes, avoiding frequent model
   unload/reload across tasks.
8. **Single TTS worker**: VoxCPM currently uses one Uvicorn worker, avoiding
   duplicate large-model loads and VRAM waste.
9. **Asynchronous pipeline**: device capture, media upload, memory
   consolidation, and realtime dialogue are decoupled; the SD queue absorbs
   network and inference jitter for a smoother user interaction.

### 6.3 Optimization opportunities observed (not yet claimed)

The existing Qwen3-ASR logs also show the service runs in eager mode with
CUDAGraph disabled, and the ROCm custom paged-attention kernel falls back to a
Triton implementation when unavailable. These are the next optimization items —
**not** claimed as realized speedups. Next steps include:

- Verifying whether the model/current-vLLM/ROCm combination can disable
  `enforce_eager` and enable graph capture stably;
- Verifying ROCm custom attention-kernel compatibility to reduce Triton fallback;
- Tuning `gpu_memory_utilization`, max concurrency, max audio length, and batch
  size so KV-cache reservation does not squeeze three co-located models;
- Since the AMD Radeon API currently hosts the managed LLM, the local Radeon
  Cloud optimization scope focuses on Qwen3-ASR, VoxCPM, and unified service
  routing; precision/quantization for Qwen3.6 will be evaluated if its open
  weights are migrated locally;
- Adding long-text chunking and streaming output to TTS;
- Keeping Nginx connections long-lived with appropriate body size, read timeouts,
  and upstream connection pools;
- Running long continuous voice Q&A to check stability, audio integrity, and
  interruption recovery.

### 6.4 Runtime evidence

The project demonstrates the Radeon inference chain's usability, fluidity, and
functional completeness with real runtime evidence (screenshots under
`radeon-inference/evidence/`):

- `amd-smi` shows ROCm 7.2.1, the Radeon GPU, VRAM usage, and the inference
  processes;
- Qwen3-ASR logs show model load, warm-up, KV-cache initialization, and
  successful `/v1/audio/transcriptions` requests;
- VoxCPM-0.5 loads in BF16 and returns HTTP 200 for `/generate_tts`;
- The CoreS3 physical device shows the three interaction states
  "RECORDING / THINKING / SPEAKING";
- The Beaver Memory workbench proves real CoreS3 media forms Capsules and
  long-term Episodes.

Instantaneous throughput values in the vLLM logs are shown only as service logs;
they are not converted into audio real-time factors, and no unbenchmarked
speedup percentage is claimed.

---

## 7. Source Code and Reproducibility

### 7.1 Repository layout (this submission)

```text
track-2-beaver-genius-beaverbeaver/
├── README.md                     # Top-level submission README (setup, start, deps)
├── project-spec.md               # This specification
├── firmware/                     # Sanitized CoreS3 firmware package (pinned upstream + patch)
├── memory-server/                # Sanitized Beaver Memory runtime package
├── radeon-inference/             # Nginx three-service config + runtime evidence screenshots
└── presentation/                 # English deck and architecture artwork
```

The contest requires a complete source repository. This submission follows the
"one contest repository" approach: the firmware component, the memory server,
and the Radeon deployment configuration are all present in this PR, so judges
do not need access to any private SSH address. Model weights are **not**
committed to Git; the package READMEs give official download addresses,
licenses, and setup instructions.

- **firmware/**: minimal public firmware package. It pins upstream
  `78/xiaozhi-esp32` at commit `417f52d7597b85f3dfc6f5283bdc66df34fbd5fe`
  (2026-05-14, MIT) and provides the full `patches/0001-beaverbeaver-cores3.patch`
  needed to reconstruct the CoreS3 firmware (`prepare_firmware.sh`, build, flash,
  and `verify_public_package.sh`).
- **memory-server/**: publishable runtime subset of Beaver Memory — FastAPI
  gateway, memory pipeline, external model clients, EverOS integration, web
  workbench, device/external contracts, and deployment scripts (setup, EverOS
  installer, readiness checks, systemd templates). Deliberately excludes
  credentials, personal memory data, captured media, model weights, and private
  history. See `memory-server/README.md` for the full quick start.
- **radeon-inference/**: `nginx-three-services.conf` (the single-entry router
  for `/llm/`, `/asr/`, `/tts/`) and the runtime evidence screenshots.

### 7.2 End-to-end startup sequence (with the self-hosted Radeon models)

1. Confirm `Qwen3.6-35B-A3B` on the AMD Radeon API with a minimal `curl`;
2. Start Qwen3-ASR and VoxCPM on the Radeon Cloud node and check local health;
3. Start Nginx and run minimal `/llm/`, `/asr/`, `/tts/` requests through the
   single entry;
4. Start EverOS, Beaver Gateway, and Web on the LAN server;
5. Run the service check script to confirm inference endpoints and durable
   directories;
6. Build and flash the CoreS3 firmware; configure Wi-Fi, Gateway URL, and the
   device token;
7. Watch via serial output as images/audio enter the SD queue, upload, and
   receive ACK;
8. Open the memory Web and wait for an Episode to form;
9. Ask a question on the CoreS3 and play back the answer produced by the Radeon
   inference chain.

---

## 8. Demo Video Plan

A 3–5 minute demo video will be attached. It is recorded with the real device,
terminal, and web pages — no pre-rendered animation-only reel. Planned shots:

| Time | Scene | Emphasis |
| --- | --- | --- |
| 0:00–0:25 | CoreS3 hardware + title | "Record continuously, remember privately, recall with evidence" |
| 0:25–0:55 | Architecture diagram | Three-layer deployment, realtime loop and memory loop |
| 0:55–1:25 | Radeon terminal | `amd-smi`, ROCm version, ASR/TTS processes, Qwen3.6 request, Nginx single entry |
| 1:25–2:05 | CoreS3 real capture | A sentence with a person/object/commitment; serial shows sequence + ACK |
| 2:05–2:45 | Memory Web | Timeline entries; open the evidence drawer: source image, transcript, Capsule |
| 2:45–3:25 | Object/experience search | "Where did I leave it" / "What did I just do" with sourced results |
| 3:25–4:05 | CoreS3 voice Q&A | Live ASR → LLM/memory tools → VoxCPM → speaker playback |
| 4:05–4:30 | Runtime evidence + summary | `amd-smi`, successful request logs, CoreS3 states, privacy value |

The video keeps at least one uncut voice request while showing the CoreS3 state
transitions, the model request logs, and the Radeon VRAM status.

---

## 9. Innovation and Value

1. **From chat assistant to experience agent**: the system answers not just
   public knowledge but what the user actually experienced;
2. **Evidence first**: raw audio/visuals are irreplaceable; model results are
   re-runnable; every answer can be drilled down and verified;
3. **Edge/Radeon division of labor**: CoreS3 handles low-power sensing and
   interaction; the Radeon GPU handles large-model inference;
4. **Reliability before real-time**: store first, ACK before deletion — weak
   networks and restarts do not easily cause memory loss;
5. **Parallel and failure-isolated**: experience, object, person, voice-print,
   and commitment tasks never block each other;
6. **User-correctable**: candidates are not facts; people, Episodes, to-dos,
   and daily reviews all have confirm/correct paths;
7. **Single-entry private model service**: under the platform's one-exposed-service
   constraint, Nginx unifies the three Radeon inference APIs.

---

## 10. Known Limitations and Next Steps

- The current demo is a LAN-private memory service + AMD Radeon API + Radeon
  Cloud self-hosted speech models; full offline single-workstation deployment is
  the next milestone (Section 5.3).
- The current ASR runs in eager mode; CUDAGraph and ROCm attention-kernel
  compatibility are future optimization items, not claimed results.
- Memory-enrichment models in the current production configuration differ from
  the contest realtime loop; the contest version unifies on the Radeon models.
- Follow-up: finalize and link the demo video, and publish the top-level repo.

## 11. Sources of Fact

This specification is based on:

- The Track 2 submission requirements of the contest repository;
- The M5Stack CoreS3, `BackgroundCaptureService`, interaction modes, and bridge
  code in the working `xiaozhi-esp32` tree;
- The Beaver Memory README, current production pipeline, external service
  contracts, and Gateway documentation;
- The Radeon Cloud / ROCm / Qwen3-ASR / VoxCPM screenshots in this submission;
- The developer's deployment notes for the three Radeon services behind the
  single Nginx entry.

Items marked "planned" in this document are not rewritten as completed.
