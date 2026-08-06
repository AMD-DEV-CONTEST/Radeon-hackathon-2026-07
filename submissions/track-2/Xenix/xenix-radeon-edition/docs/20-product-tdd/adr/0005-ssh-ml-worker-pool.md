# ADR 0005: Use SSH ML workers as execution adapters

- Status: accepted
- Date: 2026-05-23
- Related: [ADR 0004](0004-native-architecture-separate-from-web.md),
  [ADR 0007](0007-remote-integrations-remain-adapters.md)

## Context

Xenix Native needs to run ML workloads on remote Python environments for users who have more capable remote machines. Existing native architecture keeps local services, SQLite metadata, and local filesystem artifacts as the product authority. ADR 0004 rejects reintroducing the web application's frontend-backend split and requires a new ADR for remote API or deployment-style boundaries.

The target users are non-technical, so remote setup must be guided. At the same time, credentials should not become part of Xenix task payloads, logs, or artifact metadata.

## Decision

Introduce a configurable ML worker pool owned by local services. The pool may contain a local worker and SSH workers. Agent tools continue to request ML workloads; they do not select workers.

SSH workers are execution adapters:

- Xenix may guide setup through Settings and may write clearly marked `Host xenix.*` OpenSSH config blocks.
- v1 supports key/agent-based SSH only.
- Xenix does not store SSH passwords, passphrases, or private-key material.
- The setup wizard initializes a remote execution root, creates or validates a remote Python environment, installs or validates dependencies, and runs smoke checks.
- The native app stages task files and a versioned worker bundle on the remote worker, runs the ML entrypoint over SSH, downloads results and logs, and rewrites result paths back to local task paths.

Local SQLite rows, local task directories, local canonical model artifacts, and local apply output artifacts remain the final authority. Remote files are cache/execution state and may be recreated or removed without changing product truth.

## Consequences

- No remote HTTP API, always-on daemon, or standalone remote client is introduced.
- Worker pool configuration lives in local JSON config, not SQLite.
- ML task states do not change. A selected-worker failure fails the task; v1 does not retry or fail over to another worker.
- Tests should cover settings validation, worker selection, path rewriting, OpenSSH config block updates, and local lifecycle invariants.

## Implementation Status

As of 2026-07-11, the accepted decision is only partially realized:

- Fresh-worker dependency setup omits the required DuckDB package.
- The worker bundle uses a static `source-v1` marker, so an existing remote marker can
  suppress upload after worker source changes.

These are known implementation gaps. They do not weaken the decision or make remote
state authoritative.
