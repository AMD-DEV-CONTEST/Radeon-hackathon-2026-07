# E2 / M1 Workflow Conformance Addendum

Status: `IMPLEMENTATION_ACTIVE / CHECKPOINT_1_UNCHANGED`

This addendum applies the user-approved PR #17 LangGraph correction to Issue
#15 / Draft PR #16. It is prospective: the already confirmed E2 Contract /
Schema + Fixture checkpoint remains valid and is not rewritten as historical
LangGraph evidence.

The machine-readable contract is
[`contracts/checkpoints/e2-m1-workflow-conformance-v1.json`](../../contracts/checkpoints/e2-m1-workflow-conformance-v1.json).

## Frozen production workflow

- Workflow version: `experience-asset/e2-m1/v1`.
- Frozen topology hash:
  `2ed5001b1c7bf177335e0bbff59e964b115c1a90c8454f3784e9e695e3cbd707`.
- E2 retry budget: `0`.
- Canonical truth: the existing SQLite Asset Repository.
- Graph-cursor truth: the LangGraph SQLite Checkpointer.
- E1 `DurableFakeAgentLoop`: retained only as a contract/restart fixture.
- Production API: one graph compiled during application startup and injected
  into the M1 router.

The compiled graph contains these independent nodes:

1. `load_run_context`;
2. `plan_m1_action`;
3. `propose_current_source_call`;
4. `evaluate_runtime_policy`;
5. `execute_current_source_tool`;
6. `verify_run_result`;
7. `persist_run_outcome`; and
8. `terminalize_run`.

The required paths are allow/execute/verify, deny-or-invalid/verify,
model-or-format-failure, and stale-or-incompatible safe termination. A single
node wrapping the old Loop is forbidden.

## State, privacy, recovery and idempotency

Graph checkpoints contain only the allowlisted orchestration identifiers,
cursor metadata, projection sequence, selected edge and terminal candidate.
They must not contain a complete asset, user/source text, raw prompt/response,
tool query or renderer output. Nodes reload product data from the exact
canonical version reference.

Node effects use `run_id:node_name:node_attempt`. A started-but-uncommitted
effect is never executed a second time automatically. Terminal writes are
idempotent. On restart, only a compatible checkpoint for the same workflow and
base version, model ID, loopback service address, model-config hash and exact
code commit may continue. Missing, corrupt, incompatible, stale or
runtime-identity-mismatched state ends safely with a visible recovery action.

The E2/M1 Agent run performs no canonical asset write: it reloads and verifies
the exact immutable asset version, then persists only run/audit projections.
Therefore the frozen canonical write key is not exercised in E2. The first
later graph node that performs a valid canonical mutation must use
`command_id:expected_current_version_id` and add duplicate-write coverage.

Node Trace records workflow/topology identity, node/attempt, selected edge,
reference IDs, policy/tool/verification outcomes, checkpoint ID, terminal and
finding codes. It excludes raw private payloads.

## Dependency reproduction

The verified Python 3.12 dependency combination is:

```text
langchain-core==0.3.86
langgraph==0.6.11
langgraph-checkpoint==3.0.1
langgraph-checkpoint-sqlite==3.0.3
```

A clean temporary Python 3.12.13 environment completed synchronous and
asynchronous SQLite Saver round-trips before the dependency contract was
frozen. Local, CI and Radeon Cloud Agent installation must resolve the same
declared versions.

## Acceptance boundary

The current uncommitted local implementation has passed production wiring,
topology/branch tests, restart without model/tool replay, corrupt/missing/stale/
incompatible checkpoint safe-stop, terminal idempotency, state/Trace privacy,
the repository gates, and the real FastAPI/React Playwright path. A clean
Python 3.12.13 `pip install -e '.[dev]'` also imported the exact graph and saver
versions above.

These local results are not yet commit-bound checkpoint evidence and do not
constitute quality-owner acceptance. Checkpoint 3 still requires the
exact-commit W7900 Serving Reference S1, Vertical Slice V1 packet and
independent quality-owner promotion decision. W7900 validation is explicitly
deferred in this work package and assigned to `kinnyuww`; `Eas000n` owns the
implementation and non-W7900 local checkpoint-2 candidate.
