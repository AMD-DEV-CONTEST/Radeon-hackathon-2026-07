# Video Voice Translator

Submission repository note:

- Canonical source repository: <https://github.com/icuic/video-voice-translator>
- Submission branch: `amd-track1-video-voice-translator`
- Evaluated commit: `ad5ed6c`

Video Voice Translator is an AI-powered multimodal content creation tool for Track 1 of the 2026 AMD AI DevMaster Hackathon. It translates video or audio content between English and Chinese, preserves the original speaker style through voice cloning, and produces a dubbed output video with synchronized audio.

This project is designed to run on AMD Radeon / ROCm environments while keeping a practical web workflow for demos and judging. The repository contains both a web interface and a command-line pipeline so evaluators can reproduce the workflow from setup to final output.

## Demo Video

A final competition recording is bundled in the submission package, and mirrored into the canonical repository so links work from both locations:

- Local demo artifact: [data/demo/demo.mp4](data/demo/demo.mp4)
- Submission package copy: `submissions/track1-video-voice-translator/demo.mp4`
- Demo guide (submission package): [`submissions/track1-video-voice-translator/DEMO_VIDEO.md`](submissions/track1-video-voice-translator/DEMO_VIDEO.md)
- Summary: 1920x1080 MP4, ~4:02, ~16.4 MB, covers upload → pipeline progress → history replay → dubbed playback.

Recommended review path: open the demo video first, then follow the reproduction steps in this document.

## Key Capabilities

- Upload and translate video or audio files in a Web UI
- Translate between English and Chinese
- Perform speech recognition with timestamped segments
- Run LLM-based text translation with retry logic
- Clone the speaker voice with IndexTTS2
- Merge translated speech back into the source video
- Resume or replay completed tasks from translation history
- Inspect progress from extraction to final rendering

## End-to-End Pipeline

The system follows a nine-step media translation pipeline:

1. Audio extraction and media normalization
2. Vocal separation from background music
3. Optional speaker diarization
4. Automatic speech recognition
5. Batch text translation
6. Reference audio extraction
7. Voice cloning for translated segments
8. Timeline-aware audio merging
9. Final video synthesis

## AMD Radeon / ROCm Adaptation

This project was tuned with AMD GPU execution in mind:

- The default ASR backend is native `whisper`, which works better on ROCm than `faster-whisper` in this branch.
- `IndexTTS2` keeps `use_fp16: true` for performance, while `use_cuda_kernel: false` avoids NVIDIA-only kernels in ROCm environments.
- Startup scripts attempt to install or repair ROCm PyTorch automatically on AMD cloud instances.
- The demo workflow uses a FastAPI backend, React frontend, and a dedicated worker process to keep long-running translation jobs isolated and more stable.

## System Architecture

- **Frontend**: React + TypeScript + Vite
- **Backend API**: FastAPI
- **Worker**: asynchronous translation job executor
- **Media stack**: FFmpeg
- **ASR**: Whisper / Faster-Whisper
- **Translation**: Qwen-compatible LLM endpoint
- **Voice cloning**: IndexTTS2

## Supported Languages

- English
- Chinese

## Quick Start

### 1. Install dependencies

Recommended:

```bash
./install_all.sh
```

This script installs system packages, IndexTTS2, project dependencies, frontend dependencies, and prepares the `.env` file from `.env.example`.

### 2. Configure the translation model

Edit `.env` in the project root:

```dotenv
LLM_BASE_URL=https://developer.amd.com.cn/radeon/api/v1
LLM_MODEL=DeepSeek-V4-Flash
LLM_API_KEY=your-api-key-here
LLM_TIMEOUT=300.0
```

### 3. Start the split frontend/backend demo stack

```bash
./service.sh up
```

Default endpoints:

- Frontend: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`

Useful service commands:

```bash
./service.sh status
./service.sh restart
./service.sh logs
./service.sh down
```

### 4. Run a demo translation

In the Web UI:

1. Upload a short English video
2. Select `English -> Chinese`
3. Start translation
4. Review the generated dubbed result
5. Reopen the task later from **History Tasks**

## CLI Usage

```bash
./run_cli.sh input.mp4 --source-lang en --target-lang zh --single-speaker
```

Additional examples are available in [docs/USAGE.md](docs/USAGE.md).

## Reproducibility Notes

- Keep the translation API key in `.env`; do not commit secrets.
- Use `./service.sh up` for the most reliable demo path.
- If the environment is remote, SSH port forwarding is recommended for local access during evaluation.
- Completed jobs are persisted under `data/task_states/` and outputs are written to `data/outputs/`.

## Submission Package

All contest-oriented materials are grouped under [submission/](submission/README.md):

- Submission index: [submission/README.md](submission/README.md)
- Submission note: [submission/SUBMISSION_NOTE.md](submission/SUBMISSION_NOTE.md)
- Project profile source: [submission/PROJECT_PROFILE.md](submission/PROJECT_PROFILE.md)
- Project profile PDF: [submission/track1-project-profile.pdf](submission/track1-project-profile.pdf)
- Poster: [submission/track1-poster.svg](submission/track1-poster.svg)
- Demo video guide: [submission/DEMO_VIDEO.md](submission/DEMO_VIDEO.md)

## Repository Guide

- Installation guide: [docs/INSTALL.md](docs/INSTALL.md)
- Usage guide: [docs/USAGE.md](docs/USAGE.md)
- Demo guide: [docs/DEMO.md](docs/DEMO.md)
- English backup README: [README_EN.md](README_EN.md)

## Known Limitations

- Multi-speaker diarization is available but not the recommended path for the current demo branch.
- Very long uploads through reverse proxies may hit timeout limits if the deployment layer is not tuned.
- The judging demo is optimized for short-form videos that clearly show the translation and dubbing workflow.
