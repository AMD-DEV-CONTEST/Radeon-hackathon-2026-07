# Scientific Verification and Validation Boundaries

## Scope

The verification target is `transport-prototype-0.3`, a transparent 1-D reactive advection–dispersion screening model. **Verification** means checking equations, contracts and software against independent analytical results. It does **not** mean environmental validation, regulatory acceptance or site calibration.

## Well-posed problem

For a dissolved concentration `C(x,t)` on a saturated semi-infinite domain `x >= 0`:

```text
R ∂C/∂t = D ∂²C/∂x² − v ∂C/∂x − λ R C
```

with:

```text
C(x,0) = 0   for x > 0
C(0,t) = C0  for t >= 0
C(∞,t) = 0
```

Definitions:

- `v`: linear pore-water velocity, not Darcy flux;
- `D`: longitudinal hydrodynamic-dispersion coefficient;
- `R = 1 + rho_b Kd_eff / n`: equilibrium linear retardation;
- `λ = ln(2) / T1/2`: physical Cs-137 decay constant;
- decay acts in dissolved and sorbed phases at the same physical constant.

The source is an indefinitely maintained boundary concentration. `C0` is therefore a source concentration, not an undefined pulse mass.

## Reactive Ogata–Banks solution

Let:

```text
A = sqrt(v² + 4 λ R D)
```

Then:

```text
C/C0 = 0.5 × [
  exp((v−A)x/(2D)) erfc((Rx−At)/(2 sqrt(DRt)))
  + exp((v+A)x/(2D)) erfc((Rx+At)/(2 sqrt(DRt)))
]
```

For `λ -> 0`, this reduces to the classic retarded Ogata–Banks constant-source solution. At `x = 0`, `C = C0` exactly. At large time:

```text
C/C0 -> exp((v−A)x/(2D))
```

The implementation evaluates the potentially ill-conditioned `exp(a) × erfc(z)` term in the log domain for large positive `z`.

## Independent analytical tests

| Case | Independent expectation | Acceptance |
|---|---|---|
| effective Kd | `Kd/(1+alpha_K[K+])` | floating-point agreement |
| retardation | `1+rho_b Kd_eff/n` | floating-point agreement |
| travel-time marker | `xR/v` | floating-point agreement |
| non-reactive solution | independently coded Ogata–Banks formula | relative error `<=1e-12` for test case |
| source boundary | `C(0,t)=C0`, including one half-life | relative error `<=1e-12` |
| reactive steady state | `C/C0=exp((v−A)x/(2D))` | relative error `<=1e-10` |
| continuous-source breakthrough | non-decreasing and bounded by `C0` | property test |
| non-finite inputs | physically undefined | NaN and infinity rejected |

Additional contract/security tests cover strict JSON, boolean rejection, planner allowlists, prompt-injection resistance, private memory and safe local HTTP paths.

## Test evidence

