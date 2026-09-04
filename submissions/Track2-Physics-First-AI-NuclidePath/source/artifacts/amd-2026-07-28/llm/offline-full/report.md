# Nuclear Emergency Transport Report - cs137-realistic-groundwater

> Private local-agent report. Deterministic tools remain authoritative; the model is not validated for operational radiological assessment.

## Execution provenance

- Mode: `offline`
- Planner: `deterministic`
- Physics tool: `simulate_transport`
- Model version: `transport-prototype-0.3`
- LLM required: `no`

## Scenario inputs

| Parameter | Value |
|---|---:|
| `scenario_id` | `cs137-realistic-groundwater` |
| `initial_concentration_bq_m3` | `1000000.0` |
| `distance_m` | `100.0` |
| `evaluation_times_s` | `[0.0, 1000000000.0, 2000000000.0, 3000000000.0, 4000000000.0, 5000000000.0, 6000000000.0, 7000000000.0, 8000000000.0, 9000000000.0, 10000000000.0]` |
| `distribution_coefficient_m3_kg` | `0.2` |
| `bulk_density_kg_m3` | `1700.0` |
| `porosity` | `0.35` |
| `groundwater_velocity_m_s` | `1e-05` |
| `dispersion_m2_s` | `1e-05` |
| `potassium_mg_l` | `20.0` |
| `competition_coefficient_l_mg` | `0.01` |
| `half_life_years` | `30.018` |

## Potassium comparison

| Case | K+ (mg/L) | Kd_eff (m³/kg) | R (-) | Travel time (years) | Sampled maximum (Bq/m³) |
|---|---:|---:|---:|---:|---:|
| K+ = 0 mg/L | 0 | 0.2 | 972.429 | 308.144 | 1127.54 |
| K+ = 20 mg/L | 20 | 0.166667 | 810.524 | 256.839 | 3614.87 |

## Time-series points

### K+ = 0 mg/L

| Time (s) | Concentration (Bq/m³) | Kd_eff (m³/kg) | R (-) |
|---:|---:|---:|---:|
| 0 | 0 | 0.2 | 972.429 |
| 1e+09 | 1.83591e-81 | 0.2 | 972.429 |
| 2e+09 | 6.12492e-30 | 0.2 | 972.429 |
| 3e+09 | 1.16839e-13 | 0.2 | 972.429 |
| 4e+09 | 3.46319e-06 | 0.2 | 972.429 |
| 5e+09 | 0.0314206 | 0.2 | 972.429 |
| 6e+09 | 5.15318 | 0.2 | 972.429 |
| 7e+09 | 89.4369 | 0.2 | 972.429 |
| 8e+09 | 408.43 | 0.2 | 972.429 |
| 9e+09 | 843.54 | 0.2 | 972.429 |
| 1e+10 | 1127.54 | 0.2 | 972.429 |

### K+ = 20 mg/L

| Time (s) | Concentration (Bq/m³) | Kd_eff (m³/kg) | R (-) |
|---:|---:|---:|---:|
| 0 | 0 | 0.166667 | 810.524 |
| 1e+09 | 4.58199e-64 | 0.166667 | 810.524 |
| 2e+09 | 1.50977e-21 | 0.166667 | 810.524 |
| 3e+09 | 2.08691e-08 | 0.166667 | 810.524 |
| 4e+09 | 0.0133301 | 0.166667 | 810.524 |
| 5e+09 | 10.3574 | 0.166667 | 810.524 |
| 6e+09 | 300.711 | 0.166667 | 810.524 |
| 7e+09 | 1484.69 | 0.166667 | 810.524 |
| 8e+09 | 2832.43 | 0.166667 | 810.524 |
| 9e+09 | 3460.48 | 0.166667 | 810.524 |
| 1e+10 | 3614.87 | 0.166667 | 810.524 |

## Assumptions and warnings

- 1-D homogeneous saturated semi-infinite medium
- constant concentration boundary at x=0; zero initial concentration for x>0
- reactive Ogata-Banks analytical solution
- groundwater_velocity_m_s is pore-water velocity
- empirical competitive adsorption
- WARNING: Prototype model; not validated for operational radiological assessment

This output is a screening demonstration. It must not be used for operational radiological decisions.

## Private agent workflow

| Capability | Verified in this run |
|---|---|
| `local_knowledge_retrieval` | yes |
| `tool_invocation` | yes |
| `multi_step_planning` | yes |
| `local_multi_turn_memory` | yes |
| `permission_privacy_control` | yes |

### Execution plan

`validate_permissions` → `site_agent` → `knowledge_retrieval` → `environment_agent` → `store_memory` → `synthesize_report`

### Local knowledge citations

- **One-dimensional reactive advection–dispersion screening** — The deterministic tool evaluates a reactive Ogata–Banks analytical solution on a homogeneous saturated semi-infinite domain. A constant dissolved Cs-137 concentration is imposed at `x=0`; the initial concentration is zero for `x>0`. Retardation is `R = 1 + rho_b Kd_eff / porosity`, pore-water travel time is marked by `xR/v`, and radioactive decay acts in dissolved and sorbed phases. ([source](https://pubs.usgs.gov/pp/0411a/report.pdf) if URL is available)
- **Cs-137 decay and emergency-use limitations** — The adopted Cs-137 physical half-life is `30.018 ± 0.022 years`, from the 2024 DDEP re-evaluation. This is a physical literature constant; environmental transport parameters remain site-dependent. The reactive Ogata–Banks solution treats radioactive decay in dissolved and sorbed phases at the same physical decay constant. ([source](https://pubmed.ncbi.nlm.nih.gov/38290201/) if URL is available)

## Uncertainty summary

Method: `independent seeded Monte Carlo`, samples: `128`, seed: `42`.

| Metric | P05 | P50 | P95 |
|---|---:|---:|---:|
| `effective_kd_m3_kg` | 0.0516213 | 0.430263 | 3.07419 |
| `retardation_factor` | 250.268 | 2179.18 | 16480.1 |
| `travel_time_s` | 9.49249e+08 | 2.28541e+10 | 4.64841e+11 |
| `sampled_max_concentration_bq_m3` | 0 | 0.000292729 | 499483 |
| `final_concentration_bq_m3` | 0 | 0.000292729 | 499483 |

Uncertainty intervals propagate declared input ranges only; they do not represent total predictive uncertainty.
