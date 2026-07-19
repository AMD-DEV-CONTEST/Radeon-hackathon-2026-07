# Adaptive Precision Controller on W7900 - v12

Measured: 2026-07-19 (UTC+8)

## Executive Result

Quark INT8 v11 showed that a model can save memory while losing policy
semantics. v12 tested whether JSON Schema constrained decoding could recover
that model and whether a fail-closed precision controller could safely use it.

The result:

- raw INT8 strict JSON: `0/12`
- JSON Schema constrained INT8 strict JSON: `2/12`
- constrained INT8 semantic admission: `0/12`
- automatic FP16 fallback: `12/12`
- final accepted output: `12/12`

Schema constrained decoding improved shape compliance but did not restore
policy meaning. The controller therefore rejected every INT8 response and
selected FP16.

## Controller

The controller has three gates:

1. **Schema gate**
   - strict object with a `constraints` array
   - closed constraint objects
   - enumerated constraint kinds
2. **Semantic admission**
   - candidate must retain every safety kind found by the deterministic runtime:
     `must_not`, `redact`, `only_if`, and `requires_confirmation`
3. **Precision fallback**
   - a request or parsing error fails closed
   - a semantic omission triggers the configured FP16 endpoint
   - the selected route and rejection reasons enter the proof core

The production default remains unchanged unless fallback environment variables
are explicitly configured.

## Recovery Matrix

| Mode | JSON valid | Semantically admitted | Median latency |
|---|---:|---:|---:|
| Raw Quark INT8 | 0/12 | 0/12 | 6.81 s |
| Schema-constrained Quark INT8 | 2/12 | 0/12 | 11.84 s |
| Adaptive controller final result | 12/12 | 12/12 | 19.42 s |
| FP16 fallback stage only | 12/12 | 12/12 | 7.58 s |

The adaptive end-to-end latency is high because the current experiment executes
the rejected INT8 request before FP16. It is a safety mechanism, not a latency
optimization.

The correct production policy for this workload is still direct FP16. Adaptive
routing becomes useful only when a future low-precision model has a meaningful
admission rate.

## Real Voice-to-Proof Validation

The implementation commit `f2fffd2` was clean-cloned on the W7900 and passed:

- typecheck
- 38/38 tests
- production build

An isolated full product run used:

- real Qwen3-ASR on W7900
- Quark INT8 C128 as primary
- existing Radeon FP16 as fallback
- JSON Schema constrained output
- deterministic semantic admission

Result:

- Voice Evidence: `pass / 100`
- INT8 primary: rejected
- reasons:
  - `missing_redact`
  - `missing_requires_confirmation`
  - `missing_only_if`
- selected route: `fallback`
- final permission: `mail.send = deny`
- verification: `7/7`
- proof status: `verified`
- proof route: `fallback`
- proof hash:
  `c306a612bdfed26a1ba7f69ee14e5cdfd230deafa91617915ba67d7e195bb71c`
- proof ZIP SHA-256:
  `913aa087c35c5f06faeff82845c64733a6208aa51e70e2e87c521c1466f1bfdc`

## Decision

JSON Schema is necessary but not sufficient. The project now treats model
precision as an untrusted runtime choice:

`low precision -> schema -> semantic admission -> FP16 fallback -> proof`

This keeps the capacity experiment available while preventing a degraded model
from silently weakening no-send, privacy, confirmation, or conditional-scope
rules.

## Evidence

- `benchmarks/adaptive-precision-v12-summary.json`
- `benchmarks/adaptive-precision-v12-primary.json`
- `benchmarks/adaptive-precision-v12.json`
- `benchmarks/adaptive-precision-v12-e2e.json`
- Release asset: `adaptive-precision-v12-evidence.zip`
- Release proof: `adaptive-precision-v12-proof.zip`
