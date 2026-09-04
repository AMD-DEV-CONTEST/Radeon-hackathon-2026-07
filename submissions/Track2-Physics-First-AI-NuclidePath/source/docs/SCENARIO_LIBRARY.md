# Versioned scenario library and safety pipeline

Status: **implemented in `scenario-library-0.4`**. The underlying physics contract and optional CPU/ROCm analysis backend remain unchanged at `transport-prototype-0.3`.

## Packaged families

| ID | Purpose | Classification |
|---|---|---|
| `cs137-baseline-1d-v1` | homogeneous maintained-boundary 1-D breakthrough | demonstration |
| `cs137-potassium-stress-v1` | controlled empirical K+ competition comparison | demonstration |
| `cs137-conservative-uncertainty-v1` | pessimistic demonstration input brackets and seeded P05/P50/P95 summaries | demonstration |

Source JSON is under `scenarios/library/` and is also included in installed packages. Every entry declares `schema_version`, `library_version`, parameter-source classifications, citations or demonstration labels, expected qualitative behaviour, receptors, and uncertainty ranges.

The only literature-valued parameters in the library are explicitly cited:

- Cs Kd context: *PNNL-16531, Geochemical Data Package for the Vadose Zone in the Single-Shell Tank Waste Management Areas at the Hanford Site* (water-borne Cs range cited in each JSON), <https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-16531.pdf>.
- Cs-137 half-life: DDEP/LNHB Table of Radionuclides, <https://www.lnhb.fr/nuclides/Cs-137_tables.pdf>.

All hydraulic, dispersion, concentration, competition, receptor, and non-cited uncertainty values are labelled **demonstration**. They are not site measurements. The library contains no regulatory criteria.

## Deterministic execution

```bash
nuclear-emergency-demo \
  --scenario scenarios/library/conservative_uncertainty_v1.json \
  --output results/library-case \
  --samples 512 \
  --seed 42
```

The versioned path runs, in order:

1. `ScenarioValidationAgent` (`scenario-validation-0.4`) checks metadata, the existing strict transport contract and units encoded by field names, provenance, duration/half-life context, and maintained-boundary compatibility. Invalid input fails closed and retains a structured failure trace on `ScenarioValidationError.trace`.
2. `screen_virtual_receptors` (`virtual-receptors-0.4`) evaluates declared points on the same 1-D path and reports seeded arrival-time, final-concentration, and `sampled_max` P05/P50/P95 distributions. Arrival is retarded advective travel time, not detection time. `declared_range_priority` orders input spans for characterization only; it is not output-response sensitivity or causal attribution.
3. `ReportSafetyGate` (`report-safety-0.5`) admits only the structured publication fields produced by this pipeline and blocks unsupported supplemental fields, safety/protective-action/regulatory/dose/operational conclusions, unsupported `peak` wording, and results missing assumptions/tool/model provenance. This deterministic gate is defense in depth, not proof that permitted scientific text is authoritative.
4. Only after the gate passes are the report, receptor SVG, validation trace, and checksummed manifest written.

Generated files are `report.json`, `report.md`, `virtual_receptors.svg`, `scenario_validation.json`, and `manifest.json`.

## Limitations

Virtual receptors are not mapped or screened wells and do not establish flow-path connectivity. Input intervals propagate declared independent ranges only; they are not total predictive uncertainty. No dose, safety, operational, protective-action, or regulatory interpretation is performed.
