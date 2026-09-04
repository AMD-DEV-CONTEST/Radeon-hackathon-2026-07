# Tool and Workflow Contracts

## Design rules

- JSON-compatible inputs and outputs;
- strict unknown-field rejection;
- explicit SI units in field names;
- finite numerical inputs only;
- normalized scenario retained in the report;
- immutable model version and assumptions;
- no LLM-generated physical values.

## Composite case

```json
{
  "site": {
    "site_id": "demo-aquifer-001",
    "event_type": "hypothetical_subsurface_release",
    "radionuclide": "Cs-137",
    "release_pathway": "groundwater",
    "source_description": "Hypothetical maintained boundary release",
    "data_provenance": "demonstration",
    "data_classification": "public"
  },
  "transport": {
    "scenario_id": "cs137-realistic-groundwater",
    "initial_concentration_bq_m3": 1000000.0,
    "distance_m": 100.0,
    "evaluation_times_s": [0.0, 5000000000.0, 10000000000.0],
    "distribution_coefficient_m3_kg": 0.2,
    "bulk_density_kg_m3": 1700.0,
    "porosity": 0.35,
    "groundwater_velocity_m_s": 0.00001,
    "dispersion_m2_s": 0.001,
    "potassium_mg_l": 20.0,
    "competition_coefficient_l_mg": 0.01,
    "half_life_years": 30.018
  },
  "query": "How does potassium competition affect Cs-137 transport?"
}
```

## Site assessment

The Site Agent returns:

```json
{
  "site_id": "demo-aquifer-001",
  "normalized_context": {},
  "missing_critical_data": ["site_specific_kd", "mineralogy", "ph"],
  "screening_only": true,
  "warnings": ["Site characterization is incomplete or non-site-specific; results are screening-only"]
}
```

The current physics tool accepts only `Cs-137` and `groundwater`.

## Transport result

```json
{
  "tool": "simulate_transport",
  "model_version": "transport-prototype-0.3",
  "scenario_id": "cs137-realistic-groundwater",
  "inputs": {},
  "points": [
    {
      "time_s": 5000000000.0,
      "concentration_bq_m3": 24733.23865826807,
      "effective_kd_m3_kg": 0.16666666666666669,
      "retardation_factor": 810.5238095238097,
      "travel_time_s": 8105238095.238097,
      "decay_factor": 0.026087
    }
  ],
  "assumptions": [],
  "warnings": []
}
```

The example is from the verified deterministic implementation. Floating-point serialization may show additional digits.

## Workflow result

`workflow.json` contains:

- `session_id`;
- six-step `plan`;
- `site_assessment`;
- ranked `knowledge_hits` with citations;
- deterministic `tool_result`;
- `memory_turns`;
- five Track 2 `capabilities`;
- `denied_actions`;
- combined warnings.

## Uncertainty range contract

```json
{
  "potassium_mg_l": {
    "low": 0.0,
    "high": 40.0,
    "distribution": "uniform",
    "classification": "demonstration-range",
    "source": "Competition sensitivity scenario; measure site water chemistry"
  }
}
```

Allowed distributions are `uniform`, `log_uniform` and `triangular`.

## Manifest

`manifest.json` maps relative artifact paths to SHA-256 checksums. It intentionally excludes itself.
