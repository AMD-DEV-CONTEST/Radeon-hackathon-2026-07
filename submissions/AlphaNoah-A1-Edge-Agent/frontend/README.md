# AlphaNoah Frontend

The frontend is a React workspace for the AlphaNoah A1 Edge Agent. F03-A
preserves the frozen F02.6 visual system while introducing a one-way Runtime
integration boundary. F03-B adds a read-only Digital Employee Center on top
of the same presentation principles:

```text
Runtime JSON -> decoder -> adapter -> View Model -> provider/hooks -> UI
```

F03-A/F03-B still do not enable Runtime requests, read SQLite, submit business
actions, change the Python Web Adapter, or alter Docker behavior.

## Requirements

- Node.js 22.12 or newer
- npm

Node.js is a development and build dependency only. Production delivery is
still expected to use the static `dist/` artifact, without a Node.js server.

## Commands

```text
npm install
npm run dev
npm run typecheck
npm test
npm run test:watch
npm run build
npm run preview
```

The development server binds to `127.0.0.1:5173`. It reserves a local `/api`
proxy to `127.0.0.1:8090`, but the default F03-A composition makes no API
requests.

`npm run build` writes static assets to `dist/` without source maps. The
directory is ignored by Git and remains the future handoff boundary for Python
static hosting.

## F03-A application boundaries

```text
src/
  app/          routes, field-first Workspace and app composition
  layouts/      shared application shell
  components/
    preferences/ browser-local settings drawer
    pulse/       compact-to-expanded Noah Pulse prototype
    workspace/   read-only, on-demand action context
    motion/      centralized entrance, morph and overlay motion
    ui/          F01 visual primitives
  i18n/         typed zh-CN and en-US message catalogs
  preferences/  locale, theme and motion provider
  features/
    runtime/
      api/       snake_case wire decoders and unavailable HTTP source
      adapter/   pure status, severity, notice and View Model mapping
      models/    provider-independent Workspace View Models
      hooks/     one snapshot resource and selector hooks
      mock/      deterministic adapter inputs and Mock data source
      composition.ts  concrete source exports for the app root/tests
    digital-employees/
      components/ accessible roster, identity and factual timeline views
      pages/      read-only list/detail route surfaces
      types/      product View Models and display projections
      provider/   one collection resource and exact-ID selector hooks
      mock/       deterministic product fixtures and Mock data source
      composition.ts  concrete source export for the app root
  styles/       semantic tokens and global accessibility rules
  types/        compatibility-only presentation type export
  mock/         test compatibility export; not used by production UI
  test/         browser-environment test setup
```

The application composition root injects `MockWorkspaceDataSource`. Its
fixture inputs pass through the same adapters and View Models that a future
HTTP source must produce. The UI imports only hooks and View Models; wire DTOs
remain internal to `features/runtime/api`.

`HttpWorkspaceDataSource` implements the same contract but deliberately
returns a typed `unavailable` error. The current Web Adapter can read only a
known event ID and cannot discover a Workspace, so F03-A does not hard-code an
event ID or silently fall back to Mock. Provider reads accept `AbortSignal`;
the React resource aborts superseded work and ignores stale completions.

`WorkspaceSnapshot.actionSummaries` retains all event-linked action
projections, while `currentFocus` is a selected projection rather than a new
Runtime relationship. `useActionSummary(eventId, actionSummaryId)` validates
both IDs, so stale or cross-event links fail closed instead of falling back to
another action. The smart-instruction form remains a local-only interaction
and performs no network request.

The Workspace leads with site context and a time-ordered event surface; it has
no marketing hero and no permanently occupied detail column. Each event maps
its retained raw Runtime status onto a read-only lifecycle projection through
a pure adapter. This does not duplicate the backend transition table.
Selecting an event opens a structured action context as an accessible overlay.

Noah Pulse derives idle from an empty notice collection and receives its
notice from the same Workspace snapshot as the event surface. Notice priority
and presentation kind are adapter projections; expand/collapse remains local
interaction state. Opening the action context first collapses Pulse and
preserves a stable keyboard return target. No acknowledgement, approval,
queue cursor or other write behavior is implemented.

## F03-B Digital Employee boundary

`/employees` and `/employees/:id` present Digital Employee as an enterprise
product projection: responsibilities, capability modules, current work,
factual work records, knowledge scope and a human-readable operating
boundary. The list and detail routes select from one injected
`DigitalEmployeeCollection`; an unknown ID returns a feature-local not-found
state and never falls back to the first employee.

The default composition injects `MockDigitalEmployeeDataSource`. Its three
fixed employees, timestamps and metrics are explicitly labelled as Mock and
do not represent Runtime employees, presence, performance or permissions.
The source performs no network request, polling or timer work. Pages and
components consume provider hooks only and do not import the Mock source.

Stage (`intern`, `trial`, `production`, `paused`, `retired`) is a read-only
product display classification, not a Runtime state machine or authorization
switch. Operational status and stage keep their raw values and use a separate
display projection for labels and tones. Capability modules may retain a safe
source reference in the View Model, but the interface never renders Skill
IDs, versions, prompts or analysis instructions. Work records are
time-ordered facts rather than chat messages.

F03-B does not create, edit, dispatch or approve anything. A future real
source requires an independently audited, read-only Digital Employee API,
decoder and adapter; it must fail closed when that contract is unavailable
and must not silently reuse the Mock collection.

## Preferences

Preferences are exposed through one React provider and stored under
`alphanoah.preferences.v1` in browser `localStorage`.

- Locale: `zh-CN` or `en-US`. The first visit maps Chinese browser locales to
  `zh-CN` and all other locales to `en-US`; a manual selection overrides it.
- Theme: `system`, `light`, or `dark`. The default is `system`, and operating
  system changes are observed only while that option is active.
- Motion: `standard` or `reduced`. The first visit follows
  `prefers-reduced-motion`; a manual selection overrides it.

A small script in `index.html` validates stored values and applies the resolved
theme before React loads. This avoids an initial light/dark flash. Fixed
interface copy is read from typed translation keys, and the document language,
title, and description update with the selected locale.

## Delivery boundary

F03-A does not modify Python or Docker. A later delivery task may use a
multi-stage build—Node.js in a build stage and only static assets in the Python
runtime image—but that split must be reviewed separately. Node.js must not
become a required production process.

## Dependency audit note

The 2026-07-28 npm advisory database reports two high-severity entries for the
same React Router RSC/Server Action issue (`GHSA-qwww-vcr4-c8h2`) across the
current 7.x line. This application uses client-only `BrowserRouter`; it does
not enable RSC, SSR, Actions, Server Actions, or server-side route execution.
React Router remains on the latest available 7.x release instead of accepting
the audit command's proposed downgrade. Re-evaluate this boundary before
adding any server-rendered React capability.
