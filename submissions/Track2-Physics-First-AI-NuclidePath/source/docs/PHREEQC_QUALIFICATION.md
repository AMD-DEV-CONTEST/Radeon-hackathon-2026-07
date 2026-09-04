# PHREEQC bounded qualification

## Verdict

**PROCESS-QUALIFIED ONLY**

Phase F qualifies artifact identity, fail-closed preflight, controlled staging,
bounded execution, strict parsing, repeatability across two runs, ReplayBundle
integrity against a trusted external manifest root for one official PHREEQC Example 2 execution
slice. It does **not** qualify PHREEQC solver correctness, experimental
agreement, regulatory validity, general PHREEQC compatibility, or equivalence
with the NuclidePath GCS model.

The later schema-2 bridge carries a separate `NUMERICALLY VERIFIED` arithmetic
oracle for declared unit conversions, transport mapping, non-negativity and
exchange-capacity closure. That oracle is not a solver oracle and does not
change the global Phase F verdict.

The later scenario compiler is a separate, narrow opt-in translation surface:
it maps only the declared NuclidePath chemistry/transport contract to a bounded
PHREEQC input. It is not a general NuclidePath-to-PHREEQC translator and does
not change the Phase F scientific verdict.

## Terminology

### Process qualification

The process executes hash-pinned artifacts through the specified contract and
produces repeatable output. This is the scope that Phase F establishes.

### Scientific-input qualification

The input and database have upstream provenance and exact checksums and match
the selected official case.

### Scientific-result qualification

Scientific-result qualification requires solver comparison, experimental
evidence, or another qualified external scientific basis. The arithmetic
oracle added to the schema-2 bridge verifies only the declared projection
contract and is not sufficient for scientific-result qualification. Phase F
therefore records:

```json
{
  "process_qualified": true,
  "scientific_input_qualified": true,
  "scientific_result_qualified": false
}
```

## Provenance

| Item | Recorded value |
|---|---|
| Release asset | PHREEQC `3.9.0-17591`, `phreeqc-3.9.0-17591.tar.gz` |
| Upstream location | HTTPS release asset under `phreeqc-dev/phreeqc3`, v3.9.0, linked by the USGS repository; accepted only after checksum verification |
| Archive SHA-256 | `fda26290d96f6785e440c05217bf4b9fa9cd1efbf2fee155591e05b30165c6cd` |
| Self-reported banner | `PHREEQC 3.8.9, October 13, 2025` |
| Database | `phreeqc.dat` |
| Database SHA-256 | `5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278` |
| Official case | Example 2, “Temperature dependence of solubility of gypsum and anhydrite” |
| Input SHA-256 | `bff24cafb046ebcb0fd54263f6617fd3bddea1fe21da079d9e13af5ebecdbcc5` |
| Selected-output SHA-256 | `d83b5148c6350aaac58c18ba5cffa4b8837b0254f7d8cac4a8d45c7681d6cfec` |
| Compiler | `c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` |
| Build tool | GNU Make 4.3 |
| Checkpoint D host | Linux 6.12.13, x86_64 |
| Fixture-generation executable | `68f3fbab44c681989cb967240de2c3629177553099cbbe8703440a188cd796c5` |
| Checkpoint C final-test executable | `52b27cba4934521726fbd2a820d79d854d7ab5e86142ba407f495f43598ce9b4` |
| Checkpoint D fresh executable | `3ce90589723a73e94c8ccd92206c5089e4617fbbca18ee38eaf08d1a545e71c1` |

Executable hashes can differ because build paths and toolchain effects may be
embedded in a binary. Reproducing the same selected output demonstrates
stability of this bounded execution slice; it does not establish binary
portability.

## Release/banner discrepancy

The verified archive is release `3.9.0-17591`, while the executable reports
`PHREEQC 3.8.9, October 13, 2025`. This is recorded as an observed upstream
anomaly. Phase F neither corrects nor reinterprets it; the exact observed banner
is part of the qualification matcher.

## Official case

`tests/fixtures/phreeqc/example2.pqi` is a byte-exact copy of upstream
`examples/ex2`. Its upstream `SELECTED_OUTPUT` block was already present, and no
scientific or output instruction was modified. Two independent clean working
directories produced byte-identical selected output with the recorded digest.
The file has 53 lines: one header and 52 data rows. The parser requires exactly
one `i_soln` row and 51 `react` rows.

