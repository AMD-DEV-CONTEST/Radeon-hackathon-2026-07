# RedactFlow AMD

## Track and team

- Track: Track 2 — Development & Local Deployment of Private AI Agents
- Team: N/A (individual entry)
- Application: RedactFlow AMD

## Summary

RedactFlow AMD is a local-first sensitive-document release agent. It retrieves
evidence from a private document vault, detects secrets and personal data,
builds an inspectable plan, pauses before consequential actions, and produces a
separate redacted release copy only after explicit approval. Decision metadata
is stored locally in SQLite without persisting raw secrets.

## Agent capabilities

- Local RAG over private documents
- Tool calling for retrieval, inspection, redaction, and audit memory
- Visible multi-step planning
- Local SQLite memory
- Explicit permission gates for transformation and persistent writes

## AMD Radeon and ROCm

The intended deployment runs Qwen2.5-7B-Instruct locally through a
ROCm-enabled llama.cpp server on AMD Radeon. The application rejects ordinary
public model endpoints for core inference. Environment probing and repeatable
benchmark scripts are included. Radeon performance figures will only be added
from an actual allocated Radeon Cloud run.

## Deliverables

- Source code and reproducibility guide: `RedactFlow-AMD/README.md`
- Project specification PDF: `RedactFlow-AMD/output/pdf/RedactFlow-AMD-Project-Report.pdf`
- Supplementary deck: `RedactFlow-AMD/output/presentation/RedactFlow-AMD-Pitch-Deck.pptx`
- Demo video: `RedactFlow-AMD/artifacts/RedactFlow-AMD-Demo.mp4`
- Tests: `RedactFlow-AMD/tests/`

## Local verification

- 7 automated tests pass.
- The permission-denied flow stops before redaction or audit writes.
- The approved flow redacts an email address, phone number, private IP address,
  and API key, then stores minimal audit metadata.
- No unmeasured Radeon benchmark result is claimed.
