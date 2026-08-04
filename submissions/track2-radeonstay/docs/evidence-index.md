# Evidence Index

> A static `READY` status means only that the referenced source/document exists.
> Target execution, performance, and deliverable statuses remain `PENDING` until
> the named artifact is generated and reviewed; this index contains no
> placeholder benchmark number or inferred GPU claim.

| Scoring requirement | Evidence | Status |
| --- | --- | --- |
| Clear hotel scenario | README + project specification | READY |
| Agent architecture and multi-turn flow | Architecture + confirmation sequence in project specification | READY |
| Pinned model/binary provenance | README + third-party notices; revision/hash verification procedure | READY DOCUMENTATION |
| C2 immutable binding freeze | Full commit; clean project; tree/source/corpus/suite/model/binary hashes | PENDING FREEZE |
| RAG with citations | Source + 8-case retrieval JSON + demo timestamp | PENDING RUN |
| Typed tools and planning | Source + tests + 30-case Agent quality JSON | PENDING RUN |
| Multi-turn memory | Agent quality JSON + consent/forget traces | PENDING RUN |
| Permission/privacy | Agent quality JSON + attack denial traces | PENDING RUN |
| One complete C3 lifecycle | Retrieval/quality/benchmark artifacts + controlled process shutdown + complete evidence bundle under one run ID | PENDING RUN |
| Radeon local inference | Same-run-ID ROCm evidence, server log, binding manifest, video | PENDING HARDWARE |
| Directed optimization | Quality-gated baseline/optimized JSON + same-run-ID ROCm monitor logs | PENDING HARDWARE |
| Stable interaction | Five distinct complete run IDs; every quality/benchmark gate passes | PENDING RUN |
| Project PDF | `docs/project-specification.pdf` | PENDING EXPORT |
| Poster/PPT | `docs/poster.pdf` or deck | PENDING |
| Demo video | Public 3–5 minute URL/file | PENDING |

`C2` is the immutable input freeze; `C3` is one fresh end-to-end target
lifecycle after that freeze. A valid C3 run starts a new model process and ROCm
monitor, executes retrieval, 30-case quality, and benchmark windows under one
run ID, captures bound live evidence, shuts both children down in a controlled
way, and then creates the final binding bundle. The live and final collection
phases are both required. No C2 or C3 status is claimed above before those
artifacts exist.

“Five-run” means five fresh C3 model-service lifecycles using one accepted final
configuration on the same pinned commit/project tree/source, corpus and suite,
model hash, `llama-server` hash, alias, context, thinking/flash settings,
GPU-layer request, batch/micro-batch, parallel slots, benchmark workload and
Radeon hardware fingerprint. These are not the differently configured A–E
tuning rows. Each run keeps its own retrieval JSON, quality JSON, benchmark JSON,
`llama-server` log, ROCm monitor log, live evidence file, orchestration status,
complete binding manifest and bundle checksum. Stability passes only when all
five report zero hard failures, 30/30 completed quality cases, a 100% benchmark
success rate, complete lifecycle markers and active same-GPU evidence. No
averaging, rerun under the same ID, or selective omission may hide a failed run.

## Final evidence register

Replace `PENDING` only after checking the artifact and its binding manifest:

| Final field | Bound value / artifact |
|---|---|
| C2 source commit, project tree and source hash | PENDING |
| Policy corpus and `30-case-p0-v3` suite hashes | PENDING TARGET BUNDLE |
| Accepted baseline C3 run ID and bundle path | PENDING |
| Accepted optimized C3 run ID and bundle path | PENDING |
| Quality-gated comparison JSON | PENDING |
| Five same-configuration stability run IDs and bundle paths | PENDING |
| AMD/ROCm server, monitor and hardware binding evidence | PENDING HARDWARE |
| Final project PDF SHA256 | PENDING EXPORT |
| Poster/PPT SHA256 | PENDING |
| Demo video URL/file SHA256 and timestamps | PENDING |
