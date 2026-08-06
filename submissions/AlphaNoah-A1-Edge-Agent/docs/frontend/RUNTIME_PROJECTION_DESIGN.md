# AlphaNoah Runtime Projection Design

> F03-D1 Runtime Projection API
> Contract status: `workspace-v1`
> Scope: read-only Runtime-to-Frontend projection

## 1. Purpose

The current backend persists real workflow state, while the default frontend
Workspace, Pulse, and Digital Employee views are primarily Mock-backed. F03-D1
adds one narrow read boundary:

```text
Frontend
    |
    v
HTTP Projection API
    |
    v
Runtime read model / SQLite / reviewed local configuration
```

The projection is not a second Runtime and is not a database dump. It converts
existing Runtime facts into explicitly allowlisted product view models so a
later frontend task can replace Mock reads without importing backend objects or
understanding the workflow state machine.

F03-D1 does not switch the frontend data source. It only establishes the real
data outlet required by that later switch.

## 2. Projection principles

### 2.1 One-way dependency

The dependency direction is:

```text
Event / Decision / Notification / Audit / configuration
                         |
                         v
              RuntimeProjectionService
                         |
                         v
               public JSON view models
                         |
                         v
                      Frontend
```

The frontend must not read or import:

- SQLite files or tables;
- `AlphaNoahRuntime`, `SQLiteStore`, or other Runtime objects;
- `runtime.snapshot()` output;
- `SkillContext` or prompt payloads;
- Audit records or Audit details;
- local configuration files;
- frontend Mock fixtures from the backend.

The backend projection must not import frontend TypeScript types or Mock data.
Wire contracts remain backend-owned, versioned, snake-case JSON. A future
frontend adapter may map these contracts into frontend camel-case view models.

### 2.2 Explicit allowlists

Each public object is constructed field by field. Domain-object `to_dict()`,
generic serialization, arbitrary metadata copying, and “serialize everything
then remove a few keys” are prohibited.

This rule is essential because current persisted objects contain private or
unsafe values. For example:

- Event contains `raw_input_ref`, `normalized_input`, `trace_id`,
  attachments, and arbitrary metadata;
- Decision contains reasoning, evidence, and model identity;
- Notification contains `trace_id`, `decision_id`, recipient details, and
  content;
- Audit contains actor identity, trace identity, transitions, and arbitrary
  details;
- Evidence may contain a local file or data reference.

### 2.3 Read-only and side-effect-free

All four endpoints are HTTP GET reads. A projection request:

- does not insert, update, or delete SQLite rows;
- does not transition Event, Decision, Task, or Evidence state;
- does not create a Notification;
- does not invoke an Analysis Provider;
- does not resolve a new `SkillContext`;
- does not run knowledge retrieval;
- does not create a Task or Digital Employee;
- does not call Ollama or another model service.

`SQLiteStore` currently initializes its schema when the application is
constructed. That startup behavior is separate from request handling. The
read-only guarantee means the contents of all business tables are unchanged
before and after every projection GET.

### 2.4 Unknown is preferable to invention

The projection never invents a site, employee presence, capability name,
metric, permission, task relationship, or business description.

When a reliable Runtime fact does not exist:

- an optional object is `null`;
- an absent collection is `[]`;
- Digital Employee operational status is `unknown`;
- no Mock value is used as fallback.

## 3. Architecture boundary

The recommended backend boundary is:

```text
SQLiteStore public read methods
ResponsibilityDirectory.resolve(Event)
persisted Audit skill provenance (strict allowlist)
Notification Outbox
                |
                v
RuntimeProjectionService
  - reads and correlates
  - applies deterministic ordering
  - derives active Event, employee state, and Pulse
  - emits safe projection objects only
                |
                v
Web projection adapter / web_api routes
  - maps paths to service reads
  - returns JSON with existing HTTP security headers
  - never exposes service dependencies
```

