> Chinese version: [README.md](README.md)

# Evidence Boundary

The main tree retains only the training evidence required for rapid judge verification:

- `training-summary.json`: a compact index of the model, data, LoRA configuration, 119-step training, Radeon environment, peak VRAM, validation curve, and adapter hash;
- `validations/`: the five raw validation results from steps 0/30/60/90/119;
- `checkpoint-000119/`: the final checkpoint completion marker and binary size/SHA-256 manifest.

The original plan, preflight gates, launch bindings, Phase 1/2 Controller reports, `checkpoint-000010`, complete run manifest, and local ledger are pinned at the Git tag [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training). The tag points to commit `c079855dabb11e50f7026b9da60e5b162e8f04d2`, so later commit deletion, PR squashing, or branch cleanup does not affect the archive entry point.

The manifests here do not contain the adapter, optimizer, RNG, or complete checkpoint binaries. The public adapter is provided through `model/SHA256SUMS` and the ModelScope download location. Training evidence proves that the frozen code completed training on the original Radeon host; it cannot substitute for Agent, board, or physical-effect evidence.
