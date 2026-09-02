# Official Export Manifest

The complete source code is the repository root. The `submission/` directory is the curated English deliverable index and must travel with that source tree.

## Include From The Repository Root

- `.env.example`, `.gitignore`, `LICENSE`, `README.md`, and `ROCM_VALIDATION.md`
- `pyproject.toml` and `requirements.lock`
- `src/`, `scripts/`, `deploy/`, `fixtures/`, `evals/`, and `tests/`
- `docs/README.md`
- this entire `submission/` directory

## Exclude

- `.git/`, `.env*` except `.env.example`, `.venv/`, caches, and local logs
- `data/`, backups, databases, downloaded source archives, and runtime state
- `models/`, `*.gguf`, build directories, and model binaries
- Chinese/internal submission drafts and legacy Radeon artifacts not present in this curated package

## Official Fork Destination

```text
submissions/track2-coreline-systems-limited-openalpha-sentinel/
```

Run the privacy and placeholder checks documented in `docs/submission/README.en.md` before creating the Pull Request.
