# Sensitivity and Uncertainty

## Purpose

NuclidePath separates deterministic physics from uncertainty propagation. The uncertainty layer explores declared assumptions; it does not convert demonstration ranges into site evidence.

## Declared ranges

| Parameter | Range | Distribution | Classification | Basis |
|---|---:|---|---|---|
| Cs Kd | 0.05–5.0 m³/kg | log-uniform | literature-informed demonstration range | spans low-end IAEA soil values through the PNNL Hanford bracket |
| porosity | 0.25–0.45 | uniform | demonstration | plausible granular-media bracket; measure on site |
| pore-water velocity | 1e-6–1e-4 m/s | log-uniform | demonstration | hydraulic bracket; derive from `K`, gradient and effective porosity |
| dispersion | 1e-6–1e-4 m²/s | log-uniform | demonstration | with baseline velocity, corresponds approximately to `alpha_L=0.1–10 m` |
| potassium | 0–40 mg/L | uniform | demonstration | ordinary-to-elevated chemistry sensitivity |
| competition coefficient | 0.005–0.02 L/mg | uniform | demonstration | uncalibrated empirical bracket |

No range is represented as total predictive uncertainty. Inputs are sampled independently because no defensible correlation model is available; that assumption is recorded as a limitation.

## One-at-a-time sensitivity

`run_sensitivity` evaluates low, baseline and high values while holding all other inputs fixed. It records:

- effective Kd;
- retardation factor;
- `xR/v` travel-time marker;
- sampled concentrations / breakthrough values;
- parameter provenance and classification.

Expected structural directions:

| Increase | Expected effect |
|---|---|
| Kd or bulk density | retardation and travel-time marker increase |
| porosity, with pore velocity held fixed | retardation decreases |
| pore-water velocity | travel-time marker decreases |
| K+ or empirical beta | effective Kd and retardation decrease |
| dispersion | front broadening increases; a point concentration need not vary monotonically |
| half-life | attenuation decreases |

Point concentration must not be assigned a universal monotonic direction with Kd, velocity or dispersion because movement and broadening can move a receptor before or behind the front.

## Seeded Monte Carlo

`run_monte_carlo` uses a local seeded pseudorandom generator. For each sample it:

1. samples each declared distribution;
2. executes `transport-prototype-0.3`;
3. stores sampled parameter values and outputs;
4. reports P05, median and P95;
5. exports the full CSV and seed.

The same inputs, seed, sample count and software version reproduce the numerical samples.

## Interpretation boundary

The reported interval excludes structural/model-form uncertainty, parameter correlations, source-duration uncertainty, spatial heterogeneity, measurement error and external validation error. It must not be presented as a regulatory confidence interval or probability of safety.

## Sources

- IAEA TECDOC-2095: <https://www.iaea.org/publications/15878/distribution-coefficients-for-soil-freshwater-and-marine-systems-for-exposure-assessments>
- Gelhar, Welty & Rehfeldt (1992): <https://doi.org/10.1029/92WR00607>
- PNNL-16531: <https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-16531.pdf>
