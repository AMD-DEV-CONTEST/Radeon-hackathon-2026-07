# E9 Public Demo Access and Queue Requirement Contract

## Metadata

- Requirement ID: `E9-DEMO-GUARD`
- Title: Access-code sessions and bounded queue for an optional public Web UI
- Created: 2026-08-03 AEST
- Requirement status: `APPROVED`
- Engineering status: `NOT_STARTED`
- Verification status: `NOT_RUN`
- Parent milestone: `E9 — Submission and demo freeze`
- Approved by: project owner / quality owner
- Approval evidence: the user explicitly confirmed the access-code and queue
  preparation, then narrowed it to the future public-WebUI deployment layer so
  that the business layer remains unchanged.

## 1. Problem

An optional judge-facing `rc-tunnel` URL is publicly reachable. Exposing the
current Web UI without an access gate would expose application operations to
anyone who discovers the URL. Sending multiple long-running model requests
directly to one W7900 can also exhaust VRAM, increase tail latency, or make the
demo appear frozen.

The core Experience Asset workflows are already governed by their own domain,
LangGraph, Runtime-policy and persistence contracts. Public-demo protection
must not force a late rewrite of those contracts.

## 2. Desired Outcome

When the team explicitly chooses to publish the optional E9 Web UI:

1. a reviewer enters a temporary access code and receives a short-lived,
   browser-bound session;
2. long-running UI requests enter a small, visible first-in/first-out queue;
3. the UI shows truthful queue and execution states rather than appearing
   frozen or inventing a completion time;
4. overload fails visibly and safely without weakening output quality; and
5. the public-demo adapter calls the already accepted application API without
   changing M1–M5/E7 business semantics.

If this gate is not fully verified, the team uses the recorded local demo and
does not publish a live URL.

## 3. Users and Scenarios

- Primary actor: an invited judge or reviewer using a temporary access code.
- Operator: the team member who starts, monitors and stops the approved E9
  public-demo window.
- Normal scenario: one reviewer submits a long-running Agent action and sees
  `QUEUED`, `RUNNING`, a real user-input gate when applicable, and a terminal
  result.
- Concurrent scenario: several reviewers arrive close together; one request is
  executed while bounded later requests show their queue positions.
- Overload scenario: the bounded capacity is full; the next request receives a
  visible retry response instead of starting another unbounded model call.
- Recovery scenario: the WebUI adapter restarts; queued work remains visible,
  and an uncertain in-flight request is never silently replayed as a duplicate
  business action.

## 4. Confirmed Decisions

### 4.1 Deployment boundary

```text
reviewer browser
  -> temporary access-code session
  -> public WebUI / demo adapter (bounded queue)
  -> existing loopback FastAPI application
  -> existing LangGraph Runtime and policy gates
  -> loopback vLLM on ROCm / W7900
```

- Queueing and session ownership live only in the E9 public-WebUI adapter.
- Existing workflow nodes, Runtime policy, domain contracts and canonical
  application database are not changed for this feature.
- The adapter may keep its own SQLite state under
  `/workspace/amd-track2-agent/demo/`; this is operational state, not a new
  product datastore.
- Local development keeps the adapter disabled by default.
- Only the WebUI/application port may be tunneled. FastAPI internals, vLLM,
  SQLite, SSH, Jupyter and admin/debug routes remain loopback-only.

### 4.2 Access-code session

- No registration, password-reset or account-management product is added.
- Access codes and the signing secret are injected at deployment time and are
  never committed, logged, placed in a URL, or returned by an API.
- A valid code creates a random session identifier carried in a signed,
  short-lived `HttpOnly`, `Secure`, same-site cookie.
- Missing, expired or invalid sessions cannot submit work or inspect another
  session's job status.
- Repeated failed access-code attempts are throttled and recorded without the
  submitted code value.
- The demo uses only synthetic, public, or explicitly approved content. This
  control does not turn P0 into a general multi-user or collaborative product.

### 4.3 Bounded queue

- Default active worker count: `1`.
- A second worker may be enabled only after the exact E9 W7900 configuration
  passes the declared concurrency and VRAM gate.
