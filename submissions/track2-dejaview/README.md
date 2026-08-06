# DejaView - Track 2 submission

**Team:** DeepSleep  
**Application:** DejaView  
**Track:** Track 2 - Development and Local Deployment of Private AI Agents  
**Source code:** [Aidenwu0209/localwork](https://github.com/Aidenwu0209/localwork)

DejaView is a private screen-memory agent. It turns screen activity that the user has permitted into a searchable timeline, answers questions with links to the supporting event or screenshot, and produces evidence-backed daily reports. A device-local privacy gate runs before OCR, storage, memory, or any Radeon request.

## Submission materials

| Requirement | Material |
| --- | --- |
| Project specification | [PDF](DejaView-Project-Specification.pdf), [Markdown](PROJECT_SPECIFICATION.md), and [editable DOCX](DejaView-Project-Specification.docx) |
| Complete source code | [Public source repository](https://github.com/Aidenwu0209/localwork) at commit [`d0582e9`](https://github.com/Aidenwu0209/localwork/commit/d0582e9) |
| Environment and reproduction guide | [English README](https://github.com/Aidenwu0209/localwork#readme) and [Radeon Cloud quick start](https://github.com/Aidenwu0209/localwork/blob/main/docs/Radeon-Cloud-QUICKSTART.md) |
| Demo video | [3:15 English demo](dejaview-demo-en.mp4) and [English captions](dejaview-demo-en.srt) |
| Supplementary material | [Editable presentation](DejaView-Track2-Presentation.pptx) |
| Radeon/ROCm evidence | [Benchmark report](https://github.com/Aidenwu0209/localwork/blob/main/docs/benchmarks.md) and [checksummed evidence](https://github.com/Aidenwu0209/localwork/tree/main/docs/benchmark-evidence/p31/p31-w7900d-20260728T075653Z) |

## What the demo shows

The demo uses synthetic screen data and walks through the complete product flow: capture, privacy blocking, evidence-backed recall, Honcho memory, a Radeon-powered daily-report agent, and a verified fallback after the Radeon compute link is disconnected. It does not include private user data or temporary Radeon Cloud credentials.

## Track 2 capabilities

DejaView implements all five capabilities listed in the Track 2 rules:

- local retrieval over timeline events and screenshots;
- tool invocation for search, evidence lookup, memory, and report generation;
- multi-step task planning and workflow orchestration;
- local multi-turn memory through Honcho;
- explicit privacy gates, permission checks, and audit records.

Core AMD inference runs on a Radeon PRO W7900D through ROCm 7.2.1 and a HIP-enabled llama.cpp build for `gfx1100`. The measured optimization campaign compares quantization, MTP, concurrency, and server-slot settings. Representative results include 23.9 tokens/s for the Q6_K brain model at concurrency 1, 41.6 tokens/s with MTP enabled in the same cell, and 50.0 aggregate tokens/s for the tested perception configuration. Full measurements, hashes, and limitations are included in the linked benchmark report.

## License

The project code and documentation are released under Apache-2.0. Model weights retain their upstream licenses. See the source repository's [LICENSE](https://github.com/Aidenwu0209/localwork/blob/main/LICENSE), [NOTICE](https://github.com/Aidenwu0209/localwork/blob/main/NOTICE), and [third-party license notes](https://github.com/Aidenwu0209/localwork/blob/main/docs/licenses.md).
