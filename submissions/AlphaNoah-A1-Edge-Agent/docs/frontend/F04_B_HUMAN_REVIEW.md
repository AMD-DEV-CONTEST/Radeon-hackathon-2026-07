# F04-B Human Review Interaction

## Result

F04-B presents the existing Human Review capability in the Workspace Event
detail panel. It completes the visible collaboration loop from AI analysis to
an explicit human decision and a persisted Task without changing the Runtime
state machine, SQLite schema, Skill Runtime, Provider orchestration, or Digital
Employee architecture.

## Existing Review Capability

### Available

- `POST /api/events/{event_id}/review` records an approved or rejected Human
  Review against the existing Decision.
- `GET /api/events/{event_id}` returns the safe Event, Analysis, and Decision
  view used by the action panel.
- `GET /api/events/{event_id}/task` returns the current persisted Task, if one
  exists.
- `POST /api/tasks/{task_id}/evidence` submits Evidence through Runtime.
- `GET /api/events/{event_id}/timeline` returns the existing bounded Event
  timeline.
- `EdgeAgentApplication.create_approved_task()` already creates the approved
  Task through the Runtime state transition.

### Missing before F04-B

- The frontend had no Human Review data source, command path, action state, or
  refresh recovery.
- The Review endpoint intentionally did not create a Task. Existing tests
  enforce that decision-only behavior.
- No HTTP command exposed the existing `create_approved_task()` application
  operation.
- No standalone Evidence status read endpoint exists. The bounded timeline
  reports lifecycle progress, but F04-B does not need Evidence detail to make
  the pending Human Review decision.

### Required minimal extension

F04-B adds `POST /api/events/{event_id}/task` as a narrow composition endpoint.
It accepts only an empty JSON object and calls the existing application
operation. It does not introduce a Runtime transition. If the Event already
has its single Task, the endpoint returns that Task instead of creating a
duplicate, allowing safe recovery after a lost response or page refresh.

## UI design

The Human Review Action Panel is placed in the existing Workspace Event detail
surface. It uses the current HSD glass, typography, spacing, status color, and
motion tokens rather than introducing a dashboard or chat interface.

The panel presents only business-facing information:

- AI recommendation: finding, analysis, a safe recommendation when Runtime
  provides one, and confidence;
- Human decision: the current persisted decision state;
- Digital Employee: the employee currently associated with the Event;
- action controls: Approve and Reject only while a decision is pending;
- bounded Runtime errors and an explicit retry/recovery action.

| Runtime state | Product state | Interaction |
|---|---|---|
| `PENDING_HUMAN_REVIEW` | Waiting for human decision | Approve and Reject are available |
| approved, Task present | Approved / Task created | No review buttons; employee is working |
| approved, Task absent | Approved / task pending | Explicit Task recovery action is available |
| `REJECTED` | Rejected / No action executed | No task action is shown |
| `CLOSED` | Completed / Audit recorded | Employee work is shown as completed |

The UI never claims success optimistically. Buttons remain busy until the HTTP
command and the following Runtime reads complete.

## Data flow

```text
Human Review Action Panel
  -> useHumanReview()
  -> HumanReviewDataSource
  -> HttpHumanReviewDataSource
  -> HTTP API
  -> Web Adapter
  -> EdgeAgentApplication / Runtime
  -> SQLite
  -> safe Event, Task, and timeline responses
  -> decoded HumanReviewSnapshot
  -> UI
```

Production composition selects `HttpHumanReviewDataSource`. Tests may inject a
test data source explicitly. There is no production Mock fallback and React
does not locally simulate a successful decision.

After a successful command, the Workspace, Pulse, and Digital Employee
projections are refreshed so that the rest of the product reflects the same
Runtime facts.

## API use

### Read current review state

```http
GET /api/events/{event_id}
GET /api/events/{event_id}/task
GET /api/events/{event_id}/timeline
```

The three bounded reads are adapted into one frontend snapshot. The timeline
is used only as a presence/count signal; raw timeline and Audit content are not
rendered.

### Approve

