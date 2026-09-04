# NuclidePath work handoff

Updated: 2026-08-06

Read this file first when resuming the project in a new ChatGPT Work session.
GitHub remote state is the source of truth; verify it before acting.

## Current repository state

- Repository: `anakinsuper/NuclidePath`
- Default branch: `main`
- Current `main` contains the Phase F merge, the generalized multicomponent PHREEQC compiler bridge, the K-free Central Oklahoma cases, and the diagnostics/report integration; fetch `main` directly for the current HEAD before acting.
- PR #2: **closed and merged** on 2026-08-03
- PR #2 head before merge: `84ff5af28fd77fb1ea6960cf0b10c2cce2da064a`
- Feature branch: `feat/phase-f-phreeqc-qualification`
- Scientific verdict: **PROCESS-QUALIFIED ONLY**
- Offline Cs calibration/hold-out gate: **implemented, not promoted**; the external benchmark registry is bundled, but no promotion-eligible experimental dataset is bundled.
- PR #7: **closed and merged** on 2026-08-03; merge commit `e068219222d24300d90bd39b49eafbf7b3cfc349`.
- PR #9: **closed and merged** on 2026-08-04; merge commit `a9ee77c254abe6a19a2011b4fb55b956b811dea4`.
- PR #11: **closed and merged** on 2026-08-04; documentation/submission synchronization merge commit `8a7ca0c7594063735c577d1e02c48a8676a05596`.
- PR #12: **closed and merged** on 2026-08-04; post-merge handoff synchronization merge commit `5c5d4b302eeb48f871c113ad523f37e25a551d39`.
- PR #13: **closed and merged** on 2026-08-04; current-main handoff wording synchronization merge commit `39cdfa07245adfff5bab54602930d0fba4f5d475`.
- PR #14: **closed and merged** on 2026-08-04; PHREEQC contract hardening and submission-state cleanup merge commit `8e8e09b658ce9fe3cb24dabc96d76066b38a6a5d`.
- PR #15: **closed and merged** on 2026-08-04; independent numerical oracle and real-run parser/replay hardening merge commit `96f31c0e21501cab582ed5600acf2de9f08a5189`.
- PRs #16–#21: **closed and merged** on 2026-08-04; documentation-only release-state synchronizations.
- PR #22: **closed and merged** on 2026-08-04; dependency-free traceable Cs calibration/hold-out gate merge commit `7c4079ad84812164a4bfd3f4f7b8f24c6708f41b`.
- PR #24: **closed and merged** on 2026-08-05; external Cs benchmark registry merge commit `2b256e322eaa8ca45a5b939fdecad09d66019b0c`; CI `30993946602` passed with `373 passed, 15 skipped`.
- PR #25: **closed and merged** on 2026-08-05; submission-state synchronization after the registry merge.
- Review-hardening commits `3714bf8` (376 passed) and `1605cc6` (377 passed) landed directly on `main` on 2026-08-06 without a pull request. Current `main` head `df8f028`; CI run `31111109865` passed with `377 passed, 15 skipped`.
- Historical science branch: `science/numeric-oracle-2026-08-04`; its reviewed content is now in `main`.

Before the external-benchmark registry work, the last code-bearing `main`
checkpoint verified for this handoff was PR #22 at head
`f74943ed12b07080578536e3d8deb0f3831ad310`, merged as
`7c4079ad84812164a4bfd3f4f7b8f24c6708f41b`. Its GitHub-hosted CI run
`30936374478` passed with `370 passed, 15 skipped`. The preceding PHREEQC bridge
checkpoint is PR #15 at `96f31c0e21501cab582ed5600acf2de9f08a5189`.
These are historical evidence checkpoints; fetch `main` directly before acting.

The merges used the ordinary merge method and preserved the reviewed commit
history. The feature branches remain available as historical provenance; the
current project state is `main`.

## Phase F completion

PR #2 qualified one checksum-pinned official PHREEQC Example 2 execution slice.
It did not establish scientific-result validation, Cs/K qualification, general
PHREEQC compatibility, GCS equivalence, regulatory validity, or production
readiness.

Completed remediation:

- R1: fail-closed non-zero/timeout handling, process-group cleanup and reaping,
  staged-artifact verification, run/result identity binding, and derived
  classification.
