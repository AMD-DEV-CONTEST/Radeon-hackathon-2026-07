# ClaimCourt Public Release Manifest

Only public, synthetic, reproducible material should be included in the final submission commit.

## Include

- `README.md`
- `.gitignore`
- `api.py`, `app.py`, `core.py`
- `requirements.txt`, `requirements-radeon.txt`
- `frontend/` source, package metadata, and production build
- `scripts/` runtime, evaluation, corpus-building, and submission-build scripts
- `training/` code, documentation, and synthetic intent data
- `tests/`
- `demo_corpus/` and `championship_corpus/`
- `evaluation/fuzzy_holdout_v1/`
- `docs/PRD.md`, `docs/company.md`, `docs/product.md`, and `docs/system.md`
- Public synthetic or sanitized evidence receipts under `docs/evidence/`
- `submission/` deliverables and the rendered English UI screenshot

## Do Not Include

- `data/` workspace indexes, query history, feedback, or local archives
- Private documents or private evaluation corpora
- Unsanitized private queries, expected labels, or local absolute paths
- `.harness/` internal execution memory
- `HANDOFF.md` internal Chinese handoff notes
- `submission/DEMO_SCRIPT_ZH.md`, which is the owner's local recording aid
- `NUL`, temporary files, logs, caches, PID files, and model weights
- `.ssh/`, tokens, credentials, browser profiles, or shell history
- Temporary Office or screenshot rendering directories

## Required Pre-Commit Gates

```bash
python -m unittest discover -s tests -t .
cd frontend && npm run lint && npm run build
git diff --check
```

The owner must review the exact staged file list before authorizing commit or push.
