# E4 / M3 W7900 execution handoff

Status: `PREPARED / KINNYUWW PHYSICAL EXECUTION PENDING`

This is an execution-only handoff:

- the implementation owner has prepared the application code, migrations,
  fixed public fixture, exact pass/fail checks, deterministic negative paths,
  real-model capture, sanitized artifact allowlist and packet finalizer;
- `kinnyuww` only starts the frozen localhost vLLM service and runs the single
  prepared command on the shared Radeon Cloud W7900 instance;
- a failed step is returned to the implementation owner. The runner or evidence
  files must not be edited ad hoc on the W7900 instance.

This proves exact-commit E4/M3 compatibility. It is not E8 Baseline v1 and
makes no latency, throughput, VRAM-improvement or optimization claim.

## What the single runner verifies

1. persistent Radeon Cloud layout and W7900 device visibility;
2. ROCm, HIP, PyTorch and vLLM `RocmPlatform`;
3. sanitized environment identity and full frozen-model SHA-256;
4. localhost vLLM health, native structured Tool Call and E1 Runtime
   allow/deny/restart behavior;
5. current E4 contract export and M3 backend regressions;
6. deterministic bounded repair, unsupported evidence rejection, forged
   permission rejection and zero-effect policy denial;
7. a real localhost-model M1→M2→M3 create, explicit review and confirmation;
8. M2 correction, M3 invalidation and real-model M3 regeneration;
9. durable sanitized model metadata, LangGraph node traces, SQLite restart
   identity and artifact hashes;
10. reviewer-visible M3 evidence moment titles, source statement text and stable
    identifiers behind each ledger claim;
11. creation of a Git-ready packet candidate containing only the public
    allowlist.

Raw prompts, model responses, tool arguments, observations, unrestricted logs,
credentials and private data are never copied into the packet candidate.

## Prerequisites

Use the existing persistent paths:

```text
/workspace/amd-track2-agent/repo
/workspace/amd-track2-agent/venvs/agent
/workspace/amd-track2-agent/venvs/vllm
/workspace/amd-track2-agent/models/Qwen2.5-14B-Instruct-3957bf39753c
```

Fetch and check out the exact reviewed E4 branch/commit. The runner rejects:

- a dirty worktree;
- a commit that differs from `--expected-commit`;
- an output path outside `/workspace/amd-track2-agent/evidence`;
- an Agent Python invoked outside the persistent Agent environment, or a
  mismatched `VIRTUAL_ENV`. The normal virtualenv Python symlink to the system
  interpreter is accepted without dereferencing the invoked path.

The M3 request is intentionally bounded for the frozen 14B profile: one ledger
entry, exactly five role statements, 1,536 output tokens and a 120-second
per-call timeout. These limits are part of the reviewed compatibility fix; do
not override them on the pod. The entry-level `source_moment_ids` capacity is
the number of M2 moments supplied in that request, and it must contain every
moment referenced by its five statements. The Runtime deterministically appends
any statement-used moment omitted from the entry envelope before applying the
unchanged strict evidence checks; it does not rewrite statement text or choose
new evidence.

The environment capture recognizes the W7900 from its stable observed hardware
profile (`gfx1100`, 96 compute units and approximately 48 GiB VRAM), not from
the PyTorch marketing/display name. The official pod may report the raw name as
`AMD Radeon Graphics`; that raw value is retained in the evidence record.

In terminal 1, start the frozen localhost profile and keep it running:

```bash
cd /workspace/amd-track2-agent/repo
bash scripts/serve_vllm.sh
```

Do not expose vLLM and do not run `rc-tunnel expose`.

## Exact command for kinnyuww

In terminal 2:

```bash
cd /workspace/amd-track2-agent/repo
source /workspace/amd-track2-agent/venvs/agent/bin/activate

e4_commit="$(git rev-parse HEAD)"
e4_run_id="$(date -u +%Y%m%dT%H%M%SZ)"
e4_run_root="/workspace/amd-track2-agent/evidence/e4-m3-w7900/${e4_run_id}"
mkdir -p "$e4_run_root"

python scripts/run_e4_w7900_gate.py \
  --expected-commit "$e4_commit" \
  --output-dir "$e4_run_root/raw"
```

The command stops on the first failure and preserves `run-result.json` plus
the failed step log. Do not delete a failed run or rerun into the same
directory. Send the failing step name and log to the implementation owner.

## Successful output

```text
<e4_run_root>/
├── raw/                        # PVC only; never commit wholesale
│   ├── run-result.json
│   ├── *.log
│   └── artifacts/
└── packet-candidate/           # sanitized; review before copying to Git
    ├── manifest.json
    ├── summary.md
    └── artifacts/
```

Review `packet-candidate` for credentials, private data and exact commit
identity. After review, copy it append-only to:

```text
evidence/milestones/e4-m3-w7900/<e4_run_id>/
```

A successful command changes the evidence status only to
`W7900_COMPATIBILITY_READY_FOR_REVIEW`. `kinnyuww` still performs the
independent quality review before E4 promotion or merge.

## Failure ownership

- Environment, model or service failure: retain the raw run and send the
  failing step/log to `kinnyuww`.
- Contract, regression, capture or finalizer failure: return it to the E4
  implementation owner; do not weaken the check.
- Credential or private-data finding: stop and do not copy the candidate to
  Git.
- Before destroying the instance, run
  `bash scripts/pre_stop_checkpoint.sh`.
