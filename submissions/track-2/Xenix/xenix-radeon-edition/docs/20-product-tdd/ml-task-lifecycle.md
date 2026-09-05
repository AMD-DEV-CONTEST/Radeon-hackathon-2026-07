# ML Task Lifecycle

## Admission

Agent tools, ML services, persistence, execution workers, and UI projections depend
on one task identity, lifecycle, placement, and finalization contract. Losing it can
make status, results, or canonical ownership disagree across units.

This contract governs persisted ML work, not task packets under `tasks/`.

## Identity and Authority

- Each accepted operation has a stable task id and individually addressable state.
- Training inputs use an immutable dataset role-binding snapshot. Services expand
  stable references into the execution request before dispatch.
- A trained analyzer is the aggregate for its canonical apply artifact, role
  contract, evaluation work, and final metrics. Consumers do not reconstruct that
  relationship by scanning unrelated dataset tasks.
- For supervised work, holdout evidence belongs to the split-trained evaluation
  artifact. The canonical apply artifact may be refit on all eligible rows and must
  not inherit an unsupported holdout-performance claim.

Exact task fields, operation enums, model taxonomy, and persistence shapes are owned
by source, schemas, and tests.

## Lifecycle and Placement

The shared semantic progression is:

```text
pending -> running -> succeeded | failed | cancelled
pending -> cancelled
```

- `succeeded` means every declared canonical output is locally present and ready.
- `failed` means the operation did not produce all required outputs.
- `cancelled` means cancellation control stopped accepted work before success.
- Services choose the local or SSH worker. Agent tool inputs do not select workers,
  and placement does not change task identity or lifecycle states.
- Worker or remote-command failure fails the task. Automatic failover is outside the
  current contract.

## Result and Failure Contract

- Remote directories are execution/cache state. Results become authoritative only
  after they are downloaded, normalized, finalized locally, and registered by the
  owning service.
- Terminal metadata preserves enough identity, status, result references, and error
  summary for later review independently of the originating conversation.
- User-relevant task logs remain available through the ML task service. Log file
  layout and application-log rotation belong to source and Deployment.
- Failure detail is actionable and may include bounded worker/setup diagnostics,
  but never SSH credentials or private-key material.
- User-openable outputs follow the [artifact link contract](artifact-links.md);
  storage medium and deletion follow [storage ownership](storage-ownership.md).

## Verification

Lifecycle and placement coverage lives in `tests/test_services.py`,
`tests/test_ml_execution.py`, `tests/test_ml_workers.py`, and the ML paths in the
Agent Harness test suites. Persistence mechanics are covered by repository and
migration tests.