## Execution contract

Configuration requires absolute paths, regular files, non-symlink sources, an
absolute non-symlink working directory, lowercase SHA-256 digests, a positive
finite timeout, and an explicit full-match banner rule. Preflight streams source
hashes, creates a dedicated empty staging directory, copies executable,
database, and input without following symlinks, and rechecks staged hashes. The
staged executable is the absolute first command token.

The generic adapter runs with a fixed working directory, `stdin` disabled, and
a minimal environment that does not inherit proxy or credential variables.
Stdout and stderr have independent 1 MiB defaults, are read incrementally, and
are hashed as raw bytes. Invalid UTF-8 replacement affects only retained text;
timeout, launch failure, non-zero status, and stream-limit violation remain
distinct fail-closed states. Duration and local paths are metadata outside the
canonical qualification payload.
Final overflow classification is derived from both completed stream counters
after bounded draining, so simultaneous stdout/stderr overflow cannot be hidden
by a fast zero exit.
On POSIX, stream draining uses non-blocking selector reads governed by the same
monotonic deadline as execution. An inherited writer outside the solver process
group cannot block the call indefinitely: incomplete drain is recorded and
rejected. This does not claim termination of a descendant that escaped through
`setsid()`; that guarantee requires external OS containment.

The Example 2 output policy is closed: `ex2.sel`, `phreeqc.out`, and
`phreeqc.log` are all mandatory, no other produced entry is accepted, each file
is limited to 16 MiB, and the combined limit is 32 MiB. Stable hashing opens
regular single-link files without following final symlinks where supported,
compares descriptor metadata before and after reading, and confirms that the
path still identifies the same file. Staged artifacts and the complete output
inventory are rechecked immediately before replay creation.

ReplayBundle is a closed directory of qualification records and digests: extra
files, directories, symlinks, or special entries are rejected. It is **not
self-contained** with respect to PHREEQC, its database, or the input fixture;
those external artifacts remain identified by digest. `results.json` carries a
`qualification_content_sha256` over a path-free canonical payload. Local paths,
duration, run identity, and Git provenance remain metadata, so identical runs
in different directories have equal canonical content digests without requiring
byte-identical bundle directories.

`verify_bundle()` establishes internal consistency only. Callers that retain
`ReplayBundle.manifest_sha256` outside the bundle can pass it back as
`expected_manifest_sha256` to bind verification to that trusted external root.
Neither mode authenticates an author: authenticity requires an external
signature, attestation, transparency log, or equivalent provenance system.

This contract does not provide operating-system sandboxing or network
isolation. Those controls must be supplied externally when required.

## Selected-output parser and case validator

The structural parser requires the exact whitespace-bearing, tab-delimited header emitted
for `sim`, `state`, `soln`, `dist_x`, `time`, `step`, `pH`, `pe`, `temp`,
`si_anhydrite`, and `si_gypsum`. It requires the exact field count and terminal
delimiter, finite numeric values, genuinely integral integer fields, only the
states `i_soln` and `react`, and the fixed 1+51 row cardinality. A separate
Example 2 validator checks only upstream control invariants: state order,
simulation/solution identifiers, step 1..51, temperature 25..75 °C, and the
emitted distance/time controls. It does not treat pH, pe, or saturation indices
as an independent scientific oracle. The byte-exact selected-output digest,
rather than semantic parsing, detects changes to those scientific values.
The selected output is hashed, retained, decoded, parsed, and normalized from
one verified file-descriptor read; it is never reopened to obtain parser input.

Units are declared separately: distance in metres, time in seconds,
temperature in degrees Celsius, state as a category, and the remaining fields
as dimensionless values. Normalization preserves emitted decimal values and
distinguishes initial and reaction rows. Exact equality is appropriate for two
textualized outputs from this same slice; it is not a numerical tolerance or a
claim of scientific validation.

## Workflow and runners

`.github/workflows/phreeqc-qualification.yml` is manual `workflow_dispatch`
only. It uses `[self-hosted, nuclidepath]`, rejects refs other than
`refs/heads/main`, grants only `contents: read`, disables checkout credential
persistence, and requires executable/database paths and hashes. It has no pull
request trigger and was not executed from this feature branch.

Separately, ordinary `.github/workflows/ci.yml` runs pull-request code only on
GitHub-hosted `ubuntu-24.04`; it cannot select the NuclidePath self-hosted
runner. Both workflows are structurally checked against an exact, versioned
policy before tests run.

