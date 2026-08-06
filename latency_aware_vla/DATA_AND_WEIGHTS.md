# Data and weights (not shipped in git)

Large assets stay on the AMD Radeon Cloud workspace (or your local mirror).

| Asset | Typical path |
|---|---|
| Env-A dataset (120 ep) | `datasets/franka-kitchen-fruit-place-120ep` · HF id `local/franka-kitchen-fruit-place-120ep` |
| SmolVLA / π0.5 / VLM bases | `/workspace/models/{smolvla_base,pi05_base,SmolVLM2-500M-Video-Instruct,paligemma-3b-pt-224}` |
| Train checkpoints | `output/train/{smolvla_fruit_place_b0,pi05_fruit_place_b1d}/final` |
| Eval videos | `output/eval/*/videos/` |
| Demo MP4 (local rebuild) | `artifacts/demo-video.mp4` · public: https://youtu.be/rXQQ4s-CxEE |

Workshop scene/asset trees used via symlinks on the cloud box
(`Robot_synthetic_data_generation_workshop/{assets,scenes}`) are not duplicated here.

Formal numbers: `artifacts/formal/`.
