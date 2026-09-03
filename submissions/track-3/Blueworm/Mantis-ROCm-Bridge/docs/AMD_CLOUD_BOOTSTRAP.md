# Radeon Cloud bootstrap gate

**Recovery status (2026-07-29):** the recreated public
`Blank OpenCode Workspace` is Ready and JupyterLab works. The participant
adopted the observed `/workspace/persistent -> /persistent` entrypoint, and one
64-byte write-`fsync`-read-delete canary passed. Package installation, data
migration, GPU workloads, training, inference, and evaluation remain
unauthorized.

Current recovery sources of truth are `configs/amd-persistence-layout-v2.json`
and `configs/amd-cloud-runtime-v3.json`. Notice-path v1/runtime-v2 and the
verified historical runtime v1 remain immutable evidence.

**Current entrypoint observation (2026-07-29):** the private `test` template's
Jupyter route returned 404. After participant-authorized recreation from the
public `Blank OpenCode Workspace`, JupyterLab opened successfully. The fresh
profile image is `amd-oneclick-base:git-proxy-test-20260528-1125`.

The fresh terminal exposes `/workspace/persistent -> /persistent`, not the
announced `/workspace/persistence`. `/persistent` is a 100 GiB read-write
NFSv3 mount whose source contains a PVC identifier. Do not create the absent
`/workspace/persistence` path: it could be a lookalike directory on the
workspace overlay. `configs/amd-persistence-layout-v2-candidate.json` records
the pre-adoption observation. The formal v2 contract records the participant's
adoption and successful canary. The persistent cloud receipt is
`/workspace/persistent/mantis-track3/evidence/recovery/wp-amd-recovery-002-persistence-canary-20260729-v1.json`.

## Create the instance after recovery

1. Sign in at `https://radeon-global.anruicloud.com/` with the registered
   contest email.
2. Select the currently offered official template and record its exact name;
   do not assume the historical `proxy` entry still exists.
3. Select PVC storage. Treat only `/workspace/persistent` as the workspace
   entrypoint to the durable mount.
4. Launch exactly one Radeon GPU and wait for `Your workspace is ready (100%)`.
5. Enter through JupyterLab or SSH. Record the exact template and instance
   identity. Verify that `/workspace/persistent` is a symlink resolving to
   `/persistent`, and that the persistence checker passes.
6. Do not install or restore anything until the persistence checker and a
   fresh wheel inventory have passed. Version a new runtime inventory rather
   than editing v3 in place.

## Freeze the official image inventory

The training material says that the image root contains ROCm 7.2.1 wheels for
PyTorch 2.9.1, torchvision 0.24.0, torchaudio 2.9.0, and Triton 3.5.1. Before
installing anything, record their resolved filenames and SHA-256 values.

Never run an unconstrained `pip install torch`: it can replace the ROCm build
with a CPU or NVIDIA build. After a fresh inventory matches the target, install
only the instance-provided wheels into the frozen durable environment:

```bash
source /workspace/persistent/mantis-track3/envs/rdna/bin/activate
python -m pip install \
  /torch-2.9.1+rocm7.2.1*.whl \
  /torchvision-0.24.0+rocm7.2.1*.whl \
  /torchaudio-2.9.0+rocm7.2.1*.whl \
  /triton-3.5.1+rocm7.2.1*.whl
```

Install the current Genesis main checkout locally, recording its resolved git
revision, and select `gs.amdgpu`. Install the teaching target `lerobot==0.4.4`
and validate the project adapter before producing data:

```bash
cd /workspace/persistent/mantis-track3/src
git clone --depth 1 https://github.com/Genesis-Embodied-AI/Genesis.git Genesis
source /workspace/persistent/mantis-track3/envs/rdna/bin/activate
python -m pip install /workspace/persistent/mantis-track3/src/Genesis
python -m pip install \
  "lerobot==0.4.4" transformers accelerate safetensors matplotlib Pillow \
  jupyter nbconvert ipykernel num2words modelscope
python -m pip install --force-reinstall --no-cache-dir \
  "numpy==2.1.2" "scikit-image>=0.22"
```

