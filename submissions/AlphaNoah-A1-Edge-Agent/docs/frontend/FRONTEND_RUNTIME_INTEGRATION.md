# AlphaNoah Frontend Runtime Integration

> F03-D2 Frontend Runtime Projection Integration
> Target contract: `workspace-v1`
> Scope: `frontend/` read integration only

## 1. Purpose

F03-D2 changes the default application composition from deterministic product
fixtures to the real, read-only Runtime Projection API introduced by F03-D1.
It does not add a page or a second Runtime model.

The production data path is:

```text
React Page / Component
          |
          v
Provider and selector hooks
          |
          v
DataSource interface
          |
          v
Runtime Projection HTTP client
          |
          v
GET Projection API
          |
          v
Runtime read model / SQLite
```

The dependency is one-way. Pages consume frontend View Models and resource
state only. They must not import wire DTOs, issue `fetch` calls, read SQLite,
import Python Runtime objects, or reproduce backend selection rules.

## 2. Scope and invariants

F03-D2 may:

- implement frontend HTTP clients, DTOs, decoders, and adapters;
- make `HttpWorkspaceDataSource` read `GET /api/workspace`;
- add an `HttpDigitalEmployeeDataSource` that reads
  `GET /api/digital-employees`;
- map the backend-owned Pulse projection into the existing Noah Pulse View
  Model;
- make the application root use HTTP sources by default;
- retain explicit Mock sources for unit tests, deterministic visual fixtures,
  and offline development;
- refresh read projections after a successful demo Activation write;
- improve loading, empty, error, partial, and stale-state presentation without
  changing the established page design.

F03-D2 must not:

- change Python Runtime code, Runtime object models, workflow transitions, or
  the SQLite schema;
- read SQLite or local responsibility/Skill files from the browser;
- create a Digital Employee Runtime entity or management API;
- add create, edit, delete, dispatch, approval, or permission behavior;
- add Ollama, QR, model-provider selection, polling, or a frontend state
  machine;
- use Mock data as a fallback when an HTTP read is empty, invalid, or
  unavailable;
- expose or infer Prompt, Audit, trace, local-path, model-response, or Skill
  definition data.

The exact F03-D1 public contract remains owned by
`RUNTIME_PROJECTION_WORKSPACE_V1.schema.json`. Frontend TypeScript describes
that wire contract for decoding; it does not redefine backend truth.

## 3. Current frontend findings

### 3.1 Workspace

The current Workspace path already has the right abstraction:

```text
WorkspacePage / AppShell / NoahPulse
                  |
                  v
       Workspace selector hooks
                  |
                  v
          WorkspaceProvider
                  |
                  v
        WorkspaceDataSource
```

`MockWorkspaceDataSource` returns a synchronous fixture snapshot.
`HttpWorkspaceDataSource` currently returns a typed `unavailable` error and
performs no request. `WorkspaceProvider` already supports cancellation, stale
completion protection, last-known data during refresh, and typed resource
states.

The HTTP implementation should preserve that provider contract. It should not
move request or decoding logic into `WorkspacePage`, `AppShell`, `NoahPulse`,
or selector hooks.

### 3.2 Pulse

Before F03-D2 there is no separate `MockPulseDataSource`; `usePulse()` selects
`WorkspaceSnapshot.activeNotices`. F03-D2 introduces a bounded Pulse resource
because the integration contract explicitly assigns Noah Pulse to
`GET /api/pulse` and requires an independently testable error state.

The production UI therefore gives each visible fact one owner:

- Workspace ignores the aggregate `pulse` field after validating the
  `workspace-v1` wire contract;
- `PulseProvider` alone owns the visible Noah Pulse notice from
  `GET /api/pulse`;
- Activation success refreshes both providers after the write completes.

This avoids duplicate UI state even though the backend intentionally derives
the aggregate and standalone Pulse fields from the same projection function.

### 3.3 Digital Employee

