# Security Model

## Purpose and boundary

Local Incident Commander is an investigation and decision-support application. It
is not an autonomous remediation system. The Agent may read from three fixed local
demo adapters, but no component can execute the command previews shown in the UI.

The security objective is to keep sensitive incident evidence inside the local
Radeon deployment while making every model decision, tool result, citation, and
operator decision reviewable.

## Protected data

Incident sessions may contain:

- internal service and host names;
- deployment versions and change history;
- logs, metrics, traces, alerts, and topology clues;
- customer-impact descriptions;
- operator questions and decisions; and
- model/tool errors that reveal implementation details.

Session snapshots and audit records must therefore be treated as sensitive
operational data even though the included checkout scenario is synthetic.

## Trust boundaries

### Untrusted incident and model content

All incident text and collected evidence is treated as data, not instructions. The
model cannot change the server-owned plan, register a tool, assign a trusted
evidence ID, or create an executable action. The system prompt explicitly treats
evidence as untrusted, but enforcement is performed in code rather than relying on
the prompt alone.

### Fixed read-only tools

The Agent tool registry contains only `get_deployments`, `query_metrics`, and
`search_logs`. Schemas reject unknown fields and invalid services, values, and
limits. The current adapters return synthetic local fixtures labeled
`local-demo-adapter`; they have no credentials and no production write path.

### Human-controlled response

Proposed actions contain a dry-run command preview, safety note, risk, and
`simulation_only: true`. Approving an action records an audit decision only. It
does not invoke a shell, Kubernetes client, cloud API, or any infrastructure
connector. Decisions are immutable after approval or rejection.

## Local inference and remote blocking

The competition Agent path is designed for a loopback OpenAI-compatible vLLM
endpoint. Before every core Agent model request, the runtime mode is checked. If it
is `remote-api`, the request is blocked and deterministic fallback runs instead;
the session retains `remote_core_requests: 0`.

`local-radeon` is not inferred from a localhost URL alone. The health check also
requires a sanitized runtime-evidence file whose model matches the configured
model and whose ROCm, GPU architecture, VRAM, compute units, vLLM version, and
timestamp pass validation. Invalid, stale, mismatched, or missing evidence yields
`local-unverified`.

The legacy `/api/analyze` compatibility endpoint uses the configured analyzer and
does not share the Agent route's remote-core blocker. For private operation, keep
`LIC_LLM_BASE_URL` on loopback or disable LLM use. Do not configure a remote URL
when sending real incident evidence through `/api/analyze`.

## Evidence and citation integrity

- The server assigns sequential `EV-TOOL-*` IDs after a tool returns.
- Model output cannot add a trusted ledger entry.
- Duplicate normalized tool calls are rejected.
- Hypotheses are regenerated from the persisted evidence ledger.
- Follow-up retrieval selects known evidence before model generation.
- Displayed follow-up citations are constrained to IDs already in the session.
- Evidence is capped at 100 records per investigation.

These controls provide provenance and reduce unsupported claims. They do not prove
that a cited source is operationally correct; the operator must still verify the
underlying system.

## Session integrity and concurrency

Each mutation requires:

- a printable ASCII `request_id` of 1-64 characters; and
- the current integer `expected_version`.

The server fingerprints the operation and payload. An exact replay returns the
original response; reusing a request ID with different content or submitting a
stale version returns HTTP `409`. A per-session lock prevents duplicate execution
inside the threaded demo server.

Snapshots are written to a temporary file, flushed, and atomically replaced. The
append-only `audit.jsonl` records the investigation, request ID, operation, prior
version, resulting version, and timestamp. A malformed snapshot is moved into a
quarantine directory so it cannot corrupt other sessions.

This design assumes one application process. It does not provide distributed locks
for multiple server processes sharing the same data directory.

## Failure and degraded operation

- Model timeout, malformed output, wrong tool, or invalid arguments: use the fixed deterministic step mapping and mark runtime degraded.
- Tool failure after fallback: retain partial evidence, mark the step failed, and end in a visible degraded state.
- Interrupted `running` step after restart: return it to pending, retry once, and record the degraded recovery reason.
- Empty or oversized model synthesis: use the deterministic cited brief.
- Corrupt persisted session: quarantine it and return a structured error.

Fallback is intentionally visible. The application never labels deterministic
output as successful Radeon model inference.

## Input and API controls

- Request bodies are limited to 1 MB.
- Investigation IDs accept only letters, digits, hyphens, and underscores.
- Incident fields and evidence objects are type-checked.
- Duplicate evidence IDs are rejected.
- Follow-up content is limited to 4,000 characters.
- Tool schemas enforce enumerations and bounded result counts.
- Errors use structured public messages and truncate stored fallback details.

The development server does not implement authentication, authorization, CSRF
protection, rate limiting, TLS, or per-user tenancy. Bind to loopback for local use.
On Radeon Cloud, access it only through the platform's authenticated proxy or an
equivalent protected tunnel. Do not expose port `8765` directly to the public
internet.

## Secrets and persisted files

- `.env` is git-ignored and must never be committed, uploaded, or shown in the demo.
- The local vLLM deployment intentionally uses no API key.
- If an API key is used for compatibility testing, rotate it after exposure and do not place it in logs or screenshots.
- Set `LIC_DATA_DIR` to protected persistent storage and restrict filesystem access to the operator account.
- Session JSON and `audit.jsonl` are not encrypted by the application.
- Back up persistent sessions only to an approved private location.
- Delete test sessions when they are no longer required.

The GPU benchmark records a public-safe allowlist of hardware fields. Raw
`amd-smi`, serial numbers, device GUIDs, bus addresses, cookies, and account data
must not be committed or displayed.

## Demo and publication checklist

Before recording or publishing:

1. verify that the UI says `Private Radeon`, not `Shared Radeon API`;
2. inspect `/api/health` for fresh sanitized runtime evidence;
3. use only the synthetic checkout incident;
4. scan the terminal, browser, benchmark files, and captions for secrets and hardware identifiers;
5. do not show `.env`, cookies, email addresses, account pages, or cloud tokens;
6. show that approvals are simulation-only; and
7. verify the public repository contains no session directory or audit log with private data.

## Known limitations

- No authentication, RBAC, multi-tenancy, TLS termination, or distributed locking
- No encryption at rest for sessions or audit logs
- No production observability or infrastructure connectors
- No sandbox for arbitrary tools because arbitrary tools are not supported
- No automatic verification that a proposed operational action is correct
- No formal defense against every prompt-injection technique; safety relies on the fixed plan, fixed tools, server-owned evidence, and absence of an executor
- The committed Radeon results are model microbenchmarks, not a security or full-workflow performance certification

## Verification coverage

Automated tests exercise input validation, duplicate evidence rejection, tool-call
parsing, remote-core blocking, idempotent replay, stale-version conflicts,
concurrent mutation, session recovery, corrupt-file quarantine, citation
constraints, immutable approvals, sanitized accelerator manifests, runtime evidence
validation, and deterministic fallback.

Run:

```bash
python3 -m unittest discover -s tests -v
```

Security findings should include the affected commit, reproduction steps using the
synthetic incident, expected impact, and a proposed mitigation. Do not include real
incident evidence or credentials in a public report.
