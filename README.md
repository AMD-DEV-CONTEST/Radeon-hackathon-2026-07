# Aetheris

**A local, private AI coding agent for AMD Radeon GPUs.** Chats, reads and edits files, runs shell commands, checks git state, searches your codebase, plans multi-step work, and remembers things across sessions, all running on your own machine. No cloud API key, no data leaving your GPU.

Built for **Track 2: Development & Local Deployment of Private AI Agents**.

Under the hood, Aetheris runs on **VTE**, a from-scratch inference engine we also built for this hardware instead of depending on an existing runtime. That part's genuinely interesting if you're into GPU kernels, and it gets its own section [below](#under-the-hood-vte-the-engine-we-built-to-power-this), but it's the supporting cast here, not the headline. Aetheris is the project; VTE is what lets it run entirely local.

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
| **App (GUI)** | ✅ [below](#windows-app-the-full-experience) | Not available yet, the desktop UI is a Windows build for now (see [Note on Linux](#note-on-linux)) |
| **Terminal** | ✅ [below](#terminal-windows-or-linux) | ✅ [below](#terminal-windows-or-linux) |

### Prerequisites (all paths)

- Python 3.10+
- An AMD Radeon GPU with the HIP runtime available: **Windows** needs the AMD HIP SDK installed, **Linux** needs ROCm (normally under `/opt/rocm`)
- Enough VRAM for whatever model you pick (run `vte list` after installing to see every curated model and its size; the demo model, Qwen2.5 1.5B, needs about 1 GB)

VTE reads your GPU's real architecture and compute-unit count at startup; there's nothing to configure by hand beyond having the driver/SDK installed.

### Windows: app (the full experience)

```bash
cd "Aetheris Studio"
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -e "..\VTE"
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\vte pull qwen2.5:1.5b-q4_k_m

cd aetheris_ui
flutter pub get
flutter run -d windows
```

The UI starts the Python backend for you on launch and waits for it to come up; you don't run anything else by hand. First run generates a local login and writes it to `Aetheris Studio\GENERATED_LOGIN_READ_AND_DELETE.txt`, log in with those credentials once, then delete the file.

### Terminal (Windows or Linux)

Same backend the app uses, just driven from a small chat script instead of the Flutter UI. This is the primary way to run Aetheris on Linux today, and works just as well on Windows if you'd rather skip the Flutter build.

```bash
cd "Aetheris Studio"
python -m venv .venv

# Windows
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -e "..\VTE"
.venv\Scripts\pip install -r requirements.txt

# Linux
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e "../VTE"
.venv/bin/pip install -r requirements.txt
```

Pull a model (downloads the public GGUF from Hugging Face into `VTE/Model/`):

```bash
.venv\Scripts\vte pull qwen2.5:1.5b-q4_k_m    # Windows
.venv/bin/vte pull qwen2.5:1.5b-q4_k_m         # Linux
```

Start the backend (leave this running in its own terminal):

```bash
.venv\Scripts\python app.py    # Windows
.venv/bin/python app.py        # Linux
```

In a second terminal, start chatting:

```bash
.venv\Scripts\python scripts\chat.py path\to\your\project    # Windows
.venv/bin/python scripts/chat.py path/to/your/project         # Linux
```

The `project` argument is the folder the agent's file/git/search tools operate on, defaults to the current directory if you leave it off. Type a message, press Enter, watch it stream, approve any file write/edit it proposes with `y`.

### Note on Linux

The Flutter desktop UI is a Windows-only build right now (no `linux/` target configured), so the app-with-a-window experience is Windows-only for the moment. The agent *backend* underneath it has no such limitation: it's plain Python/FastAPI, and this project's own testing ran it headless (no UI, real HTTP calls against the live agent loop) on an AMD Radeon Cloud W7900 Linux instance, confirming tool dispatch, memory, skills, and the write-confirmation gate all work identically there. `scripts/chat.py` above is that same validated path, just packaged as something you can actually type into instead of hand-rolling `curl` SSE parsing.

## Things to try

A few prompts to get a feel for what the agent actually does, assuming `project_path` points at some real codebase (yours, or this repo itself):

- *"What does this codebase do? Give me a two-paragraph summary."* Exercises file search plus reading, no writes.
- *"Find every place `TODO` appears and summarize what's left."* `search_files` across the whole project.
- *"What changed in the last 5 commits?"* `git log`/`git show`, no working-tree access needed.
- *"Add a docstring to the `main` function in `<some file>`."* A real edit; you'll see the confirmation prompt before it lands.
- *"Plan out how you'd add rate limiting to this API, but don't touch anything yet."* Switches the agent into Planner mode, streams a plan, waits for your go-ahead.
- *"Remember that this project uses tabs, not spaces."* Writes to the memory tool; ask again in a later session and it recalls it without the fact being back in the chat transcript.
- *"Look up the current stable version of \<some library> online."* Read-only browser tool, no form-filling or credentials, ever.

## Under the hood: VTE, the engine we built to power this

Aetheris needed a local inference engine that runs entirely on an AMD Radeon GPU with nothing else installed, so we wrote one: **VTE**, hand-written HIP kernels, no llama.cpp/vLLM/PyTorch in the inference path. It turned into its own small systems project along the way, GEMV kernels tuned against real memory-bandwidth measurements, a HIP-Graph-captured decode loop, custom attention, the works, and on the demo hardware it decodes slightly *faster* than Ollama/llama.cpp on the same GGUF file (112.98 vs 110.76 tok/s, Qwen2.5 1.5B, RX 7600).

None of that is required reading to use Aetheris. If you're curious how it works or want the full kernel-optimization writeup (what worked, what didn't, and the real numbers behind each decision): [`VTE/README.md`](VTE/README.md) and [`VTE/docs/PERFORMANCE.md`](VTE/docs/PERFORMANCE.md).

One more sign of how real this is: VTE is currently in review to become an official experimental backend in [Lemonade](https://github.com/lemonade-sdk/lemonade), AMD's own local LLM server, not a submission sitting in a queue, an actual maintainer going through the code line by line. Six review rounds so far, each one catching something real and getting it fixed in the open: a runtime-lifecycle race between VTE's own idle-unload timer and Lemonade owning model lifetime, a GPU-exclusivity policy that had to be redesigned around each backend's *actual* resolved device instead of a static descriptor default, a checksum-registry collision, mixed-GPU-generation device selection. Full trail: [the PR](https://github.com/lemonade-sdk/lemonade/pull/2675), [the RFC discussion](https://github.com/lemonade-sdk/lemonade/issues/2679).

## Repository layout

- **`Aetheris Studio/`**: the agent, backend (FastAPI, `app.py`) plus the Flutter desktop UI (`aetheris_ui/`). Depends on VTE being installed.
- **`VTE/`**: the inference engine. Usable entirely on its own too, see its own README.
- **`PROJECT_SPECIFICATION.md`**: the full Track 2 submission writeup, architecture, capabilities, model list, benchmarks.
- **`PLATFORM_ISSUES.md`**: three ROCm/RDNA3 platform gaps found and reported while building this, with repro steps.

### Running VTE and Aetheris from two separate machines/checkouts

VTE has no compiled or frozen dependency on Aetheris. A `pip install -e` pointing at any VTE checkout works; there's no requirement that the two folders live side by side.

### Development extras

`pytest`/`mypy`/`pyinstaller` (not needed just to run inference or the agent):

```bash
cd VTE && .venv\Scripts\pip install -e ".[dev]"      # Windows
cd VTE && .venv/bin/pip install -e ".[dev]"          # Linux
```

> **Troubleshooting the Windows build.** If `flutter run -d windows` fails with a long wall of `Error when reading ... system cannot find the path specified`, it's stale generated build state, not a code problem: run `flutter clean` inside `aetheris_ui/`, then `flutter pub get`, then try again.
