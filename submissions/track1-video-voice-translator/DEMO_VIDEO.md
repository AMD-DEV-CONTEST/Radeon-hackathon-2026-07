# Demo Video

The final competition demo video is bundled **inside this submission folder** so evaluators can play it offline without leaving the PR:

- Local artifact: [`demo.mp4`](demo.mp4)
- Mirror in canonical source repo: [`data/demo/demo.mp4`](https://github.com/icuic/video-voice-translator/blob/repro-bd6d3e22/data/demo/demo.mp4)
- Submission branch: `repro-bd6d3e22`
- Submission commit: `ad5ed6c`

## File Summary

| Property | Value |
| --- | --- |
| Container / codec | MP4 (H.264 + AAC) |
| Duration | ~242 seconds (~4:02) |
| Resolution | 1920 x 1080 |
| File size | ~16.4 MB |
| Average bitrate | ~568 kbps |

## What the Demo Shows

According to the contest requirement, the recording demonstrates the complete evaluation path:

1. **Environment overview** — AMD/ROCm demo stack (FastAPI backend, React frontend, isolated worker) running end-to-end.
2. **Web UI upload flow** — open the upload page, pick a source video, configure source/target languages, and submit the translation job.
3. **Live pipeline progress** — real-time step reporting across audio extraction, vocal separation, ASR, text translation, voice cloning, audio merging, and final video synthesis.
4. **History & result replay** — completed jobs are persisted and reopened from the history sidebar; evaluators can switch between the original and dubbed playback and inspect segments.
5. **Output quality inspection** — final dubbed video playback inside the editor, showing speaker-preserved cloned speech, synchronized timeline, and bilingual transcript editing.

## Recommended Review Order

1. Play the bundled [`demo.mp4`](demo.mp4) to get the full 4-minute workflow.
2. Follow the reproduction steps in [`PROJECT_README.md`](PROJECT_README.md) if you want to rerun the pipeline locally.
3. Cross-check the output samples shown in the video against the persisted history tasks under `data/task_states/` and `data/outputs/` when reproducing.

## Repository References

- Source repository: <https://github.com/icuic/video-voice-translator>
- Canonical demo path inside the source repo: `data/demo/demo.mp4`

