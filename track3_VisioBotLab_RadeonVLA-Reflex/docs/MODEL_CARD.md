---
license: other
library_name: lerobot
base_model: lerobot/smolvla_base
tags:
  - robotics
  - vision-language-action
  - imitation-learning
  - amd-rocm
  - genesis
---

# RadeonVLA-Reflex SmolVLA Physical-2K cumulative-200K Model Card

> Release status: cumulative-200K checkpoint complete, locally hash-verified, and evaluated on
> 100 disjoint-seed strict-physics rollouts. The learned first attempt succeeds on 36/100; the
> explicitly enabled Precision-Reflex system finishes 91/100.

## Model

- Base model: lerobot/smolvla_base
- Base revision: `c83c3163b8ca9b7e67c509fffd9121e66cb96205`
- Fine-tuned checkpoint: Physical-1K 100K history + Physical-2K 100K continuation
- Public URL: https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k
- Local checkpoint tree SHA256: `ad0ec7c1271b73b0ba684180b71a80ae1a9dad22c64a38796ba28f6597991683`
- Evaluation implementation: `c5c37576d4b80f056205ef7920a5f1ebfa614f86`
- Dataset: https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k
- Dataset revision: `2779b7c5566df9072bb9a7c43335d6203ea97887`

## Download and load

```bash
python -m radeonvla.download_artifacts --artifact physical-2k model-200k
python - <<'PY'
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

path = "checkpoints/radeonvla_reflex_smolvla_2k_200k"
policy = SmolVLAPolicy.from_pretrained(path)
print("loaded:", path, "parameters:", sum(p.numel() for p in policy.parameters()))
PY
```

The full 20-task × 5-seed command is documented in `README.md` under
“Reproduction sequence.”

## Intended use

Language-conditioned Franka fruit sorting in the project Genesis scene.

## Inputs and outputs

- Image inputs: observation.images.world + observation.images.wrist (320×240 RGB); renamed to camera1/camera2 for SmolVLA
- State shape and ordering: 9-D qpos — panda_joint1..7, panda_finger_joint1..2
- Language input: natural-language task instruction
- Action type, shape, and ordering: 9-D absolute joint positions (same order as state)
- Control frequency: 20 Hz
- Action chunk size: determined by SmolVLA checkpoint config

## Training

| Item | Value |
|---|---|
| Radeon GPU | AMD Radeon Graphics, `gfx1100`, 51.5 GB VRAM |
| ROCm | 7.2.1 / HIP runtime 7.2.53211 |
| PyTorch | 2.9.1+rocm7.2.1 |
| Precision | FP32 (`use_amp=false`) |
| Batch size | 4 |
| Gradient accumulation | Not configured; one optimizer update per batch |
| Cumulative training steps | approximately 200,000 |
| Final continuation | 100,000 steps / 400,000 sampled frames |
| Final continuation time | 3h 45m 32s |
| Final throughput | 30 samples/s / 7.41 optimizer steps/s |
| Peak training memory reported by LeRobot | 2.22 GB |
| Final logged minibatch loss | 0.058 |

## Evaluation

The formal benchmark covers 20 L1 tasks × 5 disjoint seeds (100 total, seeds 52000–52099)
using the exact language stored during collection. `first_attempt_success` measures learned
SmolVLA execution. When explicitly enabled, Precision Reflex handles terminal failures with
the strict-physics geometry controller under `forbid_rigid_pose_writes()` and
`allow_kinematic_assist=False`; no fruit pose reset, teleport, grasp glue, or placement nudge
is permitted.

| Metric | Result |
|---|---:|
| Learned first-attempt success | 36/100 (36.0%; Wilson 95% CI 27.3–45.8%) |
| Precision-recovery attempts | 63 |
| Precision-recovery success | 55/63 (87.3%) |
| Precision-recovery contribution | 55/100 (55.0 points) |
| Final system success | 91/100 (91.0%; Wilson 95% CI 83.8–95.2%) |
| Inference latency P50 / P95 | 4.54 ms / 37.27 ms |

The nine retained failures are eight `empty_grasp` events and one `wrong_object` event.
Final success by fruit is apple 20/20, banana 19/20, lemon 19/20, orange 17/20, and plum
16/20. The latency values were recorded while five disjoint evaluation partitions shared
one Radeon GPU and therefore include concurrent-evaluation contention.

## Limitations

Training and evaluation are limited to Genesis simulation. Coverage includes the
registered language and task suite, dual RGB cameras at 320×240, and 9-D absolute joint
actions. Precision recovery uses simulator geometry and is not evidence of learned visual
recovery. Real-robot transfer is outside the current evaluation scope. The published card
lists failure modes observed in the final evaluation run.

## License note

The upstream `lerobot/smolvla_base` repository did not declare license metadata when the
base revision above was frozen. This model card therefore uses Hugging Face's `other`
marker instead of inventing a permissive license. The Physical-2K training dataset is
CC BY 4.0 and its attribution requirements remain applicable to the dataset and rendered
examples. Users must review the upstream base-model terms before redistribution or
commercial use.
