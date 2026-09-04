# Phase D2–D3: observation inference boundary

The platform accepts immutable, schema-strict JSON and CSV observations. Records require radionuclide, receptor/location ID, ISO-8601 timestamp, value, supported unit, positive uncertainty, detection-limit fields, and non-empty provenance. Supported concentration units normalize to `Bq/m3`; unknown, ambiguous, malformed, or incompatible fields fail closed.

Gaussian and left-censored Gaussian log-likelihoods are validation-only utilities. `bounded_grid_recovery` evaluates a caller-supplied deterministic predictor over an explicit finite parameter grid and reports ties or flat objectives as non-identifiable. It is a deterministic synthetic parameter-recovery harness, not Bayesian inference and makes no posterior claims.

HMC/NUTS remains gated pending an optional inference backend and validated observational data. No sampler is implemented or implied by these utilities. The Sr-90 mechanistic boundary remains governed by `docs/SR_EVIDENCE_GATE.md`.