The projection service may receive the already-composed `SQLiteStore` and
`ResponsibilityDirectory` as dependencies. It must use the same store/database
as the existing Web application. It must not create a parallel Runtime or use a
different default database.

The service must use store read methods rather than opening the SQLite file from
the HTTP handler. HTTP routing must not contain SQL or product derivation rules.

## 4. Real data sources

### 4.1 Event

`Event` is persisted in SQLite through `SQLiteStore`. F03-D1 uses only:

| Public field | Runtime source | Rule |
|---|---|---|
| `id` | `Event.event_id` | Copy generated Event identity |
| `type` | `Event.event_type` | Copy validated Runtime event type |
| `status` | `Event.status.value` | Preserve the real Event state |
| `timestamp` | `Event.timestamp` | Copy persisted Event timestamp |
| `severity` | `Event.severity` | Normalize only for safe presentation |

The Event projection does not expose source input, description, asset,
location, reporter, analysis, trace, attachments, or metadata.

Severity has the public values `UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`, and
`CRITICAL`. A missing or unsupported Runtime severity is projected as
`UNKNOWN`; it is never silently mapped to a lower risk.

### 4.2 Responsibility

`ResponsibilityDirectory.resolve(event)` applies the existing deterministic
priority:

```text
asset_id -> location -> event_type -> UNASSIGNED
```

Only the resolved owner ID and owner name enter the Event projection. A result
whose owner ID is `UNASSIGNED`, or whose public values fail output safety
validation, is projected as `null`.

The local configuration path, `configuration_notice`, match key, and internal
rule collection are never returned.

Responsibility configuration is a reviewed local configuration, not a
versioned persisted employee directory. Section 12 records the resulting
historical-consistency limitation.

### 4.3 Notification

Notification Outbox rows are persisted in SQLite. Pulse selection uses:

- `Notification.event_id`;
- `Notification.status`;
- `Notification.title`;
- the associated Event status and severity.

The following Notification fields are not public in F03-D1:

- `notification_id`;
- `trace_id`;
- `decision_id`;
- `recipient_id`;
- `recipient_name`;
- `content`;
- `channel`;
- `created_at`.

`NotificationStatus.CREATED` means a durable local notification intent, not a
delivered message. Pulse therefore describes attention state, not delivery
state.

### 4.4 Skill

Skill definitions live in Python memory rather than SQLite. They include
private analysis instructions, escalation guidance, and knowledge query hints.
Those definition objects are not serialized by F03-D1.

After real analysis, the selected Skill identity is persisted inside an Audit
record's bounded `model_metadata`. Digital Employee projection may extract only
the string `skill_id` from this persisted provenance. The public skill
`name` is exactly that persisted `skill_id`; F03-D1 does not invent a product
capability name.

The projection does not invoke `SkillResolver` during GET. Consequently, a NEW
Event with no persisted analysis provenance has no projected Skill.

### 4.5 Data inspected but not projected

The service may inspect relationships needed to correlate real state, but the
following objects have no direct public representation in the four v1
contracts:

- Decision;
- HumanReview;
- Task;
- Evidence;
- post-review Review;
- KnowledgeDocument and KnowledgeContext;
- raw Audit records.

They remain Runtime implementation facts. Adding their summaries requires a
separate versioned projection review.

## 5. Shared Event contract

The Event shape is identical in `GET /api/events` and
`GET /api/workspace`. This prevents the endpoints from creating two public
interpretations of one Event.

```json
{
  "id": "event_0123456789abcdef0123456789abcdef",
  "type": "device_not_shutdown",
  "status": "PENDING_HUMAN_REVIEW",
  "timestamp": "2026-07-30T10:42:00+08:00",
  "severity": "HIGH",
  "responsibility": {
    "id": "maintenance_001",
    "name": "Equipment Maintenance"
  }
}
```

Exact contract:

