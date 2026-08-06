# ProofLaunch five-day competition delivery runbook

The clock starts when the Radeon kernel can accept a WebSocket connection.
Every day has an evidence exit gate; schedule pressure cannot convert a missing
artifact into a pass.

| Day | Primary outcome | Required work | Exit evidence |
|---|---|---|---|
| 1 | Multimodal-safe Gemma adapter | Run the safe Notebook from a clean kernel; prove HIP/device; train language-side-only LoRA; reject every vision/audio/projector trainable parameter; run frozen pre/post emotion and visual-retention sets | `multimodal_retention.json`, post-fine-tune predictions, trainable-parameter inventory, model/adapter hashes, peak VRAM, wall time |
| 2 | Real Radeon creation path | Run the V7 Gate in order: Qwen3-VL → GroundingDINO → Gemma → SDXL → SigLIP2 → LTX video → SAM2 → CLAP; unload between phases; verify pre/post-codec identity, A/V alignment, and cross-media gates | `generation-benchmark.json`, `video-benchmark.json`, `encoded-delivery-gate.json`, `sam2-temporal-segmentation.json`, PNG, MP4, campaign ZIP, ledger, model plan, HIP/device, latency, peak VRAM, hashes |
| 3 | Stability and diversity | Freeze the protocol, V7 build, named baseline version/settings, and 30 permitted product hashes; execute the exact 450-case matrix and ≥30 video cases; record explicit failure rows; run the same IDs through the baseline | Immutable manifest, ProofLaunch/baseline case-level JSONL, pass/fail summary, crash rate, p50/p95, peak VRAM, 90 seed-diversity groups |
| 4 | Human value and demo proof | Run randomized candidate-hash publish preference with ≥5 raters covering all 30 products plus operator-time tasks; compile all 20 bars; record a continuous 3–5 minute real Radeon flow | Blinded human CSV, compiled evidence/report, confidence intervals, final video URL, no-cut Radeon/device and output-hash shots |
| 5 | Submission seal | Re-run all local and Radeon gates from a clean checkout; scan for credentials/private paths; rebuild English PDF/poster/source archive; verify every hash; fork and open the exact-title English PR only if all P0 gates pass | `SUBMISSION_GATE.json` = `ready`, clean-run log, final archive checksum, PDF/PPT hashes, video URL, PR URL |

## Fixed decision order

1. Restore the Radeon Kernel/Terminal/Events WebSocket path. File upload alone
   is not execution evidence.
2. Run the safe Gemma Notebook before the V7 Gate. The older `all-linear`
   adapter is evidence of a risk and must not be promoted.
3. Keep one heavy model resident at a time and follow the execution plan
   recorded by V7; unload and clear Radeon memory between phases.
4. A failed claim, product-identity, typography, safe-zone, semantic, retention,
   hash, or runtime assertion blocks export and submission.
5. Do not publish “outperforms” language without the frozen matched-task and
   blinded-human bars in `COMPETITIVE_BENCHMARK_PROTOCOL.md`.

## Stop conditions

- Kernel remains disconnected or reports zero connections.
- HIP runtime or Radeon device evidence is absent.
- Any forbidden multimodal LoRA parameter is trainable.
- Gemma visual retention is below 75% or drops by more than five points.
- The SDXL/LTX asset fails any mechanical, SigLIP2, GroundingDINO/SAM2,
  decoded-identity, CLAP, A/V-alignment, or cross-media gate after two repairs.
- A required file, video, human record, license decision, or hash is missing.
- `SUBMISSION_GATE.json` contains any blocked P0 item.