The Digital Employee pages already consume `DigitalEmployeeProvider` and
exact-ID selector hooks. `MockDigitalEmployeeDataSource` is the only concrete
source currently composed. There is no HTTP source or wire adapter.

The existing Digital Employee View Model is intentionally richer than
`workspace-v1`. F03-D1 exposes observed responsibility-owner facts only:
identity, operational status, current Event ID, one responsibility summary,
and persisted Skill identities. It does not expose stage, presence, metrics,
work records, knowledge scope, permissions, Skill version, or capability
availability.

The HTTP adapter must mark those unsupported product fields unknown or
unavailable. It must not copy values from `mockDigitalEmployees`.

### 3.4 Activation

The current demo Activation returns an `ActivationSnapshot` and locally
overlays that snapshot onto:

- the Workspace Event list;
- Noah Pulse;
- a hard-coded Digital Employee binding.

That overlay was useful before the read projection existed, but it is not a
durable F03-D2 source of truth. It disappears on browser refresh and its
employee identity can differ from the F03-D1 responsibility-owner identity.
For example, the existing overlay binds `maintenance_001` to the Mock ID
`equipment-maintenance`, while F03-D1 groups employees by the real owner ID.

After F03-D2, Activation UI may retain local request progress and success/error
feedback, but Workspace, Pulse, and Digital Employee business presentation
must come from a projection re-read.

## 4. Target composition

The application root is the only production source-selection point:

```text
App
 |
 +-- WorkspaceProvider(httpWorkspaceDataSource)
 |
 +-- ActivationProvider(httpActivationDataSource)
 |
 +-- DigitalEmployeeProvider(httpDigitalEmployeeDataSource)
 |
 +-- ProjectionRefreshCoordinator
 |
 +-- AppRoutes
```

Recommended injectable root contract:

```ts
interface AppProps {
  readonly workspaceDataSource?: WorkspaceDataSource;
  readonly digitalEmployeeDataSource?: DigitalEmployeeDataSource;
  readonly activationDataSource?: ActivationDataSource;
}
```

Defaults are HTTP instances. Tests pass Mock or purpose-built fake sources
explicitly. Environment heuristics such as `import.meta.env.DEV` must not
silently select business Mock data; a developer who wants an offline fixture
must opt in through an explicit test/story/offline entry point.

Concrete sources stay out of feature barrel exports used by pages. They are
selected through feature `composition.ts` modules at the application root.

## 5. HTTP client, DTO, decoder, and adapter boundary

The recommended dependency chain is:

```text
HttpWorkspaceDataSource
        |
        +-- RuntimeProjectionHttpClient.getWorkspace()
        |        |
        |        +-- fetch("/api/workspace")
        |        +-- status/content handling
        |        +-- decodeWorkspaceProjection()
        |
        +-- adaptWorkspaceProjection()

HttpDigitalEmployeeDataSource
        |
        +-- RuntimeProjectionHttpClient.getDigitalEmployees()
                 |
                 +-- fetch("/api/digital-employees")
                 +-- status/content handling
                 +-- decodeDigitalEmployeeProjectionList()
        |
        +-- adaptDigitalEmployeeCollection()
```

One shared client may expose the endpoint methods, or the two HTTP sources may
receive a small common request helper. In either case, `fetch` and JSON error
normalization belong below the DataSource interface, never in providers or
pages.

Recommended client surface:

```ts
interface RuntimeProjectionHttpClient {
  getWorkspace(options?: {
    readonly signal?: AbortSignal;
  }): Promise<WorkspaceProjectionDto>;

  getDigitalEmployees(options?: {
    readonly signal?: AbortSignal;
  }): Promise<readonly DigitalEmployeeProjectionDto[]>;

  // Optional for standalone consumers; the default F03-D2 UI reads Pulse
  // atomically from WorkspaceProjectionDto.pulse.
  getPulse?(options?: {
    readonly signal?: AbortSignal;
  }): Promise<PulseProjectionDto | null>;
}
```