- Default total nonterminal capacity: `6`, including running and queued jobs.
- Each session may own at most one nonterminal long-running job.
- Duplicate clicks with the same idempotency key return the original job rather
  than starting another model call.
- Accepted work returns HTTP `202` with a job ID, status URL, real state and
  queue position when queued.
- A full queue returns HTTP `429` plus `Retry-After` and a user-readable busy
  message.
- Queue order is FIFO unless a future, prospectively approved change documents
  another policy. There is no hidden priority lane for judges or team members.
- A queued job may be cancelled before it starts. A running business workflow
  follows its existing safe-stop and durable-recovery semantics.

### 4.4 Truthful status and recovery

Public states are limited to observable facts:

- `QUEUED`
- `RUNNING`
- `WAITING_FOR_USER`
- `SUCCEEDED`
- `NEEDS_USER_INPUT`
- `POLICY_BLOCKED`
- `FAILED_RETRYABLE`
- `FAILED_TERMINAL`
- `CANCELLED`

The UI may show queue position and elapsed time. It must not show a fabricated
percentage, unsupported countdown, or estimated completion time.

Queued jobs survive an adapter restart. A job that was `RUNNING` when the
adapter lost contact is reconciled with the existing application run when a
durable run identity is available; otherwise it becomes visibly
`FAILED_RETRYABLE`. The adapter must not automatically repeat an uncertain
state-changing operation.

## 5. Assumptions

- `rc-tunnel` continues to expose one loopback HTTP/WebSocket port.
- Long-running generation calls, not small reads/autosaves, are the only
  operations that need queueing.
- One worker is the safe starting point for the selected W7900 serving profile.
- Queue capacity and session lifetime remain configuration values; changing
  them requires a recorded E9 rehearsal, not a business-schema migration.
- The existing application API remains the authority for business validation,
  permissions, idempotency and terminal results.

## 6. Open Engineering Decisions

These choices do not change the approved user behavior and may be resolved in
the E9 engineering proposal:

- whether the adapter is a small FastAPI boundary process or a deployment-only
  router inside the existing WebUI process;
- the exact cookie lifetime and access-code failure window;
- which existing long-running endpoints enter the queue after E7/E8 freezes the
  final demo path;
- whether a `RUNNING` job can always bind to an existing durable workflow run
  identity or must use the conservative retryable outcome.

## 7. Scope

### In scope

- temporary access-code form and signed session cookie;
- session-scoped job and demo-asset registry at the adapter boundary;
- SQLite-backed bounded FIFO queue for long-running public-demo actions;
- idempotent submission, queue position, truthful state and overload handling;
- a small operator view of capacity, active job count and safe public errors;
- restart reconciliation, shutdown procedure and sanitized operational logs;
- responsive visual states suitable for the E9 demo and video;
- public-demo tests, rehearsal evidence and a rollback-to-recorded-demo path.

### Out of scope

- changing M1–M5/E7 business behavior, LangGraph topology or Runtime policy;
- adding ownership columns to the canonical product schema;
- full accounts, registration, collaboration, sharing permissions or billing;
- a distributed queue, Redis, Celery, Kubernetes or multi-Pod scheduling;
- exposing raw vLLM, FastAPI documentation, databases, Jupyter, SSH or admin
  interfaces;
- claiming that the live URL is required by the competition;
- using queueing to weaken prompts, reduce verification, truncate outputs or
  silently choose a lower-quality model.

## 8. Constraints and Approval Boundaries

- Core inference remains local on the W7900 through ROCm/vLLM.
- The public adapter and all operational state remain under persistent
  `/workspace`; source remains backed up in GitHub.
- No private user data, session cookie, access code, signing secret, IP address
  or unrestricted raw prompt/trace enters Git evidence.
- Public errors do not expose filesystem paths, internal exception text,
  prompts, model-server URLs or credentials.
- Running `rc-tunnel expose`, sharing the URL, uploading demo media, or opening
  the official contest PR still requires separate explicit human approval.
- The operator records the URL owner and shutdown time and stops the tunnel
  after the approved window.

## 9. Acceptance Criteria