```text
EventProjection {
  id: string
  type: string
  status: string
  timestamp: string
  severity: "UNKNOWN" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  responsibility: {
    id: string
    name: string
  } | null
}
```

The projection preserves unknown future Event status text rather than mapping
it to a successful state. Under the current model, normal persisted Event rows
deserialize through the closed `EventStatus` enum.

Text values that contain a credential-shaped token, secret assignment, or
absolute local path must not be returned verbatim. Event type and generated IDs
already have bounded identifier shapes. Configuration-backed responsibility
values must additionally pass the public-output safety policy.

## 6. `GET /api/events`

Purpose: discover persisted Events after page refresh without knowing an Event
ID in advance.

Response status: `200 OK`.

Response body:

```json
[
  {
    "id": "event_0123456789abcdef0123456789abcdef",
    "type": "device_not_shutdown",
    "status": "PENDING_HUMAN_REVIEW",
    "timestamp": "2026-07-30T10:42:00+08:00",
    "severity": "HIGH",
    "responsibility": {
      "id": "maintenance_001",
      "name": "Equipment Maintenance"
    }
  }
]
```

Empty state:

```json
[]
```

Ordering is newest Runtime update first, with Event ID as the deterministic
tie-breaker. The public `timestamp` remains the Event's persisted occurrence
timestamp; internal SQLite update time is an ordering input and is not exposed.

The v1 feed is bounded to the 100 most recently updated Events. This bound
applies only to the public feed array. Active Event, Pulse, and Digital
Employee derivation inspect all valid persisted Events so an older unresolved
Event cannot disappear merely because 100 newer Events exist. F03-D1 does not
add query parameters, pagination, cursors, or filtering. Existing global query
rejection remains in effect.

This GET shares the path with the existing `POST /api/events`. HTTP method
dispatch keeps their behaviors separate: GET reads, POST retains its current
Event-creation contract.

## 7. `GET /api/workspace`

Purpose: provide one read-only Workspace aggregate from the same real
projections used by the standalone endpoints.

Response status: `200 OK`.

Exact contract:

```text
WorkspaceProjection {
  version: "workspace-v1"
  events: EventProjection[]
  active_event: EventProjection | null
  pulse: PulseProjection | null
  employees: DigitalEmployeeProjection[]
}
```

Example:

```json
{
  "version": "workspace-v1",
  "events": [
    {
      "id": "event_0123456789abcdef0123456789abcdef",
      "type": "device_not_shutdown",
      "status": "PENDING_HUMAN_REVIEW",
      "timestamp": "2026-07-30T10:42:00+08:00",
      "severity": "HIGH",
      "responsibility": {
        "id": "maintenance_001",
        "name": "Equipment Maintenance"
      }
    }
  ],
  "active_event": {
    "id": "event_0123456789abcdef0123456789abcdef",
    "type": "device_not_shutdown",
    "status": "PENDING_HUMAN_REVIEW",
    "timestamp": "2026-07-30T10:42:00+08:00",
    "severity": "HIGH",
    "responsibility": {
      "id": "maintenance_001",
      "name": "Equipment Maintenance"
    }
  },
  "pulse": {
    "level": "attention",
    "title": "Industrial incident requires human review",
    "event_id": "event_0123456789abcdef0123456789abcdef"
  },
  "employees": [
    {
      "id": "maintenance_001",
      "name": "Equipment Maintenance",
      "status": "working",
      "current_event_id": "event_0123456789abcdef0123456789abcdef",
      "responsibility": "Equipment Maintenance",
      "skills": [
        {
          "name": "restaurant-aircon-shutdown"
        }
      ]
    }
  ]
}
```

Empty state:

```json
{
  "version": "workspace-v1",
  "events": [],
  "active_event": null,
  "pulse": null,
  "employees": []
}
```

`events`, `pulse`, and `employees` are generated by the same service functions
as the standalone endpoints. The Workspace endpoint must not implement separate
field mappings or different status rules.

