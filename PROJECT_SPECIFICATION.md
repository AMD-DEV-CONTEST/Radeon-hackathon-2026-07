# Project Specification: Aetheris

**Track 2: Development & Local Deployment of Private AI Agents**

## Executive Summary

**Aetheris** is a local, private coding agent — reads, edits, and runs commands against a real codebase, plans multi-step work, remembers across sessions — running entirely on the user's own AMD Radeon GPU. Two things set it apart.

**VTE**, an inference engine built from scratch in raw HIP (no llama.cpp/vLLM/PyTorch anywhere in the path), decodes faster than llama.cpp on the identical GGUF file for two of the eight curated models (104.0% and 112.8%), validated on both a consumer card (RX 7600) and a 48 GB workstation card (W7900), scaling to a 70B-parameter stretch test. It's currently in review to become an official backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server — six rounds of real maintainer review, one fix already shipped and credited by name in Lemonade's own release notes — and surfaced five real ROCm/RDNA3 platform gaps along the way, each reported with repro steps ([`PLATFORM_ISSUES.md`](PLATFORM_ISSUES.md)).

**Blackbox**: every local agent claims your code never leaves the machine. Aetheris makes that claim checkable at runtime instead of asserted -- a hash-chained, independently re-verifiable log of every action, a live and auditable zero-egress indicator, one-click undo via git shadow-refs that never touch your real repo state. A real A/B test on the RX 7600 confirms this project's own documented "vague prompt" failure mode is now fixed by Cartographer's automatic codebase mapping, not just described as a known limitation.

That optimization work is no longer purely manual: `aetheris optimize` searches VTE's own kernel space using the methodology AMD open-sourced as [Hyperloom](https://github.com/AMD-AGI/Hyperloom) on 2026-07-22, validated against its actual source rather than its description, and hardened past it in two places ([Section 6.1](#61-self-optimizing-kernels-built-on-amds-own-methodology)). Its first honest verdict was that the hand-tuned kernel already beats every variant in its catalog, so it promoted nothing.

All 5 optional Track 2 capabilities are implemented (2 is the minimum), each demonstrated live, not diagrammed. 112 automated tests on the agent (plus 81 in VTE), including one that drives two real GPU-resident inference servers end to end, real hardware validation for every Blackbox component, and one real correctness bug caught by the test suite before it shipped.

The rest of this document is the detail behind that; the short version is a coding agent that proves what it does, running on an engine good enough to give back to the ecosystem it depends on.

---

**Aetheris** is a local, private coding agent: a desktop app that chats, edits and reads files, runs shell commands, inspects git state, searches a codebase, browses the web read-only, and plans multi-step work, all on the user's own AMD Radeon GPU, no cloud API or account required. The model weights never leave the machine, no request or file content is ever sent anywhere over the network, and the app functions fully offline once a model is pulled once. The tool dispatch, planning, memory, and skill-retrieval logic below are this project's own code, built because the project brief asked for a private agent.

