# Demo video source

The English narration script is split into seven verified scenes in
`video/narration/`. The corresponding browser captures and generated audio are
local build inputs and are excluded from Git.

Build the reproducible 1080p fallback video with:

```bash
bash scripts/build_demo_video.sh
```

Output:

```text
output/video/track2_demo_1080p_ava.mp4
```

The scenes cover the product pitch, deterministic strategy pipeline, required
Agent capabilities, system architecture, measured AMD evidence, a real Open
WebUI result, and the final validation/backtest/risk verdict.
