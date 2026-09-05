# E3 / M2 W7900 execution handoff

Status: `PREPARED / REAL W7900 EXECUTION PENDING`

This handoff separates preparation from physical execution:

- the implementation owner prepares the exact commands, fixed public input,
  pass/fail checks, sanitized artifacts and packet finalizer;
- `kinnyuww` runs the prepared gate on the unified Radeon Cloud W7900 instance
  and returns the generated packet candidate for review;
- no one may mark W7900, ROCm, vLLM or model compatibility as passed before
  that real run succeeds.

This is an exact-commit compatibility rerun for E3. It is not E8 Baseline v1,
does not measure a Candidate, and makes no latency, throughput, VRAM-improvement
or optimization claim.

## What is already prepared

The single runner performs and retains:

1. persistent Radeon Cloud and W7900 device checks;
2. ROCm, HIP, PyTorch and vLLM `RocmPlatform` checks;
3. a sanitized machine-readable environment record;
4. full SHA-256 verification of the frozen 14B BF16 model snapshot;
5. localhost vLLM health and native structured Tool Call checks;
6. the real-model proposal contract and Runtime allow/deny/effect/restart gate;
7. E3 M2 API and LangGraph regressions;
8. a fixed public M1→M2 scenario covering cue, change/turning point, surprise,
   trusted user decisions, correction invalidation and latest-version
   regeneration;
9. a sanitized semantic-model record containing the localhost identity,
   exact model-call count and validated proposal hash without raw prompts or
   responses;
10. sanitized artifact hashes and a Git-ready packet candidate.

Raw logs stay under `/workspace`; the packet finalizer copies only the explicit
public allowlist and never copies unrestricted logs.

## One-time prerequisites

Use the existing persistent layout:

```text
/workspace/amd-track2-agent/repo
/workspace/amd-track2-agent/venvs/agent
/workspace/amd-track2-agent/venvs/vllm
/workspace/amd-track2-agent/models/Qwen2.5-14B-Instruct-3957bf39753c
```

The target task branch must be fetched, checked out, clean and pushed. The
runner rejects a dirty tree, a mismatched commit, a non-persistent output
location, or an Agent Python outside the persistent Agent environment.

Start the frozen localhost vLLM profile in a separate terminal and leave it
running:

```bash
cd /workspace/amd-track2-agent/repo
bash scripts/serve_vllm.sh
```

Do not expose the raw vLLM API or run `rc-tunnel expose`.

## Exact teammate command

In a second terminal:

```bash
cd /workspace/amd-track2-agent/repo
source /workspace/amd-track2-agent/venvs/agent/bin/activate

e3_commit="$(git rev-parse HEAD)"
e3_run_id="$(date -u +%Y%m%dT%H%M%SZ)"
e3_run_root="/workspace/amd-track2-agent/evidence/e3-m2-w7900/${e3_run_id}"
mkdir -p "$e3_run_root"

python scripts/run_e3_w7900_gate.py \
  --expected-commit "$e3_commit" \
  --output-dir "$e3_run_root/raw"
```

The command stops at the first failed gate but retains `run-result.json` and
the failed step log. Do not delete or rerun over a failure. Correct the cause
and use a new UTC run directory so the history remains append-only.

## Outputs

After a successful run:

```text
<e3_run_root>/
├── raw/                        # PVC only; never commit wholesale
│   ├── run-result.json
│   ├── *.log
│   └── artifacts/
└── packet-candidate/           # sanitized, review before copying to Git
    ├── manifest.json
    ├── summary.md
    └── artifacts/
```

Review `packet-candidate` for credentials, private data and accurate commit
identity. After review, copy it append-only to:

```text
evidence/milestones/e3-m2-w7900/<e3_run_id>/
```

The quality owner then reviews the packet and PR. A successful execution
changes the evidence status to `W7900_COMPATIBILITY_READY_FOR_REVIEW`; only the
quality owner can accept E3 or merge the PR.

## Failure ownership

- Environment/model/service failure: retain the raw failed run and send the
  failing step name plus its log to `kinnyuww`.
- E3 regression or artifact failure: return it to the E3 implementation owner;
  do not weaken the gate or edit the generated result.
- Any credential/private-data finding: stop; do not copy the candidate into
  Git.
- Before destroying the instance, run `bash scripts/pre_stop_checkpoint.sh`.
