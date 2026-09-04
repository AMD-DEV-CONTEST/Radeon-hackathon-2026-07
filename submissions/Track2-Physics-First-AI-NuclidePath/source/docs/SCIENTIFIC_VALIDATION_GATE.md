# Scientific calibration and hold-out gate

## Status

The repository now contains an executable, dependency-free contract for the
next scientific gate: ingesting traceable Cs exchange observations, fitting a
transparent multi-cation apparent-`Kd` calibration, and evaluating it on a
group-disjoint hold-out split.

This closes the software/infrastructure gap without inventing a calibration
dataset. The repository now contains a separately validated external-benchmark
registry, but none of its rows are accepted as calibration observations. The
implementation does not change the canonical transport model or the PHREEQC
result. The global PHREEQC status therefore remains **PROCESS-QUALIFIED ONLY**.

## External benchmark registry

`data/benchmarks/cs/manifest.json` records three deliberately separate
materials:

- [EPA Safety Light Corps](https://catalog.data.gov/dataset/safety-light-corps-sediment-and-cs-sorption-dataset): public `q` measurements with an explicitly derived
  apparent `Kd`; CEC and Ca are unavailable, so the rows cannot satisfy the
  observation contract.
- [Fuller et al. (2014)](https://eprints.whiterose.ac.uk/id/eprint/80294/): micaceous-sediment Fig. 1 values, retaining article
  values where reported and marking approximate digitizations and derived
  `Kd` values with uncertainty.
- [Dubus et al. (2023)](https://cea.hal.science/cea-03770057v1): selected Fig. 2 points for vermiculite conditioning
  series with Ca/Mg/K and CEC metadata; the points are plot digitizations, and
  article redistribution rights are not assumed.

The registry validator checks source digests, CSV headers, row counts, unique
observation IDs and the explicit `calibration_eligible: false` policy. The
materials remain separate by mineral/source and are never concatenated into a
single calibration dataset. Validate the registry with:

```bash
python -c "from nuclear_agent.dataset_registry import validate_benchmark_registry; validate_benchmark_registry('data/benchmarks/cs/manifest.json')"
```

These files are benchmark evidence and ingestion scaffolding, not a scientific
promotion. A future authorized dataset must still satisfy the strict
`ObservationDataset` contract below.

## Dataset contract

`nuclear_agent.scientific_validation.ObservationDataset` accepts only schema
`nuclidepath-cs-exchange-observations-1`. Every dataset must declare:

- a stable `dataset_id` and `data_status`;
- source, license, method, retrieval date, units and permission provenance;
- `observation_id` and independent `group_id` values;
- mineral identifier, CEC, Cs concentration and apparent `Kd`;
- all four competitor concentrations (`K`, `Na`, `Ca`, `Mg`), including an
  explicit `0.0` when an ion was absent or intentionally controlled to zero;
- disjoint calibration and hold-out group lists covering every observation.

The loader rejects unknown keys, duplicate observations, non-finite or
non-positive target values, missing competitor values, split leakage, and
measured data without documented/public permission. A group is the unit of the
split: replicate measurements from one batch, column, mineral preparation or
other declared group cannot be scattered across calibration and hold-out.

The helper `deterministic_group_split()` is available when a dataset author
needs a reproducible initial split. The resulting group IDs must still be
reviewed and recorded in the dataset itself before scientific use.

## Calibration model

The first supported model is intentionally a limited empirical screening
surrogate, not a PHREEQC thermodynamic model:

```text
log10(Kd) = b0
          + bK  log1p(K  / sK)
          + bNa log1p(Na / sNa)
          + bCa log1p(Ca / sCa)
          + bMg log1p(Mg / sMg)
          + bCEC log(CEC / sCEC)
```

The included model specification records the selected ions, concentration
scales and ridge regularization. All scales are explicit and dimensionless in
the transformed features; they are not asserted as physical constants. The
fit uses only the calibration groups. The hold-out is never used to optimize
coefficients.

The resulting report records coefficients, exact group membership, calibration
and hold-out metrics, the acceptance policy, and a canonical SHA-256 report
digest. The available metrics include log-space RMSE, absolute error, relative
error and per-group hold-out RMSE.

## Promotion rule

The gate opens only when both conditions hold:

1. the hold-out split satisfies the declared minimum counts and error limits;
2. `data_status` is `measured_traceable` and permission is `documented` or
   `public`.

Synthetic fixtures deliberately remain `NOT_PROMOTED` even when the numerical
fit and hold-out metrics pass. `require_experimental_validation()` fails closed
for every blocked report. A successful promotion, when a real authorized
dataset is eventually supplied, is scoped only to the empirical multi-cation
apparent-`Kd` calibration. It does not promote PHREEQC, establish GCS
equivalence, validate transport/decay coupling, or establish dose, safety or
regulatory validity.

## Offline usage

The implementation has no solver or GPU dependency. After installing the
package, a future dataset can be evaluated with:

```bash
nuclear-validate-cs-exchange \
  observations.json \
  --model model.json \
  --output validation-report.json
```

Add `--require-promotion` in a release/calibration pipeline that must stop
unless the measured-data gate opens. The repository's tests use only generated
synthetic values to exercise parser, split, fit, metric and fail-closed
behaviour; those values are not scientific evidence.

## What remains outside this gate

The following are intentionally separate:

- a trusted PHREEQC execution on `refs/heads/main`;
- a calibrated PHREEQC species/selectivity definition and solver-level
  comparison;
- an independent transport/reference-code comparison;
- finite-duration source terms, heterogeneous flow paths and model-form
  uncertainty;
- dose, operational, site-specific and regulatory validation.

The calibration report must be retained beside the raw observations, provenance
and hold-out definition. It must not be used to silently replace the canonical
K-only screening path until a separate model-integration review accepts the
scope and evidence.
