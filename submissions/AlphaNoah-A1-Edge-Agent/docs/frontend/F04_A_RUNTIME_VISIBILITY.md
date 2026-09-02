# F04-A Runtime Visibility & AI Environment Awareness

## Result

F04-A exposes the existing Provider Runtime projection as a calm, read-only
product surface. It adds no AI capability and does not modify Runtime core,
Provider orchestration, Provider factory, API behavior, SQLite, Skills, or
Docker.

## Existing Runtime capability audit

### Available

- `ProviderRuntimeOrchestrator` is the startup source of truth for discovery,
  selection precedence, validation, and Provider construction.
- `GET /api/runtime` already exposes the exact credential-free
  `runtime-status-v1` contract.
- Runtime status: `ready`, `unconfigured`, `unavailable`,
  `invalid_configuration`, or `degraded`.
- Selected Provider: `ollama`, `vllm`, `openai_compatible`, `fake`, or `null`.
- Safe model identifier or `null`.
- Execution mode: `local`, `remote`, `demo`, or `none`.
- Configuration source: `command_line`, `environment`, `saved_config`,
  `injected`, or `none`.
- Health: `healthy`, `synthetic`, `not_configured`, `unavailable`,
  `invalid_configuration`, or `degraded`.
- Existing backend tests assert the response allowlist and reject credential,
  endpoint, path, traceback, and diagnostic leakage.

### Missing

- No frontend consumer for `GET /api/runtime` existed before F04-A.
- No public AMD GPU or ROCm hardware status exists.
- No public doctor/discovery candidate list exists.
- No frontend Provider setup or selection write contract exists.
- No API applies configuration changes or reports restart requirements.

### Need extension later

- A safe hardware/environment projection if the product must identify AMD GPU
  or ROCm explicitly.
- A product-facing doctor/discovery projection implemented on top of the
  existing orchestrator.
- An authenticated and audited Provider selection write boundary.

F04-A does not implement these extensions.

## Frontend implementation

The new boundary lives below `frontend/src/features/runtime/status/`:

```text
status/
  api/
    providerRuntimeApiDtos.ts
    providerRuntimeApiDecoder.ts
    HttpProviderRuntimeDataSource.ts
  adapter/
    providerRuntimeAdapter.ts
  models/
    providerRuntime.ts
  provider/
    ProviderRuntimeStatusContext.tsx
  components/
    RuntimeStatusCard.tsx
    AiRuntimeSetupPanel.tsx
  mock/
    MockProviderRuntimeDataSource.ts
```

Production composition selects `HttpProviderRuntimeDataSource`. Tests can
explicitly inject `MockProviderRuntimeDataSource`; there is no implicit Mock
fallback.

## Data flow

```text
Workspace / Settings
  -> useProviderRuntimeStatus()
  -> ProviderRuntimeStatusProvider
  -> ProviderRuntimeDataSource
  -> HttpProviderRuntimeDataSource
  -> GET /api/runtime
  -> existing runtime-status-v1 projection
  -> decoder
  -> adapter
  -> ProviderRuntimeSnapshot
  -> read-only UI
```

Pages and presentation components do not call `fetch` and do not consume raw
Runtime JSON.

## API used

F04-A uses only:

```http
GET /api/runtime
Accept: application/json
Cache-Control behavior: browser request uses cache: no-store
```

Example response:

```json
{
  "version": "runtime-status-v1",
  "status": "ready",
  "provider": "ollama",
  "model": "qwen3.5:9b",
  "execution": "local",
  "selection_source": "saved_config",
  "health": "healthy"
}
```

No backend endpoint or response was changed.

## UI behavior

### Workspace Runtime Status Card

The compact glass surface appears after field context and before activity. It
shows Provider, model, execution, health, and configuration source while
keeping events as the main workspace surface.

| Projection result | UI state | Behavior |
|---|---|---|
| `status=ready` | Ready | Shows the exact Provider identity and health |
| Any explicit non-ready status | Unavailable | Shows the corresponding bounded reason; never falls back |
| Transport, HTTP, JSON, or contract failure | Unknown | Hides stale identity and does not display Online |
| Read/refresh in progress | Reading/Refreshing | Does not claim a successful state before the read completes |

Explicit Fake execution is labelled `Demo Provider`, `Demo`, and
`Synthetic demo`; it is never presented as local inference.

### Settings: AI Runtime Setup

The existing Settings drawer now includes a future setup entry with:

- AMD GPU: explicitly "Not reported by Runtime API";
- Local model Runtime: only the current local selection, if reported;
- Cloud Provider: only the current remote selection, if reported;
- Current selection: exact Provider/model/execution projection;
- Refresh detection: a re-read of `GET /api/runtime` only.

The entry does not scan hardware, enumerate ports, save configuration, select
a Provider, or initiate Runtime actions.

## Internationalization and accessibility

- English and Simplified Chinese labels are included.
- Status is expressed in text as well as color.
- The setup refresh is a semantic button and participates in the existing
  Settings focus trap.
- Motion remains governed by the existing application preference and
  `prefers-reduced-motion` boundary.

## Visual review

- Uses existing Glass, StatusBadge, IconContainer, Button, tokens, and motion
  system; no new visual framework or dependency was introduced.
- The Runtime card is compact and horizontal at desktop widths, avoiding a
  dashboard tile grid.
- Green is limited to a verified healthy state.
- Unavailable and Unknown states remain calm and do not animate continuously.
- Responsive layout collapses the facts safely below 1080 px and to two
  columns below 680 px.

## Screenshots

The intended untracked output location is:

```text
tmp/f04-a-runtime-visibility/
```

No F04-A capture was generated in this Windows Codex desktop run. The desktop
sandbox supplied duplicate case-insensitive `Path`/`PATH` entries to detached
process creation, and its native process-creation fallback was denied. Both
attempts used bounded timeouts; all temporary processes and files were removed.
This is a visual-evidence gap, not an application test failure. A Linux host or
an interactive browser session should capture the ready Ollama state before the
task is declared visually accepted.

## Verification

Automated coverage includes:

- exact `runtime-status-v1` decoding;
- ready Provider/model/execution/health mapping;
- explicit unavailable mapping with no fallback;
- unknown contract and transport handling;
- Ready, Unavailable, and Unknown UI states;
- explicit data-source refresh;
- existing workspace, Pulse, preferences, activation, and digital employee
  regression suites.

Final command counts and results are recorded in the task completion report.

Results for this implementation run:

- TypeScript typecheck: PASS.
- Frontend tests: 181/181 PASS across 32 files.
- Vite production build: PASS; source maps remain disabled.
- Python tests: 214/214 PASS.
- Python compileall: PASS.
- Backend source changes: none.

## Completion decision

**NEEDS REVIEW** — implementation and automated verification are complete, but
the required visual capture could not be produced in the current desktop
sandbox. Visual acceptance on the target Linux/Ollama environment remains.

## Follow-up

See [AI_RUNTIME_SETUP_DIRECTION.md](./AI_RUNTIME_SETUP_DIRECTION.md) for the
future installation and Provider setup direction. Human Review UI remains a
separate next-stage task.
