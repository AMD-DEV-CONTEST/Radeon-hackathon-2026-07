# AMD Evidence Contract

The final submission must prove that the environment, final model training, and
closed-loop inference ran on a single AMD Radeon GPU through ROCm. This is the
strict interpretation of the Track 3 overview on the official ModelScope event
page. A package list or a compatible Dockerfile is insufficient by itself.

For every claimed AMD training or inference run, preserve:

- UTC start/end time and run identifier;
- git revision and dirty-tree status;
- container image digest or environment lock hash;
- sanitized `rocminfo`/AMD SMI summary;
- PyTorch version, HIP version, visible Radeon device name, and device count;
- Genesis backend selection and a minimal tensor/device probe;
- dataset revision and normalization-statistics hash;
- complete config hash, seeds, checkpoint SHA-256, and episode JSONL;
- wall time, throughput, peak memory, success metrics, and failure taxonomy;
- an unedited terminal or screen recording segment showing the backend and run result.

The device count must be exactly one for the final contest path. The NVIDIA
8×4090 environment is a source-reference and development aid. It must be
disclosed as such and must not be presented as AMD execution evidence. Final
training, inference, comparison, and confirmation must run on the allocated
single-GPU Radeon Cloud worker.

## Official Radeon Cloud main path

`configs/amd-cloud-runtime-v1.json` preserves the destroyed instance's verified
runtime history. `configs/amd-persistence-layout-v2.json`,
`configs/amd-cloud-runtime-v3.json`, and `docs/AMD_CLOUD_BOOTSTRAP.md` define
the current recovery boundary. A participant-supplied organizer broadcast
named `/workspace/persistence`, but the recreated workspace proved it absent
and exposed `/workspace/persistent -> /persistent`. The participant adopted
the observed path, and one minimal write-`fsync`-read-delete canary passed on
the 100 GiB NFS PVC. This is not persistence-across-recreation or direct-local-
SSD evidence. The dated training material specified the Radeon
Cloud `proxy` image and instance-provided
ROCm 7.2.1 wheels for PyTorch 2.9.1, LeRobot 0.4.4, NumPy 2.1.2, and Genesis
from current main with `gs.amdgpu`.

## Stage 1 and Stage 2 receipts (2026-07-25) ✅ VERIFIED

**Runtime availability is now proven.** The following receipts were captured on
the official AMD Radeon Cloud single-GPU instance:

### Stage 1: ROCm wheel installation and torch HIP smoke
- **Receipt:** `receipts/amd-promotion-20260725-v1/mantis_amd_stage1_receipt_20260725_v1.json`
- **Status:** `stage1_pass: true`, `validation_pass: true`
- **Captured at:** 2026-07-25T03:43:39.816033+00:00
- **GPU:** gfx1100 AMD Radeon Graphics, ~48GiB VRAM
- **ROCm:** 7.2.1
- **Wheels verified:**
  - torch 2.9.1+rocm7.2.1.gitff65f5bc (SHA256: 5a47e74d991a91985f4546c6336bd10caee7b80380d2dd365bcae9aa77b51920)
  - torchvision 0.24.0+rocm7.2.1.gitb919bd0c (SHA256: c3debf2074570d3698aacb185e2ad9ca10a039361db580ab63f301e78c485c96)
  - torchaudio 2.9.0+rocm7.2.1.gite3c6ee2b (SHA256: 2b59b88b31a47faef823af1004dcb8950a7b435b953959f5096f7b857746ff51)
  - triton 3.5.1+rocm7.2.1.gita272dfa8 (SHA256: fad31a22feacc46da10bd31dd0ea7f4da2331603ad1a68d4c89d20ceaae2cfbd)
- **torch HIP smoke:** device_count=1, HIP version 7.2.53211-e1a6bc5663

### Stage 2: Genesis, LeRobot, and smoke tests
- **Receipt:** `receipts/amd-promotion-20260725-v1/mantis_amd_stage2_receipt_20260725_v2.json`
- **Status:** `stage2_pass: true`, `validation_pass: true`
- **Captured at:** 2026-07-25T04:11:48.083629+00:00
- **Genesis:** 1.2.3 at commit `2a40c87ad4e89a0f115cc43fb45195a8260aad0e`
- **Genesis backend:** `gs.amdgpu` available
- **LeRobot:** 0.4.4 installed and version-verified
- **Additional stack:** NumPy 2.1.2, scikit-image 0.26.0, FFmpeg present at `/usr/bin/ffmpeg`
- **Genesis scene smoke:** Passed (after `gs.morph` → `gs.morphs` correction)
- **Stage 1 chain-of-custody:** Validated (instance_id match, stage1_pass true)

### Evidence tarball
- **Path:** `receipts/amd-promotion-20260725-v1/mantis_amd_promotion_evidence_20260725_v1.tar.gz`
- **SHA256:** `1290a79da763ff373dad34362977a69788dc44ec6b28f54a0ceb0cc971f1349d`
- **Contents:** All receipts, logs, pip freeze, wheel inventory, constraints file

### Chronology of Genesis scene smoke fix
1. **Stage 2 v1 (first attempt):** Failed with `AttributeError: 'Scene' object has no attribute 'morph'`
   - Console: `mantis_amd_stage2_console_20260725_v1.log`
   - Failure log: `mantis_amd_stage2_genesis_scene_failure_20260725_v1.log`
2. **Stage 2 v2 (retry):** Succeeded with corrected `scene.morphs` attribute
   - Console: `mantis_amd_stage2_console_20260725_v2.log`
   - Retry log: `mantis_amd_stage2_genesis_scene_retry_20260725_v2.log`

This demonstrates runtime availability only. Mantis adapter verification, dataset
generation, multi-seed training, and G3/G4 evaluation require separate immutable
receipts on the same single-GPU Radeon environment.

## Portable fallback container

`configs/rocm-container-v1.json`, `docker/Dockerfile.rocm`, and
`docker/compose.rocm.yaml` retain the ROCm 6.4.1 / PyTorch 2.6 / Genesis 1.2.3
/ LeRobot 0.4.2 environment as a portable fallback candidate. It is no longer
the main Radeon Cloud path. If it is ever used, the compose boundary still
requires `/dev/kfd`, `/dev/dri`, an immutable image digest, and the same strict
runtime and run receipts.
