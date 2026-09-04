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
| `evaluation_times_s` | `[0.0, 5000000000.0, 10000000000.0]` |
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
| 5e+09 | 0.0314206 | 0.2 | 972.429 |
| 1e+10 | 1127.54 | 0.2 | 972.429 |

### K+ = 20 mg/L

| Time (s) | Concentration (Bq/m³) | Kd_eff (m³/kg) | R (-) |
|---:|---:|---:|---:|
| 0 | 0 | 0.166667 | 810.524 |
| 5e+09 | 10.3574 | 0.166667 | 810.524 |
| 1e+10 | 3614.87 | 0.166667 | 810.524 |

## Assumptions and warnings

- 1-D homogeneous saturated semi-infinite medium
- constant concentration boundary at x=0; zero initial concentration for x>0
- reactive Ogata-Banks analytical solution
- groundwater_velocity_m_s is pore-water velocity
- empirical competitive adsorption
- WARNING: Prototype model; not validated for operational radiological assessment

This output is a screening demonstration. It must not be used for operational radiological decisions.
