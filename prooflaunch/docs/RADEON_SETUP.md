# AMD Radeon / ROCm Setup

This is the evaluator-facing path for live competition evidence. It complements
the deeper reproduction contract in
[`RADEON_REPRODUCTION_EXECUTION_CONTRACT_V1.md`](RADEON_REPRODUCTION_EXECUTION_CONTRACT_V1.md).

## Minimum evidence contract

The final live run must record:

- AMD Radeon device identity and VRAM;
- ROCm/HIP and PyTorch versions;
- exact model and adapter revisions;
- input and output SHA-256 values;
- seed, dtype, generation parameters, latency, and peak VRAM;
- final inspectable media;
- audit and repair results;
- continuous 3–5 minute Demo Video.

## Preflight

```bash
python scripts/capture_v10_radeon_live_preflight.py \
  --output evidence/v10/radeon-live-preflight.json
```

Required observations include a non-empty HIP version, an AMD device name,
available VRAM, and passing BF16 matmul, backward, and SDPA probes. PyTorch ROCm
uses the `torch.cuda` API namespace; the hardware identity in the receipt must
still be AMD Radeon.

## Model execution

Use the reviewed Radeon notebook or equivalent local CLI path. Keep the model
ID, revision, input, seed, progress, and final output visible. At least one key
inference must run locally on Radeon; an API call, deterministic replay, mock,
CPU result, Apple Metal result, or cloud-provider asset does not close this
gate.

The runtime uses sequential single-model residency:

`Qwen3-VL → SDXL → SigLIP2 → LTX-Video → SAM2 + CLAP`

Optional roles are loaded only when required. Explicitly unload the current
heavy model, collect memory, and verify the available VRAM before loading the
next role.

## Final capture

Follow
[`submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md`](../submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md)
and [`DEMO_VIDEO_SHOTLIST.md`](DEMO_VIDEO_SHOTLIST.md). Preserve raw receipts
and video before destroying any temporary Radeon instance.

## Fail-closed rules

- Do not rewrite or manually bless a failed receipt.
- Do not splice a non-Radeon output into the live Radeon segment.
- Do not label a preflight as model inference.
- Do not mark `SUBMISSION_GATE.json` ready until the final bytes exist and their
  hashes are recorded in the submission manifest.
