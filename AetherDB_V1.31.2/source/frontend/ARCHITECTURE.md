# AetherDB Frontend Architecture

> Status: living contract for the V1.31 desktop UI. Update this file when a
> feature changes ownership or data-flow boundaries.

## Product Boundaries

| Surface | Responsibility | Must not own |
|---|---|---|
| Home (`/`) | Current-world summary, continue-writing entry, quick creation, import entry, recent content | Full chapter editor or independent draft persistence |
| Workspace (`/workspace`) | Chapter selection, writing, autosave, version history, analysis preview and confirmation | Direct formal entity writes from generated output |
| Immersive workspace (`/workspace?mode=immersive`) | Distraction-reduced writing with an adjustable/collapsible assistant rail | A separate document model or a second save implementation |
| Import (`/import`) | Durable import tasks and ImportChangeSet review | Immediate writes before user confirmation |
| Graph (`/graph`) | Render and interact with `GraphDataset` | Page-local graph data models or backend query construction |
| Settings (`/settings`) | Providers, models, routes, prompts, local runtime, hardware, backup and access controls | Plaintext credential persistence |

## Data Flow

```text
Vue view/component
  -> Pinia domain store
  -> frontend/src/api/*.js
  -> frontend/src/api/client.js
  -> authenticated FastAPI route
  -> service/repository layer
```

- Views own layout and transient presentation state.
- Pinia stores own cross-component workflow state and orchestration.
- API modules own endpoint paths and request/response adaptation.
- `client.js` is the only browser HTTP boundary and attaches `X-API-Key`.
- Backend data is authoritative. `localStorage` is recovery/preferences only.

## Creative Loop Invariants

1. A database and a book must be selected before chapter editing starts.
2. Saving chapter text and confirming worldview changes are separate actions.
3. Analysis produces a preview/ChangeSet. It never writes formal entities by itself.
4. Only explicit user confirmation may commit entities, relations or timeline data.
5. Home and normal/immersive workspace reuse the same chapter store and API methods.
6. Empty and unavailable capabilities stay truthful. Do not ship static sample results as user data.
7. Visual and voice tools remain disabled capability states until task, progress, result and binding APIs exist.

## Workspace Components

| Component | Ownership |
|---|---|
| `WorkspaceNavigator.vue` | Workflow capability state, real chapter list and runtime summary |
| `WorkspaceEditor.vue` | Text/title editing, Markdown helpers, word count, autosave and manual save commands |
| `ChapterReviewPanel.vue` | ChangeSet preview/confirmation and immutable version history |
| `ImmersiveAssistantPanel.vue` | Adjustable assistant rail; width/collapse are user preferences only |
| `Workspace.vue` | Context bar and responsive composition; no endpoint calls outside the store |

## Compatibility Rules

- Use explicit `.js` extensions for local ESM imports. Vue SFC imports retain `.vue`.
- Supported Node runtime is `>=20.19.0`; use an active LTS release for packaging.
- `pnpm-lock.yaml` is the dependency lock. In an offline managed environment, existing
  `node_modules` may be verified through `npm.cmd run ...` without changing the lock.
- Do not major-upgrade Vite/Tauri/Vue during feature work. Upgrade them as a dedicated
  compatibility task with desktop packaging and viewport regression evidence.
- PowerShell commands should use single-quoted regular expressions or separate command
  arguments to avoid nested quote parsing failures.
- Vite development and production builds use `--configLoader runner`; the default
  temporary bundled config can fail under restricted Windows workspace permissions.

## Required Gates

```powershell
cd frontend
npm.cmd run test:api
npm.cmd run build -- --configLoader runner
cd ..
.\venv\Scripts\python.exe -m pytest tests\test_frontend_core_routes.py tests\test_creative_loop.py -q
.\venv\Scripts\python.exe scripts\audit_frontend_api_coverage.py
```

Run backend pytest and the route/API audit serially. Both initialize the SQLite
registry, so parallel execution can create a false `database is locked` failure.

For layout changes, verify at minimum 1280x720, 1920x1080 and a narrow 800x600
window. A 3840x2160 pass is required before desktop release sign-off.

## Known Backend Dependencies

Workspace writes must carry an explicit `database_id` and the backend must
validate `book_id` ownership. AI settings, model execution, context approval,
recovery, and home-page creation flows remain backend-owned contracts. A
frontend fallback or optimistic state does not replace backend persistence,
authorization, capability checks, or durable task state.
