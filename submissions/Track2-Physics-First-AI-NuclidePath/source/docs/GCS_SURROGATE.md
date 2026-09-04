# Guarded GCS surrogate — research-only AMD evidence

## Scope

This optional PyTorch model approximates the output of NuclidePath's deterministic **Cs/K-only software oracle**. It does not approximate experimental observations, does not establish that the secondary Bradbury transcription is correct, and is not a regulatory or operational model.

The canonical oracle remains `nuclear_agent.gcs.calculate_kd`. Surrogate use is allowed only when its immutable metadata, oracle-parameter hash, domain, dtype, tensor schema, held-out error metrics, and declared acceptance gate all validate. Every rejected case falls back explicitly to the deterministic oracle or returns a fail-closed rejection when even the oracle input is invalid.

## Demonstration training domain

| Input | Domain |
|---|---:|
| `log10(K [mol/L])` | -6 to -1 |
| `log10(stable Cs [mol/L])` | -12 to -3 |
| Illite mass fraction | 0.01 to 1.0 |

These are demonstration sampling bounds selected for software approximation. They are not environmental validity ranges.

The output is `log10(bulk Kd [L/kg])`.

## Reproducible AMD training

- GPU: AMD Radeon Graphics, `gfx1100`
- PyTorch: ROCm build documented by the AMD environment evidence
- dtype: FP64
- architecture: `3 → 64 → 64 → 1`, tanh activations
- optimizer: Adam, learning rate 0.01
- loss: MSE in log10 Kd
- training samples: 40,000
- epochs: 30,000
- training seed: 20260728
- independent final-validation samples: 100,000
- final-validation seed: 20260730

The validation set is independently generated from the deterministic oracle and is not used for optimization.

## Accuracy gate

Metrics are calculated in linear Kd space:

```text
relative error = abs(10^predicted_log10_Kd / 10^oracle_log10_Kd - 1)
```

Independent 100,000-case result:

| Metric | Result |
|---|---:|
| Maximum relative Kd error | 0.113673 (11.37%) |
| Median relative Kd error | 0.009598 (0.96%) |
| Declared research demonstration gate | max ≤ 0.15 |
| Gate result | pass |

The 15% maximum-error gate is an explicit software-approximation criterion chosen for this research prototype. It is not a scientific, environmental, dose, or regulatory tolerance.

## Measured performance

On an independent 100,000-case batch:

| Path | Time | Throughput |
|---|---:|---:|
| Deterministic CPU oracle, parameters loaded once | 0.7753 s | 128,980 evaluations/s |
| Single batched ROCm FP64 forward pass | 0.006378 s | 15,678,356 evaluations/s |

Measured kernel-only speedup: **121.56×**.

The surrogate timing excludes feature-tensor construction and host transfer. The CPU oracle timing includes scalar Python calculation but excludes repeated parameter-file loading. This is not an end-to-end application latency claim.

## Artifact and guard contract

Evidence and model files are under `artifacts/amd-2026-07-28/surrogate/`:

- JSON metadata;
- tensor-only `.pt` state loaded with `weights_only=True`;
- SHA-256 hashes;
- independent benchmark JSON;
- training-run metadata.

Safeguards include:

- exact oracle parameter SHA-256;
- deeply immutable metadata;
- authoritative metadata domain;
- separate training and validation seeds;
- explicit dtype and architecture;
- exact tensor keys, shapes, and dtypes;
- atomic writes and post-save reload verification;
- safe malformed-artifact errors;
- invalid/nonfinite input rejection;
- outside-domain and failed-inference oracle fallback;
- mandatory validation metric threshold.

## Usage

Training is optional and requires PyTorch:

```bash
train-gcs-surrogate \
  --samples 80000 \
  --epochs 30000 \
  --seed 20260728 \
  --validation-seed 20260729 \
  --device cuda \
  --dtype float64 \
  --output gcs-surrogate.json
```

The CLI uses `cuda` as PyTorch's device name for both CUDA and ROCm builds. It rejects the request when `torch.cuda.is_available()` is false.

The checked-in model is evidence of a specific research run, not a universal default. Production callers must use `predict_guarded`; direct unguarded model inference is outside the supported contract.
