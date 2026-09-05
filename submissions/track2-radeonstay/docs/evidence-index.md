# Evidence Index

> `HISTORICAL / NON-FINAL` means the legacy deliverable exists and its SHA256 was
> verified, but it predates the current C2 source and must not be submitted as a
> final artifact. C2 v3 is frozen. The submission performance claim is the
> smaller, completed B→C single-variable experiment; D–H, five-run Stability,
> and soak remain explicitly deferred and are not required for the deployed C
> profile.

| Scoring requirement | Evidence | Status |
| --- | --- | --- |
| Clear hotel scenario | README + project specification | READY |
| Agent architecture and multi-turn flow | Architecture + confirmation sequence in project specification | READY |
| Pinned model/binary provenance | README + third-party notices; revision/hash verification procedure | READY DOCUMENTATION |
| C2 immutable binding freeze | Commit `f7ba681…`; project tree `b44fb212…`; source/corpus/suite/model/binary hashes in reviewed comparison | **FROZEN** |
| RAG with citations | Source + fixed 16-case B/C projection; 15/16 expected citation-section checks in both runs | **MEASURED / DISCLOSED** |
| Typed tools and planning | Source + 16/16 successful B/C requests; zero model-call failures | **MEASURED** |
| Independent stress gate | Separate immutable 12-case fixture remains available; not rerun for minimal B/C | DEFERRED |
| Multi-turn memory | Source, persisted Journey state, consent/forget implementation | READY SOURCE / DEMO |
| Permission/privacy | Source, confirmation capability, identity boundary, Privacy Proof | READY SOURCE / DEMO |
| Minimal target comparison | Fresh B and C model lifecycles, process manifests, benchmark JSON, server logs, ROCm monitors, controlled shutdown | **COMPLETE / HASH BOUND** |
| Radeon local inference | ROCm 7.2.1, gfx1100, 41/41 offload, 100% peak GPU busy, process binding in both B/C runs | **VERIFIED** |
| Directed optimization | B Flash off → C Flash on; exact quality projection; throughput +6.455%/+6.491%; C4 P95 -5.428% | **ACCEPTED MINIMAL B/C** |
| Optional Radeon Cloud API bonus path | Explicit `radeon_cloud_free` opt-in, pinned Public Free endpoint/model, synthetic-only boundary, fail-closed validation, and fused plan/evidence optimization variable | **IMPLEMENTED / BONUS RESULT NOT CLAIMED** |
| E/F context transition | Full-matrix optional experiment | DEFERRED / NOT CLAIMED |
| Stable interaction | Five fresh Winner lifecycles and long soak | DEFERRED / NOT CLAIMED |
| Public Radeon demo | [Authenticated live application](https://rc-5ec89b08f896792e.radeon.firstdg.ai/) using Optimized C | **LIVE** |
| Project PDF | Pre-C1 archive outside the frozen repository, 10 A4 pages, 46,010 bytes | HISTORICAL / EXCLUDED / HASH VERIFIED |
| English submission PPT | [`RadeonHotel-Track2-Submission.pptx`](RadeonHotel-Track2-Submission.pptx), 10 slides, 16:9, 704,431 bytes | **FINAL / HASH VERIFIED** |
| Demo video | [`RadeonHotel-Track2-Demo.mp4`](RadeonHotel-Track2-Demo.mp4), 293.306 s, 1920×1080, 30 fps, H.264/AAC with embedded English captions | **FINAL / HASH VERIFIED** |
| English subtitles | [`RadeonHotel-Track2-Demo.en.srt`](RadeonHotel-Track2-Demo.en.srt), 65 cues covering the complete narration | **FINAL / HASH VERIFIED** |

`C2` is the immutable executable/evaluation input freeze. The released C2 v3
commit is `f7ba6811205a40ba51ca74c82b43129b616f74c5`, with project tree
`b44fb212b77c06ee9c8d097b5a9f2f891f79a389`. The C2 source digest is shared by
the evaluators and collector. It
uses committed blobs and file modes only for the frozen executable/evaluation
allow-list, then requires each selected working-tree file to match `HEAD`
byte-for-byte. Documentation, media and generated evidence are intentionally
outside that scoped digest and remain covered by the separate C2 project tree.

The minimal B/C comparison starts a fresh bound model process and ROCm monitor
for each side, uses one fixed 16-case request set at concurrency 1 and 4 after
three warmups, and retains each report, runtime-instance manifest, complete
server log, and monitor log. The only effective service change is Flash
Attention. The two exact quality projections are identical. The raw strict gate
is false on both sides because `MS-001` returns three citations but covers only
15/16 expected citation-section checks. This is disclosed in the selected JSON;
no metric is promoted to 300/300.

The original full A–H/five-run/soak contract remains documented as an optional
post-submission extension. Its unexecuted rows cannot be cited as evidence for
this release.

## Final evidence register

Every final artifact below was reviewed against its recorded hash. The English
submission deck and narrated demo were generated from frozen C2 v3, the
accepted B→C evidence, and sanitized captures of the deployed C profile. Legacy
PDF/PPTX/MP4/SRT hashes are retained only to prevent accidental reuse of
superseded files:

| Final field | Bound value / artifact |
|---|---|
| C2 source commit, project tree and source hash | Commit `f7ba6811205a40ba51ca74c82b43129b616f74c5`; tree `b44fb212b77c06ee9c8d097b5a9f2f891f79a389`; source `168abd8f26578ac58cff1173c0323f6da6664eec169a32b4ae8fab5bf4272285` |
| Policy corpus and fixed suite hashes | Corpus `58f15bd9f3b4f5b3c69e92491054349f29a496ac17931bf8e341b03aa562cdb1`; suite `60fae4be0bd7a16ee9b2e7963bb3afccbf319c2ed64cd3ba43acfc912bfd3d1b` |
| Minimal Reference | B, run `c3min-f7ba681-B`, Flash Attention off |
| Minimal Winner | C, run `c3min-f7ba681-C-r3`, Flash Attention on |
| Reviewed B/C comparison | [`docs/evidence/c3min-f7ba681-bc-comparison.json`](evidence/c3min-f7ba681-bc-comparison.json), SHA256 `7f85a614a31da10e5484ee41034282210ac44caf84012617dea5c786c0f03f59` |
| Raw B benchmark/binding | SHA256 `41a46d12…` / `245375d5…`; retained privately |
| Raw C benchmark/binding | SHA256 `3428177c…` / `a83b7540…`; retained privately |
| Five same-configuration Stability report | DEFERRED / NOT CLAIMED |
| Independent long-soak report | DEFERRED / NOT CLAIMED |
| Accepted-final full-matrix runtime proof | DEFERRED / NOT CLAIMED |
| AMD/ROCm hardware binding | Both B/C: process binding true, gfx1100, 41/41 offload, 100% peak GPU busy; full raw log hashes are in the comparison JSON |
| Public Radeon demo | [https://rc-5ec89b08f896792e.radeon.firstdg.ai/](https://rc-5ec89b08f896792e.radeon.firstdg.ai/) |
| Optional Radeon Cloud API bonus route | Implemented as an explicit synthetic-only candidate; accepted comparison, server-side quantization, and bonus score are not claimed |
| Final English submission PPT SHA256 | `c6e3e523045044e7a805beca8c34e8c8788bebf80159d18d6912df1cf5a7f91f` (704,431 bytes) |
| Final English demo video SHA256 | `89e9e9779d1e15f34b5af81e41a6cb0eed9f47d5bec3ab9c5ee338af7544701b` (8,116,726 bytes; 293.306 s; 1920×1080; H.264/AAC; embedded English `mov_text`) |
| Final English subtitle sidecar SHA256 | `395471b927b5f036c53dc0192feb0507939c6899e5e65af617ef6788bd441889` (7,316 bytes; 65 cues) |
| Historical non-final project PDF SHA256 | `a3e64e406d9f0170ee14acadc4bf6e9a970523395ac4855550969ae2ce951401` |
| Historical non-final bilingual PPT SHA256 | `41d432010060ac6ae97cafa185a12cbe0bdf222abebc3161bdb6fb19fccbf574` |
| Historical non-final demo video and subtitle SHA256 | MP4: `d4fda194053f3ec0d488138794a5c723de96fea1697c2d412c4c59ec87fc5df1`; SRT: `eb05f7118fcc911a554c279d121bc6ace447eeb671df914836b087887e1e3fa9` |
