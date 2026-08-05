# SmolVLA inference optimization change record

Date: 2026-08-04<br>
Hardware: AMD Radeon `gfx1100`, 96 CUs, 48 GiB VRAM<br>
Scope: inference-only changes; no training, weight, architecture, action horizon,
or denoising-step changes.

## Frozen result

The accepted deployment bundle reduced synchronized policy latency from
`321.7635 ms/replan` to `289.2548 ms/replan` (30 paired-order samples per side):

- latency reduction: `10.1033%`;
- speedup: `1.11239x`;
- baseline P10/P90: `313.1312 / 362.0245 ms`;
- optimized P10/P90: `288.0216 / 300.0382 ms`;
- maximum absolute action difference: `0.00092876`;
- mean absolute action difference: `0.00018328`.

The authoritative raw measurements are in
`reports/inference_optimization_final_gfx1100.json`.

## Accepted changes

1. `SMOLVLA_ATTENTION_BACKEND=sdpa_auto` permits PyTorch/ROCm to select a
   fused SDPA implementation instead of forcing `SDPBackend.MATH`.
2. `SMOLVLA_USE_INFERENCE_MODE=1` uses `torch.inference_mode()`.
3. `SMOLVLA_OPTIMIZE_LOOP=1` replaces the CUDA-scalar-controlled denoising
   loop with the configured fixed iteration count while retaining the same
   Euler update operations.
4. `SMOLVLA_CACHE_LANGUAGE=1` reuses token IDs and masks for an unchanged task
   string and device.
5. `SMOLVLA_CACHE_MODEL_LAYERS=1` reuses the static VLM/expert layer-reference
   lists.
6. `SMOLVLA_LIGHTWEIGHT_OUTPUT=1` omits the RL training payload for pure action
   deployment. Set it to `0` for Q-guidance or data collection.

## Continued optimization after the frozen commit

`SMOLVLA_CACHE_DENOISE_LAYOUT=1` moves the invariant suffix Boolean attention
mask and position IDs outside the 10-step denoising loop. It does not cache
actions, timestep embeddings, hidden states, or attention outputs.

An isolated 20-sample incremental comparison on top of the accepted deployment
bundle measured `290.1827 -> 289.2843 ms/replan`, a further `0.3096%` reduction.
The maximum/mean action differences were `0.00044155 / 0.00008707`. Raw results
are in `reports/inference_optimization_layout_incremental_gfx1100.json`.

`SMOLVLA_OPTIMIZE_RESIDUAL=0` is deliberately retained: removing the residual
clone did not improve measured latency.

## Validation protocol

- Same checkpoint, observation, task, reset state, and explicit flow noise.
- Five warmup calls and 30 timed calls per side.
- Baseline and candidate order alternated.
- GPU synchronized immediately before and after `predict_action_batch()`.
- LIBERO reset and environment stepping excluded from latency.
- A 20-step LIBERO Task 7/state 1 smoke test completed with finite actions.

## Reproduction

Benchmark:

```bash
python scripts/benchmark_smolvla_policy_latency.py \
  --model-path /path/to/pretrained_model \
  --warmup 5 --repeats 30 \
  --compare-inference-optimization \
  --optimization deployment_bundle \
  --optimized-backend sdpa_auto \
  --out reports/inference_optimization_final_gfx1100.json
```

Deployment:

```bash
./scripts/run_smolvla_inference_optimized.sh \
  --model-path /path/to/pretrained_model \
  --task-id 7 --task-reset-state-id 1 --seed 2001 \
  --action-steps 5 --max-steps 240 --no-video
```

## Rollback

All behavior changes are opt-in environment switches. Restore the original
inference path with:

```bash
export SMOLVLA_ATTENTION_BACKEND=sdpa
export SMOLVLA_USE_INFERENCE_MODE=0
export SMOLVLA_OPTIMIZE_LOOP=0
export SMOLVLA_OPTIMIZE_RESIDUAL=0
export SMOLVLA_CACHE_LANGUAGE=0
export SMOLVLA_CACHE_MODEL_LAYERS=0
export SMOLVLA_LIGHTWEIGHT_OUTPUT=0
export SMOLVLA_CACHE_DENOISE_LAYOUT=0
```