- R2A: raw-byte bounded streams, closed output and replay policies, stable file
  checks, canonical qualification content, and separated structural/case
  validation.
- R2B: GitHub-hosted automatic CI, trusted manual-runner boundary, full Action
  SHA pins, Python 3.11.15, hash-locked CI dependencies, and credential
  persistence disabled.
- R3: same-byte selected-output hashing/parsing, trusted external ReplayBundle
  root verification, exact YAML workflow structure checking, and pinned lock
  bootstrap.
- R4: selector-based bounded POSIX draining after leader exit, fail-closed
  incomplete drain, bounded post-SIGKILL reap, explicit `setsid()` escape
  boundary, and exact workflow step policy.

## Verified evidence

The final Phase F PR CI run was:

- Run: `30839222404`
- Runner: GitHub-hosted `ubuntu-24.04`
- Python: `3.11.15`
- Workflow policy: PASS
- Dependency-light suite: `339 passed, 14 skipped, 0 failed`
- Wheel build: successful
- Whitespace check: successful

The multicomponent PR #9 CI run was:

- Run: `30864728585`
- Runner: GitHub-hosted `ubuntu-24.04`
- Python: `3.11.15`
- Workflow policy: PASS
- Dependency-light suite: `356 passed, 15 skipped, 0 failed`
- Wheel build: successful
- Whitespace check: successful

The documentation/submission synchronization PR #11 CI run was:

- Run: `30867706949`
- Python: `3.11.15`
- Workflow policy: PASS
- Dependency-light suite: successful
- Wheel build: successful
- Whitespace check: successful

PR #11 also regenerated the current internal deck, specification PDF, contact
sheets and video cards; `submission/ARTIFACT_MANIFEST.json` recorded 16 tracked
artifact hashes **at that PR #11 checkpoint**; the manifest has since grown and
currently tracks 22 artifacts. The visual package is intentionally core-path evidence and
does not show or claim a trusted PHREEQC multicomponent run.

Independent final review also verified the real PHREEQC test as
`1 passed, 0 skipped, 0 failed`, including two clean runs, byte-identical
selected output, same-byte parsing, canonical qualification content, trusted
root replay verification, classification derivation, and no residual PHREEQC
processes. The executable digest is build-specific.

## Latest merged bridge evidence

PR #14, PR #15 and PR #22 are merged into `main`. The final GitHub-hosted
integration CI run for the merged bridge path is `30928408962`: 364 passed, 15
skipped, workflow security policy PASS, compilation PASS, wheel PASS and
whitespace PASS. The later PR #22 calibration-gate CI run is `30936374478`: 370
passed, 15 skipped, with the same technical gates PASS. The pinned local PHREEQC execution of both Central Oklahoma fixtures
also passed parsing, the independent oracle and ReplayBundle verification;
this is process/integration evidence, not calibrated scientific validation.

## PHREEQC chemistry bridge milestone

The first bridge increment is now represented by the compiler, CLI, full-pipeline
demonstration scenario, deterministic selected-output parsing, bounded
execution through the existing adapter, replay writing, chemistry diagnostics,
and compile-only report artifacts. It maps declared water chemistry, CEC and Cs plus one or more declared
K/Na/Ca/Mg exchange coefficients into PHREEQC input. Schema 2 generates the
selected-output columns, parser mappings, and per-ion diagnostics from the
declared set, so K-free Na-Ca-Mg cases are supported. The canonical empirical
Kd and decay path remain unchanged. The merged PR #15 adds an independent
arithmetic oracle for unit, grid, non-negativity and exchange-site occupancy
invariants, persisted in diagnostics and replay JSON.

Its scientific status is deliberately limited:

- PROCESS-QUALIFIED ONLY;
- the arithmetic oracle verifies only the declared software/unit contract;
- no calibrated multi-cation Cs database or experimental agreement;
- paired K-free Central Oklahoma brine/recharge fixtures are sourced-composition integration cases, not validated transport predictions;
- no GCS equivalence or general PHREEQC compatibility claim;
- no automatic execution on the self-hosted runner;
- ordinary reports are compile-only and label the external run as pending;
- no LLM authority over coefficients or physical outputs.