The preceding merged-bridge integration checkpoint is PR #15 CI run
[30928408962](https://github.com/anakinsuper/NuclidePath/actions/runs/30928408962):

```text
364 passed, 15 skipped, 0 failed; workflow policy, wheel and whitespace checks PASS
```

The latest calibration/hold-out checkpoint is PR #22 CI run
[30936374478](https://github.com/anakinsuper/NuclidePath/actions/runs/30936374478):

```text
370 passed, 15 skipped, 0 failed; workflow policy, wheel and whitespace checks PASS
```

The dated AMD/ROCm core-platform snapshot from 28 July 2026 passed 231 tests,
with the dependency-light controller at 216 passed/13 optional-PyTorch skips
and the PyTorch controller at 231 passed. That snapshot predates the PHREEQC
bridge merge and must not be described as a full current-main rerun.

The PHREEQC path has a separate scope: the official Example 2 process
qualification is recorded as `1 passed` across two clean runs. The new Central
Oklahoma multicomponent cases also completed a pinned local process/integration
projection with 40 shifts and 41 parsed rows per case; a trusted real projection
on `refs/heads/main` remains pending. The schema-2 bridge includes an
independent arithmetic oracle labelled `NUMERICALLY VERIFIED`; this checks the
declared software/unit contract, not the PHREEQC solver or calibrated chemistry.

The deck/PDF, contact sheets and current video cards have been regenerated from the verified source snapshot; their hashes are recorded in `submission/ARTIFACT_MANIFEST.json`. Future resyncs must repeat this step, while historical visual checkpoints remain labelled rather than reused as current evidence.

## What the tests establish

- equations are implemented consistently with the declared IC/BC;
- source concentration is not amplified above `C0`;
- the non-reactive limit matches an independent analytical oracle;
- retardation and potassium effects have the expected algebraic direction;
- results are finite and deterministic for the declared demo range;
- the LLM cannot replace deterministic numerical outputs;
- the PHREEQC bridge preserves explicit chemistry declarations, dynamic output
  closure and comparative-only status without replacing canonical Kd;
- the independent numerical oracle rejects non-finite/non-negative violations,
  off-grid mapping and overfull exchange-site occupancy.

## Calibration and hold-out gate

The repository now includes a dependency-free calibration gate for the next
scientific increment. It validates traceable observation metadata, requires
explicit K/Na/Ca/Mg values and units, enforces group-disjoint calibration and
hold-out sets, fits only on the calibration groups, and records hold-out error
metrics plus a canonical report digest. Synthetic fixtures can exercise the
software but are always blocked from promotion. No experimental dataset is
bundled, so this gate is currently infrastructure evidence rather than
experimental validation. See [SCIENTIFIC_VALIDATION_GATE.md](SCIENTIFIC_VALIDATION_GATE.md).

## What remains unvalidated

The project has not been validated against:

- site-specific monitoring or column-breakthrough data;
- MODFLOW 6 GWT, MT3DMS or another independent transport code;
- 2-D/3-D flow, transient velocity or heterogeneous stratigraphy;
- scale-dependent dispersion outside the stated bracket;
- nonlinear, kinetic or irreversible sorption;
- mineral-specific exchange-site populations or calibrated K+ competition;
- calibrated multi-cation Cs selectivity/CEC mapping and experimental or
  solver-level PHREEQC agreement; the arithmetic oracle covers only the declared
  bridge contract;
- finite-duration/depleting sources, daughter products, dose or protective-action criteria.

The time `xR/v` is an advective-center marker. With dispersion and decay, it is not generally the time of a concentration maximum or a regulatory arrival threshold.

## Acceptance boundary

NuclidePath is suitable for reproducible research demonstration and transparent preliminary sensitivity screening. It is not an operational emergency decision system, safety case, dose model or substitute for qualified authorities.

## Sources

- Ogata, A. & Banks, R.B., *A Solution of the Differential Equation of Longitudinal Dispersion in Porous Media*, USGS Professional Paper 411-A: <https://pubs.usgs.gov/pp/0411a/report.pdf>
- IAEA TECDOC-2095, *Distribution Coefficients for Soil, Freshwater and Marine Systems*: <https://www.iaea.org/publications/15878/distribution-coefficients-for-soil-freshwater-and-marine-systems-for-exposure-assessments>
- Leblond et al. (2024), DDEP re-evaluation of the Cs-137 half-life: <https://pubmed.ncbi.nlm.nih.gov/38290201/>
- EPA, *Understanding Variation in Partition Coefficient Kd Values*: <https://www.epa.gov/radiation/understanding-variation-partition-coefficient-kd-values>

## Current PR #24 registry checkpoint

PR #24 added the separate EPA/Fuller/Dubus external Cs benchmark registry. It merged into `main` as `2b256e322eaa8ca45a5b939fdecad09d66019b0c`; its GitHub-hosted CI run `30993946602` passed with `373 passed, 15 skipped`, including workflow policy, compilation, wheel and whitespace checks. This is not a trusted self-hosted PHREEQC run, an AMD post-merge rerun, or scientific calibration evidence. Two later review-hardening commits `3714bf8` and `1605cc6` landed directly on `main` on 6 August 2026 (oracle row binding, report numeric-finiteness gate, calibration promotion-gate tightening, atomic session-memory rewrite, free-text secret redaction, editorial CI gate). The current `main` head `df8f028` passed GitHub-hosted CI run `31111109865` with `377 passed, 15 skipped`.
