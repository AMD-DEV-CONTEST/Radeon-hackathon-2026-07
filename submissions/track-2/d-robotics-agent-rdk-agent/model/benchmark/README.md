> English version: [README.en.md](README.en.md)

# Frozen Base/SFT model replay

This directory contains three small, standard-library-only tools:

- `eval_ab.py` runs one Base or SFT arm and writes resumable raw JSONL plus an atomic identity manifest.
- `seal_interrupted_arm.py` creates a one-time, read-only recovery seal for a cleanly interrupted capped arm.
- `summarize_ab.py` accepts two arm manifests, verifies every raw record and hash, then emits one summary.

The runner is deliberately specific to the frozen Test and the two released model identities. The Test was historically held out during evaluation and released afterward for reproducibility. It pins 113 tasks, 413 assistant turns per arm, 3,562,357 bytes, and SHA-256 `d1e1856b…5e283` in code. The 413 turns contain 300 tool-call turns (467 individual calls) and 113 final-answer turns. Results are reported separately for curated and promoted samples.

## Published result

The current published run is `model-ab-heldout113-20260805-v2`:

- [Human-readable result](runs/model-ab-heldout113-20260805-v2/RESULTS.md)
- [Canonical machine summary](runs/model-ab-heldout113-20260805-v2/summary.json)
- [Checksum ledger](runs/model-ab-heldout113-20260805-v2/SHA256SUMS)

It is a recovery-sealed, user-capped ordered prefix of 49 complete tasks / 170
assistant turns per arm, not a representative result over all 113 tasks. The run
document states the supported claim, observed cost, and evidence boundary.

## Portable independent recomputation

From the published run directory, a judge can verify the frozen Test, rebuild each
reference, independently rescore the Base/SFT responses, and compare every headline
metric with the published summary:

```bash
python3 ../../recompute_ab.py \
  --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
  arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
```

Providing `--test` selects the portable independent-rescore path. The manifests and
recovery seals remain the historical run provenance; the stricter summarizer below
also validates original-host filesystem snapshots and is not the cross-machine entry.

## One-arm runner

Run on the model host. The API key remains a host-local file and is never written to output. Pin every service identity field and immutable file needed for that arm:

```bash
python3 -B eval_ab.py \
  --test /path/to/frozen/test.jsonl \
  --api-key-file /host-only/path/api_key \
  --label base \
  --run-id model-ab-heldout113-YYYYMMDD-v1 \
  --raw-out /run/base.raw.jsonl \
  --manifest-out /run/base.manifest.json \
  --service-pid-file /path/to/server.pid \
  --expect-process-arg Qwen3-32B-Base-bnb-4bit \
  --forbid-process-arg=--adapter \
  --expect-file-sha256 /path/to/base-config=EXPECTED_SHA256 \
  --expect-file-sha256 /path/to/model-index=EXPECTED_SHA256 \
  --expect-file-sha256 /path/to/server=EXPECTED_SHA256 \
  --expect-file-sha256 /path/to/launcher=EXPECTED_SHA256 \
  --expect-file-sha256 /path/to/deployment-manifest=EXPECTED_SHA256
```

`--label` selects the built-in Base or checkpoint-000119 SFT identity contract: canonical request/response model, health fields, fingerprint, required artifact hashes, and adapter rules cannot be overridden from the command line. The raw file and manifest intentionally share one run directory. The same command safely resumes after evaluator interruption when both are present, the complete run contract is unchanged, and the serving process identity has not restarted. A completed arm is immutable: raw drift is rejected instead of being resealed. HTTP errors, health drift, port-owner/process drift, response-model drift, input drift, identity-file drift, malformed output, and duplicate records all exit non-zero. Failed requests are never recorded as completed.

## Original-host strict summary

```bash
python3 -B summarize_ab.py \
  base.manifest.json sft.manifest.json \
  --test /path/to/frozen/test.jsonl \
  --out summary.json
```

The summarizer independently reloads the frozen Test, rebuilds all 413 references and strata, and recomputes every score without trusting the stored reference or score fields. Full mode refuses partial arms; both modes refuse contract/hash drift, Base/SFT identity substitution, response-identity drift, mismatched Test data, different record sets, or overwrite of an existing summary. It scores every ordered tool call and its finish reason, requires non-empty clean final answers, and also reports strict final-text agreement.

For the user-capped run, both evaluators must be stopped cleanly with `SIGTERM`
after reaching the same frozen prefix. The fixed cap is the first 49 complete tasks
(task indices 0 through 48), containing 170 assistant turns per arm. Before switching
the service to the other model, recovery-seal the interrupted arm while the exact
original service PID is still live:

```bash
python3 -B seal_interrupted_arm.py sft.manifest.json \
  --test /path/to/frozen/test.jsonl \
  --api-key-file /host-only/path/api_key \
  --out sft.recovery-seal.json
```

The seal leaves the original manifest unchanged. Under the same directory and PID-file
locks used by the evaluator, it verifies the complete ordered prefix, rechecks the
current health, PID/start ticks/argv/listener, and identity-file hashes against the
original contract, then binds the read-only manifest and raw snapshots in a new
read-only sidecar. The API key remains host-local and is not written to the seal.

After both arms are sealed, summarize them:

```bash
python3 -B summarize_ab.py \
  base.manifest.json sft.manifest.json \
  --test /path/to/frozen/test.jsonl \
  --capped-prefix-170 \
  --base-recovery-seal base.recovery-seal.json \
  --sft-recovery-seal sft.recovery-seal.json \
  --out summary.json
```

The capped summarizer accepts exactly 170 durable records, or 171 when a request
finishes before the evaluator observes `SIGTERM` at a safe point. In the latter case
it verifies that the extra record is exactly the next frozen-plan turn and excludes
it symmetrically. The summary status is `CAPPED_RECOVERY_SEALED`.

This prefix is deterministic but not representative of the full Test: it contains
28 curated live-diagnostic, 5 curated controlled-actuation, and 16 promoted
live-diagnostic tasks; it omits all 15 promoted controlled-actuation tasks. The cap
was not part of the original evaluator contract. Because the original
`SIGTERM` manifest did not hash raw output or capture stop-time final identity, the
recovery seal proves only the later read-only snapshot and seal-time identity check;
it does not retroactively create runner-finalized evidence at the stop instant.
The origin host produces the summary while inode/stat assertions remain valid;
exported bundles are subsequently verified through the sealed hashes and checksum
ledger rather than by replaying host-local inode assertions.

Runtime state belongs in a dedicated run directory, never beside these source files. Only frozen raw JSONL, the two arm manifests, both recovery seals when capped, `summary.json`, and their final checksum ledger belong in a published evidence bundle. Temporary atomic-write files are removed by the tools themselves.

This is teacher-trajectory replay agreement, not end-to-end Agent success, real-board execution, or physical-effect evidence.
