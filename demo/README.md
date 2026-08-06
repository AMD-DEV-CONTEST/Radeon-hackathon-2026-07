# Demo package

`Local-Incident-Commander-demo.mp4` is the submission-ready product demo.

- Duration: 00:03:55.92
- Resolution: 1600x900, 16:9, 25 fps
- Video: H.264 High, yuv420p
- Audio: AAC-LC, 44.1 kHz mono
- Subtitles: English subtitles are burned into the MP4; the editable SRT is also included
- Live provenance: `00:22.44-01:48.20` is a sanitized Radeon Cloud session captured on 2026-08-06. It shows the Radeon/ROCm runtime, the local vLLM model endpoint, `mode=local-radeon`, and the complete Agent workflow.
- Fallback provenance: the later deterministic fallback segment is visibly labelled as degraded recovery; it is not presented as GPU inference.
- Benchmark provenance: the throughput card uses committed model-level evidence captured on 2026-07-30 (`39.35 tok/s`, approximately `2.5x` the compiled configuration for this workload).

## Source materials

- `capture_demo.mjs`: Playwright capture script using system Chrome and the real app
- `../scripts/run-demo-workflow.py`: repeatable live workflow recorder; it refuses to run unless `/api/health` reports `local-radeon`
- `render_final_video.sh`: reproducible assembly and subtitle burn-in command
- `make_subtitles.py`: sentence-timed subtitle generator
- `DEMO_SUBTITLES.srt`: subtitle source
- `../docs/architecture.png`: architecture export used by the closing card
- `../benchmarks/radeon-qwen3-8b-awq-8k*.json`: public-safe benchmark evidence shown in the video
- `stills/`: representative interaction captures for review
- `qa/final-live/`: representative final encoded frames used for cut, subtitle, and privacy QA

`demo-narration.aiff`, `ui-capture.webm`, reconstructed CDP frames, and other
intermediate assets are local production inputs and are intentionally excluded
from the official submission commit.

The video does not show account UI, API keys, cookies, email addresses, serials,
or any infrastructure command execution. Proposed actions are simulation-only and
the recorded degraded state is intentional and visible in the operator console.