### 7.1 Active Event derivation

The terminal Event statuses for `workspace-v1` are:

```text
CLOSED
REJECTED
FAILED
CANCELLED
```

`active_event` is the most recently updated valid persisted Event whose status
is not in that terminal set. The same deterministic newest-first ordering as
`GET /api/events` is used, but active selection is not truncated to the
100-item feed window. Consequently, an older unresolved active Event may be
returned even when it has fallen outside `events`. If every Event is terminal,
or the database contains no Events, `active_event` is `null`.

This field is a read projection only. Selecting it does not activate, retry, or
transition the Event.

## 8. `GET /api/digital-employees`

Purpose: present observed responsibility owners as a bounded product
projection without creating a DigitalEmployee Runtime entity or table.

Response status: `200 OK`.

Exact contract:

```text
DigitalEmployeeProjection[] where each item is {
  id: string
  name: string
  status: "working" | "unknown"
  current_event_id: string | null
  responsibility: string
  skills: [
    {
      name: string
    }
  ]
}
```

Example:

```json
[
  {
    "id": "maintenance_001",
    "name": "Equipment Maintenance",
    "status": "working",
    "current_event_id": "event_0123456789abcdef0123456789abcdef",
    "responsibility": "Equipment Maintenance",
    "skills": [
      {
        "name": "restaurant-aircon-shutdown"
      }
    ]
  }
]
```

### 8.1 Identity and grouping

The projection evaluates all valid persisted Events with the injected
`ResponsibilityDirectory` and groups matched results by
`ResponsibilityAssignment.owner_id`.

- `id` is the safe owner ID;
- `name` is the safe owner name;
- `responsibility` is the same reviewed owner name used as the only available
  human-readable responsibility summary;
- `UNASSIGNED` does not create a synthetic employee;
- multiple Events assigned to one owner produce one employee projection.

This is an observed responsibility-owner product view, not an authoritative
employee roster, login identity, authorization subject, or durable employee
aggregate.

### 8.2 Status and current work

For each projected owner, the service selects the most recently updated
non-terminal Event assigned to that owner.

- if such an Event exists, `status` is `working` and `current_event_id` is that
  Event's ID;
- otherwise, `status` is `unknown` and `current_event_id` is `null`.

The projection never returns `online` or `offline`, because the current Runtime
has no employee presence or heartbeat source. `working` means only “a real,
non-terminal Event is currently projected to this responsibility owner.” It
does not mean an autonomous agent process or person is online.

### 8.3 Skill projection

`skills` is the deterministic, de-duplicated set of safe `skill_id` values
found in persisted Audit `model_metadata` for the owner's projected Events.
The array is sorted by the skill ID.

Each public object contains only:

```json
{
  "name": "restaurant-aircon-shutdown"
}
```

No Skill is inferred for a NEW Event, and no Skill definition is serialized.
The following Skill fields are prohibited:

- analysis instructions;
- escalation rules;
- knowledge query hints;
- Skill resolution reason;
- prompt payload;
- arbitrary Audit metadata.

Empty state and no responsibility match both produce:

```json
[]
```

## 9. `GET /api/pulse`

Purpose: let the backend decide which persisted Notification currently requires
user attention.

Response status: `200 OK`.

Exact contract:

```text
PulseProjection =
  {
    level: "attention" | "critical"
    title: string
    event_id: string
  }
  | null
```

Example:

```json
{
  "level": "critical",
  "title": "Industrial incident requires human review",
  "event_id": "event_0123456789abcdef0123456789abcdef"
}
```

No-notification state:

```json
null
```

### 9.1 Pulse candidate rules

A Notification from any valid persisted Event is eligible only when all of the
following are true:

1. it is a real persisted Notification Outbox row;
2. its Notification status is `CREATED`;
3. its associated Event exists;
4. the Event status is one of:
   - `PENDING_HUMAN_REVIEW`;
   - `NEEDS_MORE_EVIDENCE`;
   - `ESCALATED`.

