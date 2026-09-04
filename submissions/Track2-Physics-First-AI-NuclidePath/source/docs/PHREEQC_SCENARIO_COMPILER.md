# PHREEQC scenario compiler

## Purpose

The Phase F PHREEQC harness proved that NuclidePath can execute a pinned
external solver with bounded streams, closed outputs, and replayable integrity
records. This compiler adds the first scientific bridge: an **opt-in**
projection of a NuclidePath Cs-137 groundwater scenario into a PHREEQC input
that represents declared water chemistry, aqueous Cs, declared competitors, and cation exchange.

The bridge is intentionally one-way and explicit:

```text
NuclidePath scenario + declared chemistry/CEC/selectivity
                              │
                              ▼
                  deterministic PHREEQC input
                              │
                              ▼
       PHREEQC speciation/exchange/1-D transport evidence
                              │
                              ▼
             replay bundle + later discrepancy analysis
```

The existing NuclidePath transport model remains the canonical screening
calculation. PHREEQC is not allowed to silently replace the empirical
`Kd_eff = Kd / (1 + alpha_K [K+])` path.

## Input contract

The existing scenario keeps its original `site` and `transport` blocks. A
separate `phreeqc` block is required for this projection:

```json
{
  "phreeqc": {
    "water_density_kg_m3": 1000.0,
    "water": {
      "units": "mmol/kgw",
      "pH": 7.0,
      "pe": 12.0,
      "temperature_c": 25.0,
      "ions_mmol_kgw": {"Ca": 0.6, "Cl": 2.711, "K": 0.511, "Na": 1.0}
    },
    "exchange": {
      "cec_mmolc_kg": 100.0,
      "log_k": {"Ca": 0.2, "Cs": 1.2, "K": 0.4, "Na": 0.0}
    },
    "discretization": {"cells": 20},
    "provenance": {
      "water": "synthetic demonstration water; not site data",
      "cec": "synthetic demonstration CEC; requires calibration",
      "selectivity": "synthetic demonstration log K; requires multi-cation Cs experiments"
    }
  }
}
```

`Cs` plus at least one competitor selectivity value are mandatory and have no
defaults. The competitor set may contain any subset of K, Na, Ca, and Mg; K is
not required. The compiler rejects unknown components, non-finite values, missing provenance,
zero velocity/CEC, unsorted evaluation times, and a shift cap that cannot cover
the requested time range. Requested evaluation times must align with the derived
PHREEQC transport time-step grid; the selected output is emitted at those times
without interpolation. A request requiring more than 100,000 transport shifts
fails closed.

The scenario's boundary activity is converted from Bq/m³ to mol/kgw using the
declared Cs-137 half-life and water density. PHREEQC receives total `Cs` as a
minimal inline aqueous component (`Cs+ = Cs+`). This is a transparent unit
conversion, not a complete isotope or aqueous-complexation database.

CEC is converted from mmolc/kg dry bulk medium to exchange-site mol/kgw with

```text
sites = CEC × 10⁻³ × dry_bulk_density / (porosity × water_density)
```

The dry-bulk-density interpretation must be checked against the site's
characterization convention before any scientific use.

## Generated PHREEQC model

The compiler emits:

- an inline minimal Cs aqueous definition;
- a Gaines–Thomas-compatible exchange site `X`;
- explicit Cs and every declared K/Na/Ca/Mg exchange species;
- a maintained `SOLUTION 0` boundary and initial aquifer solutions;
- one exchange assemblage per transport cell, initially equilibrated with the
  initial water;
- `SELECTED_OUTPUT` columns for total, aqueous, and exchange amounts for every declared ion;
- a 1-D `TRANSPORT` block using the existing distance, velocity, and dispersion;
- a deterministic metadata record containing the mapping and provenance.

Dispersion is mapped to PHREEQC dispersivity as `alpha = D / v`. NuclidePath's
radioactive decay is **not** inserted into this PHREEQC input; decay remains in
the canonical NuclidePath model until a separately qualified coupled contract
exists.

The PHREEQC database is assumed to be `phreeqc.dat` plus the inline minimal Cs
definition. The module does not claim compatibility with every PHREEQC
database, a complete Cs thermodynamic data set, or a calibrated exchange
model.

## Usage

Compile the included synthetic demonstration projection:

```bash
nuclear-phreeqc-scenario \
  cs137_exchange_scenario.json \
  --output results/phreeqc-chemistry
```

