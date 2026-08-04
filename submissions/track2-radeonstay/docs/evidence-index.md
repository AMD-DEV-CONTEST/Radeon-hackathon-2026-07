# Evidence Index

> Status values remain `PENDING` until the corresponding artifact has been
> generated on the target Radeon system.

| Scoring requirement | Evidence | Status |
| --- | --- | --- |
| Clear hotel scenario | README + project specification | READY |
| RAG with citations | Source + 8-case retrieval JSON + demo timestamp | PENDING RUN |
| Typed tools and planning | Source + tests + 30-case Agent quality JSON | PENDING RUN |
| Multi-turn memory | Agent quality JSON + consent/forget traces | PENDING RUN |
| Permission/privacy | Agent quality JSON + attack denial traces | PENDING RUN |
| Radeon local inference | Same-run-ID ROCm evidence, server log, binding manifest, video | PENDING HARDWARE |
| Directed optimization | Quality-gated baseline/optimized JSON + same-run-ID ROCm monitor logs | PENDING HARDWARE |
| Stable interaction | Five distinct complete run IDs; every quality/benchmark gate passes | PENDING RUN |
| Project PDF | `docs/project-specification.pdf` | PENDING EXPORT |
| Poster/PPT | `docs/poster.pdf` or deck | PENDING |
| Demo video | Public 3–5 minute URL/file | PENDING |

“Five-run” means five fresh model-service lifecycles on the same pinned commit,
model hash, llama-server hash and Radeon host. Each run keeps its own quality
JSON, benchmark JSON, monitor log, server log and complete binding manifest;
stability passes only when all five report zero hard failures, 30/30 completed
quality cases and a 100% benchmark success rate. No averaging may hide a failed run.
