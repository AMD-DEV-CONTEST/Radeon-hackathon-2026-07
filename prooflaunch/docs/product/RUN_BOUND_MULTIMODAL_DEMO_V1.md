# Run-bound GTM portfolio and multimodal evidence demo V1

This demo closes the mechanical gap between a generated media file and a governed
GTM run. It does not claim that mechanical closure is equivalent to human creative
quality or production effect.

## What is real

- The 4K PNG, 48 kHz stereo WAV and 4K MP4 are real files whose byte lengths and
  SHA-256 digests are independently checked.
- The audio chain includes cached Qwen3-TTS inference observed on Apple Metal and
  deterministic local mastering.
- The video chain records its mixed provenance: one provider-managed source-image
  generation plus local audio and deterministic composition. It is not labeled as
  a purely local video-model result.
- Both deliverables enter the production API through signature-checked CAS upload,
  tenant authorization, immutable execution receipts, campaign/run identity and a
  project rights locator.
- Eight delivered JSON artifacts—strategy, scheduling, copy, analytics, GEO, SEO,
  Graph/Loop/Harness and advertising portfolio—re-enter the same API through a
  second registry. Every byte must exactly match its named artifact in the approved
  run bundle; a matching receipt alone cannot substitute or relabel another file.
- The two registries converge only in the Cockpit matrix. Generated evidence,
  named-human review and production effect remain separate states.

## What is synthetic or unproven

- The release approval is a synthetic control-plane exercise. It proves that the
  code gate can be traversed; it is not a real human quality judgment.
- No named human media review, external publication, production outcome, causal
  revenue, 4A preference, Top-1 standing or Radeon execution is claimed.

## Run

```bash
.venv/bin/python scripts/run_run_bound_multimodal_demo.py
```

The script makes no new model call and performs no download. It starts the actual
single-port API on an ephemeral loopback port, creates and releases a synthetic
governed run, downloads its approved bundle, re-uploads and registers eight exact
JSON deliverables, uploads the existing media and execution receipts, registers the
audio/video masters, then verifies the cockpit matrix.

## Evidence

- `artifacts/run-bound-multimodal-demo-v1/demo-receipt.json`
- `artifacts/run-bound-multimodal-demo-v1/audio-execution-receipt.json`
- `artifacts/run-bound-multimodal-demo-v1/video-execution-receipt.json`
- `artifacts/run-bound-multimodal-demo-v1/capability-execution-receipts.json`
- `artifacts/run-bound-multimodal-demo-v1/gtm-cockpit.json`

The expected cockpit state is exactly ten `generated_unreviewed` capability rows:
eight run-exact JSON deliverables plus audio and video. Cross-device memory remains
contract-only because no authorized inherited memory exists. Named-human quality
and production-effect counts both remain zero.