A `CREATED` Notification associated with CLOSED, REJECTED, FAILED, CANCELLED,
APPROVED, or another non-attention Event state does not produce Pulse.

If multiple candidates exist, the service orders them by:

1. critical level before attention level;
2. newest Notification creation time;
3. stable Event ID tie-breaker.

Only the first candidate is returned.

### 9.2 Pulse level

Level derivation is backend-owned:

```text
if Event.severity == CRITICAL or Event.status == ESCALATED:
    level = critical
else:
    level = attention
```

The frontend must not re-derive whether an Event requires attention.

`title` comes from the persisted Notification title after public-output safety
validation. F03-D1 does not return Notification content, recipient, trace,
decision, channel, status, ID, or timestamp.

## 10. Security boundary

### 10.1 Prohibited output

No F03-D1 response may contain these fields or equivalent nested content:

```text
prompt
system instruction
system_instruction
analysis_instructions
raw analysis
reasoning_summary
model_or_rule
model internal response
trace_id
request_id
actor
reviewer
raw_input_ref
normalized_input
attachments
metadata
audit
audit_id
audit details
details
local file path
database path
database_path
file_or_data_ref
credential
secret
token
```

The prohibition applies to both JSON keys and values. Renaming a private field
does not make its content public.

### 10.2 Safe text handling

Any text copied from Runtime data or reviewed local configuration must pass a
central public-output policy. At minimum it must prevent verbatim exposure of:

- Windows absolute paths such as `C:\...`;
- Unix absolute paths, including parenthesized paths and locations such as
  `/root`, `/home`, `/Users`, `/tmp`, `/var`, `/etc`, and `/opt`;
- Windows UNC paths and parent-directory references;
- `file:` references;
- API keys, passwords, authorization/Bearer values, access tokens, and common
  token-shaped values such as JWT-bearing headers, Slack tokens, and AWS
  access-key IDs, including prefixed environment-variable assignments;
- control characters and unbounded text.

Unsafe optional responsibility values cause responsibility to become `null`;
they do not fall back to Mock data. Unsafe employee identity values cause that
employee projection to be omitted. Unsafe Notification title text is replaced
with a fixed non-sensitive title or redacted safe text, never the original
value.

Generated Event IDs, Event types, enum statuses, and persisted Skill IDs must
also be checked against their expected bounded identifier/value shapes before
serialization.

### 10.3 Audit extraction

Audit is private even when it contains some safe provenance. Skill extraction
must:

- inspect only the known analysis Audit metadata shape;
- accept only the exact `skill_id` key;
- accept only a bounded valid Skill ID string;
- copy no sibling fields;
- return no Audit identity, action, actor, sequence, transition, trace, model
  metadata object, or details object.

The complete Audit record must never enter an intermediate public dictionary.

### 10.4 HTTP behavior

The endpoints retain the current local Web API boundary:

- bind to loopback only;
- JSON response with UTF-8;
- `Cache-Control: no-store`;
- `X-Content-Type-Options: nosniff`;
- no CORS expansion;
- no query parameters in F03-D1;
- unsupported routes and methods keep controlled errors;
- unexpected failures return the existing generic safe error, never a
  traceback, database path, request content, or exception detail.

## 11. Verification requirements

Projection unit and API integration tests must cover:

### Workspace

- empty database;
- Event exists;
- Event status is FAILED;
- Event status is CLOSED;
- active Event chooses the newest non-terminal Event;
- active Event is not lost outside the 100-item feed window;
- embedded objects equal standalone endpoint projections.

### Events

- an Event is discoverable after creation;
- state changes are reflected by a later GET;
- deterministic newest-first ordering;
- unmatched responsibility is `null`;
- unsupported severity is `UNKNOWN`.

### Digital Employees

