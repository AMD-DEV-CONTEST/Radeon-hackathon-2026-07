# Evidence Index

> `HISTORICAL / NON-FINAL` means the named legacy deliverable exists and its
> SHA256 has been verified, but it was generated before the current C1/C2 source
> and must not be submitted as the final artifact. Formal target-run statuses
> remain `PENDING` until a clean C2 freeze and complete bound C3 bundles are
> generated and reviewed. The current single-request proof and B/C/D candidate
> metrics are likewise non-final and do not constitute an accepted
> baseline/optimized result.

| Scoring requirement | Evidence | Status |
| --- | --- | --- |
| Clear hotel scenario | README + project specification | READY |
| Agent architecture and multi-turn flow | Architecture + confirmation sequence in project specification | READY |
| Pinned model/binary provenance | README + third-party notices; revision/hash verification procedure | READY DOCUMENTATION |
| C2 immutable binding freeze | Full commit; clean project; tree/source/corpus/suite/model/binary hashes | PENDING FREEZE |
| RAG with citations | Source + 8-case retrieval JSON + demo timestamp | PENDING RUN |
| Typed tools and planning | Source + tests + 30-case Agent quality JSON | PENDING RUN |
| Independent stress gate | Separate 12-case `stress.json`; six security cases require 100%, six open-language cases require ≥95%; excluded from official score/hash | PENDING RUN |
| Multi-turn memory | Agent quality JSON + consent/forget traces | PENDING RUN |
| Permission/privacy | Agent quality JSON + attack denial traces | PENDING RUN |
| One complete C3 lifecycle | Retrieval/official-quality/stress/benchmark artifacts + controlled process shutdown + complete hash-bound evidence bundle under one run ID | PENDING RUN |
| Radeon local inference | Same-run-ID ROCm evidence, server log, binding manifest, video | PENDING HARDWARE |
| Directed optimization | Quality-gated baseline/optimized JSON + same-run-ID ROCm monitor logs | PENDING HARDWARE |
| E/F context transition | E `context-selection.json` + F `context-proof.json`; source-report hashes, manifest fields, `SHA256SUMS.txt`, and recomputation | PENDING HARDWARE |
| Stable interaction | Five distinct complete run IDs; every quality/benchmark gate passes | PENDING RUN |
| Project PDF | Pre-C1 archive outside the frozen repository, 10 A4 pages, 46,010 bytes | HISTORICAL / EXCLUDED / HASH VERIFIED |
| Bilingual PPT | Pre-C1 archive outside the frozen repository, 9 slides, 16:9, 175,367 bytes | HISTORICAL / EXCLUDED / HASH VERIFIED |
| Demo video | Pre-C1 archive outside the frozen repository, 276 s, 1920x1080, 25 fps | HISTORICAL / EXCLUDED / HASH VERIFIED |
| English subtitles | Pre-C1 archive outside the frozen repository, 23 cues covering 00:00:00–00:04:36 | HISTORICAL / EXCLUDED / HASH VERIFIED |

`C2` is the immutable input freeze; `C3` is one fresh end-to-end target
lifecycle after that freeze. A valid C3 run starts a new model process and ROCm
monitor, executes retrieval, 30-case quality, independent stress, and benchmark
windows under one run ID, captures bound live evidence, shuts both children down
in a controlled way, and then creates the final binding bundle. Every bundle
includes `stress.json`. Run E additionally includes `context-selection.json`;
run F instead includes `context-proof.json`. The applicable context filename and
hash are present in `binding-manifest.txt`, and both stress and context artifacts
are covered by `SHA256SUMS.txt`. The E/F artifacts bind their source
quality/benchmark hashes, are recomputed, and must prove that F reproduces E's
minimum-safe context selection. The live and final collection phases are both
required. No C2 or C3 status is claimed above before those artifacts exist.
The C2 source digest is shared by every evaluator and the final collector. It
uses committed blobs and file modes only for the frozen executable/evaluation
allow-list, then requires each selected working-tree file to match `HEAD`
byte-for-byte. Documentation, media and generated evidence are intentionally
outside that scoped digest and remain covered by the separate C2 project tree.

“Five-run” means five fresh C3 model-service lifecycles using one accepted final
configuration on the same pinned commit/project tree/source, corpus and suite,
model hash, `llama-server` hash, alias, context, thinking/flash settings,
GPU-layer request, batch/micro-batch, parallel slots, benchmark workload and
Radeon hardware fingerprint. These are not the differently configured A–H
tuning rows. Each run keeps its own retrieval JSON, quality JSON, independent
stress JSON, benchmark JSON, `llama-server` log, ROCm monitor log, live evidence
file, orchestration status, complete binding manifest and bundle checksum.
Stability passes only when all five report zero hard failures, 30/30 completed
quality cases, passing independent stress gates, a 100% benchmark success rate,
complete lifecycle markers and active same-GPU evidence. No averaging, rerun
under the same ID, or selective omission may hide a failed run.

## Final evidence register

Replace target-run `PENDING` values only after reviewing the artifact and its
binding manifest. Legacy static deliverables below were verified directly
against the files under `output/`, but every listed PDF/PPTX/MP4/SRT hash is
historical and non-final. Replace its row label and hash only after regeneration
from frozen C2 source and accepted C3 evidence:

| Final field | Bound value / artifact |
|---|---|
| C2 source commit, project tree and source hash | PENDING |
| Policy corpus and `30-case-p0-v3` suite hashes | PENDING TARGET BUNDLE |
| Independent stress suite hash and bound `stress.json` | PENDING TARGET BUNDLE |
| E/F context artifact hashes and source-report bindings | PENDING TARGET BUNDLES |
| Quality-qualified Reference (A or B) C3 run ID and bundle path | PENDING |
| Accepted Winner C3 run ID and bundle path | PENDING |
| Quality-gated comparison JSON | PENDING |
| Five same-configuration Stability report, run IDs and bundle paths | PENDING |
| Independent passed long-soak report and fresh run ID | PENDING |
| Accepted-final runtime proof and release-profile SHA256 | PENDING |
| AMD/ROCm server, monitor and hardware binding evidence | PENDING HARDWARE |
| Historical non-final project PDF SHA256 | `a3e64e406d9f0170ee14acadc4bf6e9a970523395ac4855550969ae2ce951401` |
| Historical non-final bilingual PPT SHA256 | `41d432010060ac6ae97cafa185a12cbe0bdf222abebc3161bdb6fb19fccbf574` |
| Historical non-final demo video and subtitle SHA256 | MP4: `d4fda194053f3ec0d488138794a5c723de96fea1697c2d412c4c59ec87fc5df1`; SRT: `eb05f7118fcc911a554c279d121bc6ace447eeb671df914836b087887e1e3fa9` |
