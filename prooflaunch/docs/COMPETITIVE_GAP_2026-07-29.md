# ProofLaunch competitive gap — 2026-07-29

## Decision

ProofLaunch is not yet entitled to a “top 10” or superiority claim. The strongest
public Track 1 reference inspected on 2026-07-29 is Dukaan PR #43: it shows a
real Radeon LTX-2.3 audio-video run, phase-separated memory, a 3-product batch
benchmark, 30 tests, a 4:32 demo, galleries, source, PDF, and poster.

ProofLaunch V7 is intentionally differentiated on evidence and release safety:

- independently hashed image, PDF, audio, video, and text intake;
- source-located Qwen3-VL / Whisper / exact-PDF observations;
- immutable product pixels in stills and pre-encode video frames plus a
  decoded H.264 tolerance gate;
- GroundingDINO spatial product evidence, SAM2 temporal masks, CLAP audio
  semantics, and timestamped A/V alignment;
- unsupported-claim, typography, safe-zone, semantic, rights, and cross-media
  release gates;
- at most two repairs, immutable task-graph hash, resumable checkpoints, and a
  hash-chained trace;
- multimodal-safe Gemma LoRA that cannot train vision/audio/projector towers.
- a compiler-enforced 450-case matrix with a named/versioned/settings-hashed
  baseline, 30 video cases, 90 diversity groups, and blind A/B artifact hashes;
- a phase-batched matrix runner with single-model residency, atomic
  checkpoints, bounded transient retries, crash recovery, and verified shard
  merge;
- a fail-closed Radeon preflight that validates HIP, VRAM, disk, dependencies,
  FFmpeg, safe Gemma LoRA retention, all specialist caches, and exact frozen
  source bytes before the expensive matrix.

## Matched evidence table

| Dimension | Dukaan PR #43 | ProofLaunch V7 current | Gate to close |
|---|---|---|---|
| Real Radeon generation | LTX-2.3 audio-video shown | Not executed; WS 403 | Produce model logs, HIP/device, VRAM, latency, hashes |
| Input modalities | Product image + prompt | Image/PDF/audio/video/text contracts | Execute frozen mixed-input fixture |
| Output modalities | Audio-video, three formats, stills | Still + locally muxed A/V code path | Produce and inspect final MP4 on Radeon |
| Product identity | “Product not redrawn” design | Exact pre-encode overlay + decoded H.264 tolerance + SAM2 tracking | Execute frozen matrix |
| Claims/provenance | Deterministic text | Source spans and cross-media locators | Radeon-run ledger |
| Memory engineering | 43 GB / 23 GB phase separation | One-heavy-model router plus phase-batched matrix executor | Record actual per-phase VRAM on target |
| Benchmark | 3-product batch, 134.3s vs 212.1s | 250 control cases; 450-case compiler and durable matrix runner implemented, not run on Radeon | Run the frozen manifest on Radeon |
| Tests | 30 | 111 local | Re-run all 111 on Radeon |
| Demo | 4:32 real operation | Shot list only | Record 3–5 minute real operation |

## Five-day priority

1. Restore or replace the blocked Radeon WebSocket route and run V7 unchanged.
2. Record Qwen3-VL → GroundingDINO → Gemma → SDXL → SigLIP2 → LTX 2B →
   SAM2 → CLAP sequential telemetry.
3. If target VRAM is at least 46 GB, benchmark LTX-2.3 as a quality tier; do not
   replace the 2B fallback until ROCm stability is demonstrated.
4. Run the implemented decoded-frame identity and A/V alignment gates over the
   frozen matrix; do not promote their local contract tests as Radeon evidence.
5. Record the real demo, seal assets, then open the English PR only after every
   P0 gate passes.

## Primary references

- Competition repository: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
- Dukaan PR #43: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/43
- Qwen3-VL: https://github.com/QwenLM/Qwen3-VL
- LTX-Video: https://github.com/Lightricks/LTX-Video
- LTX-2.3: https://github.com/Lightricks/LTX-2
- Whisper: https://github.com/openai/whisper
- OpenWorker: https://github.com/andrewyng/openworker
