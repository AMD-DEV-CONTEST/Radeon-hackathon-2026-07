# Independent numerical oracle for the PHREEQC bridge

## Purpose

The schema-2 PHREEQC bridge now emits a separate machine-readable arithmetic
check. It is implemented in
src/nuclear_agent/phreeqc_oracle.py, independently from
diagnose_phreeqc_output, and is executed whenever selected output is
diagnosed or a scenario replay is written.

A passing oracle record has:

- oracle_version: "phreeqc-numerical-oracle-1"
- evidence_level: "NUMERICALLY_VERIFIED"
- status: "passed"

This is a limited evidence promotion for the declared numerical contract. The
global PHREEQC status remains **PROCESS-QUALIFIED ONLY**.

## Checks

The oracle recomputes and checks:

1. Cs-137 activity-to-mol/kgw conversion from the declared half-life and water
   density;
2. CEC-to-exchange-site conversion;
3. PHREEQC cell length, time step and dispersivity from the declared transport
   inputs;
4. evaluation-time alignment and shift coverage;
5. finite, non-negative totals, aqueous values and exchange amounts;
6. total exchange-site occupancy, including charge 2 for Ca and Mg;
7. solution-total residuals and the apparent Cs Kd reconstruction.

The selected-output -totals values remain solution totals. The residual
total - aqueous is therefore a reported reconstruction residual, not a global
aqueous-plus-exchange mass balance. The oracle does not silently change that
semantic.

The output is JSON-serializable and is included in the chemistry diagnostics,
the deterministic replay payload and the replay metadata. A failed invariant
raises a fail-closed error before the scenario result is returned.

## What this removes

The bridge no longer has “no independent numerical oracle” as a valid
description of its declared arithmetic contract. Unit conversions, transport
mapping, non-negativity and exchange-capacity closure now have an independent,
machine-checkable reference implementation.

This does not validate PHREEQC's equation solver, the inline Cs
thermodynamics, the supplied selectivity coefficients, or the sourced
Central Oklahoma compositions.

## Remaining scientific gates

Promotion beyond NUMERICALLY VERIFIED still requires:

- a trusted real PHREEQC run for the two multicomponent cases with fresh
  executable/database digests;
- traceable competitive Cs/K/Na/Ca/Mg measurements and a calibration/hold-out
  split;
  The repository now supplies the fail-closed schema and hold-out gate, but no dataset is bundled.
- a comparison against an independent transport/chemistry oracle or qualified
  reference implementation;
- experimental agreement and applicability review;
- separate dose, operational and regulatory validation.

The oracle is evidence for software and declared-unit consistency, not a
calibrated environmental model.