It runs on **VTE**, an inference engine also built from scratch for this hardware rather than depending on an existing runtime (llama.cpp/vLLM/Transformers). VTE is a real, separate piece of engineering with its own optimization story, covered in [Section 6](#6-bonus-powered-by-vte); everything through Section 5 is about the agent.

## 1. Application Scenario

**A coding agent whose privacy is a property you can verify at runtime, not a claim you have to take on faith.** Every local agent *says* "your code never leaves your machine." Aetheris is built so that sentence is checkable, not just assertable: a hash-chained log of every action it takes, a live counter proving zero bytes left the machine during a session, and a one-click undo for anything it changes -- collectively the **Blackbox** (see [Section 5](#5-blackbox-verifiable-runtime-privacy)). That's the actual pitch, and it's why the personas below aren't generic "a developer" -- they're the specific people who need proof, not a promise.

- **A freelancer under NDA.** Client code, client credentials in `.env` files, a contract that says nothing about that code touches a third party. Aetheris gives them something to actually show the client afterward: an exportable session log a client can independently re-verify (`scripts/audit_verify.py`, zero dependencies, doesn't require Aetheris installed) -- not just "trust me."
- **A developer at a company with a zero-egress policy.** IT doesn't want to hear "the AI tool promises not to phone home" -- they want a number. The egress indicator in the header is that number, live, and it's itself part of the audited trail, not just a UI widget that could be lying.
- **A developer working entirely offline**, or one who just doesn't want a hobby project quietly training someone else's model. Same guarantee, no policy required to care about it.

A typical session looks like: *"what does this module do"* (reads and summarizes, no side effects) -> *"add input validation to the `parse` function"* (proposes an edit, pauses for a confirm click, and now leaves a snapshot behind it can undo) -> *"remember that this project validates at the boundary, not deep in business logic"* (written to durable memory, recalled automatically in later sessions without bloating the chat transcript). See the root [`README.md`](README.md#things-to-try) for more example prompts to run against a real project.

This scenario was chosen because it's the one the tool tree actually supports end-to-end (see [Core Capabilities](#3-core-capabilities)), not retrofitted onto it: bash execution, file read/write/edit, `git`, content search, and a todo/planning surface are exactly the primitives a local dev assistant needs, and nothing here assumes internet access at inference time.

The intended user is a developer who wants a coding assistant they can actually trust with a real project: nothing typed into the chat, nothing in the codebase it reads, and nothing it writes ever leaves the machine, because there's no server on the other end to send it to. The point of building this at all was to make "local" a real, load-bearing, *verifiable* property of the tool rather than a checkbox: the agent loop, the tool dispatch, the memory and skill systems, the Blackbox audit trail, and the inference engine underneath are all things this project controls end to end, so there's no closed-source dependency anywhere in the chain that could quietly start phoning home, and no part of the privacy claim that has to be taken on faith.

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

**Request flow.** The Flutter UI launches `app.py` on startup (`BackendLauncher.ensureRunning()`, polling `/` every 500 ms, 20 s budget) and shows a connecting state until it's up. `app.py` lazily (or eagerly, via `/api/vte/warmup`) spawns `vte-server` as a subprocess and polls its `/health` endpoint (90 s budget) before serving the first real request. A chat turn streams over SSE token-by-token as VTE decodes, not buffered per round: each generated token is forwarded to the client the moment it's produced (`yield _sse_delta(token)` per token in `agent.py`'s round loop), and the round boundary is only where the accumulated text gets scanned for a fenced tool-call block (` ```toolname\n...\n``` `). This fenced-code-block convention is the *only* tool-invocation mechanism, chosen because it works with any instruction-tuned GGUF model without a native function-calling API.

**Long-conversation handling.** History isn't sent to the model unbounded: `core/memory/context_compressor.py` checks the running token count before each turn, and once it crosses 850 (of a 1000-token history budget) it summarizes everything except the last 4 messages into a single `[RESUMO]` system message via one extra LLM call, preserving decisions, facts, and code references rather than truncating blindly. If that summarization call itself fails, it falls back to a hard trim by token budget rather than erroring out the turn.

**Tool dispatch is three-way**, not one flat list:
- **Server-executed** (`TOOL_REGISTRY`): `bash`, `read_file`, `write_file`, `edit_file`, `search_files`, `git`, `manage_memory`, which are run directly by the Python backend.
- **Client-executed** (`CLIENT_EXECUTED_TOOLS`): `navigate_browser`, `read_browser_page`. The backend can't drive a browser itself, so it emits a `browser_action` event and the Flutter process performs it, feeding the result back as a hidden continuation turn.
- **Confirmation-gated**: `write_file`/`edit_file` always, `bash` when the command matches a destructive pattern (`is_risky_bash_command`). The round pauses, the UI shows a diff/command preview, and only a real user click resumes execution. The terminal client (the `aetheris` CLI, see the root README) surfaces the same pause as a typed `y`/`N` prompt, same gate either way.

**Cross-platform.** The agent *backend* (`app.py`, pure Python/FastAPI, no Windows-specific code) was separately validated headless (no UI, direct HTTP calls against the real `stream_agent` loop) on an AMD Radeon Cloud W7900 Linux instance, the same one used for the inference-engine benchmarks in Section 6. Verified for real, not assumed: server-executed tool dispatch (`bash`, real subprocess execution with correct output), skill creation and retrieval (`manage_skill`, TF-IDF search returning the right skill with its full structured content), memory creation and retrieval (`manage_memory`, including one round that survived a model-generated typo in the tool tag thanks to the fence-tag tolerance fix), and the `write_file` confirmation gate end-to-end (the `confirm_tool` pause, `POST /api/tools/execute` performing the real write after simulated approval, and the file landing with the exact requested content). The root README's terminal quickstart runs this exact path, on Windows or Linux, with no Flutter UI involved at all.

The Flutter desktop UI itself now has a `linux/` platform target (`flutter create --platforms=linux`, GTK/CMake scaffold) alongside the existing Windows one, and the one Windows-specific dependency (`webview_windows`, the embedded browser) is platform-guarded: it declares no Linux plugin implementation, so the app degrades to a clearly labeled "Windows-only" state for `navigate_browser`/`read_browser_page` instead of a raw platform-channel crash, everything else in the UI unaffected. Stated plainly: the scaffold and the guard are in place and pass static analysis, but an actual `flutter build linux` has not been run and verified end-to-end -- Flutter's Linux desktop target requires compiling on a real Linux host (no cross-compilation from Windows), which is a real next step, not a claim made here.

## 3. Core Capabilities

Implements **all 5** optional capabilities listed in the task brief (2 are the stated minimum):

| Capability | Implementation | Try it |
|---|---|---|
| Tool invocation | Fenced-code-block calls dispatched to bash, file r/w/edit, `git` (status/diff/log/show/branch), content search, memory, skills, browser navigation (see [Architecture](#2-agent-architecture)) | *"what changed in the last 5 commits?"* |
| Multi-step task planning | **Builder/Planner mode toggle.** In Planner mode the agent is restricted to read-only tools plus `write_plan`, which streams a Markdown plan to a floating review panel instead of acting; the user approves (-> Builder mode, agent executes) or sends revision feedback (plan gets rewritten, still Planner). Mode is enforced server-side (`BUILDER_ONLY_TOOLS`/`PLANNER_ONLY_TOOLS`), not just prompted | *"plan how you'd add rate limiting here, don't touch anything yet"* |
| Local multi-turn memory | Full conversation history persisted per session; a separate `manage_memory` tool (add/search/forget) gives the agent durable memory across sessions, independent of the chat transcript | *"remember that this project uses tabs, not spaces"* |
| Local knowledge retrieval (RAG) | Two corpora now, not one. **Skill library**: reusable named procedures (`SKILL.md` files, YAML frontmatter + structured body) the agent writes for itself via `manage_skill` (add/search/forget) after solving something non-trivial, retrieved via TF-IDF cosine similarity over the current library, recomputed per query. **Codebase map** (Cartographer, [Section 5](#5-blackbox-verifiable-runtime-privacy)): a background pass summarizes the project file-by-file, indexed with BM25 (`rank_bm25`) and retrievable via the `search_map` tool or injected automatically before a turn. Both are deliberately not neural embeddings (no ONNX/sentence-transformers/extra model process): on the same RX 7600 that's already fully committed to the loaded chat model, a second model competing for the remaining ~4-6 GB of VRAM (or CPU cycles, for a "local" embedding server) isn't free the way it would be on a discrete deployment | agent writes a skill on its own after a multi-step fix; ask *"what does this codebase do"* on first opening an unfamiliar project |
| Permission control & privacy | Local username/password gate in front of the whole app, generated automatically (random credentials) on first run rather than requiring manual setup; every internal API call requires a machine-local shared-secret header; destructive file writes and risky shell commands require an explicit human click (or terminal `y`) before executing; `navigate_browser`/`read_browser_page` are read-only by construction, the agent cannot submit forms, enter credentials, or take side-effecting actions on the web. Extended by the **Blackbox** ([Section 5](#5-blackbox-verifiable-runtime-privacy)): every one of those gated actions is now also logged to a tamper-evident hash chain, the "nothing leaves the machine" claim has a live, auditable counter instead of just a promise, and any approved write can be undone with one click | *"look up the current stable version of \<library> online"*, or open the Blackbox panel after a session and click Verify integrity |

## 4. Running It

Full setup, on both Windows and Linux, both as the desktop app and from a terminal: root [`README.md`](README.md#quickstart). Short version: `pip install -e` VTE into Aetheris's virtual environment, pull a GGUF model, then either launch the Flutter UI (Windows) or `cd` into the project you want to work on and run `aetheris chat` (Windows or Linux), which starts the backend itself. No manual GPU configuration; VTE reads the real architecture and compute-unit count off the device at startup.

GGUF integrity is checked against a known-good SHA-256 and a per-architecture metadata whitelist (layer count, tensor shapes) before any weight is loaded, so a corrupted or mismatched download fails loudly at load time rather than producing silently wrong output.

## 5. Blackbox: Verifiable Runtime Privacy

Four components, all opt-out (`AETHERIS_AUDIT_ENABLED`/`AETHERIS_EGRESS_ENABLED`/`AETHERIS_TIMETRAVEL_ENABLED`/`AETHERIS_CARTOGRAPHER_ENABLED`, each default-on) and each independently disable-able back to the exact pre-Blackbox agent loop -- none of this is load-bearing for the core chat path, all of it is additive around it. Zero extra VRAM (nothing here loads a model; Cartographer's summarization reuses the already-resident chat model on its own idle cycles) and zero new egress (the Model API judge script, if used, lives outside the product, in `scripts/`, never in the inference path).

**Flight Recorder** (`core/audit/flight_recorder.py`): every tool call, confirm-gate decision, and turn boundary is appended to a per-session, hash-chained JSONL log (`entry_hash = sha256(canonical_json(entry) )`, each entry pointing to the previous entry's hash). Entries never contain raw file/command content, only digests and lengths -- the log itself can't leak what the agent read or wrote, which matters because the whole point is a client can hand this file to someone else. `scripts/audit_verify.py` re-walks the chain with zero dependencies beyond the Python standard library and no Aetheris install required, so a third party can verify a session without trusting the app that produced it. **What the chain does and doesn't prove, stated plainly**: it proves internal consistency -- any retroactive edit, deletion, or reordering of an entry is detectable in O(n), because it breaks the hash link to everything after it. It does **not** prove authenticity against an attacker with root access to the machine that produced the log, who could rewrite the whole file and recompute every hash consistently; that's a different, harder problem (a v2 mitigation -- periodically anchoring the head hash into a signed git commit, or printing it for the user to note externally -- is documented as future work, not built).

**Egress Monitor** (`core/audit/egress_monitor.py`): samples the process's own network connections roughly every second (`psutil.net_connections()`, scoped to this process and the `vte-server` subprocess by PID) and classifies each as loopback or external. The "0 B external" indicator in the status footer is fed by this, and state changes are themselves logged to the Flight Recorder -- the claim is auditable after the fact, not just a number on screen during the session. Honest about its own limits: connection *enumeration* is reliable cross-platform; per-connection *byte counts* are best-effort and, when unavailable, the indicator reports a connection count rather than inventing precision it doesn't have.

**Time-Travel** (`core/audit/timetravel.py`): every approved `write_file`/`write_files`/`edit_file` call snapshots the touched files before and after, onto a git ref namespaced outside `refs/heads/*` (`refs/aetheris/session-<id>`) via an isolated `GIT_INDEX_FILE` that never touches the user's real index. Undo restores content directly (`git cat-file -p` -> a plain file write) -- never `git checkout`, which would move the user's actual HEAD/branch. v1 scope, stated plainly: git repositories only (no filesystem-snapshot fallback for non-git projects yet), and undo restores content, it doesn't reconstruct file deletion for a file that didn't exist in the target snapshot. Validated with an automated test against a disposable repo fixture (never a real project) proving the user's real `git status`/`branch`/`stash list`/tracked-blob state stays byte-identical across a simulated session of multiple snapshots and rollbacks, *and* against a real session on the RX 7600 (a live model-issued write, a real confirm-gate approval, real shadow-ref commits, confirmed invisible to `git branch`).

A real correctness bug was caught by that same test, not hypothesized: the first version of the git-plumbing wrapper stripped whitespace from every git subprocess's output uniformly, which is correct for a commit hash but silently ate the trailing newline of *restored file content* read back via `git cat-file -p` -- every rollback round-trip test failed by exactly one missing newline until it was found and fixed with a dedicated `strip=False` path for blob content specifically. The same class of bug this project has hit before (a rendered prompt's trailing whitespace being structurally meaningful, documented elsewhere) -- caught here by writing the invariant test *before* trusting the mechanism, not after.

**Cartographer** (`core/rag/cartographer.py`): a background pass maps the active project file-by-file into short markdown summaries (cheap regex-based structural extraction always runs; an LLM-generated 2-sentence responsibility summary runs on the already-loaded chat model, only while the chat itself is idle -- watches the same `EventBus` `chat_turn_start`/`chat_turn_end` signals the rest of the backend already has, since no generation lock exists in this codebase to contend on instead). Indexed with BM25 (`rank_bm25`, additive -- doesn't touch or replace the skill library's own TF-IDF search) and reachable two ways: the `search_map` tool (on-demand, the model decides when to reach for it, zero new architecture) and automatic pre-turn injection (`AETHERIS_CARTOGRAPHER_AUTO_INJECT`, its own sub-flag, genuinely new context-assembly plumbing with no precedent elsewhere in this codebase -- built anyway, deliberately, because the on-demand tool alone likely can't fix the exact vague-prompt failure this project's own README already documents: a model asked *"what does this codebase do"* with no tool named for it has historically made zero tool calls at all).

**Proven, not just argued**: the exact vague prompt from the README (*"what does this codebase do"*, no tool named), run twice on the RX 7600 against a real, freshly-mapped subset of this project, same model, same prompt, only the flag changed. With only the on-demand tool available, the model reached for `manage_memory` instead -- the wrong tool -- then produced a malformed `write_plan` block; **zero real tool calls actually dispatched**, reproducing the documented failure exactly. With automatic injection also on, the same prompt got a direct, correct answer with **zero tool calls needed**, correctly naming the Flight Recorder, Egress Monitor, and Time-Travel components and citing real function names (`timetravel_enabled`, `_ref_name`, `_temp_index_path`) pulled straight from the mapped source files. Full transcript: [`Aetheris Studio/docs/UX_METRICS.md`](Aetheris%20Studio/docs/UX_METRICS.md#done-the-vague-prompt-ab-cartographer-uc-04-real-result-on-the-rx-7600).

## 6. Bonus: Powered by VTE

Aetheris needed an inference engine that runs entirely on an AMD Radeon GPU with nothing else installed, no PyTorch, no ONNX Runtime, no dependency on llama.cpp/vLLM in the core path, so this project built one: **VTE**, hand-written HIP kernels that parse GGUF directly and generate/compile their own kernel code for the detected architecture. Every layer between the GGUF file and the GPU -- parsing, memory planning, kernel codegen, the decode loop itself -- is this project's own code.

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

On the demo model, VTE is competitive with the reference engine on the same GGUF bytes -- and on two of the eight, it's faster:

| Model | Hardware | VTE decode | Reference decode | Ratio | VTE TTFT (s) | Reference TTFT (s) |
|---|---|---|---|---|---|---|
| Qwen2.5 1.5B Q4_K_M | RX 7600 | **115.14 tok/s** | 110.76 tok/s | **104.0%** | not separately measured | not separately measured |
| Granite 4.1 3B Q8_0 | RX 7600 | **57.34 tok/s** | 50.84 tok/s | **112.8%** | not separately measured | not separately measured |
| Granite 4.1 30B Q8_0 | W7900 | 20.2 tok/s | 22.5 tok/s | 89.8% | 0.63 - 2.28 | 0.13 - 0.33 |
| Llama 3.1 8B Q4_K_M | W7900 | **79.54 tok/s** | 93.45 tok/s | 85.1% | 0.17 - 0.55 | 0.03 - 0.24 |
| Qwen2.5 32B Q4_K_M | W7900 | 22.7 tok/s | 28.56 tok/s | 79.5% | 0.57 - 2.11 | 0.11 - 0.31 |
| Llama 3.1 70B Q4_K_M | W7900 | 10.50 tok/s | 14.21 tok/s | 73.9% | 7.62 | 0.22 - 0.41 |

VTE's decode numbers above are the current build (2026-07 batched-prefill/stochastic-sampling pass); the reference engine's numbers are unchanged, since llama.cpp itself didn't move. Granite 30B, Qwen 32B, and Llama 70B weren't re-measured under the new defaults yet, so those three rows still reflect the earlier pass.

Getting to these numbers took a real optimization arc: naive per-thread GEMV at ~18.8 tok/s up to a HIP-Graph-captured decode loop at 100+ tok/s, five real profiling-driven kernel changes in between. The two beaten-reference rows and the 8B/30B rows sitting at 85-90% are the direct result of that arc; the 32B/70B rows are the part of the curve the arc hasn't reached yet, not a different codebase. A fair number of dead ends got documented instead of hidden along the way: a speculative-decoding attempt fundamentally incompatible with this GEMV design, an FFN kernel fusion that helps the small demo model but regresses larger ones for reasons that resisted two rounds of investigation, a RoPE fusion that was numerically correct but not worth its added complexity for a 0.6% gain. Full kernel-optimization history with the real numbers behind each decision, including the parts that didn't pan out: [`VTE/README.md`](VTE/README.md) and [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md).

**That optimization work is already being reviewed by AMD itself.** VTE is currently in review to become an official experimental backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server, wired into its real `WrappedServer` contract. Six rounds of maintainer review so far, each catching a real integration bug and getting it fixed in the open: a runtime-lifecycle race between VTE's own idle-unload and Lemonade owning model lifetime, a GPU-exclusivity policy redesigned around each backend's actual resolved device, a checksum-registry collision, mixed-GPU-generation device selection. [The PR](https://github.com/lemonade-sdk/lemonade/pull/2675), [the RFC discussion](https://github.com/lemonade-sdk/lemonade/issues/2679), details in `VTE/docs/LEMONADE.md`. One of those fixes (correct RX 7600 detection on Windows) already shipped and is credited by name in Lemonade's own [v11.5.0 release notes](https://github.com/lemonade-sdk/lemonade/issues/2776). Alongside that: **five ROCm/RDNA3 platform gaps found and reported while building this** (three on Linux/W7900, two more on Windows/RX 7600), each with exact repro steps: [`PLATFORM_ISSUES.md`](PLATFORM_ISSUES.md). This project doesn't just run on AMD's stack -- it's found and reported real gaps in it, and one of its own fixes has already shipped upstream.

TTFT above is for a short, tool-free prompt (the same 3-prompt methodology behind every row, see `VTE/docs/BENCHMARK_W7900.md`), predating a 2026-07 change and not yet re-measured under it: these prompts are shorter than the batched-prefill chunk size (64 tokens, below), so they wouldn't exercise that path anyway and the numbers above still reflect the single-token-at-a-time prefill loop. It got much worse with Aetheris's actual ~1361-token tool-documentation system prompt in context (measured ~125s TTFT on the 70B checkpoint) -- exactly the scenario batched prefill now targets.

**Batched prefill is implemented and on by default** (`VTE_BATCHED_PREFILL`, opt out via `=0`): the prompt is processed in fixed-size chunks (default 64 tokens) through a dedicated HIP Graph instead of one seq_len=1 graph replay per token. Two custom kernels do the work -- a Q4_K WMMA GEMM (`gemm_q4k_wmma.hip.template`, weight tiles reused in LDS across a chunk's rows) and a tree-reduction causal-attention kernel (`flash_attention_prefill.hip.template`). Measured on Llama 3.1 8B Q4_K_M / W7900, warmup-separated median of 3 runs at two different prompt lengths: **prefill TTFT drops from 6.51s to 3.33s at 517 tokens (1.96x)** and from 13.45s to 7.14s at ~1033 tokens (1.88x), generated output verified byte-identical to the sequential path token-for-token at both sizes, with no decode-throughput regression.

Re-validated on the RX 7600 (8GB): decode throughput on all five currently loadable models matches this project's historical RX 7600 numbers, confirming no regression. A real VRAM gap was found (the chunk buffer's size was only ever checked against the W7900's 48GB, past what's free on the RX 7600 for the two largest models) and fixed with a real-VRAM check before committing the reservation. A missing Windows header meant the WMMA kernel had never actually run on this card before this pass; once vendoring the header let it genuinely execute for the first time on a model other than Llama 3.1 8B, Qwen2.5 1.5B's generated text diverged from the sequential path starting at the first token. Root cause, found the same day: Qwen2.5 uses `attention_bias=True` (real `blk.N.attn_{q,k,v}.bias` tensors), unlike Llama 3.1 8B, the only model this kernel had ever been validated against -- its signature simply had no bias parameter. Confirmed by direct arithmetic (isolated kernel output plus the real bias, summed in NumPy, matched the sequential path's real output element-for-element) and fixed by adding the missing epilogue term. Re-verified byte-identical to sequential across 60 generated tokens on Qwen2.5 1.5B/RX 7600. Full investigation trail: [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#batching-and-prefill).

**Stochastic decode sampling (temperature>0, the project's actual default) is also GPU-accelerated now**, separately from the prefill work above (`VTE_STOCHASTIC_TOPK_READBACK`, opt out via `=0`). Profiling the sampler before writing any kernel found that 92.6% of `Sampler.sample()`'s own cost was a single `np.argpartition` scan over the full 128K-token vocabulary on every generated token; the existing greedy-decode top-k reduction kernel was generalized to return a handful of candidates per thread instead of one, moving just that scan to the GPU. Measured on Llama 3.1 8B Q4_K_M / W7900 at the project's real default sampling settings (temperature=0.7, top_p=0.9, top_k=50), warmup-separated median of 3 runs: **decode throughput rises from 74.36 to 79.54 tok/s, a 6.96% gain**, sampled token distribution verified statistically identical to the original path (KL-divergence 0.0001), greedy decoding confirmed byte-identical whether the flag is on or off. A real correctness edge case was found and fixed before this shipped: an early, more VGPR-conservative kernel version could drop true candidates under an adversarially clustered input (never observed on real model logits, demonstrated on a synthetic worst case) -- widened before enabling by default. Full writeup, including the rejected larger-scope design: [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#kernel-efficiency-and-rejected-optimizations).

Real GPU telemetry (`amd-smi`, sampled every ~0.5s) from the W7900 runs above, load through 3 back-to-back generations each, no thermal throttling, VRAM peaks matching the predicted weights+KV-cache+arena breakdown:

| Model | VRAM peak | Hotspot temp peak | Power peak |
|---|---|---|---|
| Granite 4.1 30B Q8_0 | 30.3 GiB | 55°C | 243 W |
| Qwen2.5 32B Q4_K_M | 20.4 GiB | 60°C | 295 W |
| Llama 3.1 8B Q4_K_M | 5.7 GiB | 48°C | 292 W |
| Llama 3.1 70B Q4_K_M | ~42.5 GiB | not sampled | not sampled |

**Bonus criterion (quantization + Radeon Cloud):** every model above runs quantized (Q4_K_M/Q6_K/Q8_0) as VTE's only supported inference format, and every W7900 row was measured on an actual AMD Radeon Cloud instance running VTE directly on the hardware, not the pre-hosted API. Radeon Cloud's pre-hosted Dedicated Model API (vLLM-backed) was also exercised directly, separately from VTE: Aetheris's external-provider bridge was pointed at it running Qwen3.6-35B-A3B, a model far larger than anything VTE serves locally, specifically to stress-test the agent loop against a model VTE can't run itself. That testing caught two real bugs, both since fixed: a reasoning-heavy response silently burning its entire token budget on `delta.reasoning` with zero visible output for up to 122s, indistinguishable from a hang until the reasoning/content stream was split (`core/utils/vte_bridge.py`); and a tool-name hallucination pattern (a plausible but unregistered `read_files` call, confused with the real `write_files`) that VTE-served local models never triggered, now caught by `find_unmatched_tool_attempt` (`core/utils/tools.py`).

The 70B row is a stretch test past the eight curated models above (70.6B parameters, loaded via VTE's architecture-generic metadata path with zero model-specific code): the engine scales, not just runs, on hardware well beyond the 8 GB card it was designed against.

### 6.1 Self-optimizing kernels, built on AMD's own methodology

Every kernel improvement above was found by hand. The natural next step is letting the agent run that search itself, which is exactly the problem AMD open-sourced [**Hyperloom**](https://github.com/AMD-AGI/Hyperloom) to solve (`v1.0.0a1`, tagged 2026-07-22, days before this submission). Aetheris ships `aetheris optimize`, a kernel optimizer for VTE built on Hyperloom's core idea and then validated mechanism by mechanism against Hyperloom's actual source rather than against its description.

**Hyperloom targets datacenter CDNA; this runs the same methodology on RDNA3.** Hyperloom's supported GPU set is `{mi300x, mi308x, mi325x, mi355x}` (`inference_optimizer/gpu_types.py`) and its `_GFX_TO_RUNNER` map covers exactly two architectures, `gfx942` (CDNA3) and `gfx950` (CDNA4). RDNA is not simply unlisted, its absence is codified: Hyperloom's own test suite asserts `_GFX_TO_RUNNER.get("gfx1100") is None`. Hyperloom also optimizes established serving stacks (SGLang, vLLM, AITER), whereas the target here is an inference engine with none of those in its path. Aetheris runs the methodology on a consumer `gfx1102` (RX 7600, 8 GB) and a workstation `gfx1100` (W7900, 48 GB), against hand-written HIP kernels, which is a hardware and software combination the reference implementation explicitly does not cover.

The safety invariants it adopts, each traced to the real implementation:

| Invariant | Hyperloom | Aetheris |
|---|---|---|
| Bounded discrete catalog, no LLM authoring C++ | rung ladder | `catalog.py`, deterministic parameters only |
| Correctness gate runs **before** any benchmark is trusted | `make_proposal` checks `correctness_passed` first | `validate_pair` precedes the benchmark call |
| Interleaved A/B, warmup discarded | `reps`, `warmup_discarded` | alternating order, 2 warmups dropped |
| Significance by non-overlapping interquartile ranges | `apply_and_bench` | `_is_significant` |
| Graded verdict instead of a boolean | `KEEP` / `PARTIAL` / `NEEDS_REVIEW` / `REVERT` | `KEEP` / `NEEDS_REVIEW` / `REVERT` with reasons |
| Engagement proof: did the patch actually run? | greps the server log for rebuild markers | compares the rendered C++ each instance really compiled |
| Rollback path revalidated against its expected root | `_safe_rel` rejects traversal | `_require_contained` |

Two places go further than the reference. Hyperloom patches the live tree and undoes it in a `finally: _revert_all()`, which leaves a window where a concurrent request could be served an unvalidated kernel; Aetheris never mutates production during a test at all, spinning up two throwaway `vte-server` subprocesses on separate ports and separate working directories, one per template variant. And where Hyperloom infers engagement from log markers, Aetheris compares the actual rendered C++ each instance compiled, since VTE writes every source it hands to `hipcc`.

That engagement check earned its place immediately. The first version of this catalog exposed a `BLOCK_SIZE` knob documented as *"doubled block size for higher CU occupancy"*. It did nothing: `gemv_q4k`'s launch geometry is fixed at 64 threads by `GEMV_COALESCED_BLOCK` in `VTE/vte/core/fallback_executor.py`, and the template only ever reads `blockDim.x`. Rewriting the template's shared-memory array changed no thread count whatsoever, so every "block size" measurement was really measuring the unroll change sitting next to it. It was also latently unsafe: the validator accepted `BLOCK_SIZE=32`, which renders `warp_sums[1]` while 64 real threads still write `warp_sums[warp]`, an out-of-bounds shared-memory write. The knob was removed rather than papered over, and the validator now rejects unknown parameters instead of ignoring them, which is how it went unnoticed in the first place.

**The first honest run reports that nothing should change.** On the RX 7600 (`gfx1102`), 3 interleaved trials per variant against `qwen2.5:1.5b-q4_k_m`:

| Variant | Reference | Candidate | Delta | Engaged | Significant | Decision |
|---|---|---|---|---|---|---|
| `unroll_2` | 109.8 tok/s | 64.5 tok/s | -41.3% | yes | yes | REVERT |
| `unroll_4` | 110.7 tok/s | 69.1 tok/s | -37.6% | yes | yes | REVERT |
| `unroll_8` | 109.5 tok/s | 71.9 tok/s | -34.4% | yes | yes | REVERT |

Nothing was promoted. Forcing any fixed `#pragma unroll N` on `gemv_q4k` is consistently worse than leaving the bare pragma for the compiler to schedule, and the penalty shrinks monotonically as the factor grows, consistent with a register-pressure and occupancy tradeoff. The hand-optimized production kernel is already the best configuration in the catalog. A measurement harness was validated against its own null hypothesis before any of this was believed: two byte-identical instances measured 0.37% apart, establishing the noise floor that the significance test now enforces against.

An optimizer whose first published verdict is "change nothing here" is the one worth trusting when it does report a win.

## 7. Judging-Criteria Mapping (Track 2, 120 points)

Mapped directly to the rubric, with a pointer to where each point was actually verified, not just described:

| Axis | Points | Where it's addressed | Verified how |
|---|---|---|---|
| Task positioning & application scenario | 20 | [Section 1](#1-application-scenario), [Section 5](#5-blackbox-verifiable-runtime-privacy) | A real project folder, a real codebase read/summarized/edited on camera in the [demo video](https://drive.google.com/drive/folders/1a6CQkLn0nwz_gbBwckKcNBmiN-YMQpfD?usp=sharing); the "privacy verifiable at runtime" positioning has real evidence to point at, not just a claim -- a real hash-chained session log independently re-verified via `scripts/audit_verify.py`, a live 0-external-connections indicator confirmed against the real process tree, a real git shadow-ref undo validated both against a disposable-repo test fixture and a real session on the RX 7600 |
| Core capabilities (planning, tools, RAG, memory) | 20 | [Section 3](#3-core-capabilities), 5 of 5 implemented (2 is the stated minimum) | Each demonstrated live, not just in a diagram: `write_plan` produces a real approval popup the user clicks, not prose; `manage_memory` recalled a fact in a brand-new chat session with no shared history; `manage_skill` search found a previously-saved skill from a different conversation; Cartographer's `search_map` returned a real, BM25-ranked, LLM-summarized answer about a real project on the RX 7600, and a real A/B on the exact vague prompt this project's own README documents as a failure case (*"what does this codebase do"*) confirmed the on-demand tool alone reproduces that failure (zero real tool calls, wrong tool attempted) while automatic injection answers it correctly with zero tool calls needed; `write_file`/`edit_file` paused for a real click before touching disk; `navigate_browser`/`read_browser_page` correctly read a real inbox |
| Smooth multi-turn interaction | 20 | Round-based SSE streaming, tool calls shown as a status animation instead of raw fenced text; [Section 5](#5-blackbox-verifiable-runtime-privacy)'s Time-Travel | Cancel-mid-generation tested directly: confirmed it releases the server-side generation lock in seconds, not just hides the output client-side. Time-Travel adds a second, novel interaction: a real model-issued edit, approved through the gate, undone with one click on a real repo, verified the user's actual git state (`status`/`branch`/`stash`/tracked blobs) came back byte-identical. UX metrics ([`Aetheris Studio/docs/UX_METRICS.md`](Aetheris%20Studio/docs/UX_METRICS.md), `Aetheris Studio/scripts/metrics_report.py`) are now a direct byproduct of the audit trail: TTFT, turn duration, confirm-gate approval rate and decision latency, rollback rate, all measured, not estimated, from real session logs |
| Core inference on AMD Radeon GPU | 20 | [Section 6](#6-bonus-powered-by-vte) | No remote API anywhere in the core chat path; live GPU telemetry (`hipMemGetInfo`, not cached) confirmed on both a consumer card (RX 7600) and a workstation card (W7900) |
| Optimization for inference speed | 20 | [Section 6](#6-bonus-powered-by-vte), [Section 6.1](#61-self-optimizing-kernels-built-on-amds-own-methodology) | Real profiling-driven optimization arc (~18.8 to 100+ tok/s), documented including the attempts that didn't pan out, not just the ones that did. That search is now automated in `aetheris optimize`, built on the core idea of AMD's own [Hyperloom](https://github.com/AMD-AGI/Hyperloom) (open-sourced 2026-07-22) and validated mechanism by mechanism against its actual source: correctness gated before any benchmark is trusted, interleaved A/B with interquartile-range significance, graded KEEP/NEEDS_REVIEW/REVERT, and two isolated `vte-server` instances so production is never mutated mid-test. Its engagement proof immediately caught a knob in this project's own catalog that was measurably doing nothing, and its first honest verdict was that the hand-tuned kernel already beats every catalog variant, so nothing was promoted |
| Bonus: quantization + Radeon Cloud | 20 | [Section 6](#6-bonus-powered-by-vte) | Quantization (Q4_K_M/Q6_K/Q8_0) is VTE's only supported inference format, not an optional flag; every W7900 number above was measured on a real AMD Radeon Cloud instance running VTE directly; the Radeon Cloud Dedicated Model API (vLLM) was separately exercised via Aetheris's external-provider bridge, catching two real bugs (a silent reasoning-token hang, a tool-name hallucination pattern) |