### 5.1 DTO rules

Wire DTOs:

- retain backend `snake_case` names;
- remain internal to the `api/` layer;
- contain only the F03-D1 allowlisted fields;
- never extend frontend View Models;
- are not re-exported from the feature public barrel.

The required shapes are:

```ts
interface WorkspaceProjectionDto {
  readonly version: "workspace-v1";
  readonly events: readonly EventProjectionDto[];
  readonly active_event: EventProjectionDto | null;
  readonly pulse: PulseProjectionDto | null;
  readonly employees: readonly DigitalEmployeeProjectionDto[];
}

interface EventProjectionDto {
  readonly id: string;
  readonly type: string;
  readonly status: string;
  readonly timestamp: string;
  readonly severity:
    | "UNKNOWN"
    | "LOW"
    | "MEDIUM"
    | "HIGH"
    | "CRITICAL";
  readonly responsibility: {
    readonly id: string;
    readonly name: string;
  } | null;
}

interface PulseProjectionDto {
  readonly level: "attention" | "critical";
  readonly title: string;
  readonly event_id: string;
}

interface DigitalEmployeeProjectionDto {
  readonly id: string;
  readonly name: string;
  readonly status: "working" | "unknown";
  readonly current_event_id: string | null;
  readonly responsibility: string;
  readonly skills: readonly {
    readonly name: string;
  }[];
}
```

### 5.2 Decoder rules

Decoders accept `unknown` and validate before producing a DTO. They must:

- require the exact `workspace-v1` version;
- validate every required object, array, string, enum, nullable field, and
  Event ID shape;
- reject missing required fields;
- reject unexpected fields because the F03-D1 schema sets
  `additionalProperties: false`;
- reject more than 100 `events`;
- preserve unknown future Event status text as a string so the existing
  presentation status adapter can fail closed to `UNKNOWN`;
- never use `as WorkspaceProjectionDto` on unvalidated JSON;
- report a typed `contract` error without adding rejected values to an error
  message shown by the UI.

A missing required wire field is a broken contract, not partial data. Partial
presentation is produced from valid contract values such as `null`, `[]`,
`UNKNOWN`, or fields that F03-D1 intentionally does not expose.

### 5.3 HTTP error rules

The HTTP layer should normalize:

| Condition | Frontend error |
|---|---|
| request was aborted | `aborted` |
| network failure | `transport` |
| endpoint unavailable or non-success response | `unavailable` or `transport`, according to the existing typed contract |
| malformed JSON or DTO mismatch | `contract` |
| unexpected frontend failure | `unknown` |

The client must not retry a write, change Runtime state, or fall back to Mock.
Normal relative `/api/...` URLs preserve the existing Vite development proxy
and same-origin production deployment boundary.

## 6. Workspace projection adapter

`adaptWorkspaceProjection(dto)` creates a `WorkspaceSnapshot` with
`source: "http"`. The UI remains unaware of the wire shape.

Recommended Event mapping:

| View Model field | Projection source |
|---|---|
| `id` | `event.id` |
| `title` | literal `event.type` |
| `runtimeStatus`, lifecycle, status label | existing status presentation adapter from `event.status` |
| `severity`, severity label | existing severity presentation adapter from `event.severity` |
| `occurredAt` | `event.timestamp` |
| `sourceLabel` | responsibility name when responsibility is present |
| `detail`, `location`, `assetId` | `null` |
| `actionSummaryId` | `null` |

The adapter must not synthesize analysis, evidence, location, asset, action,
or notification content. A technical Event type is preferable to a polished
but invented title.

`active_event` must be retained as an explicit frontend identity. The preferred
small View Model extension is:

```ts
interface WorkspaceSnapshot {
  // existing fields...
  readonly activeEventId: string | null;
}
```

