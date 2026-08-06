# AudioSight

**Turn any video into an audio-described soundtrack, entirely on your own AMD
Radeon GPU.**

AudioSight is an offline Linux CLI that makes visual media accessible to blind
and low-vision audiences. It listens to the dialogue, watches the picture,
understands the story scene by scene, writes narration in Simplified Chinese and
English, speaks it, and mixes it into the original audio at moments where it
will not collide with speech.

Everything runs locally. After the models are downloaded, no video, audio,
frame, prompt, or analysis result ever leaves the machine.

> This is the **submission repository** for the AMD AI DevMaster Hackathon,
> **Track 1 — Development of Multimodal Content Creation Tools**. AudioSight was
> developed and verified end to end on an AMD Radeon gfx1100 GPU with ROCm 7.2.1.

---

## Submitted deliverables

| # | Deliverable | Location |
| --- | --- | --- |
| 1 | Project profile document (PDF) | [AudioSight-Project-Profile.pdf](AudioSight-Project-Profile.pdf) |
| 2 | Project source code + README | `AudioSight/` git submodule → <https://github.com/austin1997/AudioSight> (this README is its copy) |
| 3 | Demo video (9 min 59 s) | [demo.mp4](demo.mp4) — H.264/AAC 1080p, plays inline on GitHub |
| 4 | Supplementary material — poster | [AudioSight-Poster.png](AudioSight-Poster.png) (preview below) · [AudioSight-Poster.pdf](AudioSight-Poster.pdf) (print) |

### Demo video chapters

| Time | Section |
| --- | --- |
| 0:00 | The problem, the target users, and the AMD Radeon GPU it all runs on |
| 3:00 | Live walkthrough of the full pipeline on the Radeon GPU |
| 8:29 | The result — listening to the finished audio-described soundtrack |

Reviewers short on time can jump straight to **8:29** to hear the output, then
back to **3:00** for how it was produced.

### Poster preview

![AudioSight poster: audio description for blind and low-vision audiences, created locally on an AMD Radeon GPU](AudioSight-Poster.png)

The source code is referenced as a git **submodule** rather than a copied
snapshot, so the code under review is always an exact upstream commit instead of
a divergent duplicate. Clone this repository with submodules:

```bash
git clone --recurse-submodules \
  https://github.com/austin1997/Radeon-hackathon-2026-07.git
```

Every relative path in the sections below — `src/`, `docs/`, `scripts/`,
`environments/`, `.venvs/`, `models/`, `work/`, `outputs/` — is relative to that
submodule directory.

The profile document above is rendered from
[AudioSight/docs/amd-devmaster-project-profile.md](AudioSight/docs/amd-devmaster-project-profile.md);
it carries the architecture rationale and the full ROCm benchmark results.

---

## Table of contents