Install FFmpeg and its development libraries as described in the teaching
material. Run the supplied `setup_torchcodec.sh` only after its exact source has
been audited and saved with a hash; do not substitute an unknown script.

## Persist caches

Append these values to the durable environment activation script:

```bash
export HF_HOME=/workspace/persistent/mantis-track3/cache/huggingface
export HF_LEROBOT_HOME=/workspace/persistent/mantis-track3/cache/huggingface/lerobot
export MODELSCOPE_CACHE=/workspace/persistent/mantis-track3/cache/modelscope
```

## Historical verification results (destroyed instance, 2026-07-25)

### Stage 1: ROCm wheel installation and torch HIP smoke
- Receipt: `receipts/amd-promotion-20260725-v1/mantis_amd_stage1_receipt_20260725_v1.json`
- Result: `stage1_pass: true`, `validation_pass: true`
- ROCm 7.2.1, single gfx1100 AMD Radeon Graphics (~48GiB VRAM)
- Official local wheels verified: torch 2.9.1, torchvision 0.24.0, torchaudio 2.9.0, triton 3.5.1
- torch HIP smoke passed: device_count=1, hip_version=7.2.53211-e1a6bc5663

### Stage 2: Genesis, LeRobot, and smoke tests
- Receipt: `receipts/amd-promotion-20260725-v1/mantis_amd_stage2_receipt_20260725_v2.json`
- Result: `stage2_pass: true`, `validation_pass: true`
- Genesis 1.2.3 at commit `2a40c87ad4e89a0f115cc43fb45195a8260aad0e`
- Genesis `gs.amdgpu` backend available
- LeRobot 0.4.4 installed and version-verified
- NumPy 2.1.2, scikit-image 0.26.0
- FFmpeg present at `/usr/bin/ffmpeg`
- **Genesis scene smoke:** Passed after fixing `gs.morph` → `gs.morphs`
  - First attempt (v1) failed with `AttributeError: 'Scene' object has no attribute 'morph'`
  - Second attempt (v2) succeeded with corrected `scene.morphs` attribute

### Chronology and evidence
- Evidence tarball: `receipts/amd-promotion-20260725-v1/mantis_amd_promotion_evidence_20260725_v1.tar.gz`
- SHA256: `1290a79da763ff373dad34362977a69788dc44ec6b28f54a0ceb0cc971f1349d`
- See `receipts/amd-promotion-20260725-v1/README.md` for complete file manifest

## Promotion receipts

Before training or inference, preserve:

- root wheel filenames and hashes, `pip freeze`, Python and pip versions;
- `rocminfo`, AMD SMI, `torch.__version__`, `torch.version.hip`, device name,
  and visible device count (exactly one);
- Genesis revision and a rendered or headless `gs.amdgpu` scene smoke;
- LeRobot 0.4.4 imports plus the Mantis 16D/18D adapter and three-camera smoke;
- NumPy/scikit-image versions, FFmpeg version, and TorchCodec import;
- project contract validation and unit-test output.

For a future worker, first run the persistence receipt from the project source:

```bash
PYTHONPATH=src python tools/check_amd_persistence.py \
  --check-filesystem
```

This first admission gate creates no directory. After a versioned restore or
migration has created the durable evidence directory, rerun it with a fresh
`--output` path below that directory. Then run the strict project receipt with
its output beneath the same durable root:

```bash
PYTHONPATH=src python tools/check_rocm.py \
  --require-rocm \
  --output /workspace/persistent/mantis-track3/evidence/runtime/rocm-runtime-v1.json
```

**Stage 1 and Stage 2 receipts prove runtime availability only.** Final training,
checkpoint, closed-loop inference, and evaluation need separate immutable receipts
on that same single-GPU Radeon environment. The Mantis adapter, dataset generation,
16D virtual gripper implementation, multi-seed training, and G3/G4 evaluation
remain unverified and require their own promotion gates.

The current persistence receipts verify only the new mount, base-image
inventory, and a single-session write/read/delete lifecycle. The prior Stage
1/2 receipts belong to the destroyed worker. Training, inference, evaluation,
migration, and new-worker ROCm execution remain separately gated.
