> Chinese version: [README.md](README.md)

# Qwen3-32B Agentic LoRA-SFT (Judge-Focused Bundle)

This directory retains the core Radeon training code, runtime environment, five validation points, final-checkpoint manifest, and a compact training summary. Historical plans, preflight reports, launch/controller reports, and the complete run manifest were removed from the main tree so judges do not encounter a large collection of machine-generated JSON before the core result.

The complete original evidence has not been lost. It is pinned at [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training) (commit `c079855dabb11e50f7026b9da60e5b162e8f04d2`).

## One-Minute Verification

```bash
python3 verify_subset.py
```

This command uses only the Python standard library to verify file hashes in the current trimmed tree plus the Test row count and SHA-256. It requires no GPU, model weights, or network access. Start with [`evidence/training-summary.json`](evidence/training-summary.json) for the training result.

## Training Result

- Base model: `unsloth/Qwen3-32B-bnb-4bit@7f721e74a6a8cc9ee352f7e49303a2c1705f9083`
- Method: 4-bit NF4 base + LoRA-SFT (r=8, alpha=16, 67,108,864 trainable parameters), assistant-only shifted CE
- 1 epoch, 119 optimizer steps, 948 training micro-windows, maximum window of 8192 tokens
- Validation mean CE: 1.151614 (step 0) -> 0.593663 (step 119)
- Final adapter: 268,555,264 bytes, SHA-256 `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf`
- One AMD Radeon gfx1100 GPU; the Phase 2 PyTorch peak was 37,633,069,056 allocated / 38,593,888,256 reserved bytes

## What the Main Tree Retains

| Content | Location | Purpose |
|---|---|---|
| Trainer, controller, gate, and build tools | `configs/`, `gates/`, `tools/` | Show the actual training implementation |
| Pinned model revision and runtime environment | `artifacts/model-acquisition/`, `environment/` | Define the Radeon/ROCm and dependency context |
| Training summary and learning curve | `evidence/training-summary.json`, `evidence/validations/` | Enable a quick audit of the 119-step result |
| Final-checkpoint manifest | `evidence/checkpoint-000119/` | Bind the size and hash of the released adapter |
| Public Test | `../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl` | Independently recompute the Base/SFT A/B result |

The 946-row training split and 116-row validation split used for training are published in sanitized form on [ModelScope](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/summary). The 113-row Test was historically held out during evaluation and was released with the repository after evaluation solely to reproduce this result.

## Reproduction Scope

The public adapter is the artifact used by the demo and A/B evaluation. See [`../../model/README.en.md`](../../model/README.en.md) and [`../../model/serving/README.en.md`](../../model/serving/README.en.md) for download and serving interfaces. Full retraining is optional, and numerical results may vary with hardware and software versions.

The files under `configs/` are historical training originals with bound-host fail-closed gates, not cross-machine plug-and-play scripts. On another machine, regenerate the plan, model-verification manifest, and host gates. `tools/build_qwen3_32b_train_plan.py` and `tools/build_qwen3_32b_loss_window_plan_v2.py` provide the plan-construction logic; see [`docs/RUNBOOK.en.md`](docs/RUNBOOK.en.md) for the execution contract. Never treat an archived historical PASS as authorization for a new host.

## Evidence Boundary

The decline in validation CE proves that training ran and converged. The separate Base/SFT A/B raw outputs establish the Agentic capability gain. Neither result proves live `rdk-agent -> sophonctl -> RDK` board execution or a physical effect; those require evidence from the corresponding live demonstration.
