# Submission Documentation

This directory contains reviewable sources for the SignalForge judge package.

## Artifacts

- `architecture.svg`: primary scalable architecture diagram.
- `architecture.png`: deterministic raster used by the project PDF.
- `project-specification.md`: human-reviewable project specification source.
- `demo-script.md`: verified 4 minute 12.9 second final cut sheet mapped to Track 2 evidence.
- `demo-voiceover.txt`: narration source used by the final local video artifact.
- `../output/pdf/SignalForge-Project-Specification.pdf`: final six-page project documentation.
- `../output/presentation/SignalForge-Judge-Deck.pptx`: final six-slide supplemental deck.
- `../output/video/SignalForge-Radeon-Demo.mp4`: final local H.264/AAC demo video.
- `../evidence/runs/sprint13/live-demo-capture.json`: safe capture, runtime, QA, and hash record.

## Rebuild The PDF

Install the isolated documentation dependency, then build:

```bash
python3 -m pip install -r requirements-docs.txt
python3 scripts/build_project_spec.py
```

The production application does not import ReportLab. Documentation dependencies remain separate
from the runtime and verification dependency path.

The committed PDF was visually inspected after rendering all six pages with Poppler. It contains
no private prompts, credentials, raw model responses, source bodies, or chain-of-thought.

The PowerPoint deck was rendered through the presentation QA toolchain, visually inspected slide
by slide, and passed the canvas-overflow gate. The Radeon demo lasts 252.9 seconds and contains a
real local run, source proof, a deterministic receipt, a governed follow-up, memory controls,
optimization evidence, and hardening evidence. The video and supporting judge artifacts were
downloaded from the public Sprint 13 pre-release without authentication and matched their local
hashes.
