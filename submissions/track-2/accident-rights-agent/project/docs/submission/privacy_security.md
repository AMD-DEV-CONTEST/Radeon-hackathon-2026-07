# Privacy and Security Statement

## 1. Local Deployment Boundary

The core model, embedding, reranker, Agents, legal index, case database, and
audit logs run on the same Radeon Cloud instance or controlled local
environment. vLLM listens only on `127.0.0.1:8000`; the UI listens on
`127.0.0.1:7860` by default. Remote demonstration uses a private SSH tunnel and
does not publish the model service.

`app/policy/local_only.py` rejects non-HTTP protocols, non-loopback hosts,
ports other than 8000, credentials, query strings, fragments, and paths outside
`/v1`. If the `local_vllm` doctor fails, execution stops. There is no fallback
to Qwen, DeepSeek, OpenAI, or another public model API.

## 2. Data Isolation

- each case uses an independent directory and SQLite state;
- source files are hashed and written atomically;
- duplicate sources are identified by hash;
- path traversal, symlinks, empty files, false extensions, and oversized files
  are rejected;
- original evidence is not lossily compressed and cannot be overwritten by the
  UI;
- source-role corrections, human confirmations, and supplemental materials are
  appended as audit events;
- Qdrant uses a local persistent index; tests do not call a cloud embedding
  service.

Competition Demo materials are synthetic and contain no real party data. A
production deployment must not accept live cases until tenant isolation,
identity, encryption, backup, and retention controls are implemented.

## 3. Redaction

Audit outputs and Demo views apply field policies to names, identity numbers,
telephone numbers, license plates, addresses, and internal paths. SEC-03 found
zero unredacted real-name, telephone, or identity-card matches.

Before submission, the final video must also be reviewed manually for browser
history, terminal scrollback, SSH host/port, private-key information, GPU serial
numbers, names, telephone numbers, identity numbers, plates, and addresses.
Regex scanning alone is not sufficient.

## 4. Human Approval

Every review, appraisal, or communication document starts as `draft`. Passing
the Policy Gate permits human review only. Approval is bound to the exact
document version and input hash; a changed fact or draft invalidates the old
approval.

The maximum external-facing system state is
`approved_for_manual_submission`. The Agent does not send, file, or submit a
document and never fabricates an accepted status from an external institution.

## 5. Audit Trail

The system records case creation, file receipt, Evidence/Fact state, Agent
nodes, rule versions, retrieved citations, Verifier outcomes, retries, document
versions, and human decisions. SQLite checkpoints support interruption and
resume. High-cost evidence nodes use input hashes to avoid duplicate parsing.

This application-level trail is not a substitute for a platform-level
tamper-evident store. Production requires WORM or signed records, centralized
logging, access auditing, and retention governance.

## 6. Evidence of No Public Model API

Measured on 2026-08-01:

- public model Base URL/API-key code-scan matches: 0;
- `http://127.0.0.1:8000/v1/models`: HTTP 200;
- returned model: `Qwen/Qwen3-VL-8B-Instruct`;
- vLLM arguments include `--host 127.0.0.1 --port 8000`;
- the listener is `127.0.0.1:8000` only.

Raw evidence is stored under `benchmarks/results/security/`.

## 7. Current Security Limitations

The competition build does not provide complete multi-tenant authentication,
fine-grained RBAC, KMS, disk-encryption attestation, centralized immutable
audit, malicious-file sandboxing, or production disaster recovery. Remote Demo
ports must not be exposed publicly and temporary tunnels must be closed after
recording. Outputs are decision support, not legal advice or final liability
determination.