## Cs/K gap

The qualified `phreeqc.dat` does not contain enough evidence for a credible
Cs/K qualification: the required master species, aqueous species, exchange
reactions, and scientifically defensible constants are not available as a
complete supported set. Phase F adds no demonstration constants and makes no
Cs/K qualification claim.

## Reproduction

Install into a new absolute directory and record the emitted provenance:

```bash
scripts/install_phreeqc_3_9_0.sh /workspace/phreeqc-phase-f
sha256sum /workspace/phreeqc-phase-f/install/bin/phreeqc \
  /workspace/phreeqc-phase-f/install/share/doc/phreeqc/database/phreeqc.dat
```

Run the dependency-light suite (the real test skips before reading solver
variables):

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
```

Run the real test explicitly:

```bash
PHREEQC_EXECUTABLE=/absolute/path/phreeqc \
PHREEQC_DATABASE=/absolute/path/phreeqc.dat \
PHREEQC_EXECUTABLE_SHA256=<lowercase-sha256> \
PHREEQC_DATABASE_SHA256=<lowercase-sha256> \
python -m pytest -q tests/test_phreeqc_external.py --run-external-solver
```

Success requires two zero-exit, non-timeout runs; the exact banner and selected
output digest; byte-identical and normalized-identical output; valid row counts;
a ReplayBundle verified against its externally retained root digest; and
`scientific_result_qualified: false`. Missing variables, relative paths,
symlinks, malformed hashes, mismatches, parser deviations, timeouts, nonzero
status, or replay mutation fail closed. ReplayBundle is a Python API; the public
replay CLI verifies an existing bundle but intentionally does not infer a rerun.

## Limits

- Executable hashes are build-specific.
- The arithmetic oracle covers only declared unit, mapping, non-negativity and
  exchange-capacity invariants; there is no experimental dataset or calibrated
  multi-cation Cs result.
- There is no **general** NuclidePath-to-PHREEQC input translation; only the
  explicit schema-2 scenario compiler is supported.
- There is no equivalence claim with GCS.
- There is no general PHREEQC compatibility claim.
- There is no regulatory validation.
- The schema-2 multicomponent Cs bridge is not scientifically qualified: its
  selectivity, CEC mapping and transport pairing remain calibration-dependent.
- There is no operating-system-level network isolation in the adapter.

## Current bridge gate

The schema-2 bridge now includes the independent arithmetic oracle described in
[PHREEQC numerical oracle](PHREEQC_NUMERICAL_ORACLE.md). Its evidence level is
`NUMERICALLY VERIFIED`; it does not promote the PHREEQC result to a validated
scientific result.

The merged multicomponent bridge is covered by final integration CI run
[30928408962](https://github.com/anakinsuper/NuclidePath/actions/runs/30928408962):
364 passed, 15 skipped, workflow policy PASS, wheel PASS and whitespace PASS.
A pinned local PHREEQC execution also completed for both Central Oklahoma cases
with 40 shifts and 41 rows each; parser, arithmetic oracle and ReplayBundle
verification passed. This is process/integration evidence only. The trusted
manual workflow for the two Central Oklahoma cases remains pending on
`refs/heads/main` and is still the separate qualification gate.

PR #22 adds the non-runner calibration/hold-out infrastructure and its CI run
[30936374478](https://github.com/anakinsuper/NuclidePath/actions/runs/30936374478)
passed with 370 passed and 15 skipped. PR #24 subsequently added the separate
external Cs benchmark registry; its CI run `30993946602` passed with 373
passed and 15 skipped. The later review-hardening commits `3714bf8` and
`1605cc6` brought the current `main` head `df8f028` to run `31111109865` with
377 passed and 15 skipped. This validates the software gate only;
without an authorized measured dataset it does not qualify Cs chemistry or
promote the global PHREEQC verdict.

## CI security boundary

Automatic pull-request checks run only on GitHub-hosted `ubuntu-24.04`; the
self-hosted NuclidePath runner is reserved for trusted manual qualification on
`refs/heads/main`. Actions and Python CI tools are immutably pinned, checkout
credentials are not persisted, and no shared workflow cache is used. See
[CI and runner trust boundary](CI_SECURITY.md) for the residual administrative
and host-security assumptions.
