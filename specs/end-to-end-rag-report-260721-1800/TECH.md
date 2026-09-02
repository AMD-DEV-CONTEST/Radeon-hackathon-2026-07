# End-to-End RAG Report Run

- Level: S2
- Status: implemented

## Design

- `build_project_report_tools()` registers the five fixed runner tools only:
  scan, index, retrieve, evaluate, and draft.
- Import uses `import_project()` with the configured project root.
- Indexing uses `ProjectIndex`; retrieval uses `Retriever` for every task
  query; evaluation keeps the rule engine as the status authority.
- Production evaluation uses the configured chat model only for explanations.
- The report is written under `outputs/<project_id>/reports/<run_id>.md`.
- `POST /api/projects/{project_id}/runs/{run_id}/execute` is the explicit
  execution boundary.

## Risks and rollback

- RAG or chat failures produce a failed run and JSONL audit event; they do not
  create a completed report.
- Roll back by removing the execute endpoint and workflow registration while
  retaining immutable run diagnostics.

## Verification

- Local fixture test with a deterministic mock embedder.
- Cloud smoke test with the live embedding and chat endpoints via
  `scripts/verify_end_to_end_rag_report_cloud.py`.