- matched responsibility creates one owner projection;
- multiple Events for one owner are grouped;
- no responsibility match creates no employee;
- only non-terminal current work yields `working`;
- terminal-only history yields `unknown` and a null current Event;
- only persisted, valid Audit `skill_id` values become Skill names;
- prompt-related Skill fields never appear.

### Pulse

- CREATED Notification plus eligible Event produces Pulse;
- an eligible Notification is not lost outside the 100-item feed window;
- no Notification returns `null`;
- Notification for a non-attention Event returns `null`;
- CRITICAL severity or ESCALATED status produces `critical`;
- other eligible candidates produce `attention`;
- candidate ordering is deterministic.

### Read-only and security

- business-table contents are identical before and after each GET;
- no GET invokes Provider, SkillResolver, knowledge retrieval, or Runtime write
  methods;
- recursive response inspection rejects every prohibited key;
- malicious path-, secret-, and token-shaped values are never returned;
- no frontend Mock file is read or imported.

## 12. Known limitations

1. **Digital Employee is not a Runtime entity.** The endpoint groups observed
   responsibility owners. It does not establish a durable employee lifecycle,
   employee-to-Skill binding, employee authentication, or permissions.
2. **Responsibility may drift with configuration.** ResponsibilityAssignment is
   normally re-resolved from the current reviewed directory. It is not a
   versioned historical entity. Notification recipient fields are persisted,
   but F03-D1 does not expose them as an immutable employee roster.
3. **Skill projection begins after real analysis.** A Skill name appears only
   when a valid selected `skill_id` exists in persisted Audit provenance.
4. **Employee status is not presence.** `working` is derived from Event state;
   `unknown` is used when no current work exists. There is no online/offline
   health source.
5. **Pulse is not notification delivery.** Outbox status `CREATED` records
   local intent. There is no read/dismiss/acknowledge protocol in F03-D1.
6. **The Workspace is not a transactionally versioned snapshot.** Concurrent
   workflow writes may occur between separate store reads. F03-D1 does not add
   snapshot IDs, ETags, database locks, or a new schema.
7. **The Event feed is bounded but not paginated.** It returns at most 100
   records and accepts no cursor or filter. Active Event, Pulse, and Digital
   Employee derivation still inspect all valid persisted Events to preserve
   current-state correctness, so their read cost grows with local history.
8. **Runtime timestamp validation is limited.** Event creation currently
   requires a non-empty timestamp but does not fully enforce ISO-8601 syntax.
   F03-D1 preserves the persisted value subject to output safety; a later
   contract may introduce explicit invalid-time quality metadata.
9. **No integrated health or site model exists.** Workspace v1 does not return
   Mock site, edge node, health, command suggestion, metric, or permission
   fields.
10. **No authentication system is added.** The current service remains a
    loopback-only demo boundary. F03-D1 must not be interpreted as an
    authenticated enterprise read API.

## 13. Non-goals

F03-D1 does not:

- modify frontend code or select `HttpWorkspaceDataSource`;
- create a `DigitalEmployee` table, aggregate, state machine, or Runtime;
- modify the SQLite schema;
- change Event, Decision, Task, Evidence, or review state transitions;
- change `DecisionHook`;
- modify Skill definitions, Skill resolution, or Skill Runtime behavior;
- expose or edit prompts;
- expose Knowledge content;
- connect Ollama or change provider selection;
- implement authorization, users, roles, permissions, or LAN access;
- implement write endpoints for Pulse or Digital Employees;
- implement complete task/evidence/work-record projections;
- add WebSocket, SSE, polling, cursor pagination, or caching;
- host frontend static assets;
- validate AMD Linux or ROCm deployment;
- claim that the frontend already uses real Runtime state.

The completion state of F03-D1 is:

```text
Runtime / SQLite / reviewed configuration
                  |
                  v
       safe read-only Projection API
                  |
                  v
             Frontend ready
```
