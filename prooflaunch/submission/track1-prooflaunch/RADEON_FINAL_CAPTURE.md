# Final AMD Radeon capture card — mandatory Track 1 gate

**Team:** Banyan  
**Application:** ProofLaunch: Multimodal GTM Studio

This is the shortest valid path to close the only competition-critical evidence
gap. Target one continuous 3–5 minute session, matching the official
recommended duration. Do not splice a Mac/cloud result into the Radeon section
or replace an error with a mock success screen.

## Before recording

1. Copy the repository or checksum-verified Radeon archive to the active AMD
   Radeon instance. Preserve outputs outside any disposable instance.
2. Run:

   ```bash
   python scripts/capture_v10_radeon_live_preflight.py \
     --output evidence/v10/radeon-live-preflight.json
   ```

3. Confirm the receipt shows all of:

   - `torch.hip_version` is non-empty
   - `torch.cuda_api_available` is `true` (PyTorch ROCm uses this API name)
   - an AMD Radeon device name and VRAM are present
   - BF16 matmul, backward and SDPA are observed

The preflight alone is not model inference evidence.

## Continuous recording sequence

| Time | Required visible evidence |
|---|---|
| 00:00–00:25 | `Team Banyan` and `ProofLaunch: Multimodal GTM Studio`, Track 1, rights-bound brief and source image |
| 00:25–00:55 | `rocminfo`, `rocm-smi`, PyTorch version, HIP version and device name |
| 00:55–01:20 | Exact model ID/revision, adapter hash, dtype, seed and input hash |
| 01:20–02:10 | Start one real image/video/audio inference; keep progress visible |
| 02:10–02:40 | Show final output plus latency and peak VRAM receipt |
| 02:40–03:15 | Show claim/identity/safe-zone audit and one bounded repair or clean pass |
| 03:15–03:40 | Run governed replay/export and open the hash-bound manifest |
| 03:40–04:00 | State truth boundary and show final inspectable media, not a slide |

Use `notebooks/prooflaunch_radeon_gate_v7.ipynb` for the competition matrix or
the relevant local model route already present on the instance. At least one
key final inference must be executed on AMD Radeon; API-only generation does not
close this gate.

## Evidence files to retain locally

- `evidence/v10/radeon-live-preflight.json`
- exact model/adapter/input/output hashes
- raw timing and peak-VRAM receipt
- final generated media file(s)
- audit/repair receipt
- original continuous recording and final Demo Video export

Copy them to durable local storage before destroying or switching the Radeon
instance. Re-run `scripts/build_v10_final_locks.py` only after all final evidence
and submission documents are stable.

## Pass condition

Update `SUBMISSION_GATE.json` only when the bytes exist and are independently
inspectable:

- `real-radeon-creative-run = passed`
- `demo-video-3-to-5-minutes = passed`

Until then, `overallStatus` must remain `blocked`.
