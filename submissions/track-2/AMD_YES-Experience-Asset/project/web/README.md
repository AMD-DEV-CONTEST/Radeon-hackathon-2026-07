# Experience Asset Agent — React workspace

The user-facing workspace covers the complete M1-M5 Experience Asset journey:
Experience Brief, Critical Moment Map, Decision Evidence Ledger, Insight
Boundary Map, and route/publish preview. It lands on M1 by default; system
status is an engineering utility view.

The shell only presents and navigates existing product state. Business state,
permissions, and model tool-call boundaries remain controlled by backend
contracts and the Agent Runtime. The UI uses same-origin `/api`; local
development may connect to a loopback remote tunnel with `VITE_PROXY_TARGET`.

The E1-B React/Vite/TypeScript status shell remains available for engineering
inspection. E2 adds the real M1 product workspace at:

```text
http://127.0.0.1:5173/?view=m1&source=live
```

The M1 workspace creates, autosaves, pauses, resumes and confirms
`Experience Brief v0.1`, and shows the persisted bounded Agent trace through
the same-origin local `/api` proxy. See
[`../docs/E2_M1_VERTICAL_SLICE.md`](../docs/E2_M1_VERTICAL_SLICE.md) for the
backend command, API and current evidence boundary.

The status surface
**truthfully** presents service health, durable version/autosave state,
milestone progress, confirmed/unresolved counts, route-readiness placeholders,
stale/invalidation notices, and current run/terminal state. It is driven only by
typed API contracts and never fabricates progress, ETA, or permission.

See `../spec/README.md` for the authoritative scope and safety boundaries.

## Requirements

- Node 20+ (developed on Node 24), npm 10+.

## Install and run

```bash
cd web
npm install                 # or: npm ci (after a lockfile is committed)
npm run dev                 # http://127.0.0.1:5173 (mock data by default)
```

## Verify (all green in CI-equivalent order)

```bash
npm run verify:contracts    # vendored E1-A contracts match recorded provenance
npm run typecheck           # tsc project references, no emit
npm run lint                # eslint (flat config)
npm run test                # vitest: contract, provenance, view-model, components, hook
npm run build               # tsc -b && vite build
npm run e2e:install         # one-time: download the Chromium headless shell
npm run e2e                 # Playwright: mock states (live spec auto-skips without URL)
```

## Data sources: mock ↔ live (no UI contract change)

Both sources return the same typed `StatusSnapshot`; only the provider changes.

- **Mock (default):** checked-in fixtures under `src/data/fixtures.ts`, validated
  against the vendored JSON Schemas by the contract test.
- **Live:** reads the localhost FastAPI backend **same-origin** through the Vite
  `/api` proxy (no CORS needed; backend stays loopback-only).

Select via env or URL query params (query wins):

| Param | Values | Meaning |
|---|---|---|
| `source` | `mock` \| `live` | data source |
| `scenario` | `healthy`, `loading`, `empty`, `failure`, `safe-stop`, `stale`, `terminal-failure`, `relation-ready`, `relation-no-match`, `relation-confirmed`, `relation-detail-denied`, `relation-invalidated` | mock scenario |
| `delay` | ms | artificial mock latency (to observe the loading state) |

Env equivalents are `VITE_DATA_SOURCE` and `VITE_MOCK_SCENARIO` (see
`.env.example`). Live browser requests always use same-origin `/api`; query and
browser-env base URL overrides are intentionally unsupported. The dev/preview
proxy target is `VITE_PROXY_TARGET` (default `http://127.0.0.1:8080`) and fails
closed unless it is a loopback HTTP(S) origin using `localhost`, `127.0.0.1`,
or `::1`.

Examples:

```bash
# Point the shell at a running local backend (same-origin proxy):
VITE_PROXY_TARGET=http://127.0.0.1:8080 npm run dev
# then open http://127.0.0.1:5173/?source=live

# Capture live E2E against a running backend:
E2E_LIVE_BASE_URL=http://127.0.0.1:8080 VITE_PROXY_TARGET=http://127.0.0.1:8080 npm run e2e
```

## Contracts and provenance

`web/contracts/` holds the final E1-A public contracts **vendored verbatim** from
`main@431e1a5` (JSON Schema + OpenAPI + examples). Lane B does not own or fork
them. Their source commit and SHA-256 hashes are recorded in
`web/contracts/PROVENANCE.md` and enforced by `npm run verify:contracts` and
`src/contracts/provenance.test.ts`.

## Layout

```text
web/
├── contracts/              # vendored E1-A contracts + provenance
├── scripts/                # verify-contract-provenance.mjs
├── src/
│   ├── contracts/          # typed mirror of the contracts + contract/provenance tests
│   ├── data/               # provider seam, mock/live providers, fixtures, config
│   ├── viewmodel/          # pure snapshot -> view-model derivation (+ tests)
│   ├── components/         # presentational panels + state screens
│   ├── hooks/              # useStatus (load/refresh/error)
│   └── App.tsx
└── e2e/                    # Playwright specs (mock states + gated live)
```

## Truthfulness guarantees (tested)

- Progress `percent` renders only with the public
  `milestones_done/milestones_total` basis; internal units never become public
  progress. ETA renders only when E1-A supplies both value and basis (AC-17).
- The checked-in run fixture validates and renders final canonical work-plan,
  retrieval-scope, policy-decision, tool-execution and verification states;
  proposals never imply execution.
- Cross-asset candidates come from final canonical asset fields only after the
  accepted M4 readiness is bound to its current version/hash. Candidates stay
  summary-only; confirmation/decline is explicit, and detail retrieval is shown
  only for the confirmed relation. A no-match result is valid.
- Confirmed / unresolved counts derive from statement and question state.
- Stale/invalidation derives from real invalidation markers (AC-15).
- Tool-call proposals render with `permission_granted=false`; the UI grants no
  execution or publication permission.
- Live mode reports `not_served` for endpoints the backend does not yet expose,
  rather than inventing asset/run state.
