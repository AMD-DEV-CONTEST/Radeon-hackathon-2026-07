# Track 1 Submission Note

This document is the English submission companion for the 2026 AMD AI DevMaster Hackathon Track 1 entry: **Video Voice Translator**.

## Suggested Pull Request Title

Use the official format:

```text
Track 1, <Team Name or Your Name>, Video Voice Translator
```

## Submission Package Checklist

The repository is prepared to include the following materials:

1. **Project Source Code**
   - Canonical repository: <https://github.com/icuic/video-voice-translator>
   - Submission branch: `amd-track1-video-voice-translator`
   - Evaluated commit: `ad5ed6c`
   - Repository README: <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/README.md>
   - Supporting documentation under this submission folder and the source repository `docs/`

2. **Project Profile Document (PDF)**
   - Generated file: `submissions/track1-video-voice-translator/track1-project-profile.pdf`
   - Source markdown: `submissions/track1-video-voice-translator/PROJECT_PROFILE.md`

3. **Demo Video**
   - Bundled artifact (PR-local): `submissions/track1-video-voice-translator/demo.mp4`
   - Canonical repository mirror: <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/data/demo/demo.mp4>
   - Guide: `submissions/track1-video-voice-translator/DEMO_VIDEO.md`

4. **Supplementary Material**
   - Poster artifact: `submissions/track1-video-voice-translator/track1-poster.svg`

## What the Project Demonstrates

Video Voice Translator is a multimodal content creation tool that:

- takes a source video or audio file,
- recognizes speech content,
- translates the transcript between English and Chinese,
- clones the original speaking style with IndexTTS2,
- and renders a dubbed output video for content localization.

## How Evaluators Can Review the Project

### Option A: Watch the demo first

Play the bundled video inside this submission folder:

- `submissions/track1-video-voice-translator/demo.mp4`

Or open the canonical repository mirror:

- <https://github.com/icuic/video-voice-translator/blob/amd-track1-video-voice-translator/data/demo/demo.mp4>

### Option B: Reproduce locally

1. Install dependencies:

   ```bash
   ./install_all.sh
   ```

   Source repository:

   ```text
   https://github.com/icuic/video-voice-translator
   ```

2. Configure `.env` with a valid translation API key.

3. Start the demo stack:

   ```bash
   ./service.sh up
   ```

4. Open the frontend:

   ```text
   http://127.0.0.1:5173
   ```

5. Upload a short English video and run `English -> Chinese`.

## Main Technical Highlights

- Frontend/backend split architecture for a cleaner demo experience
- Task persistence for replaying completed results from history
- Progress reporting across extraction, ASR, translation, voice cloning, and final synthesis
- AMD/ROCm-oriented runtime tuning
- Practical scripts for installation, startup, and service management

## AMD Radeon / ROCm Notes

- Native `whisper` is the default ASR backend in this branch for better ROCm compatibility.
- ROCm PyTorch installation is handled by the install script on AMD cloud environments.
- `IndexTTS2` keeps FP16 enabled while disabling CUDA-only kernels that are not suitable for ROCm.

## Known Constraints

- The strongest demo path is short-form single-speaker content.
- Reverse-proxy deployments may need additional tuning for very long uploads.
- Multi-speaker processing exists but is not the main evaluation path for this submission.