The command writes `input.pqi` and `metadata.json`. To include the bridge in
the full private-agent report pipeline, use the complete demonstration scenario:

```bash
nuclear-emergency-demo \
  --scenario scenarios/cs137_phreeqc_bridge_demo.json \
  --output results/phreeqc-bridge-demo \
  --knowledge-dir knowledge \
  --uncertainty-ranges scenarios/uncertainty_ranges.json \
  --samples 512 --seed 42
```

That run remains offline and deterministic. It publishes
`phreeqc-input.pqi`, path-free `phreeqc-metadata.json`, and a
`phreeqc_bridge` report section with status `compiled-not-run`; both new
files are covered by the ordinary output manifest. The ordinary report
pipeline remains compile-only. Trusted release qualification still uses the
manual PHREEQC workflow on `refs/heads/main`; the pinned local verification
recorded below is separate and does not change that trust boundary.

A Python caller can then run the compiled input through the existing bounded adapter:

```python
from nuclear_agent.phreeqc_scenario import (
    compile_phreeqc_scenario, run_phreeqc_scenario, write_scenario_replay,
)

compiled = compile_phreeqc_scenario(scenario)
run = run_phreeqc_scenario(
    compiled,
    executable=trusted_phreeqc,
    database=trusted_database,
    executable_sha256=trusted_executable_sha256,
    database_sha256=trusted_database_sha256,
    working_directory=absolute_empty_run_root,
)
bundle = write_scenario_replay(replay_directory, run)
```

The runner requires explicit lowercase SHA-256 values, stages all artifacts
inside a dedicated directory, uses the Phase F bounded process contract, and
rejects any output inventory other than `nuclidepath.sel`, `phreeqc.out`, and
`phreeqc.log`. The replay result remains process-qualified only; its integrity
manifest is not an author signature. The deterministic payload also contains
the separate arithmetic oracle described in
[PHREEQC numerical oracle](PHREEQC_NUMERICAL_ORACLE.md).

## Scientific role in NuclidePath

This is the first implementation step toward replacing an empirical Kd
correction with a chemistry-aware hierarchy:

1. use the same scenario and declared water chemistry in both paths;
2. run PHREEQC to obtain aqueous speciation and exchange occupancy;
3. derive a documented chemistry diagnostic, such as dissolved/exchange Cs
   fractions or an apparent retardation factor;
4. compare that diagnostic with the current empirical K+/Kd path;
5. calibrate selectivity, CEC, and any surface/mineral model against multi-cation
   Cs experiments before changing the canonical screening result;
6. retain both results, assumptions, discrepancy, and replay evidence in the
   report.

The compiler, bounded runner, exact selected-output parser,
chemistry diagnostics, replay writer, and full-pipeline compile-only report
artifacts now cover steps 1–4 as an opt-in evidence path. A trusted release
qualification run must still be performed through the manual workflow. The implementation
supports the hackathon story—local agent proposes a declared scenario,
deterministic code compiles it, and a verified external scientific tool can
produce inspectable chemistry evidence—without presenting demonstration
constants as site truth.

The diagnostics treat PHREEQC `-totals` values as solution totals and select
exchange amounts separately. They reconstruct the displayed aqueous-plus-
exchange partition, report the solution-total residual, derive an apparent
exchange `Kd` and retardation factor when the aqueous amount is positive, and
place these values beside (not instead of) the canonical empirical `Kd_eff`.

## Independent numerical oracle

The compiler invokes an independent arithmetic oracle before returning selected
output. It verifies unit conversions, transport-grid arithmetic, non-negative
phase values, total exchange-site occupancy and transparent residual/apparent-
`Kd` reconstruction. Its record is labelled `NUMERICALLY VERIFIED` and remains
explicitly separate from solver correctness, calibration and experimental
validation. See [PHREEQC numerical oracle](PHREEQC_NUMERICAL_ORACLE.md).

## Official PHREEQC basis

The input uses the documented `SOLUTION`, `EXCHANGE_MASTER_SPECIES`,
`EXCHANGE_SPECIES`, `EXCHANGE`, `SELECTED_OUTPUT`, and `TRANSPORT` blocks. The
USGS manual describes exchange as equilibrium among an assemblage and solution,
defines exchange half-reactions and relative log K values, and exposes aqueous
and exchange species through selected output. See the official [EXCHANGE]
documentation, [EXCHANGE_SPECIES] documentation, [SELECTED_OUTPUT]
documentation, and [Example 11: Transport and Cation Exchange] and [Example 14: Central Oklahoma aquifer].