If the active Event is not present in the bounded 100-item `events` feed, the
adapter may include the identical active Event projection once in the visible
Event collection, with deduplication by ID. It must not invent an active Event
or reorder terminal Events based on frontend state rules.

F03-D1 does not provide site, health, context-signal, action-summary, command,
or snapshot-observation facts. Their safe HTTP representation is:

- site ID, area, and observation time: `null`;
- site name: localized generic product copy such as “Runtime workspace,” not a
  Mock site name;
- health: unavailable/unknown, not healthy;
- context signals: empty unless they are direct presentation of a decoded
  projection value;
- action summaries and current focus: empty/`null`;
- command suggestions: empty for the real business snapshot;
- `observedAt`: `null`, because client receipt time is not Runtime observation
  time;
- snapshot quality: `partial`, listing only the unsupported frontend product
  fields.

A successful empty response is still a ready HTTP snapshot:

```json
{
  "version": "workspace-v1",
  "events": [],
  "active_event": null,
  "pulse": null,
  "employees": []
}
```

It must render “no current events” and an idle Pulse. It must never reveal the
Mock Event list.

## 7. Digital Employee projection adapter

`HttpDigitalEmployeeDataSource` reads the standalone
`GET /api/digital-employees` endpoint and returns a
`DigitalEmployeeCollection` with `source: "http"`.

Recommended mapping:

| View Model field | Projection source or safe value |
|---|---|
| `id` | employee `id` exactly |
| `name` | literal employee `name` |
| operational status | direct display projection of `working` or `unknown` |
| `responsibilities` | one item from the projected responsibility summary |
| `skills` | one capability item per projected skill name |
| current work | `current_event_id`, when non-null |
| description | `null` |
| stage | `unknown` |
| metrics | all values `null`, quality unavailable |
| work records | `[]` |
| knowledge | `[]` |
| permission summary | unknown, non-authoritative, no constraints |
| observed time | `null` |

Skill name is real persisted provenance, but capability availability and Skill
version are not projected. Therefore a capability item:

- uses the projected skill name as literal display text;
- has no invented description;
- has `availability: "unknown"`;
- has `sourceSkill: null`;
- is marked partial for the unavailable capability fields.

When `current_event_id` is present, the View Model may represent one current
work item whose identity and `eventId` are that real Event ID. Its display
title must either be the literal Event ID or generic localized presentation
copy clearly labelled as current Runtime Event. It must not invent a task
title, task ID, Task state, or last-updated time. If the UI cannot make that
distinction clearly, expose `currentEventId` directly on the employee View
Model instead of pretending the Event is a Task.

An empty array is a successful, ready empty collection. `unknown` status is a
valid projected state and must not be mapped to online, offline, or success.

## 8. Pulse projection adapter

The default F03-D2 Pulse adapter consumes the standalone
`GET /api/pulse` response.

When `pulse` is `null`:

- `PulseResource.notice` is `null`;
- `usePulse().currentNotice` is `null`;
- `NoahPulse` renders idle;
- no fixture, prior Activation overlay, or severity heuristic creates an
  alert.

When Pulse exists, mapping is direct:

| Pulse View Model field | Projection source or safe value |
|---|---|
| `eventId` | `pulse.event_id` |
| `title` | literal `pulse.title` |
| `kind` | direct `pulse.level` (`attention` or `critical`) |
| presentation severity | direct `pulse.level` |
| ID | stable presentation ID derived from `event_id`, not a Notification ID claim |
| facts, analysis, next action | `null` |
| created time | `null` |
| source Notification status | `null` |

The adapter must not call `derivePulseNoticeKind`, inspect Event severity,
inspect Event status, or decide whether a Notification needs attention. That
decision and Pulse level are backend-owned. Presentation priority may map
`critical` above `attention`, but it must not change the level.

The existing Pulse View Model has fields that F03-D1 intentionally withholds.
Those fields remain empty and its quality is partial. Generic localized UI
copy may explain that this is a Runtime notification, but it must not be
presented as Event analysis or evidence.