```http
POST /api/events/{event_id}/review
Content-Type: application/json

{"action":"approve","comment":"Approved in the AlphaNoah Human Review panel."}
```

After Runtime confirms approval:

```http
POST /api/events/{event_id}/task
Content-Type: application/json

{}
```

The client then performs the three current-state reads and renders only their
confirmed result.

### Reject

```http
POST /api/events/{event_id}/review
Content-Type: application/json

{"action":"reject","comment":"Rejected in the AlphaNoah Human Review panel."}
```

No Task command is sent after rejection. The client re-reads the Runtime state
before showing the result.

## Digital Employee integration

The action panel associates an existing Digital Employee projection by
matching `current_event_id` to the selected Event ID. It does not create a new
employee object, table, or Runtime abstraction. If no employee projection is
available, the existing Responsibility name is used as a business-facing
fallback.

The visible employee state follows persisted Human Review facts:

- pending: waiting for approval;
- approved with Task: working, Task created;
- rejected: decision recorded, no Task;
- closed: Task completed.

## Security boundary

The panel and its view model do not expose:

- prompts or system instructions;
- Trace IDs or request IDs;
- raw Audit details or timeline entries;
- Provider or model internals;
- local file or database paths;
- model internal responses.

Event IDs are validated before requests. HTTP, JSON, and contract failures are
mapped to bounded product errors. The frontend consumes only existing safe web
projections; it never reads SQLite or Runtime objects directly.

## Tests

Frontend coverage includes:

- pending review presentation;
- persisted approval followed by Task creation;
- persisted rejection without Task creation;
- rejected/error response without optimistic UI mutation;
- page remount and Runtime-state recovery;
- Human Review HTTP decoding and request order;
- preservation of existing standalone workspace presentation tests.

Backend coverage includes:

- Review remains decision-only;
- Task command requires an approved Decision;
- duplicate Task commands return the existing single Task;
- extra Task command fields are rejected;
- full HTTP Review and Task command flow.

Implementation verification:

- TypeScript typecheck: PASS.
- Frontend tests: 190/190 PASS across 34 files.
- Python tests: 215/215 PASS.
- Vite production build: PASS; source maps remain disabled.
- Python compileall: PASS.
- Real-browser pending-to-approved flow against the local HTTP API and a
  temporary SQLite Runtime: PASS.

## Visual review

- The interaction remains inside one focused Event detail card, with only two
  primary decision controls.
- Finding, analysis, recommendation, and confidence have a clear reading
  hierarchy.
- The existing glass surface and status tokens are reused; no traditional OA
  form or chat surface was introduced.
- Pending motion is limited to a narrow status accent and respects both the
  application reduced-motion setting and small-screen layout.
- Success, rejection, unavailable, and loading states are expressed with text
  as well as color.

Temporary, untracked visual evidence from this implementation run is stored at:

```text
tmp/f04-b-visual/pending-review-final-4.png
tmp/f04-b-visual/approved-task.png
```

The first capture shows the real pending Human Review projection. The second
was taken after the browser submitted approval, Runtime persisted the Human
Review and Task, and the frontend re-read the Event, Task, Workspace, Pulse,
and Digital Employee projections. These Windows captures are implementation
evidence; target AMD Linux screenshots remain a separate acceptance activity.

## Known limitations

- Approval creates the existing Runtime Task but does not execute the Task,
  submit Evidence, or close the Event. Those remain later steps in the existing
  workflow. The panel displays Completed when Runtime eventually reports
  `CLOSED`.
- A separate recommendation is shown only when the safe Decision evidence
  contains `suggested_human_action=...`; otherwise the UI explicitly reports
  that Runtime did not provide one.
- Reviewer identity and authentication remain outside the current local demo
  boundary; F04-B does not add an authorization system.
- Raw Evidence submission and final Review actions are not added to this panel.
- Target AMD Linux screenshot evidence remains a separate acceptance activity.

## Completion decision

**F04-B COMPLETE** — the Human Review interaction is connected end to end to
the existing Runtime and safe projections. No Mock state or product-layer
Runtime substitute was introduced.
