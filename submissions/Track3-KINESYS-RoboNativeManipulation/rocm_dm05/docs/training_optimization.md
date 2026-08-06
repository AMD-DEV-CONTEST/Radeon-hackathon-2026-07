# DM0.5 AMD training optimization

Every optimization below was retained after a real training-step benchmark
with finite loss.

## Measurement scope

The controlled throughput study used one AMD Radeon PRO W7900 (`gfx1100`, 96
CUs, 48 GiB), ROCm 7.2.1, PyTorch 2.8.0, Triton 3.4 and Liger Kernel 0.8.0.
The workload was DM0.5 LoRA rank 32 on BiGym ReachTarget with three 448-pixel
cameras, 15D absolute actions, chunk 16 and micro-batch 8.

These absolute timings belong to that ReachTarget benchmark. The public
CutleryLong recipe uses the same effective runtime changes, but keeps sequence
length 896 because its own processed samples were not part of the 2,809-sample
ReachTarget length audit.

## Effective changes

### 1. Cache episode JSONL metadata in persistent workers

The OpenDM runtime patch caches each episode's parsed JSONL lines instead of
opening and allocating the same metadata on every sample. Two persistent
workers and prefetch factor 2 keep that cache alive across steps. The combined
data-path profile reduced the measured step from the 6.43-second long-run
reference to 5.614 seconds at sequence length 896.

The implementation is in `patches/opendm-runtime.patch`; the public launcher
keeps `DATALOADER_NUM_WORKERS=2` by default.

### 2. Use the shortest audited sequence length

All 2,809 processed ReachTarget samples were audited before changing
`model_max_length` from 896 to 880. No sample was truncated. That reduced mean
step time from 5.614 to 5.505 seconds and increased throughput from 1.425 to
1.453 samples/s.

This is a data contract, not a universal constant. The CutleryLong launcher
therefore defaults to 896. Set a lower value only after auditing every processed
sample in the target dataset:

```bash
MODEL_MAX_LENGTH=880 bash scripts/train_cutlery_amd.sh
```

### 3. Tune exact GEMM shapes once, then replay

PyTorch TunableOp selected rocBLAS/hipBLASLt implementations for 90 GEMM shapes
actually observed by the workload. Formal training disabled online tuning and
replayed the saved CSV.

At length 880, the 20-step screen improved from 5.505 to 5.103 seconds/step.
The conservative 40-step confirmation measured 5.169 seconds/step and 1.548
samples/s. A matched ROCprofiler trace showed 9.03% less total kernel time and
14.29% less GEMM time, while attention time changed by less than 1%.

A replay database is specific to GPU architecture, ROCm/PyTorch libraries,
batch, sequence and model shapes. Do not reuse the ReachTarget length-880 CSV
for CutleryLong length 896. Generate a database with a separate shape-coverage
run on the exact target workload, then use replay-only mode for formal training:

```bash
TUNABLEOP_FILENAME=/data/tunableop/cutlery-w7900-rocm7.2.1.csv \
OPENDM_TUNABLEOP_TUNING=1 \
RUN_NAME=cutlery-tunableop-discovery MAX_STEPS=100 \
NPROC=1 AMD_GPU_IDS=0 \
  bash scripts/train_cutlery_amd.sh

TUNABLEOP_FILENAME=/data/tunableop/cutlery-w7900-rocm7.2.1.csv \
OPENDM_TUNABLEOP_TUNING=0 \
RUN_NAME=dm05-cutlery-long-amd MAX_STEPS=10000 \
  bash scripts/train_cutlery_amd.sh
```

The launcher rejects a missing or empty replay file. Production logs must show
`TunableOp enabled` and `tuning=False`.

## Retained execution profile

The final benchmark kept LLM eager execution, Vision SDPA/AOTriton, Action
Expert SDPA, Liger kernels, VLM gradient checkpointing, Action Expert gradient
checkpointing disabled, fused AdamW, two persistent workers, cached JSONL
metadata and TunableOp replay. Checkpoints include adapter, optimizer,
scheduler, trainer state and normalization statistics so a resume preserves the
learning-rate schedule.

| Measured profile | Mean step | Throughput | Peak VRAM |
| --- | ---: | ---: | ---: |
| Long-run reference | 6.430 s | 1.244 samples/s | about 56% |
| Cached data, length 896 | 5.614 s | 1.425 samples/s | 57% |
| Cached data, length 880 | 5.505 s | 1.453 samples/s | 55% |
| Length 880 + TunableOp, 40-step confirmation | 5.169 s | 1.548 samples/s | 55% |

The final confirmed profile improved samples/s by 24.4% over the long-run
reference. After resuming the complete checkpoint-7000, formal steps continued
at the expected learning rate (about `1.519e-4` at step 7001) and stabilized at
about 5.08-5.11 seconds/step.

## CutleryLong batch-size selection

A separate matched sweep on the processed 32-episode
`DishwasherUnloadCutleryLong` workload tested larger micro-batches with the same
BF16 LoRA graph, sequence length 880, chunk 16, two persistent workers, LLM
eager execution, Vision and Action Expert SDPA, VLM gradient checkpointing and
Action Expert gradient checkpointing disabled. First-step compilation was
excluded and every retained step had finite loss.

| Micro-batch | Accumulation used for timing | Mean step | Throughput | Decision |
| ---: | ---: | ---: | ---: | --- |
| 8 | 1 | 5.3106 s | 1.5064 samples/s | Matched baseline |
| 12 | 1 | 7.8555 s | 1.5276 samples/s | Best throughput |
| 16 | 1 | 10.5247 s | 1.5202 samples/s | Rejected |

The production-equivalent confirmation used micro-batch 12 and gradient
accumulation 4, preserving effective batch 48. Two steady optimizer steps
averaged 31.3823 seconds, or 1.5295 samples/s. Mean GPU utilization was 99.47%
over the complete steady-step window and peak VRAM was 28.74 GiB. The public
launcher therefore defaults to `PER_DEVICE_BATCH=12` and
`GRADIENT_ACCUMULATION=4`; both remain explicit environment overrides.

These CutleryLong numbers are a workload-specific supplement. They do not
replace the ReachTarget TunableOp study above, whose replay database is tied to
batch 8 and its exact tensor shapes.

## Acceptance checks

For every new dataset or software stack, retain an optimization only when:

1. timed steps exclude warm-up and checkpoint writes;
2. loss and gradient norm remain finite;
3. no processed sample is truncated;
4. the replay database was generated on the exact shape/software profile;
5. resume restores optimizer, scheduler and trainer state.