The stable contract is documented in
`docs/PHREEQC_SCENARIO_COMPILER.md`. The report bridge was covered by PR CI runs
`30852320378` and final documentation run `30852551207`: Python `3.11.15`,
`354 passed, 15 skipped`, workflow policy PASS, wheel and whitespace checks
successful. PR #9 then generalized the bridge and passed CI run
`30864728585` with `356 passed, 15 skipped`, workflow policy PASS, wheel and
whitespace checks successful. A real PHREEQC run should be
performed only as a trusted manual qualification on `main`, with fresh
explicit executable and database digests.

## Scientific calibration gate

The non-runner remediation now includes [`docs/SCIENTIFIC_VALIDATION_GATE.md`](docs/SCIENTIFIC_VALIDATION_GATE.md) and `nuclear_agent.scientific_validation`.
The module validates traceable Cs exchange observations, explicit K/Na/Ca/Mg
units, group-disjoint calibration/hold-out membership, a transparent empirical
multi-cation apparent-Kd fit, hold-out metrics and a canonical report digest.
It fails closed for missing provenance, split leakage, non-finite values and
promotion without measured traceable data. Synthetic tests do not count as
scientific evidence. This gate is separate from the PHREEQC runner and does not
promote the global PHREEQC verdict.

`data/benchmarks/cs/manifest.json` separately records EPA, Fuller and Dubus
benchmarks with source hashes, CSV integrity checks and `calibration_eligible:
false`. The registry is useful for traceable comparison and later ingestion,
but its public-raw, derived and figure-digitized rows remain outside the
`ObservationDataset` promotion contract.

## Stable technical boundaries

### External solver and PHREEQC

The adapter provides artifact identity checks, bounded execution, bounded raw
stdout/stderr capture, timeout and overflow distinction, closed output policy,
and replayable records. On POSIX, non-blocking selector reads share one
monotonic deadline with leader execution. Escaped `setsid()` descendants may
survive, but inherited pipe writers cannot block the qualification call
indefinitely. Universal process-tree termination requires external OS
containment.

### ReplayBundle

Verification without an external root establishes internal consistency.
Verification with an externally retained `manifest_sha256` establishes
integrity relative to that trusted root. Neither mode authenticates an author or
provides a cryptographic signature. The bundle identifies PHREEQC, its database,
and fixtures by digest; it is not self-contained with respect to those
artifacts.

### Workflow and runner

Automatic pull-request and ordinary CI run only on GitHub-hosted
`ubuntu-24.04`. The PHREEQC workflow is manual-only, rejects refs other than
`refs/heads/main`, and uses the trusted `[self-hosted, nuclidepath]` runner.
That runner is not claimed to be ephemeral, isolated, or a sandbox. The manual
workflow must not be started automatically from a feature branch.

## Documentation map

- `README.md` — project purpose, architecture, quick start, and scientific
  limits.
- `docs/README.md` — complete documentation index.
- `docs/ROADMAP.md` — submission and future expansion roadmap.
- `docs/EXTERNAL_SOLVER_ADAPTERS.md` — generic execution contract.
- `docs/PHREEQC_QUALIFICATION.md` — Phase F evidence and limitations.
- `docs/PHREEQC_SCENARIO_COMPILER.md` — compiler, chemistry diagnostics and report bridge.
- `docs/PHREEQC_NUMERICAL_ORACLE.md` — independent arithmetic evidence contract.
- `docs/PHREEQC_MULTICOMPONENT_CASES.md` — sourced K-free Na-Ca-Mg cases and scientific boundary.
- `data/benchmarks/cs/manifest.json` — separate external Cs benchmark registry and digests.
- `docs/RELEASE_STATE.md` — current source/evidence/submission record.
- `docs/SUBMISSION_CHECKLIST.md` — human and technical gates.
- `docs/CI_SECURITY.md` — CI and runner trust boundary.
- `tests/fixtures/phreeqc/README.md` — fixture provenance.
- PR #2 — public review history and merged Phase F summary.
- PR #7 — merged PHREEQC diagnostics/report integration summary.

Stable technical contracts belong under `docs/`; current operational state
belongs here. Historical test counts and hashes must always be labelled with
the checkpoint they support.

## Next project gate