## 9. Loading, empty, error, partial, and stale states

Resource state and data availability are separate:

| Condition | Resource state | Presentation |
|---|---|---|
| first HTTP read in flight | `loading`, no data | stable loading surface |
| valid empty projection | `ready`, empty data | explicit empty Event/employee state and idle Pulse |
| valid projection with `null`/unknown fields | `ready`, partial View Models | render known facts and mark unsupported facts unavailable |
| initial transport/contract error | `error`, no data | Runtime unavailable plus explicit retry |
| refresh in flight with prior data | `refreshing`, retain data | keep last-known projection, indicate refresh |
| refresh failed with prior data | `error`, retain data | mark last-known data stale and allow retry |

No state is permitted to replace Runtime failure with Mock success.

Workspace, Digital Employee, and Activation failures are independently scoped.
For example, a valid Workspace with an unavailable employee endpoint still
shows real Events and Pulse while the employee page shows its own error. A
Pulse of `null` is not an error. An Event with `responsibility: null` remains
visible and does not create a synthetic employee.

Pages must not render blank content for a known resource state. The current
Digital Employee pages already distinguish loading, empty, error, and stale
states. Workspace needs an explicit valid-empty Event presentation in addition
to its existing initial loading/error boundary.

## 10. Activation-to-projection refresh

The required successful flow is:

```text
POST /api/demo/events
          |
          v
Runtime commits Event / Notification facts
          |
          v
Activation request reports success
          |
          v
ProjectionRefreshCoordinator invalidates reads
          |
          +-- WorkspaceProvider.refresh()
          |       |
          |       +-- GET /api/workspace
          |               +-- Events
          |               +-- active Event
          |               +-- Pulse
          |
          +-- DigitalEmployeeProvider.refresh()
                  |
                  +-- GET /api/digital-employees
```

The coordinator is a composition concern, not an adapter concern. It should be
a small descendant of all required providers, or receive provider refresh
callbacks explicitly. It observes an accepted Activation success transition
and triggers each projection read once. It does not copy the
`ActivationSnapshot` into Workspace or employee state.

Recommended semantics:

- do not refresh while the POST is still in flight;
- refresh after the successful Activation snapshot has passed its decoder and
  source check;
- refresh again when a recovery read changes Activation from error to ready;
- allow Workspace and employee reads to complete or fail independently;
- preserve their last-known projections while refreshing;
- do not retry the Activation write when a projection GET fails;
- avoid unbounded polling or timers.

The locally returned Activation snapshot may continue to drive the trigger's
request feedback. It must no longer be prepended to the Workspace Event list,
used as the Noah Pulse notice, or overlaid on the employee collection in the
production path.

Browser reload performs normal HTTP initial reads. No local persistence is
needed for Event, Pulse, or employee business state; durability comes from the
Runtime/SQLite projection.

## 11. Mock policy

Mock sources remain useful, but their role becomes explicit:

```text
Production/runtime demo:
  HttpWorkspaceDataSource
  HttpDigitalEmployeeDataSource
  HttpActivationDataSource

Unit/component tests, stories, explicit offline fixture entry:
  MockWorkspaceDataSource
  MockDigitalEmployeeDataSource
  MockActivationDataSource or focused fakes
```

Rules:

- do not delete deterministic Mock fixtures required by focused tests;
- do not import Mock fixtures from HTTP adapters;
- do not choose Mock because an API call failed;
- do not make the normal application root default to Mock in development;
- tests that exercise application composition must inject Mock sources
  explicitly if they do not intend to exercise HTTP;
- HTTP integration tests must assert that Mock constructors and data are not
  read.

## 12. Recommended test contract

### 12.1 Decoder and adapter tests

Cover:

- exact valid `workspace-v1` response;
- empty Workspace;
- Event with and without responsibility;
- known and unknown Event status presentation;
- all severity values;
- `pulse: null`, attention, and critical;
- Digital Employee working, unknown, no current Event, empty skills, and empty
  list;
- rejected version, missing required field, wrong enum, wrong nullability,
  malformed Event ID, more than 100 feed Events, and unexpected field;
- absence of Prompt, Audit, trace, local-path, raw-analysis, and model-response
  DTO fields.

### 12.2 DataSource tests

Cover:

- correct GET path and method;
- relative same-origin URL;
- `AbortSignal` forwarding and pre-aborted request;
- successful decode and adapter output;
- non-success HTTP response;
- invalid JSON and invalid contract;
- no Mock fallback;
- no write method or request body.

### 12.3 Provider and application tests

Cover:

- production root defaults to HTTP Workspace and employee sources;
- test root can explicitly inject Mock/fake sources;
- initial loading, valid empty, initial error, partial, refreshing, and stale
  states;
- Pulse idle when backend Pulse is null;
- Pulse level comes directly from the Pulse DTO even when Event fields would
  tempt a different frontend result;
- successful Activation causes one Workspace and one employee projection
  refresh;
- the visible Activation Event, Pulse, and employee state come from those GET
  responses rather than the Activation snapshot;
- browser-style remount reads persisted projection and restores the same
  business state without Mock or browser storage;
- employee ID selection uses the projection ID and has no Mock-ID binding.

## 13. Integration risks and decisions

### 13.1 Rich UI versus narrow projection

The current View Models contain more fields than `workspace-v1`. The correct
response is partial presentation, not new backend fields and not fixture
enrichment. Site health, action detail, employee stage, metrics, work records,
knowledge, and permissions remain unavailable in F03-D2.

### 13.2 Pulse ownership

`workspace-v1` still carries an aggregate Pulse for other clients, but the
frontend adapter does not copy it into `WorkspaceSnapshot.activeNotices`.
`PulseProvider` is the sole visible owner and reads `GET /api/pulse`. This
preserves the endpoint-specific loading/error contract without creating two
frontend sources for one notice.

### 13.3 Activation overlay identity drift

The Mock employee identity and responsibility-owner identity are not the same
contract. Projection refresh removes this hard-coded join and makes the
backend projection the only identity authority.

### 13.4 Active Event outside the feed

F03-D1 can return an `active_event` that is outside the bounded 100-item Event
feed. The frontend must retain that identity instead of assuming
`events[0]` is always active.

### 13.5 Contract error versus partial data

Silently defaulting a missing required field would hide backend/frontend
version drift. Required wire-field failure is a contract error. Only explicit
contract nulls, empty collections, unknown enum values allowed by the
contract, and unsupported product fields become partial View Models.

### 13.6 Snapshot observation time

`workspace-v1` has Event timestamps but no aggregate or employee observation
timestamp. The frontend must not label `Date.now()` as Runtime observation
time. The UI may track request completion internally, but the View Model
observation field remains `null`.

## 14. Completion boundary

F03-D2 is complete when:

- normal application composition reads Workspace and Digital Employees through
  HTTP sources;
- Workspace Events are decoded from the real `workspace-v1` aggregate and
  Noah Pulse is decoded from the real standalone Pulse projection;
- Digital Employee pages render only facts allowed by the projection and safe
  unknown/partial placeholders;
- no real HTTP empty/error path falls back to Mock;
- successful Activation invalidates and re-reads projections;
- a remount restores Runtime state through GET reads;
- UI code remains separated from HTTP DTOs and Runtime internals;
- all changes remain frontend-only and do not modify Runtime, SQLite, Skill,
  Provider, Ollama, or workflow behavior.

The resulting boundary is:

```text
React UI
   |
   v
Frontend View Models
   |
   v
HTTP DataSources and strict decoders
   |
   v
Runtime Projection API
   |
   v
Existing Runtime / SQLite
```