1. [How it works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [Environment configuration](#3-environment-configuration)
4. [Downloading models](#4-downloading-models)
5. [Startup guide](#5-startup-guide)
6. [Command reference](#6-command-reference)
7. [Dependency list](#7-dependency-list)
8. [Project layout](#8-project-layout)
9. [Development](#9-development)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. How it works

### Architecture

![AudioSight pipeline architecture](https://raw.githubusercontent.com/austin1997/AudioSight/master/docs/assets/architecture.png)

The three stages above map onto three CLI commands. `analyze` extracts the
soundtrack and frames, transcribes the dialogue with Qwen3-ASR, splits the video
into scenes, and has Qwen3.5 record the visible facts plus a running summary of
the story so far. `draft` turns those facts into scene narration, optionally
stopping for human review. `render` speaks the narration with Qwen3-TTS and
appends it to the scene soundtrack, producing the final composited audio track.

### Command flow

```
doctor ─▶ init ─▶ analyze ─▶ draft ─┬─▶ (human edit YAML) ─┬─▶ validate ─▶ render
                                     └─▶ preview ──────────┘
```

The core CLI process contains **no machine-learning framework at all** — it
never imports PyTorch, Transformers, vLLM, or any Qwen package. All neural
inference runs in short-lived worker processes in separate, self-contained
environments, addressed through a versioned JSON protocol:

| Environment | Contains | Worker actions |
| --- | --- | --- |
| `audiosight-core` | CLI, SQLite state, FFmpeg, shot detection | — |
| `audiosight-vl` | Torch + vLLM + TorchCodec | `asr/analyze`, `vision/cluster`, `vision/analyze`, `narration/draft` |
| `audiosight-tts` | Torch + vLLM-Omni + qwen-tts | `tts/synthesize_batch` |

Each model gets the whole GPU while it runs and releases it fully on worker
exit, so a single card can host all four models across one job without ever
holding them resident together.

Four Apache-2.0 models do the work:

| Role | Model |
| --- | --- |
| Speech recognition | `Qwen/Qwen3-ASR-1.7B` |
| Word-level alignment | `Qwen/Qwen3-ForcedAligner-0.6B` |
| Vision + narration | `Qwen/Qwen3.5-9B` or `Qwen/Qwen3.5-4B` |
| Speech synthesis | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` |

Rendering uses an **expanded timeline**: at each anchor the original soundtrack
pauses, the narration is inserted, and the original audio resumes exactly where
it stopped. Nothing is overlaid or ducked, so no dialogue is ever masked and no
description is truncated to fit a gap.

---

## 2. Prerequisites

### Hardware

| | Minimum | Recommended (verified) |
| --- | --- | --- |
| GPU | AMD Radeon with 16 GiB VRAM | AMD Radeon gfx1100 / RDNA 3, 48 GiB |
| Profile | `portable-16gb` (Qwen3.5-4B) | `workstation-32gb` (Qwen3.5-9B) |
| Free disk | 30 GiB for models | 45 GiB for models, plus project working space |

Multi-GPU is not used; all inference targets device 0.

### Software

- Linux x86_64
- Python 3.12
- FFmpeg 6 with `ffmpeg` and `ffprobe` on `PATH`
- ROCm 7.2.1, working `/dev/kfd` and `/dev/dri`, and a bootstrap interpreter
  containing ROCm PyTorch (default `/opt/venv/bin/python`)
- Root access on first setup, so the script can install FFmpeg development
  libraries, CMake, `pkg-config`, and a C++ compiler if they are absent

Verify your AMD GPU before starting:

```bash
rocm-smi --showproductname --showmeminfo vram
/opt/venv/bin/python -c \
  'import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())'
```

The availability value must print `True`. PyTorch intentionally exposes HIP
devices through its `torch.cuda` API, so AudioSight's workers use explicit
`cuda:0` placement while reporting `backend: rocm` — this is a ROCm run, not a
CUDA one.

---

## 3. Environment configuration

### 3.1 Setting up the three environments

```bash
cd AudioSight   # the source submodule of this submission repository
AUDIOSIGHT_ROCM_PYTHON=/opt/venv/bin/python ./scripts/create-rocm-envs.sh
```

If you cloned the project repository on its own
(`git clone https://github.com/austin1997/AudioSight.git`), run the same script
from its root; the remaining commands in this README are identical.

This creates three isolated virtual environments under `.venvs/`:

- `.venvs/audiosight-core` — the CLI, with no Torch or Transformers;
- `.venvs/audiosight-vl` — Torch 2.10.0 for ROCm 7.2.1, Triton 3.6.0,
  Transformers 4.57.6, TorchCodec 0.10, qwen-asr, and vLLM 0.18.1;
- `.venvs/audiosight-tts` — the same Torch/vLLM ABI plus vLLM-Omni 0.18.0 and
  qwen-tts 0.1.1 as an explicit fallback.

Two components are **compiled from source** because no compatible prebuilt wheel
exists:

- **vLLM 0.18.1** is built with `PYTORCH_ROCM_ARCH=gfx1100` and
  `VLLM_TARGET_DEVICE=rocm`. Override the architecture for a different Radeon
  card by exporting `PYTORCH_ROCM_ARCH` before running the script. Set
  `MAX_JOBS` to control build parallelism (default 64).
- **TorchCodec 0.10** is built against the ROCm Torch ABI and the system FFmpeg
  libraries; the generic PyPI CPU wheel is not ABI-compatible and fails at
  import.

Expect the first run to take a while — the vLLM build dominates. The compiled
tree is shared between `audiosight-vl` and `audiosight-tts`, which are pinned to
a byte-identical Torch ABI, so it is only built once.

Verify the result:

```bash
.venvs/audiosight-vl/bin/python -c \
  'import vllm; from vllm.model_executor.models.registry import ModelRegistry; print(vllm.__version__, {"Qwen3_5ForConditionalGeneration", "Qwen3ASRForConditionalGeneration"} <= set(ModelRegistry.get_supported_archs()))'
.venvs/audiosight-vl/bin/python -c \
  'from torchcodec.decoders import VideoDecoder; print(VideoDecoder("video.mkv").metadata)'
.venvs/audiosight-tts/bin/python -c \
  'import vllm; from vllm_omni import Omni; print(vllm.__version__, Omni)'
```

The setup script performs equivalent assertions itself and exits with code `3`
if either runtime is incomplete.

### 3.2 Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `AUDIOSIGHT_ROCM_PYTHON` | Bootstrap ROCm PyTorch interpreter used by the setup script | `/opt/venv/bin/python` |
| `AUDIOSIGHT_PYTHON_CORE` | Override the core worker interpreter | resolved from `.venvs/` |
| `AUDIOSIGHT_PYTHON_VL` | Override the ASR/vision/narration interpreter | resolved from `.venvs/` |
| `AUDIOSIGHT_PYTHON_TTS` | Override the TTS interpreter | resolved from `.venvs/` |
| `PYTORCH_ROCM_ARCH` | Target GPU architecture for the vLLM build | `gfx1100` |
| `MAX_JOBS` | vLLM build parallelism | `64` |
| `HF_ENDPOINT` | Hugging Face mirror, for `models fetch` only | unset |
| `AUDIOSIGHT_WORKER_MODE` | Set to `fake` for GPU-free contract testing | unset |

`AUDIOSIGHT_PYTHON_ASR` remains as a compatibility alias; new deployments should
point ASR and alignment at `AUDIOSIGHT_PYTHON_VL`.

---

## 4. Downloading models

Model download is the **only** step that touches the network. Everything
afterwards runs offline against repository-local paths.

```bash
.venvs/audiosight-core/bin/audiosight models fetch --profile workstation-32gb
.venvs/audiosight-core/bin/audiosight models verify --profile workstation-32gb
```

If `huggingface.co` is unreachable, set a mirror for the fetch command only:

```bash
HF_ENDPOINT=https://hf-mirror.com \
  .venvs/audiosight-core/bin/audiosight models fetch --profile workstation-32gb
```

Snapshots are stored under `models/<role>/<revision>/` and pinned in
`models/manifest.lock.json`. `models verify` re-checks every file's size and
SHA-256 plus the environment digest, and `models list` shows the locked
snapshots without any network access.

### Profiles

| Profile | Vision/narration model | Free VRAM required | Disk | Batch size |
| --- | --- | ---: | ---: | ---: |
| `workstation-32gb` (default) | Qwen3.5-9B bf16 | 29.5 GiB | 45 GiB | 4 |
| `portable-16gb` | Qwen3.5-4B bf16 | 14.5 GiB | 30 GiB | 1 |
| `portable-16gb-q4` | Qwen3.5-9B W4A16 GPTQ | 14.5 GiB | 30 GiB | 1 |

`portable-16gb-q4` is **experimental**. vLLM 0.18.1 reports its ROCm 4-bit
kernel as buggy, and in our benchmarks it was 57 % slower per output token than
4B bf16 while producing fewer visible facts. Use `portable-16gb` for supported
16 GiB runs.

The profile is fixed at `init` and cannot be changed for an existing project.

### Health check

```bash
.venvs/audiosight-core/bin/audiosight doctor \
  --profile workstation-32gb --accelerator rocm --deep --json
```

`--deep` loads each of the four models in turn, runs a minimal real GPU
inference, records peak VRAM and duration, and confirms memory is released on
worker exit. Run this before your first real job.

---

## 5. Startup guide

### 5.1 Quick start (automatic approval, no human review)

This is the fastest path to a listenable result, suitable for personal use. The
generated narration is not proofread, and every report correctly retains
`human_reviewed: false`.

```bash
CLI=.venvs/audiosight-core/bin/audiosight

# 1. Create the project and fingerprint the source
$CLI init video.mkv \
  --project work/demo \
  --review-policy prototype-auto \
  --accelerator rocm

# 2. Transcribe, align, cluster scenes, and analyze the picture (GPU-heavy)
$CLI analyze work/demo

# 3. Draft narration in both languages from one analysis pass
$CLI draft work/demo --languages zh-CN,en-US

# 4. Validate and render each language
$CLI validate work/demo --language zh-CN
$CLI render   work/demo --language zh-CN --output outputs/demo.zh-CN.m4a

$CLI validate work/demo --language en-US
$CLI render   work/demo --language en-US --output outputs/demo.en-US.m4a
```

Rough timings on the verified gfx1100 system for a 10-minute source with the
9B profile: `analyze` ≈ 34 min, bilingual `draft` ≈ 8 min, each `render`
≈ 4–5 min. The 4B profile is 15–50 % faster depending on the stage.

### 5.2 Full workflow with human review (recommended for publishing)

Omit `--review-policy` to get the default `manual` policy, which stops after
drafting and hands you an editable file.

```bash
$CLI init video.mkv --project work/film --accelerator rocm
$CLI analyze work/film
$CLI draft work/film --languages zh-CN,en-US --density standard
```

Now edit `work/film/review/narration.en-US.yaml`. Each item carries a time
anchor, the scene range, a length budget, the draft text, a confidence score,
and four timestamped evidence frames under `work/film/evidence/`:

```yaml
- id: N0001
  language: en-US
  anchor_source_ms: 22800
  scene_range_ms: [0, 22800]
  length_budget_units: 19
  draft: A detective leans close to the car window, gesturing with a hand as he
    speaks to the distressed man inside.
  final: ''            # write your corrected text here
  status: pending      # -> approved | rejected | needs_revision
  confidence: 0.95
  visual_event_ids: [SEG0001]
  evidence:
    - frame: evidence/SEG0001_001.jpg
      source_ms: 4560
    # ... three more frames
  warnings: []
  reviewer_note: ''
  voice: {speaker: Aiden, speed: 1.0, style: neutral}
```

Set `final` to your corrected text and `status` to `approved`. Only approved
items are rendered; an empty `final` falls back to the draft. The file header
records the exact model revision, prompt version, and sampling settings that
produced the batch.

Listen to any single line in context before committing to it:

```bash
$CLI preview work/film --language en-US --id N0001 --context 8.0
```

Then validate and render as in the quick start. `validate` binds its report to
the SHA-256 of the exact review file it inspected, and `render` refuses to run
against a stale report — so you cannot accidentally ship audio that does not
match what you approved.

### 5.3 Useful adjustments

```bash
# Denser or sparser narration
$CLI draft work/film --languages zh-CN,en-US --density detailed

# Re-run only one analysis stage after changing settings
$CLI analyze work/film --rebuild vision

# Skip semantic boundary judgement entirely (faster, less coherent scenes)
$CLI analyze work/film --cluster-mode heuristic

# Tune scene granularity
$CLI analyze work/film --min-scene-seconds 8 --max-scene-seconds 30

# Use the stable TTS fallback instead of experimental vLLM-Omni
$CLI init video.mkv --project work/film --tts-backend qwen-tts

# Adjust narration playback rate and insertion padding at render time
$CLI render work/film --language en-US --output out.m4a \
  --narration-speed 2.6 --pre-silence-ms 200 --post-silence-ms 200
```

Every stage is content-addressed and checkpointed, so re-running a command
reuses valid cache and an interrupted `analyze` resumes from its last
checkpoint rather than starting over.

---

## 6. Command reference

Global options: `--log-level {debug,info,warning,error}`,
`--log-format {text,json}`, `--no-color`, `--offline`, `--model-root DIR`,
`--version`.

Text mode prints stable `key: value` lines to stdout; `--log-format json` emits
one JSON object. Live progress plus warning and diagnostic events go to stderr;
the final stdout summary may still include warning counts.
`analyze`, `draft`, `render`, and `preview` also write a complete JSONL event log
under `<project>/logs/`.

Interactive terminals show a rate-limited progress bar with the current stage,
completed/total work, elapsed time, and ETA when at least two measurable items
have completed. `--no-color` and non-interactive terminals use periodic plain
text lines instead of cursor updates. Batched ASR and vLLM-Omni TTS calls report
their current substage and elapsed time but do not invent an item-level ETA.

| Command | Purpose | Key options |
| --- | --- | --- |
| `models fetch` | Download model snapshots and write the lock file | `--profile` |
| `models verify` | Re-check sizes, hashes, and environment digests | `--profile` |
| `models list` | List locked snapshots offline | — |
| `doctor` | Check the environment; `--deep` runs real GPU smoke tests | `--project`, `--profile`, `--accelerator`, `--deep`, `--json` |
| `init VIDEO` | Create a project and fingerprint the source | `--project`, `--review-policy`, `--profile`, `--accelerator`, `--audio-stream`, `--subtitle-stream`, `--subtitle-file`, `--source-language`, `--tts-backend`, `--narration-speed` |
| `analyze PROJECT` | ASR, alignment, scene clustering, visual analysis | `--rebuild`, `--cluster-mode`, `--asr-batch-size`, `--min-scene-seconds`, `--max-scene-seconds`, `--max-frames-per-segment`, `--burned-subtitles` |
| `draft PROJECT` | Generate narration for one or more languages | `--languages LANG[,LANG]` (required), `--density`, `--max-expansion-ratio`, `--narration-thinking` |
| `preview PROJECT` | Audition one narration item in context | `--language`, `--id` (both required), `--context`, `--text`, `--output`, `--regenerate-tts` |
| `validate PROJECT` | Check reviewed narration against the timeline | `--language` (required), `--scope`, `--report` |
| `render PROJECT` | Synthesize and mix the final soundtrack | `--language`, `--output` (both required), `--narration-speed`, `--pre-silence-ms`, `--post-silence-ms`, `--fade-ms`, `--overwrite` |

`--languages` takes a comma-separated list of one or more supported languages,
for example `--languages zh-CN` or `--languages zh-CN,en-US`.
Commands never implicitly run their prerequisites: `draft` will not re-analyze,
`render` will not re-draft, and `validate` never repairs human-edited text.

### Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Success, possibly with non-blocking warnings |
| `2` | Bad arguments or configuration |
| `3` | Environment, GPU, driver, dependency, or model unavailable |
| `4` | Invalid project, source media, or input file |
| `5` | A prerequisite stage has not completed |
| `6` | Model load or inference failure |
| `7` | Review or project data failed validation |
| `8` | Media processing, TTS, or render failure |
| `10` | Partially complete; at least one work unit failed and can be retried |
| `130` | Interrupted by the user |

---

## 7. Dependency list

### Core CLI — `environments/core-rocm.txt`

Python 3.12 · `click==8.1.8` · `pydantic==2.10.6` · `ruamel.yaml==0.18.10` ·
`huggingface-hub==0.34.4` · `scenedetect==0.6.6` ·
`opencv-python-headless==4.10.0.84` · FFmpeg 6.1.x
(plus `pytest==8.3.4`, `hypothesis==6.124.7`, `ruff==0.9.4`, `mypy==1.14.1`
for development)

### Vision / ASR worker — `environments/vl-rocm.txt`

| Package | Version | Source |
| --- | --- | --- |
| `torch` | 2.10.0+rocm7.2.1 | `repo.radeon.com` wheel |
| `torchvision` | 0.25.0+rocm7.2.1 | `repo.radeon.com` wheel |
| `triton` | 3.6.0+rocm7.2.1 | `repo.radeon.com` wheel |
| `vllm` | 0.18.1 | source build, `gfx1100` |
| `torchcodec` | 0.10 | source build |
| `transformers` | 4.57.6 | PyPI |
| `accelerate` | 1.12.0 | PyPI |
| `amdsmi` | 7.0.2 | PyPI |
| `numpy` / `scipy` / `numba` | 2.2.2 / 1.18.0 / 0.61.2 | PyPI |
| `librosa` / `soundfile` / `soxr` | 0.11.0 / 0.14.0 / 1.1.0 | PyPI |
| `safetensors` / `huggingface-hub` | 0.8.0 / 0.34.4 | PyPI |
| `pillow` / `timm` | 11.1.0 / ≥1.0.17 | PyPI |
| `qwen-asr` | 0.0.6 | PyPI, `--no-deps` (`environments/vl-qwen-asr.txt`) |

### TTS worker — `environments/tts-omni-rocm.txt`

Same Torch 2.10.0 / Triton 3.6.0 / vLLM 0.18.1 ABI as above, plus
`torchaudio==2.10.0+rocm7.2.1`, `onnxruntime==1.28.0`, `einops==0.8.2`,
`omegaconf==2.3.0`, `scikit-learn==1.9.0`, `sox==1.5.0`, and `pyzmq==27.1.0`.
`vllm-omni==0.18.0` and the `qwen-tts==0.1.1` fallback are installed with
`--no-deps` from `environments/tts-runtime-no-deps.txt`, which deliberately
omits vLLM-Omni's diffusion, video, and UI extras.

Every ROCm wheel is pinned by URL **and** SHA-256 in the requirement files, so
an install either reproduces the verified stack byte for byte or fails. Refresh
the pins after dependency changes with
`./scripts/lock-environments.sh <core|asr|vl|tts|all>`.

---

## 8. Project layout

```
src/audiosight/       core CLI, pipeline, worker protocol
  worker_main.py      the only module that imports Torch/vLLM
docs/                 requirements, CLI design, architecture, ROCm notes
environments/         pinned ROCm requirement files and environment locks
scripts/              create-rocm-envs.sh, lock-environments.sh
tests/                deterministic unit and property tests
models/               downloaded snapshots + manifest.lock.json   (git-ignored)
work/<name>/          per-video project state                     (git-ignored)
outputs/              rendered soundtracks                        (git-ignored)
```

A project directory holds `project.yaml` (source fingerprint and settings),
`state.sqlite` (stage tracking, WAL mode), `analysis/` (transcript, shots,
segments, visual events, story state), `evidence/` (JPEG frames), `review/`
(editable narration YAML), `synthesis/` (cached TTS), and `render/` (reports,
previews, and the sample-accurate source↔output timeline map).

Model weights, generated projects, rendered audio, and source media are
intentionally git-ignored and must never be committed.

### Output format

48 kHz stereo, normalized to −18 LUFS with a −1.5 dBFS true-peak ceiling.
`.wav` produces `pcm_f32le`; `.m4a` or `.mp4` produces AAC at 192 kbit/s with
`+faststart`. The output is longer than the source because narration is inserted
rather than overlaid; `render/source_to_output.<language>.jsonl` maps between
the two timelines sample by sample.

---

## 9. Development

The core CLI is importable and testable without Torch, Transformers, ROCm, or
any Qwen package, so contract and media plumbing work needs no GPU and no model
weights:

```bash
AUDIOSIGHT_WORKER_MODE=fake PYTHONPATH=src python -m audiosight --help
```

Fake mode is rejected unless explicitly requested through the environment, and
every report it produces is stamped `synthetic_test_data: true` so it can never
be mistaken for model output.

Three quality gates must pass before submitting a change:

```bash
.venvs/audiosight-core/bin/pytest -q
.venvs/audiosight-core/bin/ruff check src tests
.venvs/audiosight-core/bin/mypy src/audiosight
```

Ruff enforces rules `E`, `F`, `I`, `UP`, `B`, `SIM` at a 100-character line
limit; mypy runs in strict mode. See [AudioSight/AGENTS.md](AudioSight/AGENTS.md)
for the full contribution conventions and architecture boundaries.

Further reading, all inside the source submodule:

- [AudioSight/docs/amd-devmaster-project-profile.md](AudioSight/docs/amd-devmaster-project-profile.md)
  — project profile, architecture rationale, ROCm benchmarks; submitted here as
  [AudioSight-Project-Profile.pdf](AudioSight-Project-Profile.pdf)
- [AudioSight/docs/architecture.md](AudioSight/docs/architecture.md) — operational gates and worker boundaries
- [AudioSight/docs/rocm.md](AudioSight/docs/rocm.md) — ROCm setup, kernel selection, measured results
- [AudioSight/docs/vllm-qwen3.5.md](AudioSight/docs/vllm-qwen3.5.md) — engine options, video-input parity, GPTQ constraints
- [AudioSight/docs/cli-commands.md](AudioSight/docs/cli-commands.md) — complete command specification
- [AudioSight/docs/requirements.md](AudioSight/docs/requirements.md) — product requirements

---

## 10. Troubleshooting

**`ROCm PyTorch is unavailable in <path>` (exit 3).** The bootstrap interpreter
does not have a working ROCm PyTorch. Check `/dev/kfd` and `/dev/dri`
permissions, then point `AUDIOSIGHT_ROCM_PYTHON` at the right interpreter.

**TorchCodec fails to import, or `VideoDecoder` raises an ABI error.** The
generic PyPI wheel was installed instead of the source build. Re-run
`./scripts/create-rocm-envs.sh`; it compiles TorchCodec against the ROCm Torch
ABI and the system FFmpeg libraries.

**vLLM build fails or the GPU is not gfx1100.** Export the correct
`PYTORCH_ROCM_ARCH` for your card before running the setup script. Lower
`MAX_JOBS` if the build runs out of memory.

**FlashAttention errors.** The verified ROCm base ships an unusable optional
CUDA `flash_attn` package that the bundled vLLM revision misdetects. AudioSight
guards that probe so vLLM selects its ROCm fallback. FlashAttention is not a
runtime requirement — if you still hit this, confirm you are running through the
project's worker entry point rather than invoking vLLM directly.

**`MODEL_OUT_OF_MEMORY` (exit 6).** Switch to `--profile portable-16gb` at
`init`, or lower `--asr-batch-size` and re-run the same command; completed work
is cached.

**Stage prerequisite errors (exit 5).** Commands never run their prerequisites
implicitly. Run the missing stage explicitly.

**`render` rejects a validation report.** The review file changed after
validation. Re-run `validate` for that language, then `render`.

**TTS reports `TTS_VLLM_OMNI_UNAVAILABLE`.** The experimental vLLM-Omni backend
failed and the qwen-tts fallback was used. This is recorded, never silent. To
choose the fallback up front, pass `--tts-backend qwen-tts` at `init`.

---

## License and acknowledgements

The Qwen3-ASR, Qwen3-ForcedAligner, Qwen3.5, and Qwen3-TTS models are used under
their respective Apache-2.0 licenses and are not redistributed with this
repository. AudioSight's own license has not yet been selected.

Thanks to **AMD** for the Radeon GPU resources and the ROCm software stack that
made this project possible, and for supporting accessibility work aimed at
people with visual impairments. Thanks to the Qwen team for releasing capable
multimodal models openly, and to the vLLM and PyTorch ROCm communities.