The private documentation, submission package and non-runner PHREEQC remediation are synchronized in `main`; documentation-only merges after PR #22 do not change the reviewed code path. Fetch `main` directly for the current state.
A **post-merge AMD/ROCm rerun of the `main` tree at head `b6d4c61e74`** was executed on 2026-08-05 on the AMD workspace (gfx1100, ROCm 7.2.1, torch `2.9.1+gitff65f5b`, head `b6d4c61e74`): **388 passed, 2 skipped** (only the external-PHREEQC solver tests), with the FP64 platform benchmark reproducing 1.82 ms median / 132.8× / 7.94e-14 max error. Evidence under `artifacts/amd-2026-08-05/post-merge/` with SHA256SUMS.
The public contest-fork branch
`submission/track2-physics-first-ai-nuclidepath` was synchronized on 2026-08-05
to `main` (verified byte-identical to head `df8f028` on 2026-08-06; re-sync required after any further `main` change) (latest documentation head
including the deck multicomponent bridge card and the spec cover multicomponent
note; code-bearing checkpoint
`2b256e322eaa8ca45a5b939fdecad09d66019b0c` from PR #24): the complete current
source is copied under `submissions/Track2-Physics-First-AI-NuclidePath/source/`
(clean tree, excluding `.git`, `.venv`, `node_modules`, `build`, `dist`,
`results` and `private-deliverables`), the specification PDF and deck are the
current `main` artifacts, and the contest-local manifest is
`nuclidepath-contest-manifest-2.0`. The public video URL remains the only
missing submission link.
The deadline-critical human-gated items remain due **6 August 2026, 17:59 CEST**:

1. confirm eligibility and AMD programme requirements;
2. collect and unauthenticatedly verify the judge-accessible video URL;
3. decide whether the complete source is made public or copied to the contest
   submission;
4. authorize the official public contest pull request.

The offline calibration gate is ready but awaits an authorized traceable experimental dataset. The external registry contains EPA, Fuller and Dubus benchmark material, but none is eligible for promotion and no thesis data or unapproved private data has been added. The next PHREEQC technical gate is a trusted real projection on
`refs/heads/main` for both sourced Central Oklahoma cases, using fresh
executable and database digests. The merged code has also passed a pinned local
process/integration run for both cases, but that run is not a substitute for the
trusted workflow and does not promote the scientific verdict. Do not start the
manual workflow automatically, from a feature branch, or from an untrusted ref.
Keep the result process-qualified/comparative evidence until calibration data and
experimental or otherwise qualified scientific agreement are available. The
arithmetic oracle is already present for the declared software contract.

Automated work may prepare and verify internal release material, but changing
repository visibility, publishing private source, or opening the official
public contest PR remains a separate explicit publication decision.

## Operational safety rules

- Preserve the `PROCESS-QUALIFIED ONLY` boundary in code, documentation, and
  release material.
- Do not present the self-hosted runner as a sandbox or universal process-tree
  cleanup mechanism.
- Do not run the manual PHREEQC workflow automatically or on a feature branch.
- Do not expose tokens, secrets, credentials, or private runtime state.
- Do not publish the private repository or contest source without the explicit
  publication decision recorded above.

## Reproduction commands

For dependency-light verification, use Python `3.11.15` and the committed
hash lock:

```bash
PYENV_VERSION=3.11.15 python -m venv /tmp/nuclidepath-review-venv
. /tmp/nuclidepath-review-venv/bin/activate

python -m pip install \
  --disable-pip-version-check \
  --no-input \
  --only-binary=:all: \
  --require-hashes \
  -r requirements/ci.txt

python -m pip install \
  --disable-pip-version-check \
  --no-input \
  --no-deps \
  --no-build-isolation \
  -e .

python -m pip check
python scripts/check_workflow_security.py
scripts/update_ci_lock.sh --check
python -m compileall -q src tests
python -m pytest -q
python -m build --wheel --no-isolation
```

Run the real solver test only with a fresh installation and explicit trusted
paths and digests:

```bash
scripts/install_phreeqc_3_9_0.sh /workspace/phreeqc-final-review

PHREEQC_EXECUTABLE=/workspace/phreeqc-final-review/install/bin/phreeqc \
PHREEQC_DATABASE=/workspace/phreeqc-final-review/install/share/doc/phreeqc/database/phreeqc.dat \
PHREEQC_EXECUTABLE_SHA256=<fresh-build-sha256> \
PHREEQC_DATABASE_SHA256=5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278 \
python -m pytest -q tests/test_phreeqc_external.py --run-external-solver
```
