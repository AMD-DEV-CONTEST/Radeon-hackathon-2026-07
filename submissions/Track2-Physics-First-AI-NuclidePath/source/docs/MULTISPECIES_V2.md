# Multi-isotope contract v2

## Status

**Implemented as an opt-in research contract:** independent Cs-137 and Sr-90 transport runs sharing one explicit aqueous-chemistry record. The legacy v0.3 contract and pipeline are unchanged.

This is not a coupled reactive-transport model. The radionuclides do not interact. In the opt-in primary-paper Cs GCS path, K and Na compete on all three illite sites and NH4 competes on FES only. Ca and Mg are recorded and converted but are explicitly treated as effectively noncompetitive in this Cs model, following Bradbury & Baeyens (2000).

## Supported physics

| Species | Linear sourced Kd | Three-site GCS |
|---|---:|---:|
| Cs-137 | Yes | Cs/K-only |
| Sr-90 | Yes | No; fails closed |

Each radionuclide requires independently supplied:

- initial activity concentration in Bq/m3;
- half-life in years;
- half-life source and classification;
- sorption model, source, and classification.

No built-in Sr-90 Kd or half-life is silently selected. Values are scenario inputs and must carry provenance.

## Shared chemistry

The contract requires explicit K, Na, Ca, Mg, and NH4 entries in mg/L. A field may be zero, but it may not be omitted. Each entry also requires source and classification.

Internally, concentrations are converted using:

```text
concentration_mol_L = concentration_mg_L / 1000 / molar_mass_g_mol
```

Molar masses are versioned in `src/nuclear_agent/data/parameters/molar_masses_v1.json`, with CIAAW source metadata. NH4 is derived from conventional N and H values declared in that record.

Current usage:

- K and Na are used on all three sites by the primary-paper Cs GCS calculation;
- NH4 is used on FES only because the primary paper does not provide Type-II/planar NH4 coefficients;
- Ca and Mg are preserved and explicitly marked effectively noncompetitive within this Cs model;
- all five values are preserved even when a linear Kd model is selected.

## GCS integration

For `gcs_cs_k`, the scenario must provide:

- positive dissolved stable Cs concentration in mol/L;
- illite mass fraction in `[0, 1]`;
- positive K concentration through the shared chemistry.

The GCS result is converted from L/kg to m3/kg exactly once. The legacy empirical potassium competition inputs passed to the transport solver are then set to zero, preventing a second K correction.

GCS is rejected for Sr-90. No effects from Ca/Mg on Cs uptake, cross-isotope competition, Sr sorption through GCS, or non-illite sorption are implied. The primary source, exact tables, PDF hash and limits are documented in [GCS_FOUNDATION.md](GCS_FOUNDATION.md).

## Contract safeguards

`ScenarioInputV2.from_dict` and direct construction use the same nested validators. They enforce:

- exact schema version `nuclidepath-multispecies-2.0`;
- no unknown fields;
- supported and unique radionuclides;
- finite values and domain bounds;
- strictly increasing, unique evaluation times;
- `0 < porosity <= 1`;
- complete provenance-bearing chemistry and sorption records;
- deep immutability of normalized input and output structures.

## Verification

- v2-specific tests: 19 passed;
- recorded controller checkpoints: 216 passed/13 optional-PyTorch skips dependency-light; 231 passed with CPU PyTorch;
- dated AMD ROCm core-platform snapshot: 231 passed, including exact primary-GCS and end-to-end tensor-pipeline parity; it predates the PHREEQC bridge merge.

The tests include direct-constructor bypasses, unit conversion, independent decay, an independently evaluated GCS Kd, no-double-competition behavior, and explicit legacy-contract stability.

These gates establish software consistency. They do not validate Sr geochemistry, multi-ion exchange coefficients, or regulatory applicability.
