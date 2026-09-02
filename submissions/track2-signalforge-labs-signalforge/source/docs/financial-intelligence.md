# Financial Intelligence Runtime

Status: integrated on `main` and verified on CPU  
Baseline: `v1.0.0` remains immutable  
Radeon journey evidence: not yet collected

## Purpose

Sprint 16B extends the frozen 28-operation Tier 0 engine with 52 governed financial-intelligence
operations. The extension turns point-in-time reported facts into inspectable cash-generation,
return, quality, capital-allocation, valuation, peer, and association evidence without delegating
arithmetic or numerical authorship to a language model.

The `v1.0.0` tag is unchanged and remains the reproducible hackathon baseline. The current
mainline integrates this extension without rewriting the historical Tier 0 identity or its
evidence.

## Runtime Boundary

```text
reported fact + filing availability
        |
        v
typed period and sign normalization
        |
        v
canonical metric registry (80 active definitions)
        |
        v
role-authorized deterministic Go executor
        |
        v
hash-verifiable calculation receipts
        |
        +--> authoritative numerical context
        |
        +--> value-free model view
        |
        v
deterministic reference renderer
```

`Tier0Registry()` remains the frozen 28-operation surface. `FinancialIntelligenceRegistry()` owns
the 52 post-v1 additions. `RuntimeRegistry()` composes both without changing the historical Tier 0
identity.

All 80 registered operations have an explicit unit contract for every required input. The executor
also enforces currency and governed period compatibility before dispatch. Auxiliary cohort,
historical-band, debt-maturity, scenario, tornado, and diagnostic helpers are deterministic
composition surfaces; they cannot independently publish an authoritative value outside an owning
registered receipt and deterministic presentation path.

## Added Capability Groups

| Group | Operations | Primary controls |
|---|---:|---|
| Financial analysis | 30 | cash generation, returns, liquidity, debt maturity, typed cash conversion, payout, and sources-and-uses reconciliation |
| Valuation | 19 | CAPM, beta conventions, multi-stage DCF, dividend discount, reverse expectations, detailed value bridge, scenarios, tornado inputs, and governed multiples |
| Comparison | 2 | DuPont and robust peer statistics with governed cohorts and historical bands |
| Economics | 1 | lagged association with train/test, missingness, stability, and confidence diagnostics, explicitly labeled non-causal |

The generated canonical catalog is produced with:

```bash
go run ./cmd/signalforge-export-metric-registry
```

Every active definition records formula version, meaning, typed inputs, sign policy, period basis,
applicability, GAAP status, authority, implementation owner, and fail-closed dispositions.

## Period And Sign Authority

`internal/financialperiod` distinguishes reported facts, normalized facts, derived metrics,
estimates, and scenarios. It supports instant, quarter, YTD, annual, and TTM periods. TTM is built
only as prior annual plus current YTD less comparable prior YTD, with cutoff and lineage checks.

Sign normalization never overwrites source truth. A normalized fact retains the raw reported value,
the transformation ID, the selected sign policy, source fact IDs, amendment chain, availability
time, and computation time.

## Numerical Silence

`FinancialIntelligencePacket` contains two deliberately different views:

- `numerical_context` contains authoritative values derived from validated receipts;
- `model_view` contains only closed references, meanings, periods, methods, formula versions,
  evidence, receipt IDs, relations, and warnings.

The model view cannot contain a `value` property under the portable JSON Schema. Final numerical
release uses the existing deterministic presentation compiler. Models cannot alter receipt values
or introduce an authoritative number.

Role-scoped specialist packets preserve this boundary: they carry value-free receipt references
with operation, formula, period, status, assumptions, evidence IDs, and hashes, but never normalized
inputs, intermediate values, or numerical outputs. The Evidence Critic receives an independent
superset of those references rather than copied specialist prose.

## Fail-Closed Behavior

The runtime rejects unsupported operations, roles, inputs, units, currencies, periods,
future evidence, formula versions, invalid denominators, inapplicable company profiles, unresolved
reconciliations, non-convergent reverse valuations, small peer samples, zero-variance regressions,
and value-level mismatches.

Operating-company formulas explicitly exclude banks, insurers, and REITs where the definition is
structurally misleading. Sector-specific models require separate reviewed definitions.

## Verification

The financial-intelligence checks are reproducible from the repository root:

```bash
go test ./internal/capability ./internal/engine ./internal/finance \
  ./internal/financialintelligence ./internal/financialperiod ./internal/metricregistry
python3 scripts/reference_finance.py
go run ./cmd/signalforge-export-metric-registry >/tmp/signalforge-metric-registry.json
```

The complete `scripts/verify.sh` gate additionally validates the immutable evidence baseline,
exports all 80 canonical definitions through tests, confirms the 52-operation extension, runs the
full race-enabled Go suite, and checks complex methods through an independent Python
implementation.

Property and metamorphic tests cover beta leverage round trips, DCF monotonicity, capital-allocation
conservation, invalid rates and denominators, TTM look-ahead, common-size period compatibility, and
sign preservation. Fuzz seeds cover financial denominator and period normalization boundaries.

The first benchmark exposed avoidable registry reconstruction in each financial packet. Reusing the
immutable canonical registry reduced packet construction from approximately 582 KB and 5,021
allocations to 6.3 KB and 59 allocations on the development Mac. These are CPU development results,
not Radeon claims.

## Remaining Evidence Gates

- Use the committed 240-case development and restricted 80-case future holdout for subsequent
  changes; it cannot retroactively prove changes made before its commitment.
- Run complete Accounting, Financial Quality, Valuation, Economics, Market Behavior, critic, and
  final-analysis journeys on the selected local Radeon runtime.
- Measure factual correctness, abstention, evidence coverage, latency, VRAM, and complete-task
  success separately.
- Preserve the implemented product-facing comparison, valuation, capital-allocation, missing-data,
  and not-applicable replay journeys when exercising the selected model runtime.
- Record the Radeon evidence decision before cutting a reviewed release newer than `v1.0.0`.

Until those gates pass, this work is a public, verified CPU implementation, not a Radeon
performance or independent model-quality claim.
