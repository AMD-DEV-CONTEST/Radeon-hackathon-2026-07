# Submission Documentation

This directory contains reviewable sources for the SignalForge judge package.

Judges should begin with the concise [`JUDGES.md`](../JUDGES.md) route and use
[`track2-compliance.md`](track2-compliance.md) to map every official Track 2 requirement to
evidence.

## Artifacts

- `architecture.svg`: primary scalable architecture diagram.
- `architecture.png`: deterministic raster used by the project PDF.
- `project-specification.md`: human-reviewable six-page championship project specification source.
- `demo-script.md`: verified 4 minute 44.9 second final cut sheet mapped to Track 2 evidence.
- `demo-voiceover.txt`: narration source used by the final local video artifact.
- `financial-intelligence.md`: current financial-intelligence architecture, numerical authority,
  CPU verification, and remaining Radeon evidence gates.
- `hybrid-vllm-specialists.md`: optional organizer-provided vLLM specialist path, runtime
  configuration, secret handling, fallback, and proof requirements.
- `track2-compliance.md`: official Track 2 requirement, submission, scoring, rights, and artifact
  integrity matrix.
- `../output/pdf/SignalForge-Project-Specification.pdf`: final six-page project documentation.
- `../output/presentation/SignalForge-Judge-Deck.pptx`: final six-slide supplemental deck.
- `../output/video/SignalForge-Radeon-Demo.mp4`: final local H.264/AAC demo video.
- `../evidence/sprint36-radeon-demo-journey.json`: privacy-safe current Radeon demo journey.
- `../evidence/sprint36-radeon-resilience.json`: current API-loss and model-loss behavior.

## Rebuild The PDF

Install the isolated documentation dependency, then build:

```bash
python3 -m pip install -r requirements-docs.txt
python3 scripts/build_project_spec.py
```

The production application does not import ReportLab. Documentation dependencies remain separate
from the runtime and verification dependency path.

The committed PDF and deck document the current championship capability boundary while retaining
clearly labeled historical golden-run and optimization evidence. The PDF was visually inspected
after rendering all six pages with Poppler. It contains
no private prompts, credentials, raw model responses, source bodies, or chain-of-thought.

The PowerPoint deck was rendered through the presentation QA toolchain, visually inspected slide
by slide, passed template-fidelity validation, and passed the canvas-overflow gate. The 284.970
second Radeon demo combines only current privacy-safe captures from a real accepted hybrid journey,
its deterministic receipts, correlated Mission Control view, bounded optimization evidence, and
tested failure behavior. The public artifact identities are recorded in
[`judge-package.json`](../evidence/judge-package.json). Historical Sprint 34 artifacts and
[`sprint34-release-attestation.json`](../evidence/sprint34-release-attestation.json) remain
immutable and explicitly historical.
