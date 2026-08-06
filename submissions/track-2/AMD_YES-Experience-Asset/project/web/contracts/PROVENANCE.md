# Vendored contract provenance

## Active E2 M1 contract source

The E2 M1 contract is developed in the same bounded Issue as its typed client,
so it is **not** falsely attributed to either historical E1 manifest below.
Its canonical sources are:

- `contracts/openapi.json`;
- `contracts/json-schema/experience-brief-v0.1.schema.json`; and
- `contracts/json-schema/m1-workspace-v1.schema.json`.

`web/src/features/m1/types.ts` is the reviewed UI projection and
`web/src/features/m1/api.ts` is the same-origin typed client. Backend contract
exports are checked by `python scripts/export_contracts.py --check`; frontend
API/component tests exercise the projection. A future re-vendor may bind these
files to the accepted merge commit. Until then, the existing manifests remain
historical E1/RAG provenance and must not be edited to claim an uncreated
source commit.

Each vendored contract source has its own manifest bound to its true source
commit, and `npm run verify:contracts` checks all of them:

| Manifest | Source | What it governs |
|---|---|---|
| `provenance.json` | final E1-A contract on `main@431e1a5` (merged PR #7) | health, progress, terminal, structured proposal, durable run state and components, experience asset, OpenAPI |
| `rag-contract-provenance.json` | `main` commit `14a43a4` (PR #9, `qa/schema/`) | `retrieval-phase-trace-v1.schema.json` — the M4 KnowledgeCardReady gate and cross-asset relation discovery |

The two sources are deliberately kept separate: the retrieval-phase trace is a
public RAG contract that landed on `main` via PR #9, not part of the E1-A
`contracts/` inventory, so it retains its own true source attribution.

## E1-A frontend contract (`provenance.json`)

These files are copied **verbatim** from the final E1-A contract inventory merged
to `main`. Lane B (E1-B) does not own or fork them; it derives its typed client
and mock fixtures from them and records provenance so a reviewer can confirm
they are unchanged.

- Source repository path: `contracts/`
- Source branch: `main`
- Source commit: `431e1a54040efbe4ccf04daf51b96e3642d233da`
- Vendored on: 2026-07-26 (UTC)

## Why vendored instead of referenced

The frontend keeps a byte-identical local inventory so its build and tests remain
self-contained while still binding every file to the final reviewed E1-A merge.
The manifest and verification gate make any local contract fork visible.

## Verifying identity with Lane A

```bash
# From the repository root, confirm the recorded inventory matches the source commit:
for f in $(node -e "const p=require('./web/contracts/provenance.json'); console.log(Object.keys(p.sha256).join(' '))"); do
  diff <(git show 431e1a54040efbe4ccf04daf51b96e3642d233da:contracts/"$f") \
    web/contracts/"$f" \
    && echo "OK  $f" || echo "DRIFT  $f"
done
```

The tamper-evident checksums below are also asserted by
`npm run verify:contracts` and by the Vitest suite
(`src/contracts/provenance.test.ts`). Any local edit to a vendored file fails
both checks.

The complete lowercase SHA-256 inventory is machine-readable in
`provenance.json`; it includes the final durable run state, work plan, policy
decision, tool execution, verification report, progress, relation readiness,
and all previously frozen E1-A contracts.

## RAG retrieval-phase contract (`rag-contract-provenance.json`)

Vendored **verbatim** from `main` (PR #9), which owns the public RAG gate:

- Source repository path: `qa/schema/`
- Source branch: `main`
- Source commit: `14a43a47cd929fb612987be8e66c712993181419`
- Vendored on: 2026-07-24 (UTC)

| File | SHA-256 |
|---|---|
| `json-schema/retrieval-phase-trace-v1.schema.json` | `fb50e816ef654746373814386403efe60c4c874342aa7333066a369680073408` |

```bash
# Confirm byte-identity with the source on main:
diff <(git show 14a43a4:qa/schema/retrieval_phase_trace.schema.json) \
     web/contracts/json-schema/retrieval-phase-trace-v1.schema.json \
  && echo OK
```

The E1-B trace fixtures (`web/src/data/traces/*.json`) are derived from this
schema and independently pass the public AC-30 checker
(`qa/scripts/check_retrieval_phase.py`); they are not part of the vendored
contract and carry no provenance hash.

## Change policy

A contract change after freeze requires the owning Issue/PR to change the source,
then Lane B re-vendors, updates these checksums, regenerates types/mocks, and
both lanes review. Lane B never edits a vendored file in place. This applies to
both the E1-A frontend contract and the RAG retrieval-phase contract.
