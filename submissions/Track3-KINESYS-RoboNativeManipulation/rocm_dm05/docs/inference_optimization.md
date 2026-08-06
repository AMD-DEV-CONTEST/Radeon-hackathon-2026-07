# DM0.5 AMD inference optimization

The public evaluator enables three changes that preserve the 10-step
`DishwasherUnloadCutleryLong` policy contract.

## 1. Direct merged-model loading

The published checkpoint already contains the task adapter merged into the base
weights. Building the inference graph with `use_lora=True` would inject a
second, empty rank-32 path and unnecessary GEMMs. The evaluator detects adapter
checkpoints, but explicitly passes `--no-lora-wrapper` for a full checkpoint.

In a same-seed four-step operator A/B used to isolate graph overhead, direct
loading reduced policy latency from 729.4 to 633.9 ms (13.1%). A steady Torch
Profiler A/B measured 675.6 to 548.5 ms (18.8%), with GPU self kernel time down
about 12.4%. This microbenchmark is not the release quality protocol. Action
tensors were unchanged because the removed adapter contained no learned
weights.

The merge utility performs PEFT safe merge, rejects remaining adapter tensor
names and records weight SHA-256 values in `merge_manifest.json`.

## 2. Inference mode

Both native and 3DGS policy calls run under `torch.inference_mode()`. This
removes autograd bookkeeping without changing model weights, diffusion noise or
action tensors.

## 3. Action Expert KV workspace reuse

The reference Action Expert concatenates the long visual-language prefix and
the 16-token action suffix for every layer and diffusion step. Profiling measured
about 10.1 ms of `aten::cat` work per policy call. The AMD runtime patch
allocates reusable prefix/suffix workspaces, copies the stable prefix once and
updates only the suffix region.

The 10.1 ms operator measurement used the same four-step profiling harness. The
reference and patched paths produced identical action chunks on validation
observations. The feature is enabled by `--reuse-kv-workspace` and implemented
in `patches/opendm-amd-inference-optimizations.patch`.

## AMD performance snapshot

The merged-model path with `torch.inference_mode()`, Action Expert KV workspace
reuse and four diffusion steps was measured on one Radeon PRO W7900. After four
warm-up calls, the next 28 policy calls averaged 438.72 ms end to end (median
440.77 ms, P90 446.04 ms). During the matching closed-loop window, mean GPU
utilization was 67.68% and peak VRAM was 12.79 GiB.

The lower inference utilization is expected: one policy call alternates VLM
prefix work, four sequential Action Expert denoising steps, host-side action
conversion and simulator work. It is not evidence of an out-of-memory or data
loading bottleneck. This four-step snapshot is an operator-performance result;
the release success-rate protocol below intentionally retains 10 diffusion
steps.

## Quality protocol

The release keeps 10 diffusion steps for the long-horizon task. Under seeds
`200000-200049`, 20 Hz, chunk 16, execute 8 and maximum 800 policy steps, the
full checkpoint achieved:

| Visual domain | Success |
| --- | ---: |
| Native BiGym | 25/50 (50%) |
| Public 3DGS kitchen shell | 20/50 (40%) |

The default protocol is frozen in `scripts/run_eval.py` and is shared by native
and 3DGS evaluation. Every summary records diffusion steps, model load mode, KV
reuse and the exact seed list.

## Reproduce

```bash
NUM_EPISODES=50 SEED_START=200000 DIFFUSION_STEPS=10 AMD_GPU_IDS=0 \
  bash scripts/run_amd_eval.sh native \
  "$MODEL_PATH" "$OFFICIAL_DEMO" "$OUTPUT_ROOT/native-50"
```

An optimization is accepted only after finite-action checks, action comparison
and fixed-seed closed-loop evaluation.
