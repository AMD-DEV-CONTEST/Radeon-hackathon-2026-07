# Project Specification: Aetheris

**Track 2: Development & Local Deployment of Private AI Agents**

**Aetheris** is a local, private coding agent: a desktop app that chats, edits and reads files, runs shell commands, inspects git state, searches a codebase, browses the web read-only, and plans multi-step work, all on the user's own AMD Radeon GPU, no cloud API or account required. "Local" is meant literally, not as a marketing gloss on a thin wrapper around a hosted API: the model weights never leave the machine, no request or file content is ever sent anywhere over the network, and the app functions fully offline once a model is pulled once. It doesn't call out to an existing closed-source agent platform for its core loop; the tool dispatch, planning, memory, and skill-retrieval logic below are this project's own, built specifically because the project brief asked for a private agent, not because an existing framework didn't fit.

It runs on **VTE**, an inference engine we also built from scratch for this hardware rather than depending on an existing runtime (llama.cpp/vLLM/Transformers). VTE is a real, separate piece of engineering with its own optimization story, covered briefly in [Section 5](#5-bonus-powered-by-vte), but it exists to serve Aetheris, not the other way around; everything through Section 4 is about the agent.

## 1. Application Scenario

**Personal intelligent assistant, specialized for local software development.** A developer opens Aetheris, points it at a project folder, and works with it the way they'd work with a pairing partner: ask it to explain a part of the codebase, have it track down and fix a bug, ask it to plan a feature before touching anything, let it look something up online without ever risking a credential or a form submission.

A typical session looks like: *"what does this module do"* (reads and summarizes, no side effects) -> *"add input validation to the `parse` function"* (proposes an edit, pauses for a confirm click) -> *"remember that this project validates at the boundary, not deep in business logic"* (written to durable memory, recalled automatically in later sessions without bloating the chat transcript). See the root [`README.md`](README.md#things-to-try) for more example prompts to run against a real project.

This scenario was chosen because it's the one the tool tree actually supports end-to-end (see [Core Capabilities](#3-core-capabilities)), not retrofitted onto it: bash execution, file read/write/edit, `git`, content search, and a todo/planning surface are exactly the primitives a local dev assistant needs, and nothing here assumes internet access at inference time.

The intended user is a developer who wants a coding assistant they can actually trust with a real project: nothing typed into the chat, nothing in the codebase it reads, and nothing it writes ever leaves the machine, because there's no server on the other end to send it to. That matters more for some codebases than others (client work under NDA, anything with embedded credentials or proprietary business logic, a hobby project the developer just doesn't want feeding someone else's training data), but the point of building this at all was to make "local" a real, load-bearing property of the tool rather than a checkbox: the agent loop, the tool dispatch, the memory and skill systems, and the inference engine underneath are all things this project controls end to end, so there's no closed-source dependency anywhere in the chain that could quietly start phoning home.

## 2. Agent Architecture

Modeled in **ArchiMate** notation (Business / Application / Technology layers), all confined to a single node since this is a fully local, single-machine deployment with no distributed or cloud tier:

```mermaid
%%{init: {'flowchart': {'curve': 'linear'}}}%%
flowchart TB
    subgraph BusinessLayer["Business Layer"]
        direction LR
        Actor(["Developer\n«Business Actor»"])
        Process["Local AI-Assisted\nSoftware Development\n«Business Process»"]
    end

    subgraph ApplicationLayer["Application Layer"]
        direction TB
        UI["Aetheris UI\n(Flutter desktop)\n«Application Component»"]
        Boot["Bootstrap & Health-Poll\n(spawn app.py, retry / every\n500ms, 20s budget)\n«Application Process»"]
        BE["Aetheris Backend\n(FastAPI, app.py)\n«Application Component»"]
        Auth["Local Auth\n(PBKDF2, per-machine\naccount)\n«Application Function»"]
        Loop["Tool-Call Round Loop\n(SSE stream, one fenced\ntool-call block per round)\n«Application Process»"]
        Gate["Confirm Gate\n(pause on write_file/edit_file/\nrisky bash, wait for UI click)\n«Application Function»"]
        Tools["Tool Dispatch\n(bash, file r/w/edit, git,\nsearch, memory, skills, browser)\n«Application Function»"]
        ChatSvc(("Chat Completion\n«Application Service»"))
        VS["vte-server\n«Application Component»"]
        API["OpenAI-Compatible HTTP\n(/v1/chat/completions, /health)\n«Application Interface»"]
        VTE["VTE Inference Engine\n«Application Component»"]
        Decode["Decode Loop\n(HIP Graph replay, GEMV +\nSplit-KV attention per token)\n«Application Function»"]
    end

    subgraph TechnologyLayer["Technology Layer"]
        direction LR
        HIP["ROCm / HIP Runtime\n«System Software»"]
        GPU["AMD Radeon GPU\n«Device»"]
    end

    Actor -- assigned to --> Process
    Process -. served by .-> ChatSvc
    Actor -- triggers --> UI
    UI -- composed of --> Boot
    Boot -- triggers --> BE
    UI -. served by .-> Auth
    BE -- composed of --> Auth
    BE -- composed of --> Loop
    Loop -- triggers --> Gate
    Gate -. served by .-> UI
    Gate -- triggers --> Tools
    Loop -- triggers --> VS
    VS -- composed of --> API
    VS -- realized by --> VTE
    VTE -- composed of --> Decode
    VTE -. realizes .-> ChatSvc
    Decode -. served by .-> HIP
    HIP -- assigned to --> GPU

    classDef business fill:#FFFFB3,stroke:#C0A000,color:#000
    classDef application fill:#B3D9FF,stroke:#4A86C8,color:#000
    classDef technology fill:#C6EFCE,stroke:#5F8F4E,color:#000

    class Actor,Process business
    class UI,Boot,BE,Auth,Loop,Gate,Tools,ChatSvc,VS,API,VTE,Decode application
    class HIP,GPU technology
```

Legend: solid arrows are ArchiMate **triggering**/**assignment**/**composition** relationships (active behavior, structural containment); dotted arrows are **realization**/**serving** (a concrete element fulfilling a more abstract service). `Boot`, `Loop`, `Gate`, and `Decode` are the actual internal processes/functions behind each component, not just black boxes: bootstrap and health-polling, the per-round SSE tool-call loop, the human-in-the-loop confirmation pause, and the HIP-Graph decode step, respectively.

**Request flow.** The Flutter UI launches `app.py` on startup (`BackendLauncher.ensureRunning()`, polling `/` every 500 ms, 20 s budget) and shows a connecting state until it's up. `app.py` lazily (or eagerly, via `/api/vte/warmup`) spawns `vte-server` as a subprocess and polls its `/health` endpoint (90 s budget) before serving the first real request. A chat turn streams over SSE; each round the model's output is scanned for a fenced tool-call block (` ```toolname\n...\n``` `). This fenced-code-block convention is the *only* tool-invocation mechanism, chosen because it works with any instruction-tuned GGUF model without a native function-calling API.

**Tool dispatch is three-way**, not one flat list:
- **Server-executed** (`TOOL_REGISTRY`): `bash`, `read_file`, `write_file`, `edit_file`, `search_files`, `git`, `manage_memory`, which are run directly by the Python backend.
- **Client-executed** (`CLIENT_EXECUTED_TOOLS`): `navigate_browser`, `read_browser_page`. The backend can't drive a browser itself, so it emits a `browser_action` event and the Flutter process performs it, feeding the result back as a hidden continuation turn.
- **Confirmation-gated**: `write_file`/`edit_file` always, `bash` when the command matches a destructive pattern (`is_risky_bash_command`). The round pauses, the UI shows a diff/command preview, and only a real user click resumes execution. The terminal client (`Aetheris Studio/scripts/chat.py`, see the root README) surfaces the same pause as a typed `y`/`N` prompt, same gate either way.

**Cross-platform.** The Flutter UI itself is Windows-only today (no `linux/` platform target configured yet), but the agent *backend* (`app.py`, pure Python/FastAPI, no Windows-specific code) is not: it was separately validated headless (no UI, direct HTTP calls against the real `stream_agent` loop) on an AMD Radeon Cloud W7900 Linux instance, the same one used for the inference-engine benchmarks in Section 5. Verified for real, not assumed: server-executed tool dispatch (`bash`, real subprocess execution with correct output), skill creation and retrieval (`manage_skill`, TF-IDF search returning the right skill with its full structured content), memory creation and retrieval (`manage_memory`, including one round that survived a model-generated typo in the tool tag thanks to the fence-tag tolerance fix), and the `write_file` confirmation gate end-to-end (the `confirm_tool` pause, `POST /api/tools/execute` performing the real write after simulated approval, and the file landing with the exact requested content). The root README's terminal quickstart runs this exact path.

## 3. Core Capabilities

Implements **all 5** optional capabilities listed in the task brief (2 are the stated minimum):

| Capability | Implementation | Try it |
|---|---|---|
| Tool invocation | Fenced-code-block calls dispatched to bash, file r/w/edit, `git` (status/diff/log/show/branch), content search, memory, skills, browser navigation (see [Architecture](#2-agent-architecture)) | *"what changed in the last 5 commits?"* |
| Multi-step task planning | **Builder/Planner mode toggle.** In Planner mode the agent is restricted to read-only tools plus `write_plan`, which streams a Markdown plan to a floating review panel instead of acting; the user approves (-> Builder mode, agent executes) or sends revision feedback (plan gets rewritten, still Planner). Mode is enforced server-side (`BUILDER_ONLY_TOOLS`/`PLANNER_ONLY_TOOLS`), not just prompted | *"plan how you'd add rate limiting here, don't touch anything yet"* |
| Local multi-turn memory | Full conversation history persisted per session; a separate `manage_memory` tool (add/search/forget) gives the agent durable memory across sessions, independent of the chat transcript | *"remember that this project uses tabs, not spaces"* |
| Local knowledge retrieval (RAG) | **Skill library**: reusable named procedures (`SKILL.md` files, YAML frontmatter + structured body) the agent writes for itself via `manage_skill` (add/search/forget) after solving something non-trivial, and searches before starting a task it may have solved before. Retrieval is TF-IDF cosine similarity over the current library, recomputed per query, which is deliberately not a neural embedding (no ONNX/sentence-transformers/extra model process): on the same RX 7600 that's already fully committed to the loaded chat model, a second model competing for the remaining ~4-6 GB of VRAM (or CPU cycles, for a "local" embedding server) isn't free the way it would be on a discrete deployment. TF-IDF costs nothing beyond the CPU time to tokenize a few dozen short skill files | agent writes one on its own after a multi-step fix; ask it to search its skills before a similar task |
| Permission control & privacy | Local username/password gate in front of the whole app, generated automatically (random credentials) on first run rather than requiring manual setup; every internal API call requires a machine-local shared-secret header; destructive file writes and risky shell commands require an explicit human click (or terminal `y`) before executing; `navigate_browser`/`read_browser_page` are read-only by construction, the agent cannot submit forms, enter credentials, or take side-effecting actions on the web | *"look up the current stable version of \<library> online"* |

## 4. Running It

Full setup, on both Windows and Linux, both as the desktop app and from a terminal: root [`README.md`](README.md#quickstart). Short version: `pip install -e` VTE into Aetheris's virtual environment, pull a GGUF model, either launch the Flutter UI (Windows) or run `app.py` plus `scripts/chat.py` (Windows or Linux). No manual GPU configuration; VTE reads the real architecture and compute-unit count off the device at startup.

GGUF integrity is checked against a known-good SHA-256 and a per-architecture metadata whitelist (layer count, tensor shapes) before any weight is loaded, so a corrupted or mismatched download fails loudly at load time rather than producing silently wrong output.

## 5. Bonus: Powered by VTE

Aetheris needed an inference engine that runs entirely on an AMD Radeon GPU with nothing else installed, no PyTorch, no ONNX Runtime, no dependency on llama.cpp/vLLM in the core path, so this project built one: **VTE**, hand-written HIP kernels that parse GGUF directly and generate/compile their own kernel code for the detected architecture. This is a different kind of engineering bet than tuning an existing runtime's batching settings for a faster number in one specific case: every layer between the GGUF file and the GPU (parsing, memory planning, kernel codegen, the decode loop itself) is this project's own code, not configuration on top of someone else's engine.

It loads any of eight curated models across four architecture families, validated on both a consumer RDNA3 card (RX 7600, 8 GB) and a workstation RDNA3 card (Radeon PRO W7900, 48 GB, via AMD's Radeon Cloud):

| Model (`vte pull` name) | Architecture | Parameters | Quantization |
|---|---|---|---|
| `qwen2.5:0.5b-q4_k_m-draft` | `qwen2` | 0.5B | Q4_K_M |
| `qwen2.5:1.5b-q4_k_m` (Aetheris fallback default) | `qwen2` | 1.5B | Q4_K_M |
| `qwen2.5:7b-q4_k_m` | `qwen2` | 7B | Q4_K_M |
| `qwen2.5:32b-q4_k_m` | `qwen2` | 32.7B | Q4_K_M |
| `qwen3.5:2b-q6_k` | `qwen35` | 2B | Q6_K |
| `granite-4.1:3b-q8_0` | `granite` | 3B | Q8_0 |
| `granite-4.1:30b-q8_0` | `granite` | 28.9B | Q8_0 |
| `llama3.1:8b-instruct-q4_k_m` (Aetheris default) | `llama` | 8B | Q4_K_M |

Adding a model is copying its `.gguf` into `VTE/Model/`, no code changes: VTE's per-architecture metadata reader pulls hidden size, layer count, head count and RoPE parameters straight from the GGUF at load time rather than hardcoding them per model, so a new size within an already-supported architecture (validated up to a 70B-parameter Llama 3.1 checkpoint, see the benchmark below) just works. Aetheris ships with Llama 3.1 8B Instruct as the default, chosen specifically for reliable tool-calling and correct language-matching under load, not the smallest or fastest option available (see [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#model-compatibility) for a documented case where a different candidate model failed that bar).

On the demo model, VTE isn't just "working," it's competitive with the reference engine on the same GGUF bytes:

| Model | Hardware | VTE | Reference (Ollama/llama.cpp) | Ratio |
|---|---|---|---|---|
| Qwen2.5 1.5B Q4_K_M | RX 7600 | **112.98 tok/s** | 110.76 tok/s | **102.0%** |
| Granite 4.1 3B Q8_0 | RX 7600 | **55.65 tok/s** | 50.84 tok/s | **109.5%** |
| Granite 4.1 30B Q8_0 | W7900 | 20.2 tok/s | 22.5 tok/s | 89.8% |
| Qwen2.5 32B Q4_K_M | W7900 | 22.7 tok/s | 28.56 tok/s | 79.5% |
| Llama 3.1 8B Q4_K_M | W7900 | 72.68 tok/s | 93.45 tok/s | 77.8% |
| Llama 3.1 70B Q4_K_M | W7900 | 10.50 tok/s | 14.21 tok/s | 73.9% |

Real GPU telemetry (`amd-smi`, sampled every ~0.5s) from the W7900 runs above, load through 3 back-to-back generations each, no thermal throttling on any of them, VRAM peaks matching the predicted weights+KV-cache+arena breakdown almost exactly:

| Model | VRAM peak | Hotspot temp peak | Power peak |
|---|---|---|---|
| Granite 4.1 30B Q8_0 | 30.3 GiB | 55°C | 243 W |
| Qwen2.5 32B Q4_K_M | 20.4 GiB | 60°C | 295 W |
| Llama 3.1 8B Q4_K_M | 5.7 GiB | 48°C | 292 W |
| Llama 3.1 70B Q4_K_M | ~42.5 GiB | not sampled | not sampled |

**Bonus criterion (quantization + Radeon Cloud), explicitly:** every model above runs quantized (Q4_K_M/Q6_K/Q8_0, never full-precision weights) as VTE's only supported inference format, not an optional flag, and every W7900 row was measured on an actual AMD Radeon Cloud instance, not simulated or estimated.

The 70B row is a stretch test past the eight curated models above (70.6B parameters, loaded via VTE's architecture-generic metadata path with zero model-specific code, only reachable at all after unifying a load-time VRAM cap with the runtime safety margin, see `VTE/docs/BENCHMARK_W7900.md`): real evidence the engine scales, not just runs, on hardware well beyond the 8 GB card it was designed against.

Getting there took a real optimization arc (naive per-thread GEMV at ~18.8 tok/s up to a HIP-Graph-captured decode loop at ~100+ tok/s, five real profiling-driven kernel changes in between) and a fair number of dead ends that got documented instead of hidden: a speculative-decoding attempt that turned out fundamentally incompatible with this GEMV design, an FFN kernel fusion that helps the small demo model but regresses larger ones for reasons that resisted two rounds of investigation, a RoPE fusion that was numerically correct but not worth its added complexity for a 0.6% gain. None of that is required reading to use Aetheris. If you're curious how the engine works, or want the full kernel-optimization history with the real numbers behind each decision (including the parts that didn't pan out): [`VTE/README.md`](VTE/README.md) and [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md).

VTE is also currently in review to become an official experimental backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server, wired into its real `WrappedServer` contract rather than just being "compatible" with it. Six rounds of maintainer review so far, each catching a real integration bug and getting it fixed in the open: a runtime-lifecycle race between VTE's own idle-unload and Lemonade owning model lifetime, a GPU-exclusivity policy redesigned around each backend's actual resolved device rather than a static descriptor default, a checksum-registry collision, mixed-GPU-generation device selection. [The PR](https://github.com/lemonade-sdk/lemonade/pull/2675), [the RFC discussion](https://github.com/lemonade-sdk/lemonade/issues/2679), details in `VTE/docs/LEMONADE.md`. One of those fixes (correct RX 7600 detection on Windows) already shipped and is credited by name in Lemonade's own [v11.5.0 release notes](https://github.com/lemonade-sdk/lemonade/issues/2776).

Three ROCm/RDNA3 platform gaps found and reported while building this, with exact repro steps: [`PLATFORM_ISSUES.md`](PLATFORM_ISSUES.md).

## 6. Judging-Criteria Mapping (Track 2, 120 points)

Mapped directly to the rubric, with a pointer to where each point was actually verified, not just described:

| Axis | Points | Where it's addressed | Verified how |
|---|---|---|---|
| Task positioning & application scenario | 20 | [Section 1](#1-application-scenario) | A real project folder, a real codebase read/summarized/edited on camera in the demo video |
| Core capabilities (planning, tools, RAG, memory) | 20 | [Section 3](#3-core-capabilities), 5 of 5 implemented (2 is the stated minimum) | Each demonstrated live, not just in a diagram: `write_plan` produces a real approval popup the user clicks, not prose; `manage_memory` recalled a fact in a brand-new chat session with no shared history; `manage_skill` search found a previously-saved skill from a different conversation; `write_file`/`edit_file` paused for a real click before touching disk; `navigate_browser`/`read_browser_page` correctly read a real inbox |
| Smooth multi-turn interaction | 20 | Round-based SSE streaming, tool calls shown as a status animation instead of raw fenced text | Cancel-mid-generation tested directly: confirmed it releases the server-side generation lock in seconds, not just hides the output client-side |
| Core inference on AMD Radeon GPU | 20 | [Section 5](#5-bonus-powered-by-vte) | No remote API anywhere in the core chat path; live GPU telemetry (`hipMemGetInfo`, not cached) confirmed on both a consumer card (RX 7600) and a workstation card (W7900) |
| Optimization for inference speed | 20 | [Section 5](#5-bonus-powered-by-vte) | Real profiling-driven optimization arc (~18.8 to 100+ tok/s), documented including the attempts that didn't pan out, not just the ones that did |
| Bonus: quantization + Radeon Cloud | 20 | [Section 5](#5-bonus-powered-by-vte) | Quantization (Q4_K_M/Q6_K/Q8_0) is VTE's only supported inference format, not an optional flag; every W7900 number above was measured on a real AMD Radeon Cloud instance |

The common failure mode this table is written to avoid, seen while reviewing other Track 2 submissions during development: claiming a capability by relabeling something adjacent to it (a job checkpoint as "multi-turn memory," a fixed pipeline as "multi-step planning"), or citing an optimization number without the core inference itself ever being confirmed running on the target hardware. Every row above points to something that was actually run and watched, not inferred from the architecture.
