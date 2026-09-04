# External solver adapters

## Scope

The generic adapter layer is a process-integrity and replay contract. It does
not translate arbitrary scientific inputs, validate solver science, or claim
general PHREEQC/MODFLOW compatibility. The separate schema-2 PHREEQC scenario
compiler provides only a narrow, explicit NuclidePath-to-PHREEQC projection;
the generic adapter remains responsible for bounded execution and replay.

`ExternalSolverManifest` is frozen and records the executable, optional database,
input files, SHA-256 digests, solver version, exact command, and strict working
directory. Preflight fails closed when an artifact is missing, is a symlink, lies
outside the working directory, or has a changed digest. The command must name the
hashed executable directly by absolute path.

Subprocesses run with `stdin=DEVNULL`, a fixed `cwd`, and a minimal deterministic
environment that does not inherit proxy or credential variables. The adapter does
not provide network isolation. Deployments that require network prohibition must
supply an operating-system, container, or equivalent sandbox.

## Bounded execution and stream capture

`run_replayable()` performs preflight before every run. Stdout and stderr have
independent 1 MiB defaults, are read incrementally, and are hashed over the raw
bytes. UTF-8 replacement applies only to the retained textual representation.
The result records bytes observed and retained, raw digests, timeout, launch
failure, process exit state, simultaneous stream-limit violations, drain
completeness, drain timeout, and stream errors.

A single monotonic deadline governs the solver leader and inherited stdout/stderr
writers. On POSIX, both pipes are non-blocking and are collected through
`selectors.DefaultSelector`; there are no POSIX reader threads to join. After the
leader exits, collection continues only for the remaining deadline. If a pipe
does not reach EOF before that deadline, the local read descriptor is closed and
the result records:

```text
streams_complete = false
stream_drain_timed_out = true
exit_status = null
```

Qualification therefore fails closed rather than waiting indefinitely. Final
stream-limit classification is derived from the completed bounded capture state,
so a fast zero exit cannot hide stdout or stderr overflow. Simultaneous overflow
is preserved canonically as `("stdout", "stderr")`.

On non-POSIX systems the fallback reader threads are joined only for the
remaining deadline. A surviving reader or capture error makes the stream state
incomplete and non-qualifiable. The fallback does not claim process-tree
containment beyond the directly launched process.

## Process containment boundary

On POSIX the solver leader starts in a dedicated session. TERM/KILL can therefore
cover descendants that remain in the original solver process group. A descendant
that calls `setsid()` or otherwise escapes that group may survive and may keep an
inherited pipe writer open. The adapter does not claim to terminate that escaped
process; it only guarantees that the inherited writer cannot block the
qualification call beyond the configured bound.

Guaranteeing termination of escaped descendants requires external containment,
for example a cgroup, container, PID namespace, job object, or comparable
operating-system control. The adapter does not scan global process tables or kill
processes by name.

## Adapter surfaces

Two configurations are exposed:

- `PhreeqcAdapter.configuration()` — named PHREEQC external configuration only.
- `GroundwaterSolverAdapter` — generic external groundwater-solver process contract.

Neither adapter installs a solver or requires one to be present. Dependency-light
tests use temporary Python executables and exercise unavailable artifacts,
tampering, timeout, path traversal, direct-executable enforcement, bounded output,
escaped pipe writers, process-group cleanup, and deterministic raw-byte capture.

## Bounded PHREEQC qualification

The generic adapter, the qualification harness, and the qualified case are
separate layers:

- `src/nuclear_agent/external_adapters.py` supplies generic artifact-integrity
  and bounded process-execution contracts.
- `src/nuclear_agent/phreeqc_qualification.py` adds controlled staging, exact
  banner matching, closed output policy, stable same-byte selected-output
  parsing, derived classification, and ReplayBundle payloads.
- `tests/fixtures/phreeqc/` contains the checksum-pinned official Example 2 input
  and selected output.
- `tests/test_phreeqc_external.py` is opt-in and executes two real runs only with
  `--run-external-solver` and all required paths and digests.

Together these layers verify artifact identity, bounded process behavior,
repeatability, and replay integrity for one execution slice. Verification against
an externally retained manifest root detects a fully rebuilt bundle relative to
that trusted root, but it does not authenticate an author. These layers do not
verify general scientific correctness, arbitrary PHREEQC semantics, MODFLOW
compatibility, general NuclidePath-to-PHREEQC translation, multi-cation Cs qualification,
calibrated chemistry, or regulatory validity.

## Related documentation

- [PHREEQC bounded qualification](PHREEQC_QUALIFICATION.md)
- [CI and runner trust boundary](CI_SECURITY.md)
- [Documentation index](README.md)
- [Current work handoff](../WORK_HANDOFF.md)
- [`install_phreeqc_3_9_0.sh`](../scripts/install_phreeqc_3_9_0.sh)
- [Fixture provenance](../tests/fixtures/phreeqc/README.md)
- [Opt-in real-solver test](../tests/test_phreeqc_external.py)
- [PHREEQC scenario compiler](PHREEQC_SCENARIO_COMPILER.md)
