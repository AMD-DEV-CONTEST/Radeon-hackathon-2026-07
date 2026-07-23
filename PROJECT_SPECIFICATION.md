# Project Specification: Aetheris

**Track 2: Development & Local Deployment of Private AI Agents**

**Aetheris** is a local, private coding agent: a desktop app that chats, edits and reads files, runs shell commands, inspects git state, searches a codebase, browses the web read-only, and plans multi-step work, all on the user's own AMD Radeon GPU, no cloud API or account required. "Local" is meant literally, not as a marketing gloss on a thin wrapper around a hosted API: the model weights never leave the machine, no request or file content is ever sent anywhere over the network, and the app functions fully offline once a model is pulled once. It doesn't call out to an existing closed-source agent platform for its core loop; the tool dispatch, planning, memory, and skill-retrieval logic below are this project's own, built specifically because the project brief asked for a private agent, not because an existing framework didn't fit.

It runs on **VTE**, an inference engine we also built from scratch for this hardware rather than depending on an existing runtime (llama.cpp/vLLM/Transformers). VTE is a real, separate piece of engineering with its own optimization story, covered briefly in [Section 6](#6-bonus-powered-by-vte), but it exists to serve Aetheris, not the other way around; everything through Section 5 is about the agent.

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
- **Confirmation-gated**: `write_file`/`edit_file` always, `bash` when the command matches a destructive pattern (`is_risky_bash_command`). The round pauses, the UI shows a diff/command preview, and only a real user click resumes execution. The terminal client (`Aetheris Studio/scripts/chat.py`, see the root README) surfaces the same pause as a typed `y`/`N` prompt, same gate either way.

**Cross-platform.** The Flutter UI itself is Windows-only today (no `linux/` platform target configured yet), but the agent *backend* (`app.py`, pure Python/FastAPI, no Windows-specific code) is not: it was separately validated headless (no UI, direct HTTP calls against the real `stream_agent` loop) on an AMD Radeon Cloud W7900 Linux instance, the same one used for the inference-engine benchmarks in Section 5. Verified for real, not assumed: server-executed tool dispatch (`bash`, real subprocess execution with correct output), skill creation and retrieval (`manage_skill`, TF-IDF search returning the right skill with its full structured content), memory creation and retrieval (`manage_memory`, including one round that survived a model-generated typo in the tool tag thanks to the fence-tag tolerance fix), and the `write_file` confirmation gate end-to-end (the `confirm_tool` pause, `POST /api/tools/execute` performing the real write after simulated approval, and the file landing with the exact requested content). The root README's terminal quickstart runs this exact path.

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

Full setup, on both Windows and Linux, both as the desktop app and from a terminal: root [`README.md`](README.md#quickstart). Short version: `pip install -e` VTE into Aetheris's virtual environment, pull a GGUF model, either launch the Flutter UI (Windows) or run `app.py` plus `scripts/chat.py` (Windows or Linux). No manual GPU configuration; VTE reads the real architecture and compute-unit count off the device at startup.

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

| Model | Hardware | VTE decode | Reference decode | Ratio | VTE TTFT (s) | Reference TTFT (s) |
|---|---|---|---|---|---|---|
| Qwen2.5 1.5B Q4_K_M | RX 7600 | **115.14 tok/s** | 110.76 tok/s | **104.0%** | not separately measured | not separately measured |
| Granite 4.1 3B Q8_0 | RX 7600 | **57.34 tok/s** | 50.84 tok/s | **112.8%** | not separately measured | not separately measured |
| Granite 4.1 30B Q8_0 | W7900 | 20.2 tok/s | 22.5 tok/s | 89.8% | 0.63 - 2.28 | 0.13 - 0.33 |
| Qwen2.5 32B Q4_K_M | W7900 | 22.7 tok/s | 28.56 tok/s | 79.5% | 0.57 - 2.11 | 0.11 - 0.31 |
| Llama 3.1 8B Q4_K_M | W7900 | **79.54 tok/s** | 93.45 tok/s | 85.1% | 0.17 - 0.55 | 0.03 - 0.24 |
| Llama 3.1 70B Q4_K_M | W7900 | 10.50 tok/s | 14.21 tok/s | 73.9% | 7.62 | 0.22 - 0.41 |

VTE's decode numbers above are the current build (2026-07 batched-prefill/stochastic-sampling pass); the reference engine's numbers are unchanged, since llama.cpp itself didn't move. Granite 30B, Qwen 32B, and Llama 70B weren't re-measured under the new defaults yet, so those three rows still reflect the earlier pass.

TTFT above is for a short, tool-free prompt (the same 3-prompt methodology behind every row, see `VTE/docs/BENCHMARK_W7900.md`), predating a 2026-07 change and not yet re-measured under it: these prompts are shorter than the batched-prefill chunk size (64 tokens, see below), so they wouldn't exercise that path anyway and the numbers above still reflect the single-token-at-a-time prefill loop. It got much worse with Aetheris's actual ~1361-token tool-documentation system prompt in context (measured ~125s TTFT on the 70B checkpoint) -- exactly the scenario batched prefill now targets.

**Batched prefill is implemented and on by default** (`VTE_BATCHED_PREFILL`, opt out via `=0`): the prompt is processed in fixed-size chunks (default 64 tokens) through a dedicated HIP Graph instead of one seq_len=1 graph replay per token. Two custom kernels do the work -- a Q4_K WMMA GEMM (`gemm_q4k_wmma.hip.template`, weight tiles reused in LDS across a chunk's rows instead of every row re-reading VRAM independently) and a tree-reduction causal-attention kernel (`flash_attention_prefill.hip.template`). Measured on Llama 3.1 8B Q4_K_M / W7900, warmup-separated median of 3 runs at two different prompt lengths: **prefill TTFT drops from 6.51s to 3.33s at 517 tokens (1.96x)** and from 13.45s to 7.14s at ~1033 tokens (1.88x), generated output verified byte-identical to the sequential path token-for-token at both sizes, with no decode-throughput regression.

Re-validated on the RX 7600 (8GB): decode throughput on all five currently loadable models matches this project's historical RX 7600 numbers, confirming no regression. A real VRAM gap was found (the chunk buffer's size was only ever checked against the W7900's 48GB, and pushed past what's free on the RX 7600 for the two largest models) and fixed with a real-VRAM check before committing the reservation. A missing Windows header meant the WMMA kernel had never actually run on this card at all before this pass (see below); once vendoring the header let it genuinely execute for the first time on a model other than Llama 3.1 8B, Qwen2.5 1.5B's generated text diverged from the sequential path starting at the first token. Root cause, found the same day: Qwen2.5 uses `attention_bias=True` (real `blk.N.attn_{q,k,v}.bias` tensors), unlike Llama 3.1 8B, the only model this kernel had ever been validated against -- its signature simply had no bias parameter. Confirmed by direct arithmetic (isolated kernel output plus the real bias, summed in NumPy, matched the sequential path's real output element-for-element) and fixed by adding the missing epilogue term, mirroring how the sequential path's own kernel already handled it. Re-verified byte-identical to sequential across 60 generated tokens on Qwen2.5 1.5B/RX 7600. Full investigation trail: [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#batching-and-prefill).

**Stochastic decode sampling (temperature>0, the project's actual default) is also GPU-accelerated now, separately from the prefill work above** (`VTE_STOCHASTIC_TOPK_READBACK`, opt out via `=0`). Profiling the sampler before writing any kernel (see `VTE/docs/LIMITATIONS.md`) found that 92.6% of `Sampler.sample()`'s own cost was a single `np.argpartition` scan over the full 128K-token vocabulary on every generated token -- not the RNG, not top-p filtering, not repetition penalty, which combined cost under 0.1ms. Rather than build a full GPU-resident sampler (RNG, top-k, top-p, CDF selection) as first proposed, the existing greedy-decode top-k reduction kernel was generalized to return a handful of candidates per thread instead of one, moving just the expensive vocabulary scan to the GPU and leaving the (already-fast) rest of the sampler untouched. Measured on Llama 3.1 8B Q4_K_M / W7900 at the project's real default sampling settings (temperature=0.7, top_p=0.9, top_k=50), warmup-separated median of 3 runs: **decode throughput rises from 74.36 to 79.54 tok/s, a 6.96% gain**, with the sampled token distribution verified statistically identical to the original full-vocabulary path (KL-divergence 0.0001 against a real high-entropy logit sample) and greedy decoding (temperature=0) confirmed byte-identical whether the flag is on or off, since that path is untouched by construction. A real correctness edge case was found and fixed before this shipped: an early, more VGPR-conservative version of the kernel could theoretically drop true candidates under an adversarially clustered input (never observed on real model logits across 25 samples, but demonstrated on a synthetic worst case) -- widened before enabling by default. Also confirmed non-regressing on the RX 7600 across all five loadable models, at the same real default sampling settings, with the same warmup-separated methodology (numbers above): unlike batched prefill, this feature adds no extra VRAM cost, so it hit no ceiling on either 7B+ model. Full writeup, including the rejected larger-scope design: [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#kernel-efficiency-and-rejected-optimizations).

Real GPU telemetry (`amd-smi`, sampled every ~0.5s) from the W7900 runs above, load through 3 back-to-back generations each, no thermal throttling on any of them, VRAM peaks matching the predicted weights+KV-cache+arena breakdown almost exactly:

| Model | VRAM peak | Hotspot temp peak | Power peak |
|---|---|---|---|
| Granite 4.1 30B Q8_0 | 30.3 GiB | 55°C | 243 W |
| Qwen2.5 32B Q4_K_M | 20.4 GiB | 60°C | 295 W |
| Llama 3.1 8B Q4_K_M | 5.7 GiB | 48°C | 292 W |
| Llama 3.1 70B Q4_K_M | ~42.5 GiB | not sampled | not sampled |

**Bonus criterion (quantization + Radeon Cloud), explicitly:** every model above runs quantized (Q4_K_M/Q6_K/Q8_0, never full-precision weights) as VTE's only supported inference format, not an optional flag, and every W7900 row was measured on an actual AMD Radeon Cloud instance, not simulated or estimated.

A note on "Radeon Cloud model API," specifically: Radeon Cloud also offers a pre-hosted Dedicated Model API, which Aetheris deliberately does not use. Routing through someone else's already-optimized serving layer would mean measuring that service's engine, not this project's own -- the entire point of VTE is running our own quantized inference directly on the GPU. What's demonstrated above is the harder version of this criterion: real quantized inference, this project's own code, actually executing on real Radeon Cloud hardware, not a call to a managed endpoint.

The 70B row is a stretch test past the eight curated models above (70.6B parameters, loaded via VTE's architecture-generic metadata path with zero model-specific code, only reachable at all after unifying a load-time VRAM cap with the runtime safety margin, see `VTE/docs/BENCHMARK_W7900.md`): real evidence the engine scales, not just runs, on hardware well beyond the 8 GB card it was designed against.

Getting there took a real optimization arc (naive per-thread GEMV at ~18.8 tok/s up to a HIP-Graph-captured decode loop at ~100+ tok/s, five real profiling-driven kernel changes in between) and a fair number of dead ends that got documented instead of hidden: a speculative-decoding attempt that turned out fundamentally incompatible with this GEMV design, an FFN kernel fusion that helps the small demo model but regresses larger ones for reasons that resisted two rounds of investigation, a RoPE fusion that was numerically correct but not worth its added complexity for a 0.6% gain. None of that is required reading to use Aetheris. If you're curious how the engine works, or want the full kernel-optimization history with the real numbers behind each decision (including the parts that didn't pan out): [`VTE/README.md`](VTE/README.md) and [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md).

VTE is also currently in review to become an official experimental backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server, wired into its real `WrappedServer` contract rather than just being "compatible" with it. Six rounds of maintainer review so far, each catching a real integration bug and getting it fixed in the open: a runtime-lifecycle race between VTE's own idle-unload and Lemonade owning model lifetime, a GPU-exclusivity policy redesigned around each backend's actual resolved device rather than a static descriptor default, a checksum-registry collision, mixed-GPU-generation device selection. [The PR](https://github.com/lemonade-sdk/lemonade/pull/2675), [the RFC discussion](https://github.com/lemonade-sdk/lemonade/issues/2679), details in `VTE/docs/LEMONADE.md`. One of those fixes (correct RX 7600 detection on Windows) already shipped and is credited by name in Lemonade's own [v11.5.0 release notes](https://github.com/lemonade-sdk/lemonade/issues/2776).

Five ROCm/RDNA3 platform gaps found and reported while building this (three on Linux/W7900, two more on Windows/RX 7600), with exact repro steps: [`PLATFORM_ISSUES.md`](PLATFORM_ISSUES.md).

## 7. Judging-Criteria Mapping (Track 2, 120 points)

Mapped directly to the rubric, with a pointer to where each point was actually verified, not just described:

| Axis | Points | Where it's addressed | Verified how |
|---|---|---|---|
| Task positioning & application scenario | 20 | [Section 1](#1-application-scenario), [Section 5](#5-blackbox-verifiable-runtime-privacy) | A real project folder, a real codebase read/summarized/edited on camera in the [demo video](Assets/Aetheris%20Video.mp4); the "privacy verifiable at runtime" positioning has real evidence to point at, not just a claim -- a real hash-chained session log independently re-verified via `scripts/audit_verify.py`, a live 0-external-connections indicator confirmed against the real process tree, a real git shadow-ref undo validated both against a disposable-repo test fixture and a real session on the RX 7600 |
| Core capabilities (planning, tools, RAG, memory) | 20 | [Section 3](#3-core-capabilities), 5 of 5 implemented (2 is the stated minimum) | Each demonstrated live, not just in a diagram: `write_plan` produces a real approval popup the user clicks, not prose; `manage_memory` recalled a fact in a brand-new chat session with no shared history; `manage_skill` search found a previously-saved skill from a different conversation; Cartographer's `search_map` returned a real, BM25-ranked, LLM-summarized answer about a real project on the RX 7600, and a real A/B on the exact vague prompt this project's own README documents as a failure case (*"what does this codebase do"*) confirmed the on-demand tool alone reproduces that failure (zero real tool calls, wrong tool attempted) while automatic injection answers it correctly with zero tool calls needed; `write_file`/`edit_file` paused for a real click before touching disk; `navigate_browser`/`read_browser_page` correctly read a real inbox |
| Smooth multi-turn interaction | 20 | Round-based SSE streaming, tool calls shown as a status animation instead of raw fenced text; [Section 5](#5-blackbox-verifiable-runtime-privacy)'s Time-Travel | Cancel-mid-generation tested directly: confirmed it releases the server-side generation lock in seconds, not just hides the output client-side. Time-Travel adds a second, novel interaction: a real model-issued edit, approved through the gate, undone with one click on a real repo, verified the user's actual git state (`status`/`branch`/`stash`/tracked blobs) came back byte-identical. UX metrics ([`Aetheris Studio/docs/UX_METRICS.md`](Aetheris%20Studio/docs/UX_METRICS.md), `Aetheris Studio/scripts/metrics_report.py`) are now a direct byproduct of the audit trail: TTFT, turn duration, confirm-gate approval rate and decision latency, rollback rate, all measured, not estimated, from real session logs |
| Core inference on AMD Radeon GPU | 20 | [Section 6](#6-bonus-powered-by-vte) | No remote API anywhere in the core chat path; live GPU telemetry (`hipMemGetInfo`, not cached) confirmed on both a consumer card (RX 7600) and a workstation card (W7900) |
| Optimization for inference speed | 20 | [Section 6](#6-bonus-powered-by-vte) | Real profiling-driven optimization arc (~18.8 to 100+ tok/s), documented including the attempts that didn't pan out, not just the ones that did |
| Bonus: quantization + Radeon Cloud | 20 | [Section 6](#6-bonus-powered-by-vte) | Quantization (Q4_K_M/Q6_K/Q8_0) is VTE's only supported inference format, not an optional flag; every W7900 number above was measured on a real AMD Radeon Cloud instance |


