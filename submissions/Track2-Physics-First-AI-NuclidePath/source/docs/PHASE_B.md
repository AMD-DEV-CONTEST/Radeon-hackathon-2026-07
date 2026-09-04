# Phase B1–B3

The optional PyTorch path now provides an exact tensor-native primary Bradbury–Baeyens GCS kernel (`calculate_primary_kd_tensor`) and an end-to-end `evaluate_scenarios_torch` pipeline. FP64 is the parity-oriented mode; FP32 is explicit and must be tolerance-checked by callers. The legacy tuple/scalar APIs remain unchanged and are the dependency-light fallback.

`evaluate_scenarios_torch` returns device-resident Kd, retardation, and scenario × receptor × time concentration tensors. It evaluates reactive Ogata–Banks transport with radionuclide decay. Scalar randomized parity is covered by the optional PyTorch tests when PyTorch is installed.

`run_morris` provides deterministic seeded Morris elementary effects (`effects`, `mu`, `mu_star`, `sigma`). These are screening sensitivities, not input-range spans, probabilities, or causal attribution. Sobol indices are not claimed.

Run dependency-light verification with `python -m pytest -q`. Optional PyTorch verification is `python -m pytest -q tests/test_gcs_primary_accelerated.py`; skipped tests indicate PyTorch is not installed. `scripts/benchmark_phase_b.py` is intentionally honest and makes no ROCm performance claim; live AMD artifacts are required before reporting ROCm results.