[EXCHANGE]: https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-14.htm
[EXCHANGE_SPECIES]: https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-16.htm
[SELECTED_OUTPUT]: https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-45.htm
[Example 11: Transport and Cation Exchange]: https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-73.htm
[Example 14: Central Oklahoma aquifer]: https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-76.htm

## Sourced multicomponent cases

The repository includes paired K-free projections based on the Central Oklahoma
aquifer example: an initial Na-Ca-Mg brine and a dilute recharge composition.
They exercise the same compiler, dynamic selected-output schema, parser, and
component-specific exchange diagnostics without requiring a potassium column.
The Cs source term, 1-D geometry, and CEC mapping are explicitly demonstration
inputs; the water compositions are the externally sourced part of the cases.

See [PHREEQC multicomponent cases](PHREEQC_MULTICOMPONENT_CASES.md) for the
scenario files, unit conversions, provenance, and the scientific boundary.

## Current implementation evidence

The generalized schema-2 compiler, dynamic parser, diagnostics and full-pipeline
report bridge are included in merged PR #15. Final integration CI run
`30928408962` passed with 364 passed and 15 skipped; workflow policy, compilation,
wheel and whitespace checks also passed. PR #22 subsequently added the
non-runner calibration/hold-out gate; its CI run `30936374478` passed with 370
passed and 15 skipped. PR #24 then added the separate external Cs benchmark
registry; run `30993946602` passed with 373 passed and 15 skipped. The current `main` head `df8f028` passed run `31111109865` with 377 passed and 15 skipped, after the review-hardening commits `3714bf8` and `1605cc6`.
The current change set was then exercised against the pinned PHREEQC installation
locally, using release asset `3.9.0-17591` (banner `PHREEQC 3.8.9, October 13,
2025`) and database SHA-256 `5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278`.

| Case | Input SHA-256 | Canonical selected output SHA-256 | Canonical `phreeqc.out` SHA-256 | Rows | Shifts | Oracle/replay |
|---|---|---|---|---:|---:|---|
| Central Oklahoma brine | `d31e9b6e2ddbe2ff868453f8158ff9b1150b3a41ee23860bd0164e241013f46c` | `da976fd830abdc5515cdb60b828e08a9b3b1270feb0cb0bbb2c4533de12718bb` | `21a2c9a23b65a30b4a443c504889ea81626f284519d1f51c3baf6b7be5f212ac` | 41 | 40 | PASS |
| Central Oklahoma recharge | `4de600440d8a823e8b12b0c0f1b55e0eba52c468c3a02fadec1a628e71779c40` | `b7eba203aa252c95e8a091f75522cdfe129340e60a568ac04c5e34326134c801` | `e2c7f5ec667a5430f7735a12adc8dc1b559ecb39b3cd209659f62f9d38e730a1` | 41 | 40 | PASS |

The executable SHA-256 was `827626b39f0b5bdecf74536fe2aeb317127e66793a4074e18bb900caf10d8fb6`.
Each case exited with status 0, parsed the exact closed output schema, passed the
independent numerical oracle, and produced a ReplayBundle that verified. Two
isolated runs per case produced byte-identical selected output and identical
canonical replay results. Raw `phreeqc.out` and `phreeqc.log` retain their
invocation path/duration hashes in replay metadata; only those non-scientific
fields are canonicalized for deterministic replay comparison.

This is a pinned local process/integration verification of the change set. The
trusted manual workflow on `refs/heads/main` remains a separate publication
gate; the evidence does not establish calibrated Cs selectivity, experimental
agreement, GCS equivalence, general PHREEQC compatibility, or regulatory
validity. The arithmetic oracle is covered by the same dependency-light test
path and is included in replayable JSON evidence.

`PROCESS-QUALIFIED ONLY` remains the correct global scientific status. The
compiler is covered by deterministic unit tests, full-pipeline artifact tests,
and an external-run path, but the project has not yet established:

- a calibrated multi-cation Cs PHREEQC database;
- experimental agreement for the generated multi-cation exchange model;
- numerical equivalence with the existing GCS implementation;
- a coupled decay/transport result contract;
- general PHREEQC database compatibility;
- regulatory or operational validity.
