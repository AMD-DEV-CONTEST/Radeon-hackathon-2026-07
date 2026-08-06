# Video Voice Translator — Track 1 Submission

This folder contains the full English submission materials for the 2026 AMD AI DevMaster Hackathon, Track 1:

**Video Voice Translator** — A multimodal tool that dubs video content between English and Chinese while preserving the original speaker voice, with an AMD/ROCm-optimized execution path and a practical Web UI for evaluation.

---

## 1. Quick Facts for Evaluators

| Item | Value |
|---|---|
| Canonical repository | <https://github.com/icuic/video-voice-translator> |
| Submission branch | `amd-track1-video-voice-translator` |
| Evaluated commit | `5881233` |
| Source repo README | <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md> |
| Languages | English ↔ Chinese |
| Main demo path | Short-form single-speaker content |

## 2. Submission Package Checklist

All four Track 1 mandated artifacts are present in this pull request. Source links always resolve to the evaluated commit above.

### 2.1 Project Source Code

- Canonical repository: <https://github.com/icuic/video-voice-translator>
- Branch / commit: `amd-track1-video-voice-translator` @ `5881233`
- README with installation & run instructions (live, up-to-date, English):
  <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md>
- Supporting technical docs (in the source repo):
  - `docs/INSTALL.md`
  - `docs/USAGE.md`
  - `docs/DEMO.md`

### 2.2 Project Profile Document (PDF)

- Final PDF artifact: [`track1-project-profile.pdf`](track1-project-profile.pdf)
- Maintainable markdown source: [`PROJECT_PROFILE.md`](PROJECT_PROFILE.md)

### 2.3 Demo Video (required, 3–5 min)

- **Bundled playback in this PR (recommended)**: [`demo.mp4`](demo.mp4)
- Canonical mirror in the source repository:
  <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/data/demo/demo.mp4>
- Specs: 1920x1080 MP4, ~242 seconds (~4:02), ~16.4 MB, ~568 kbps average
- Covers: upload flow → live pipeline progress → history task reopen → original vs dubbed playback → bilingual segment editing.

### 2.4 Supplementary Material (one of PPT / Poster)

- Submitted poster: [`track1-poster.svg`](track1-poster.svg)

## 3. What the Project Demonstrates

Video Voice Translator is a multimodal content creation tool that, given a source video or audio file:

1. Extracts and normalizes audio, then separates vocals from background music.
2. Performs speech recognition with per-segment timestamps.
3. Translates the transcript between English and Chinese with retry logic.
4. Extracts a short speaker reference and clones the speaking style via IndexTTS2.
5. Merges the translated speech back on the original timeline, preserving background music.
6. Re-renders a fully dubbed output video with synchronized audio.

Additional demo-friendly features that are visible during evaluation:

- **Persistence & history replay** — completed tasks are persisted under `data/task_states/`, so evaluators can reopen finished jobs from the history panel without re-uploading.
- **Granular progress reporting** — step names, counters (e.g. "translating segment 3/10"), and real-time progress for ASR (by audio duration) and final FFmpeg synthesis are exposed in the Web UI.
- **Bilingual segment editor** — segments can be edited, previewed, and re-dubbed in the result page, making corrections or demo tweaks straightforward.

## 4. End-to-End Pipeline

The system follows a nine-step media translation pipeline (visible in the progress bar during the demo):

1. Audio extraction and media normalization
2. Vocal / background separation
3. Optional speaker diarization
4. Automatic speech recognition
5. Batch text translation
6. Speaker reference audio extraction
7. Voice cloning (IndexTTS2, segment-by-segment)
8. Timeline-aware audio merging (music + dubbed speech)
9. Final video synthesis with FFmpeg

All steps report structured progress (`step_name / message / detail`) back to the frontend so long-running jobs stay transparent during judging.

## 5. AMD Radeon / ROCm Adaptation

This submission was specifically tuned for execution on AMD GPUs:

- **ASR backend**: `whisper` (native) is used by default because it is more reliable on ROCm than `faster-whisper` in our demo environment.
- **IndexTTS2 tuning**: keeps `use_fp16: true` for speed on AMD devices, but explicitly disables `use_cuda_kernel` to avoid NVIDIA-only kernels that do not behave correctly on ROCm.
- **Environment setup**: the included `./install_all.sh` script installs system packages, IndexTTS2, the backend/frontend dependencies, and attempts to install or repair ROCm-aware PyTorch automatically when running on an AMD cloud machine.
- **Isolated long-running jobs**: the demo stack uses a FastAPI backend, a React frontend, and a dedicated worker process so translations run out-of-process from the web server. This is especially helpful on ROCm setups where heavy native loads should not block the frontend.

## 6. Recommended Review Order (5 minutes)

1. **Play the bundled video first** — [`demo.mp4`](demo.mp4). It walks through the complete judging flow on an AMD environment.
2. **Skim the Project Profile PDF** — [`track1-project-profile.pdf`](track1-project-profile.pdf), for background, architecture, and AMD-specific points.
3. **Open the poster** — [`track1-poster.svg`](track1-poster.svg), for the one-page overview.
4. **Reproduce locally (optional)** — follow §7 below; the evaluated commit is `5881233` in branch `amd-track1-video-voice-translator` of the source repo.
5. **Browse the source README** — <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md> for install/run details and the canonical docs folder.

## 7. How to Reproduce Locally

These are the minimal reproduction steps; the source README has additional detail.

### 7.1 Get the code at the evaluated commit

```bash
git clone https://github.com/icuic/video-voice-translator.git
cd video-voice-translator
git checkout amd-track1-video-voice-translator
git reset --hard 5881233
```

### 7.2 Install everything

```bash
./install_all.sh
```

This installs system packages, IndexTTS2, backend Python deps, frontend Node deps, and prepares `.env` from `.env.example`.

### 7.3 Configure the translation model

Edit `.env` in the project root:

```dotenv
LLM_BASE_URL=https://developer.amd.com.cn/radeon/api/v1
LLM_API_KEY=<your-key>
LLM_MODEL=qwen2.5-72b-instruct
```

Any OpenAI-compatible endpoint works; the AMD Radeon developer endpoint is the recommended default for the contest.

### 7.4 Start the demo stack

```bash
./service.sh up
```

This brings up:

- Backend API (FastAPI) on <http://127.0.0.1:8000>
- Frontend Web UI (Vite) on <http://127.0.0.1:5173>
- Dedicated worker process that executes the translation pipeline out-of-process

### 7.5 Run a job

1. Open <http://127.0.0.1:5173>
2. Upload a short English video (1–3 minutes, single speaker is the main evaluation path)
3. Source = English, Target = Chinese
4. Click "Start Translation" and watch the live progress bar
5. Once complete, play Original vs Dubbed and edit segments if desired
6. Completed jobs survive a service restart in the history panel (persisted to `data/task_states/`)

### 7.6 Remote / cloud evaluation tip

If evaluating on a remote AMD instance, SSH port forwarding is the simplest reliable path:

```bash
ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 user@<amd-instance>
```

Then open <http://127.0.0.1:5173> locally.

## 8. Known Constraints (for evaluator awareness)

- The strongest / most stable demo path is **short-form single-speaker content**.
- Reverse-proxy deployments may need tuning for very large uploads; the SSH port-forwarding path above is the most reproducible.
- Multi-speaker diarization exists in the pipeline but is not the primary evaluation path for this submission.

## 9. Contacts

- Team / author: icuic
- Source repo: <https://github.com/icuic/video-voice-translator>
- Submission branch: `amd-track1-video-voice-translator`