| ID | Criterion | Intended verification | Status |
|---|---|---|---|
| E9-D01 | Without a valid session, protected demo operations return `401`/`403`; a valid temporary code creates a short-lived HttpOnly cookie without exposing the code or signing secret. | API/browser integration test and secret/log scan | NOT VERIFIED |
| E9-D02 | Two authenticated browser sessions cannot list, poll, cancel or reuse each other's jobs or adapter-registered asset IDs. | Two-session isolation test | NOT VERIFIED |
| E9-D03 | With worker count `1`, concurrent long-running submissions execute one at a time and later accepted jobs display a deterministic FIFO position. | Controlled blocking-worker integration test | NOT VERIFIED |
| E9-D04 | Capacity `6` accepts no more than six nonterminal jobs; the next submission receives `429`, `Retry-After` and a visible busy message without calling the business API. | Queue-capacity test with call counter | NOT VERIFIED |
| E9-D05 | Repeating one submission with the same session and idempotency key returns the original job ID and produces only one downstream application call. | Duplicate-click integration test | NOT VERIFIED |
| E9-D06 | A restart preserves queued jobs; uncertain running work is reconciled by durable run ID or becomes visibly retryable and is never silently replayed. | SQLite restart/fault-injection test | NOT VERIFIED |
| E9-D07 | Queueing the final demo path does not change accepted business request/response contracts, Runtime decisions or canonical outputs. | Existing regression suite plus adapter contract tests | NOT VERIFIED |
| E9-D08 | The WebUI shows only real queue/execution/terminal states and never fabricates percentage, countdown or completion. | Browser assertions and quality-owner inspection | NOT VERIFIED |
| E9-D09 | An exact-commit W7900 rehearsal records queue wait, service time, terminal result, peak VRAM and failures for the chosen worker count; worker count `2` remains disabled unless it passes the declared gate. | E9 rehearsal manifest and retained raw records | NOT VERIFIED |
| E9-D10 | From a signed-out external browser, only the authenticated WebUI port is reachable; raw vLLM, backend internals, database, SSH, Jupyter and admin/debug routes are not exposed. | Network exposure and signed-out smoke checklist | NOT VERIFIED |
| E9-D11 | Stopping the demo invalidates the public URL/session path, and the recorded local demo remains a rehearsed fallback. | Shutdown and rollback rehearsal | NOT VERIFIED |

## 10. Requirement Risks

- The adapter cannot claim strong tenant isolation if public routes bypass it;
  therefore only the adapter port may be exposed and all public API traffic must
  pass its session/ownership check.
- Automatically replaying an uncertain running write could duplicate effects;
  recovery must prefer a visible retryable state when durable correlation is
  unavailable.
- A queue can hide an overloaded or poor model configuration; E9 evidence must
  record both queue wait and downstream service time.
- Access codes reduce accidental access but are not durable account security;
  codes must be temporary, non-default and revoked after the review window.
- Late visual polish can expand scope. E9 prioritizes login, truthful queue
  state, clear failure recovery and one polished final demo path.

## 11. Required Evidence Packet

Retain a sanitized packet under:

```text
evidence/milestones/e9-public-demo/<UTC-run-id>/
```

Minimum contents:

- exact Git commit and environment/configuration manifest with secrets removed;
- worker count, capacity, session TTL class and exposed local port;
- access deny/allow, two-session isolation, capacity, duplicate-click and
  restart test results;
- browser captures for login, queued, running, safe terminal and overload;
- one exact-commit W7900 rehearsal containing queue wait, downstream duration,
  peak VRAM, terminal outcomes and all failed observations;
- signed-out reachability check proving raw vLLM and internal services remain
  private;
- tunnel start/stop timestamps, owner and recorded-demo rollback result;
- no secret values, private inputs, raw cookies or hidden QA details.

## 12. Engineering Start Gate

Engineering begins only after the final E7/E8 demo path and long-running
endpoints are frozen. The implementation PR must state:

1. which operations enter the queue;
2. how the adapter correlates jobs with existing durable workflow runs;
3. the exact rollback command that disables the adapter and returns to the
   local/recorded demo;
4. the public tests and E9 evidence packet it will produce; and
5. why the change does not alter business contracts or competition claims.
