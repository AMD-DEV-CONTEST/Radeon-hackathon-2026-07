---
library_name: transformers
base_model: Dexmal/DM05
license: other
license_name: Gemma Terms of Use
tags:
  - robotics
  - embodied-ai
  - vision-language-action
  - bigym
  - opendm
  - rocm
  - amd
datasets:
  - WuChao-Cauchy/bigym_plus
---

# DM05 BiGym DishwasherUnloadCutleryLong

Standalone BF16 OpenDM DM0.5 checkpoint for BiGym
`DishwasherUnloadCutleryLong`. The task LoRA is merged into `Dexmal/DM05`, so
inference does not require a second adapter or base-model download.

## Results

| Visual domain | Seeds | Result |
| --- | --- | ---: |
| Native BiGym | `200000-200049` | 25/50 (50%) |
| Public 3DGS kitchen shell | `200000-200049` | 20/50 (40%) |

Protocol: 20 Hz control and policy, action chunk 16, 10 diffusion steps,
execute 8 actions per model call, maximum 800 policy steps, sequence length 896
and prompt `Unload cutlery from dishwasher to drawer task.`.

The AMD runtime was validated on a Radeon PRO W7900 with ROCm 7.2.1 and PyTorch
2.8.0 for ROCm. A final strict 10-step 3DGS gate succeeded on seed `200009` in
567 control steps at 726.58 ms mean model latency. The shell is visual only;
MuJoCo remains the physics and success engine.

## Fine-tuning recipe

- Base model: `Dexmal/DM05`
- Data: 32 successful LeRobot v3 trajectories
- Observations: head and two wrist RGB cameras plus 16D state
- Action: 16D absolute command with cumulative floating base, arm joints and
  grippers
- LoRA: rank 32, alpha 16, all linear and OpenDM action/time modules
- Effective batch 48; learning rate `5e-4`; warmup 500; 10,000 steps
- Model sequence length 896

The complete AMD training, merge, inference and strict 3DGS evaluation workflow
is maintained in
[`Kyrie-w8/amd-bigym-3dgs-opendm`](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm).

## Limitations

- This checkpoint is task-specific, not a general-purpose robot policy.
- Results depend on the exact simulator, seeds, cameras, action definition and
  control protocol.
- The large 3DGS shell is not included with the model. Download revision
  `amd-rocm-w7900d-20260804` from
  [`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804)
  and verify it with `scripts/download_3dgs_shell.py`.

## License

This checkpoint is a derivative work — the task LoRA is merged into the
`Dexmal/DM05` base model, whose weights are distributed under Google's Gemma
Terms of Use. Per those terms, distribution of this derivative must include the
Gemma Terms and downstream recipients must accept terms at least as restrictive
as the Gemma Terms. The repository SOURCE CODE remains Apache-2.0; this license
applies to the model weights only.
