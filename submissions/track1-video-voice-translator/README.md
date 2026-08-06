# Video Voice Translator — Track 1 Submission

This folder contains the full English submission materials for the 2026 AMD AI DevMaster Hackathon, Track 1:

**Video Voice Translator** — A multimodal tool that dubs video content between English and Chinese while preserving the original speaker voice, with an AMD/ROCm-optimized execution path and a practical Web UI for evaluation.

---

## 1. Quick Facts for Evaluators

| Item | Value |
|---|---|
| Canonical repository | [icuic/video-voice-translator](https://github.com/icuic/video-voice-translator) · [branch `amd-track1-video-voice-translator`](https://github.com/icuic/video-voice-translator/tree/amd-track1-video-voice-translator) · [evaluated snapshot `234f231`](https://github.com/icuic/video-voice-translator/tree/234f231) |
| Submission branch | [`amd-track1-video-voice-translator`](https://github.com/icuic/video-voice-translator/tree/amd-track1-video-voice-translator) |
| Evaluated commit | [`234f231`](https://github.com/icuic/video-voice-translator/tree/234f231) |
| Source repo README (install + run) | <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md> |
| Languages | English ↔ Chinese |
| Main demo path | Short-form single-speaker content |

## 2. Submission Package Checklist

All four Track 1 mandated artifacts are present in this pull request. Source links always resolve to the evaluated commit above.

### 2.1 Project Source Code

- Canonical repository: <https://github.com/icuic/video-voice-translator>
  - Branch view: [amd-track1-video-voice-translator](https://github.com/icuic/video-voice-translator/tree/amd-track1-video-voice-translator)
  - Evaluated snapshot: [234f231](https://github.com/icuic/video-voice-translator/tree/234f231)
- Branch / commit: [amd-track1-video-voice-translator](https://github.com/icuic/video-voice-translator/tree/amd-track1-video-voice-translator) @ [234f231](https://github.com/icuic/video-voice-translator/tree/234f231)
- README with installation & run instructions (live, up-to-date, English):
  <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md>
- Supporting technical docs (in the source repo):
  - `docs/INSTALL.md` — <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/docs/INSTALL.md>
  - `docs/USAGE.md` — <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/docs/USAGE.md>
  - `docs/DEMO.md` — <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/docs/DEMO.md>

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
- Submission package (browse online in fork): [`submissions/track1-video-voice-translator/`](https://github.com/icuic/Radeon-hackathon-2026-07/tree/track1-icuic-video-voice-translator/submissions/track1-video-voice-translator) (branch `track1-icuic-video-voice-translator` @ `53c0542`)

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

Refer to `PROJECT_PROFILE.md` for the full architecture diagram and model list. In short:

1. Audio extraction & vocal separation (FFmpeg + Demucs on CPU)
2. Whisper ASR → segment SRT with segment-level speaker hints
3. LLM translator on AMD ROCm-ready OpenAI-compatible endpoint → bilingual segment pairs with retry + length matching
4. Speaker voice cloning via IndexTTS2 → per-segment TTS audio in the target language
5. FFmpeg re-synthesis with vocal stem mixing → synchronized dubbed output video

## 5. Evaluator Quick Start (Recommended order)

1. **Open the bundled demo** — [`demo.mp4`](demo.mp4) to confirm the end-to-end flow visually.
2. **Browse the submission package online** — open [https://github.com/icuic/Radeon-hackathon-2026-07/tree/track1-icuic-video-voice-translator/submissions/track1-video-voice-translator](https://github.com/icuic/Radeon-hackathon-2026-07/tree/track1-icuic-video-voice-translator/submissions/track1-video-voice-translator) to inspect all four mandated artifacts in one browser view.
3. **Inspect the evaluated code snapshot** — [https://github.com/icuic/video-voice-translator/tree/234f231](https://github.com/icuic/video-voice-translator/tree/234f231) (`tree/234f231`) to review a stable, immutable snapshot of the source.
4. **Clone and reproduce locally** (if hardware is available):

```bash
git clone https://github.com/icuic/video-voice-translator.git
cd video-voice-translator
git checkout amd-track1-video-voice-translator
git reset --hard 234f231

./install_all.sh
# edit .env with a valid LLM endpoint + key, then:
./service.sh up
# open http://127.0.0.1:5173
```

5. **Browse the source README** — <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md> for install/run details and the canonical docs folder.

## 6. AMD / ROCm Readiness Highlights

- PyTorch + ROCm install path (see `README.md` §ROCm prerequisites) is bundled in the one-click `install_all.sh` script on the evaluated branch.
- ASR (Whisper), TTS (IndexTTS2), and Audio/Music separation (Demucs) all default to `device=cuda`/RocTorch; CPU fallback is also available for evaluators without an AMD GPU.
- Media pipeline uses `FFmpeg 7.x` for robust stream handling and frame-accurate re-synchronization.
- LLM step uses an AMD Radeon Token Factory backed **DeepSeek-V4-Flash (OpenAI-compatible)** endpoint; the UI explicitly selects this model during inference.

## 7. Reproducibility Guarantees

The evaluated commit `234f231` on branch `amd-track1-video-voice-translator` is the canonical code snapshot used during judge evaluation. The poster, profile PDF, and README are also part of the fork PR package so judges can review everything in a single PR without jumping between repositories.

- **Source repo home**: <https://github.com/icuic/video-voice-translator>
- **Submission branch (browse)**: [amd-track1-video-voice-translator](https://github.com/icuic/video-voice-translator/tree/amd-track1-video-voice-translator)
- **Evaluated snapshot (browse, immutable)**: [234f231](https://github.com/icuic/video-voice-translator/tree/234f231)
- **Fork submission package (browse)**: [https://github.com/icuic/Radeon-hackathon-2026-07/tree/track1-icuic-video-voice-translator/submissions/track1-video-voice-translator](https://github.com/icuic/Radeon-hackathon-2026-07/tree/track1-icuic-video-voice-translator/submissions/track1-video-voice-translator)
