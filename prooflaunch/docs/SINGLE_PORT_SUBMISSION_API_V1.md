# ProofLaunch single-port submission API V1

The same loopback port serves 15 source-ordered Workstream 24 control surfaces at `/control/*`. These surfaces bind run creation, observable events, human approval, model/eval records, evidence bundles, and measured-only health to the API. Media and channel previews report missing assets explicitly; they never substitute placeholders for model or Radeon evidence.

`GET /v1/launch-proof/status` is the fail-closed launch evidence control. It is
tenant authenticated and combines only public queue counts, content-free
guardrail/request-trace telemetry, the sealed readiness receipt, and an
optional Radeon live receipt. Its nine gates cover local regression, portfolio
human preference, judge calibration, deployed guardrails, deployed trace
coverage, protected remote CI, Radeon key inference, production effect, and
causal revenue. It exposes no invitation tokens, reviewer identities, model
predictions, private mapping, prompts, or raw traffic content.

This control plane exposes the local product UI and bounded JSON/SSE/media
endpoints from one loopback port. It is an execution and evidence surface, not
a claim that a model was trained or that external publishing occurred.

## Typed contracts

- `AgencyLaunchRequest` binds campaign objective, capabilities, content hashes,
  action/cost budgets, data class and a mandatory human-release boundary.
- `CampaignWorldState`, `DistillationEpisode`, `MemoryAtom` and `RewardVector`
  reuse the canonical intelligence, distillation, governed-memory and
  multi-objective alignment contracts.
- `ModelCard` cannot become `promoted` without both evaluation records and a
  Radeon execution evidence locator.
- `AgencyEvalRecord` binds a benchmark hash, finite metrics, raw denominators,
  evidence class, locator and blinding state.

## Endpoints

| Method | Path | Contract |
|---|---|---|
| `POST` | `/v1/runs` | Idempotent content-addressed run creation |
| `GET` | `/v1/runs/{run_id}` | Current status and evidence counts |
| `GET` | `/v1/runs/{run_id}/events` | Ordered SSE events |
| `GET` | `/v1/runs/{run_id}/preview` | Content-bound human-review preview |
| `GET` | `/v1/runs/{run_id}/preview/{asset_id}/{role}` | Same-origin PNG preview role |
| `POST` | `/v1/runs/{run_id}/approvals` | Named, timestamped human approve/reject decision |
| `GET` | `/v1/runs/{run_id}/outcomes` | Preregistered experiment identity and append-only observations |
| `POST` | `/v1/runs/{run_id}/outcomes` | Operator-authorized aggregate outcome intake |
| `GET/POST` | `/v1/runs/{run_id}/publication-receipts` | Tenant-bound, operator-authorized manual publication attestations |
| `POST` | `/v1/runs/{run_id}/multimodal-deliverables` | Register a rights-cleared, run-bound WAV/MP4 plus immutable model-execution receipt after release approval |
| `POST` | `/v1/runs/{run_id}/multimodal-deliverables/{registration_id}/reviews` | Named human pass/reject decision against the frozen playback, brief, safety and rights rubric |
| `POST` | `/v1/runs/{run_id}/outcomes/{observation_id}/promotions` | Second human gate for project learning memory |
| `GET` | `/v1/runs/{run_id}/learning-memories` | Scoped, append-only promoted learning collection |
| `POST` | `/v1/runs/{run_id}/strategy-memory-resolutions` | Named, idempotent conflict resolution for future runs only |
| `GET` | `/v1/strategy-memory-resolutions?project_id=...` | Tenant-scoped immutable resolution context |
| `GET` | `/v1/runs/{run_id}/bundle` | Approval-gated deterministic ZIP |
| `HEAD/PUT` | `/v1/artifacts/{sha256}` | Signature-checked, size-bounded, content-addressed PNG/JSON/WAV/MP4 intake without client paths |
| `GET` | `/v1/model-cards` | Truth-bounded model cards |
| `GET` | `/v1/evals/leaderboard` | Blinding/evidence-class-labeled evaluation rows |
| `GET` | `/v1/social-connectors` | Pinned open-source connector registry |
| `POST` | `/v1/social-collection/plan` | Rights- and budget-bounded collection plan |
| `POST` | `/v1/frontier-gtm/runs` | Tenant-authenticated, idempotent cloud-frontier strategy-to-last-mile run; server-side credential only, no local fallback |

The bundle contains the request, run, event chain, approval, campaign pack,
complete GTM artifact set, `effect-observations.json`, `effect-readiness.json`
and a member-hashed manifest. It explicitly records
`external_release_executed=false`.
The API never invokes a publisher, ad platform or payment system. The dedicated
`/v1/frontier-gtm/runs` route may invoke only a server-configured, approved cloud
frontier model after tenant authentication and idempotency binding; it fails closed
when that credential is absent and never falls back to a local model. Other generation
may happen in an isolated adapter, but its output
does not enter the product evidence chain until the artifact, execution receipt,
run/campaign identity, immutable model revision and rights locator all verify.

Outcome intake accepts aggregate counts only after a human-approved run reaches
`delivered`. It binds every observation to the preregistered experiment ID and
approved strategy SHA-256; requires a hashed source reference, deduplication and
bot-filter attestations; and emits a bounded next-cycle recommendation. It does
not accept audience identifiers or content bodies, automatically mutate
strategy, publish externally, or convert observational attribution into a
causal claim.

Manual publication receipts bridge the approved asset and outcome contracts
without publishing anything. They require the exact approved asset SHA-256,
candidate attribution tags in a public HTTPS URL, timezone-aware publication
time, and a hashed operator/platform receipt. The API stores no credential and
does not upgrade an operator attestation into platform-delivery or effect proof.

Learning promotion is a separate operator decision. Only observations with
both candidate and baseline sample gates and no zero-budget contract breach may
enter project memory. Every new run freezes the approved project-memory snapshot
at creation; later memories cannot mutate old strategies. The next experiment
surfaces the latest approved directive, but application remains human-reviewed
and no automatic strategy mutation occurs.

Run locally:

```bash
PYTHONPATH=src .venv/bin/python scripts/serve_v10_submission_api.py
```

The default bind is `127.0.0.1:8765`. Non-loopback binding is rejected by the
contract; production exposure requires a separately reviewed reverse proxy,
authentication, rate limits and transport security.

## Verification boundary

`tests/test_v10_submission_production_api.py` starts a real ephemeral HTTP
server and exercises UI delivery, run creation/idempotency, status, SSE,
approval, pre-approval bundle denial, outcome authentication/idempotency,
bundle resealing, open-source collector planning and invalid-input failures.
The mechanical fixture in
`evidence/v10/submission-api-mechanical-fixture.json` is simulated contract
evidence only. It is not Radeon, model-quality, production-reliability or
business-outcome evidence.
