# Primary-paper Bradbury–Baeyens GCS implementation

## Status and scope

**Implemented:** a deterministic, primary-paper-verified three-site cation-exchange model for concentration-dependent Cs uptake on reference illite and illite-bearing argillaceous material. The opt-in multispecies v2 transport path uses aqueous K and Na on all three sites and NH4 on FES, exactly where the primary paper provides coefficients.

This remains a research screening model—not a calibrated site model, kinetic exchange model, regulatory method, or universal clay model. The original Cs/K-only API and parameter file remain unchanged because the checked-in guarded surrogate is tied to that legacy oracle and its parameter hash.

## Primary source and artifact identity

Bradbury, M.H. & Baeyens, B. (2000), *A generalised sorption model for the concentration dependent uptake of caesium by argillaceous rocks*, Journal of Contaminant Hydrology 42, 141–163, DOI `10.1016/S0169-7722(99)00094-7`.

The supplied 23-page PDF was directly inspected. SHA-256:

```text
8a9a90a8a8e414b8936c4ab9c3e923023424b7159c66ca1418d7bdf83dbb78ac
```

The copyright PDF is not committed. Its derived, versioned parameter record is `src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json`.

## Parameters from Tables 1 and 2

Reference-illite CEC: `0.20 equiv/kg` (`0.20 mol charge/kg`).

| Site | Source capacity (% CEC) | Implemented capacity | log10 Kc(Cs/K) | log10 Kc(Cs/Na) | log10 Kc(K/Na) | log10 Kc(NH4/K) |
|---|---:|---:|---:|---:|---:|---:|
| FES | 0.25 | 0.25% | 4.6 | 7.0 | 2.4 | 1.1 |
| Type-II | 20 | 20% | 1.5 | 3.6 | 2.1 | not reported |
| Planar | ~80 | 79.75%, residual | 0.5 | 1.6 | 1.1 | not reported |

The rounded source percentages total 100.25%. The implementation preserves FES and Type-II and derives planar capacity as the exact residual. It does not invent Type-II or planar NH4 coefficients. The paper estimates selectivity-coefficient uncertainty as `±0.2 log10 units`.

## Mass-action calculation

For each site, equivalent-fraction weights are written relative to K using the Gaines–Thomas definitions in equations 1–8:

```text
w_K   = [K]
w_Na  = [Na] / Kc(K/Na)
w_Cs  = Kc(Cs/K) × [Cs]
w_NH4 = Kc(NH4/K) × [NH4]    # FES only

N_Cs = w_Cs / (w_K + w_Na + w_Cs + w_NH4)
Γ_Cs = Q_site × N_Cs
Kd_illite = Σ Γ_Cs / [Cs]
Kd_bulk   = illite_mass_fraction × Kd_illite
```

All aqueous concentrations are mol/L. Since these exchanged species are monovalent, mol charge/kg is numerically mol Cs/kg; this must not be generalized to divalent exchange.

## Ion treatment

- `K`: competitive on FES, Type-II and planar sites.
- `Na`: competitive on all three sites using Table 2.
- `NH4`: competitive on FES only; no unsupported coefficients are inferred.
- `Ca`, `Mg`, `Sr`: preserved in scenario chemistry but treated as effectively noncompetitive in this Cs model, matching the paper's hydration/steric conclusion. This is not a sorption model for Sr-90.

## Applicability and uncertainty

The implementation emits warnings outside the paper's nominal applicability:

- pH approximately 6–9;
- equilibrium Cs concentration below approximately `1e-3 mol/L`;
- illite-dominated sorption assumption;
- equilibrium exchange, no kinetics or activity-coefficient correction.

The paper tested Boom Clay, Oxford Clay, Palfris Marl and Opalinus Clay and reported prediction generally within a factor of 2–3. That is a paper-specific validation result, not guaranteed site accuracy.

## Verification

- `tests/test_gcs_primary.py`: exact primary parameters and PDF identity, mass balance, occupancy bounds, K/Na/NH4 monotonic competition, illite scaling, applicability warnings, invalid inputs and immutable provenance.
- `tests/test_scenario_v2.py`: use of K/Na/NH4 in transport integration, explicit Ca/Mg noncompetition, no double K correction, Cs-only GCS boundary and legacy stability.
- `tests/test_gcs.py` and `tests/test_gcs_surrogate.py`: legacy oracle and surrogate compatibility.

These tests verify source transcription and software behavior. They do not constitute new experimental or regulatory validation.

## Exact batched acceleration

`nuclear_agent.gcs_primary_accelerated.calculate_primary_kd_batch` evaluates the same mass-action equations with optional PyTorch tensor operations. It is deliberately **not a learned surrogate**: there are no fitted weights, training domain, or approximation gate. FP64 is the canonical parity path; FP32 is an explicitly lower-precision throughput option.

The dependency-free scalar API remains the default for single cases and rich provenance output. The batch API is intended for Monte Carlo, parameter sweeps and calibration workloads and returns Kd arrays plus backend/device/dtype metadata. PyTorch uses the device name `cuda` for both ROCm and NVIDIA builds.

Controller CPU measurement, 100,000 cases, seven repeats, PyTorch `2.13.0+cpu`, FP64:

| Path | Median time | Relative error vs scalar |
|---|---:|---:|
| scalar rich-result API | 1.0356 s | reference |
| exact batched Kd API | 0.1413 s | max `4.44e-16` |

Measured end-to-end speedup: **7.33×**. The benchmark includes tensor construction and host result conversion; the scalar path also constructs full provenance-rich result objects, so this is an application-API comparison rather than an isolated arithmetic-kernel claim. Artifact: `artifacts/controller-2026-07-28/primary-gcs-exact-batch-cpu.json`.

The AMD ROCm rerun is complete. FP64 device-resident GCS measured 3.41 million scenarios/s with `4.44e-16` maximum relative Kd error; the full GCS→transport→receptor pipeline measured 82.66 million concentration evaluations/s and 137.09× versus scalar with `7.94e-14` maximum relative error. See [AMD_PLATFORM_BENCHMARK.md](AMD_PLATFORM_BENCHMARK.md).

## Primary-paper rock input reconstructions

`bradbury-rocks-1.0` records the Table 4 mineralogy ranges and Table 5 water chemistry for Boom Clay, Oxford Clay, Palfris Marl and Opalinus Clay. The record preserves unreported values as `null`, carries the primary PDF hash/DOI, and is loaded through a strict immutable schema. Weight-percent and weight-fraction fields are deliberately distinct.

`predict_cs_isotherm_envelope` evaluates the canonical `bradbury-baeyens-gcs-2.0` oracle with simultaneous K/Na/NH4 competition at the lower and upper reported illite fractions. Unreported NH4 is explicitly treated as absent; no fallback concentration is invented.

`sample_selectivity_uncertainty` propagates the paper's `±0.2 log10` coefficient estimate under one explicitly **demonstrative** interpretation: a seeded uniform, perfectly correlated systematic shift of Cs/K and Cs/Na coefficients. This preserves the Equation 8 K/Na relationship exactly. The paper does not prescribe that probability distribution or correlation model, so these P05/P50/P95 bands are not a complete predictive uncertainty interval.

These outputs are **paper-input reconstructions, not digitized measured-isotherm validation**. Figures 7–10 have not yet been digitized; therefore NuclidePath does not yet claim to independently reproduce the paper's stated factor-2–3 agreement.
