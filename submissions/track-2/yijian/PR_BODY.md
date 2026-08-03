## Project

**YIJIAN: From Superhuman Go to Human Understanding** is a private, evidence-grounded AI Go coach for Track 2.

YIJIAN combines KataGo, deterministic Go-rule reconstruction, a server-authoritative teaching-evidence structure, Qwen3.6-27B and answer consistency validation. It explains not only which move is stronger, but why the move matters in terms of thickness, territory, initiative, shape, ko, timing and local fighting—while keeping engine facts separate from heuristic teaching language.

## AMD Radeon implementation

- AMD Radeon PRO W7900 48 GB
- Qwen3.6-27B Q4_K_M served by `llama.cpp` on ROCm 7.2.1
- KataGo v1.16.5 OpenCL with the official b40 network
- 32-visit whole-game scan and 128-visit critical-node verification
- GPU-aware scheduling and SQLite result caching

## Measured demo results

- 33 KataGo positions at 32 visits: 13.55 seconds total
- One 128-visit verification: 2.63 seconds
- Evidence-grounded coach acceptance: 6/6 constructed cases passed
- Coach acceptance latency: P95 9.536 seconds
- Automated regression tests: 373

## Materials

The submission folder contains the English README, project specification, performance report, demo runbook, presentation, PDF and a public-safe source snapshot.

The final 3–5 minute English demo link will be added before this pull request is marked ready for judging. The public package intentionally excludes private game records, creator-derived transcripts, review drafts, model weights, local databases and credentials.
