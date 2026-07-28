# Aetheris

**A local, private AI coding agent for AMD Radeon GPUs.** Chats, reads and edits files, runs shell commands, checks git state, searches your codebase, plans multi-step work, and remembers things across sessions, all running on your own machine. No cloud API key, no data leaving your GPU.

Built for **Track 2: Development & Local Deployment of Private AI Agents**.

Under the hood, Aetheris runs on **VTE**, a from-scratch inference engine also built for this project instead of depending on an existing runtime ([below](#under-the-hood-vte)).

**[Watch the demo video](https://drive.google.com/drive/folders/1a6CQkLn0nwz_gbBwckKcNBmiN-YMQpfD?usp=sharing)** — the agent reading, planning, and editing a real codebase on camera, running end-to-end on an AMD Radeon GPU. (Same folder also has the submission slide deck.)

## What it can actually do

Five capabilities, all real (not stubbed for the demo):

- **Tool use.** Reads/writes/edits files, runs shell commands, inspects `git` (status/diff/log/show/branch), searches your codebase, browses the web read-only.
- **Plans before it acts.** A Planner/Builder mode toggle: in Planner mode the agent can only read and write a plan, not touch anything, until you approve it. Enforced server-side, not just prompted.
- **Remembers across sessions.** A separate memory tool (add/search/forget), independent of chat history, so the agent doesn't start from zero every conversation.
- **Builds its own skill library.** When it solves something non-trivial, it can write itself a reusable procedure and retrieve it next time a similar task comes up, no separate embedding model needed for this.
- **Asks before doing anything risky.** File writes, edits, and destructive-looking shell commands pause for your explicit click (or, from the terminal, a typed `y`) before they run.

Full technical writeup of how each of these is wired: [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md).

## Quickstart

Pick the row that matches your setup. All three talk to the exact same backend and agent loop, just through a different front end.

| | Windows | Linux |
|---|---|---|
| **App (GUI)** | ✅ [below](#windows-app-the-full-experience) | Scaffolded (`linux/` target added), not yet built/verified on real Linux hardware (see [Note on Linux](#note-on-linux)) |
| **Terminal** | ✅ [below](#terminal-windows-or-linux) | ✅ [below](#terminal-windows-or-linux) |

### Prerequisites (all paths)

- Python 3.10+
- An AMD Radeon GPU with the HIP runtime available: **Windows** needs the AMD HIP SDK installed, **Linux** needs ROCm (normally under `/opt/rocm`)
- Enough VRAM for whatever model you pick (run `vte list` after installing to see every curated model and its size; the default model, Llama 3.1 8B Instruct, needs about 5 GB)

VTE reads your GPU's real architecture and compute-unit count at startup; there's nothing to configure by hand beyond having the driver/SDK installed.

**Default model: Llama 3.1 8B Instruct** (~5 GB), picked for reliable tool-calling and consistent language-matching. Downloads from Hugging Face into `VTE/Model/` via `vte pull`. Tighter on VRAM? `qwen2.5:1.5b-q4_k_m` (~1 GB) is the lighter fallback, same dropdown. See [`VTE/docs/LIMITATIONS.md`](VTE/docs/LIMITATIONS.md#model-compatibility) for model-choice notes.

### Windows: app (the full experience)

```bash
cd "Aetheris Studio"
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -e "..\VTE"
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\vte pull llama3.1:8b-instruct-q4_k_m

cd aetheris_ui
flutter pub get
flutter run -d windows
```

The UI starts the Python backend for you on launch and waits for it to come up; you don't run anything else by hand. First run generates a local login and writes it to `Aetheris Studio\GENERATED_LOGIN_READ_AND_DELETE.txt`, log in with those credentials once, then delete the file.

### Terminal (Windows or Linux)

Same backend the app uses, driven from a rich terminal UI (`aetheris`) instead of the Flutter front end. This is the primary way to run Aetheris on Linux today, and it works just as well on Windows if you'd rather skip the Flutter build. No login here, unlike the app above: the username/password screen is a Flutter-only gate, the backend itself only ever checks an internal token the CLI reads from `.env` automatically.

```bash
cd "Aetheris Studio"
python -m venv .venv

# Windows
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -e "..\VTE"
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .

# Linux
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e "../VTE"
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

That last line installs the `aetheris` command itself. Now pull a model (downloads the public GGUF from Hugging Face into `VTE/Model/`):

```bash
.venv\Scripts\vte pull llama3.1:8b-instruct-q4_k_m    # Windows
.venv/bin/vte pull llama3.1:8b-instruct-q4_k_m         # Linux
```

Then `cd` into whatever project you want the agent to work on, and start chatting:

```bash
cd path/to/your/project
aetheris chat
```

That's the whole thing. The CLI starts the backend itself and waits for the GPU to finish warming up, so there's no second terminal to babysit, and the agent's file/git/search tools are scoped to the directory you launched from. Type a message, press Enter, watch it stream, approve any file write or edit it proposes with `y`.

Useful flags and in-chat commands:

| | |
|---|---|
| `aetheris chat -p <dir>` | work on a different folder than the current one |
| `aetheris chat --planner` | start in Planner mode (read-only until you approve a plan) |
| `aetheris run "<prompt>"` | one-shot, non-interactive, scriptable exit codes |
| `/model`, `/tokens`, `/ctx` | change model, output limit, or context window mid-session |
| `/egress`, `/verify`, `/log` | Blackbox: live egress report, audit-chain check, session trail |
| `/optimize run` | kernel optimizer ([below](#self-optimizing-kernels-on-amds-own-methodology)) |
| `/help` | everything else |

Each response ends with a metrics footer showing real TTFT and decode speed reported by the GPU itself, not estimated from packet arrival.

### Note on Linux

The backend (plain Python/FastAPI, no Windows-specific code) is validated headless on an AMD Radeon Cloud W7900 Linux instance: tool dispatch, memory, skills, and the confirm gate all work identically there. The `aetheris` CLI drives that same path, and a dependency-free `scripts/chat.py` remains in the repo as a minimal fallback if you'd rather not install the CLI. The Flutter UI has a `linux/` target scaffolded too, but not yet built/verified on real Linux hardware.

## Things to try

A few prompts to get a feel for what the agent does, pointed at some real codebase (yours, or this repo). Naming the tool explicitly ("use the X tool") is more reliable than an open-ended ask with the default 8B model.

- *"Read the README.md and tell me in two paragraphs what this project does."*
- *"Find every place `TODO` appears and summarize what's left."* `search_files` across the project.
- *"Use the git tool to show me the last 5 commits."*
- *"Use the edit_file tool to add a docstring to the `main` function in `<some file>`."* A real edit; you'll see the confirmation prompt before it lands.
- *"Plan out how you'd add rate limiting to this API, but don't touch anything yet."* Planner mode: streams a plan, waits for your go-ahead.
- *"Remember that this project uses tabs, not spaces."* Recalled in later sessions without bloating the chat transcript.
- *"Use the browser tool to look up the current stable version of \<some library> online."* Read-only, no form-filling or credentials, ever.
- *"Use the search_map tool to find out what this codebase does."* Cartographer's background-generated map -- often faster and better-grounded than reading files one by one.
- After the agent edits a file with your approval: click the ⟲ checkpoint icon next to your message to restore the project to the state before it ran, with a diff preview first.

## Blackbox: privacy you can verify, not just a promise

Every local agent says "your code never leaves the machine." Aetheris makes that checkable at runtime, via four independently opt-out pieces:

- **Flight Recorder** -- every tool call, confirm-gate decision, and turn boundary appended to a per-session, hash-chained log, re-verifiable standalone via `Aetheris Studio/scripts/audit_verify.py` (stdlib-only, no Aetheris install needed).
- **Egress Monitor** -- a live "🔒 0 B external" indicator, backed by real connection enumeration against the process tree.
- **Time-Travel** -- every approved file write gets a git shadow-ref snapshot, undoable per-message with one click, never touching your real index or HEAD.
- **Cartographer** -- background codebase mapping that also fixes the "vague prompt hallucinates" failure mode below.

Full write-up: [`Aetheris Studio/docs/BLACKBOX.md`](Aetheris%20Studio/docs/BLACKBOX.md). UX metrics from the same audit trail: [`Aetheris Studio/docs/UX_METRICS.md`](Aetheris%20Studio/docs/UX_METRICS.md).

## Under the hood: VTE

Aetheris runs on **VTE**: hand-written HIP kernels, no llama.cpp/vLLM/PyTorch in the inference path. On two of six models it decodes *faster* than Ollama/llama.cpp on the identical GGUF file, validated on a consumer card (RX 7600) and a workstation card (W7900, via AMD's Radeon Cloud), scaling to a 70B stretch test with zero architecture-specific code:

| Model | Hardware | VTE | Ollama/llama.cpp | Ratio |
|---|---|---|---|---|
| Qwen2.5 1.5B Q4_K_M | RX 7600 (8 GB) | **115.14 tok/s** | 110.76 tok/s | **104.0%** |
| Granite 4.1 3B Q8_0 | RX 7600 (8 GB) | **57.34 tok/s** | 50.84 tok/s | **112.8%** |
| Granite 4.1 30B Q8_0 | W7900 (48 GB) | 20.2 tok/s | 22.5 tok/s | 89.8% |
| Llama 3.1 8B Q4_K_M | W7900 (48 GB) | 79.54 tok/s | 93.45 tok/s | 85.1% |
| Qwen2.5 32B Q4_K_M | W7900 (48 GB) | 22.7 tok/s | 28.56 tok/s | 79.5% |
| Llama 3.1 70B Q4_K_M | W7900 (48 GB) | 10.50 tok/s | 14.21 tok/s | 73.9% |

**In review to become an official backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server** -- six rounds of real maintainer review so far ([the PR](https://github.com/lemonade-sdk/lemonade/pull/2675)), one fix already shipped and credited by name in Lemonade's [v11.5.0 release notes](https://github.com/lemonade-sdk/lemonade/issues/2776). Also surfaced **five real ROCm/RDNA3 platform gaps**, each with exact repro steps: [`PLATFORM_ISSUES.md`](PLATFORM_ISSUES.md).

Two more optimizations shipped this cycle, both on by default and re-validated on the RX 7600 with no regression: **batched prefill** (64-token chunks through a dedicated HIP Graph) cuts TTFT ~1.9x on Llama 3.1 8B/W7900, byte-identical output to the sequential path; **GPU-accelerated stochastic sampling** moves the decode sampler's dominant cost off the CPU for a **+6.96%** decode-speed gain at the project's real sampling defaults, statistically verified against the original distribution.

Full kernel-optimization history, GPU telemetry, and the investigation trails (including what didn't pan out): [`VTE/README.md`](VTE/README.md), [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md), [`VTE/docs/BENCHMARK_W7900.md`](VTE/docs/BENCHMARK_W7900.md).

## Self-optimizing kernels, on AMD's own methodology

Every kernel win above was found by hand. `aetheris optimize` lets the agent run that search itself, built on the core idea of [**Hyperloom**](https://github.com/AMD-AGI/Hyperloom), the agentic inference optimizer AMD open-sourced on 2026-07-22, then validated mechanism by mechanism against Hyperloom's actual source: bounded discrete catalog with no LLM writing C++, correctness gate before any benchmark is trusted, interleaved A/B, statistical significance by non-overlapping interquartile ranges, and a graded KEEP / NEEDS_REVIEW / REVERT verdict.

**Hyperloom itself does not run on this hardware.** Its supported GPU set is `{mi300x, mi308x, mi325x, mi355x}` and its architecture map covers exactly two targets, `gfx942` and `gfx950`, both datacenter CDNA. RDNA is not merely unlisted, it is asserted absent: Hyperloom ships a test that pins `_GFX_TO_RUNNER.get("gfx1100") is None`. Aetheris brings that methodology to consumer and workstation RDNA3, running it on a `gfx1102` RX 7600 and a `gfx1100` W7900, against an inference engine with no vLLM or SGLang anywhere in it.

It goes further in two places. Hyperloom patches the live tree and reverts in a `finally`; Aetheris never touches production during a test, running two throwaway `vte-server` instances on separate ports instead. And where Hyperloom infers "did the patch actually run?" from log markers, Aetheris compares the rendered C++ each instance genuinely compiled.

That last check paid for itself immediately: it caught a `BLOCK_SIZE` knob in our own catalog that was doing nothing at all, because `gemv_q4k`'s launch geometry is fixed in Python and the template only reads it. It was removed rather than papered over.

**The first honest run reports that nothing should change.** All three `#pragma unroll` variants regressed 34% to 41% on the RX 7600, every one confirmed engaged and statistically significant, and none were promoted. The hand-tuned production kernel is already the best configuration in the catalog. Details and the full table: [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md#61-self-optimizing-kernels-built-on-amds-own-methodology).

## Repository layout

- **`Aetheris Studio/`**: the agent, backend (FastAPI, `app.py`) plus the Flutter desktop UI (`aetheris_ui/`). Depends on VTE being installed. Blackbox lives in `core/audit/` and `core/rag/cartographer.py`, docs in `Aetheris Studio/docs/` (`BLACKBOX.md`, `UX_METRICS.md`), tests in `Aetheris Studio/tests/`.
- **`VTE/`**: the inference engine. Usable entirely on its own too, see its own README.
- **`PROJECT_SPECIFICATION.md`**: the full Track 2 submission writeup, architecture, capabilities, model list, benchmarks.
- **`PLATFORM_ISSUES.md`**: five ROCm/RDNA3 platform gaps found and reported while building this (three on Linux/W7900, two more on Windows/RX 7600), with repro steps.

### Running VTE and Aetheris from two separate machines/checkouts

VTE has no compiled or frozen dependency on Aetheris. A `pip install -e` pointing at any VTE checkout works; there's no requirement that the two folders live side by side.

### Development extras

`pytest`/`mypy`/`pyinstaller` (not needed just to run inference or the agent):

```bash
cd VTE && .venv\Scripts\pip install -e ".[dev]"      # Windows
cd VTE && .venv/bin/pip install -e ".[dev]"          # Linux
```

> **Troubleshooting the Windows build.** If `flutter run -d windows` fails with a long wall of `Error when reading ... system cannot find the path specified`, it's stale generated build state, not a code problem: run `flutter clean` inside `aetheris_ui/`, then `flutter pub get`, then try again.

## Contact

kaue.costa15@outlook.com.br
